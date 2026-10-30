"""Loopback API and durable application workflows for the Chinese workbench."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from zoneinfo import ZoneInfo

from .store import Store, encode, uid, utcnow
from .secrets import get_key, set_key

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path(os.environ.get("USERPROFILE", Path.home())) / "TravelAssistantData" if os.name == "nt" else Path.home() / ".local" / "share" / "travel-assistant"
DATA_DIR = Path(os.environ.get("TRAVEL_DATA_DIR", str(DEFAULT_DATA_DIR)))
store = Store(DATA_DIR)
analysis_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="extraction")
wechat_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wechat")
ui_lock = threading.Lock()
analysis_ids: set[str] = set()
analysis_dirty: set[str] = set()
analysis_lock = threading.Lock()
PROCESS_SESSION_ID = uid()
background_service = None
NATIVE_SESSION_SECONDS = 1800
FOREGROUND_DISABLED_CODE = "FOREGROUND_COLLECTION_DISABLED"
FOREGROUND_DISABLED_REASON = "前台微信采集已停用；已授权好友请使用“后台同步”。原群聊及其他联系人继续暂停，已有资料仍可查看和使用。"
NATIVE_COMPATIBILITY_CODES = {"UIA_NOT_ENROLLED", "UIA_DEPENDENCY_MISSING", "ROUTE_NOT_ENROLLED",
    "PAGINATION_UNAVAILABLE", "UNVERIFIED_ENROLLMENT", "CLIENT_VERSION_MISMATCH", "CLIENT_VERSION_NOT_ENROLLED",
    "NATIVE_DRIVER_UNAVAILABLE", "OCR_UNAVAILABLE", "OCR_UNSUPPORTED", "VIEWER_UNSUPPORTED", "UNSUPPORTED_LAYOUT", FOREGROUND_DISABLED_CODE}
NATIVE_INVALIDATION_CODES = {"SOURCE_MISMATCH", "IDENTITY_MISMATCH", "GEOMETRY_CHANGED", "SESSION_EXPIRED",
    "WINDOW_REPLACED", "ACCOUNT_CHANGED", "TARGET_AMBIGUOUS", "SESSION_PROCESS_RESTART", "BINDING_CHANGED"}
DEFAULT_SETTINGS = {"timezone": "Asia/Shanghai", "provider": {"protocol": "openai_compatible", "base_url": "", "model": "", "vision_model": "", "timeout": 30, "timeout_seconds": 30, "max_concurrency": 2}}


def settings():
    return store.get("settings", "main") or DEFAULT_SETTINGS.copy()


def public_settings():
    return {**settings(), "data_dir": str(store.root), "has_api_key": bool(get_key(store.root)), "fixture_mode": os.environ.get("TRAVEL_TEST_MODE") == "1",
            "foreground_collection_enabled": foreground_collection_enabled(),
            "imported_dataset": (store.root / "imported-installation.json").is_file(),
            "live_collection_enabled": get_background().collection_enabled}


def foreground_collection_enabled():
    """Foreground collection is suspended by default; not an operator UI setting."""
    return not (store.root / "imported-installation.json").is_file() and os.environ.get("TRAVEL_ENABLE_FOREGROUND_COLLECTION") == "1"


def _foreground_disabled_response():
    return JSONResponse({"detail": FOREGROUND_DISABLED_REASON, "state": "COMPATIBILITY_BLOCKED",
                         "stop_code": FOREGROUND_DISABLED_CODE}, status_code=409)


def _block_foreground_job(job):
    if job.get("acquisition_mode") == "operator_positioned":
        job = refresh_native_counts(job)
    return store.put("jobs", {**job, "state": "COMPATIBILITY_BLOCKED", "stop_code": FOREGROUND_DISABLED_CODE,
                              "stop_reason": FOREGROUND_DISABLED_REASON})


def ai_settings():
    provider = settings().get("provider", {})
    return {**provider, "timeout_seconds": provider.get("timeout_seconds", provider.get("timeout", 30))}


def require(kind, ident):
    result = store.get(kind, ident)
    if not result:
        raise HTTPException(404, "记录不存在或已移动，请刷新后重试")
    return result


def product_snapshot(product):
    """Freeze publication evidence alongside facts; import time is not publication."""
    sources = []
    for ident in product.get("source_item_ids", []):
        material = require("materials", ident)
        source = store.get("sources", material.get("source_id")) or {}
        sources.append({"material_id": ident, "material_version": material.get("version"),
                        "source_id": material.get("source_id"), "source_name": source.get("display_name"),
                        "source_kind": source.get("kind"), "author": material.get("author"),
                        "source_time_raw": material.get("source_time_raw"),
                        "time_evidence": material.get("time_evidence"),
                        "observed_at": material.get("observed_at"),
                        "observation_time_precision": material.get("observation_time_precision")})
    return {**product, "source_snapshots": sources}


def capabilities():
    try:
        from .collectors import get_adapter
        if not foreground_collection_enabled():
            blocked = {"status": "BLOCKED", "available": False, "code": FOREGROUND_DISABLED_CODE,
                       "reason": FOREGROUND_DISABLED_REASON, "requires_foreground": True}
            return {"group": {**blocked}, "moments": {**blocked}, "upload": get_adapter("upload").probe_capabilities()}
        return {kind: get_adapter(kind).probe_capabilities() for kind in ("group", "moments", "upload")}
    except ImportError:
        return {kind: {"status": "BLOCKED", "available": False, "reason": "采集组件尚未就绪"} for kind in ("group", "moments")}


@asynccontextmanager
async def lifespan(application):
    global background_service
    lockfile = (store.root / "instance.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lockfile.seek(0)
            if not lockfile.read(1):
                lockfile.write(b"0")
                lockfile.flush()
            lockfile.seek(0)
            msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
        store.recover()
        from .background.service import BackgroundService
        background_service = BackgroundService(store)
        background_service.start()
        yield
    finally:
        if background_service:
            background_service.stop()
            background_service = None
        lockfile.close()


app = FastAPI(title="选团助手", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)


@app.middleware("http")
async def local_only(request: Request, call_next):
    # A loopback service must not accept drive-by writes from arbitrary websites.
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse({"detail": "仅允许从本机访问"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        return JSONResponse({"detail": "请求来源无效，请从本机应用页面操作"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(RequestValidationError)
async def request_validation(request, exc):
    return JSONResponse({"detail": "输入格式不正确，请检查必填项、数字和日期。"}, status_code=422)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    # Provider and parser details may contain credentials or imported content.
    return JSONResponse({"detail": "输入或文件校验未通过，请检查格式与日期；原始数据未删除。"}, status_code=422)


@app.get("/api/health")
def health():
    return {"status": "ok", "data_dir": str(store.root), "schema_version": 1,
            "instance_id": PROCESS_SESSION_ID, "live_collection_enabled": get_background().collection_enabled,
            "imported_dataset": (store.root / "imported-installation.json").is_file()}


@app.get("/api/state")
def state():
    return {"settings": public_settings(), "capabilities": capabilities(), "background": get_background().summary(), **{kind: store.all(kind) for kind in ("accounts", "sources", "jobs", "materials", "products", "cases", "recommendations", "weekly", "native_sessions", "page_observations")}}


def get_background():
    global background_service
    if background_service is None or background_service.store is not store:
        from .background.service import BackgroundService
        background_service = BackgroundService(store)
    return background_service


@app.get("/api/background")
def background_state():
    return get_background().summary()


@app.post("/api/background/bind")
def background_bind():
    return get_background().bind()


@app.get("/api/background/candidates")
def background_candidates():
    return get_background().pipeline.public_candidates()


@app.get("/api/background/candidates/{ident}/attachments/{index}")
def imported_candidate_attachment(ident: str, index: int, preview: bool = False):
    """Serve only saved managed bytes from detached imported candidates."""
    with store.connect() as db:
        row = db.execute("SELECT data FROM pending_candidates WHERE id=?", (ident,)).fetchone()
    candidate = json.loads(row[0]) if row else {}
    assets = candidate.get("item", {}).get("attachments", [])
    if not candidate.get("imported") or not 0 <= index < len(assets):
        raise HTTPException(404, "导入附件不存在")
    record = assets[index]
    if record.get("state") not in {"SAVED", "STAGED"} or not record.get("path"):
        raise HTTPException(409, "此附件未保存，缺失状态已保留")
    path = (store.root / record["path"]).resolve()
    blob_root = (store.root / "blobs").resolve()
    if (not path.is_relative_to(blob_root) or not path.is_file()
            or path.name != record.get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256")):
        raise HTTPException(404, "导入附件未通过文件校验")
    mime = record.get("mime", "application/octet-stream")
    safe_inline = preview and mime in {"image/png", "image/jpeg", "image/webp"}
    return FileResponse(path, media_type=mime, filename=record.get("name") or ("附件-" + str(index + 1)),
                        content_disposition_type="inline" if safe_inline else "attachment")


@app.post("/api/background/sources/{ident}/check")
def background_check(ident: str):
    return get_background().check_now(ident)


@app.post("/api/background/sources/{ident}/settings")
def background_settings(ident: str, body: dict):
    return get_background().settings(ident, body)


@app.post("/api/background/jobs")
def background_job(body: dict):
    return get_background().create_job(body)


@app.post("/api/background/inspection-results")
def background_inspection(body: list[dict]):
    return get_background().apply_inspection(body)


@app.post("/api/background/relevance-review")
def background_relevance_review(body: list[dict]):
    return get_background().apply_relevance_review(body)


@app.post("/api/background/shutdown")
def background_shutdown():
    service = get_background()
    service.stop()
    return {'stopped': not (service.thread and service.thread.is_alive()), 'message': '后台任务已停到安全边界；进度已保留。'}


@app.post("/api/background/jobs/{ident}/{action}")
def background_action(ident: str, action: str):
    return get_background().action(ident, action)


@app.post("/api/classifications/{kind}/{ident}")
def classification_correction(kind: str, ident: str, body: dict):
    return get_background().classify(kind, ident, body)


def _identity_snapshot(record):
    return {key: record.get(key) for key in ("id", "account_id", "kind", "display_name", "identity_evidence")}


def _native_delay(value):
    if type(value) not in (int, float) or not 0 <= value <= 10:
        raise HTTPException(422, "桌面交接等待时间应为 0 至 10 秒")
    return float(value)


def _native_budget(value):
    if type(value) is not int or not 1 <= value <= 5:
        raise HTTPException(422, "本次试采集限定为 1 至 5 页，请选择较小范围")
    return value


def _native_failure(exc):
    from .collectors import CollectorBlocked
    code = getattr(exc, "code", "NATIVE_COLLECTION_ERROR")
    reason = getattr(exc, "message", None)
    if not isinstance(reason, str) or not any('\u4e00' <= char <= '\u9fff' for char in reason):
        reason = "自动采集组件发生异常，已保留记录与检查点；请由技术人员检查兼容性。"
    if code in NATIVE_COMPATIBILITY_CODES or code.startswith(("OCR_", "VIEWER_")):
        return "COMPATIBILITY_BLOCKED", code, reason
    if isinstance(exc, CollectorBlocked):
        return "NEEDS_USER_ACTION", code, reason
    return "FAILED", code, reason


def _session_for_scan(ident, source, *, require_ready=True):
    session = require("native_sessions", ident)
    source = require("sources", source["id"])
    if session.get("source_id") != source["id"] or session.get("account_id") != source["account_id"]:
        raise HTTPException(409, "本次页面会话与所选来源或账号不一致，请重新建立会话")
    account = require("accounts", source["account_id"])
    expired = (session.get("process_session_id") != PROCESS_SESSION_ID or
               datetime.fromisoformat(session["expires_at"]) <= datetime.now(timezone.utc))
    changed = session.get("source_snapshot") != _identity_snapshot(source) or session.get("account_snapshot") != _identity_snapshot(account)
    if expired or changed:
        store.put("native_sessions", {**session, "state": "EXPIRED", "stop_code": "BINDING_CHANGED" if changed else "SESSION_EXPIRED",
                    "reason": "本次页面绑定已失效，请重新确认当前账号与所选来源；原记录仍保留。"})
        raise HTTPException(409, "本次页面会话已失效，请重新确认当前打开的微信来源")
    if require_ready and session.get("state") != "READY":
        raise HTTPException(409, "请先完成当前页面的来源确认，再开始采集")
    return session


@app.post("/api/native-sessions")
def stage_native_session(body: dict):
    if not foreground_collection_enabled():
        return _foreground_disabled_response()
    source = require("sources", body.get("source_id"))
    if source.get("kind") not in {"group", "moments"}:
        raise HTTPException(422, "当前页面采集仅支持已选择的群历史或联系人相册")
    account = require("accounts", source["account_id"])
    budget = _native_budget(body.get("page_budget", 3))
    return store.put("native_sessions", {"source_id": source["id"], "source_name": source["display_name"],
        "account_id": account["id"], "account_name": account["display_name"], "source_kind": source["kind"],
        "source_snapshot": _identity_snapshot(source), "account_snapshot": _identity_snapshot(account),
        "acquisition_mode": "operator_positioned", "source_positioning": "operator_assisted", "identity_scope": "session",
        "state": "STAGED", "page_budget": budget, "process_session_id": PROCESS_SESSION_ID,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=NATIVE_SESSION_SECONDS)).isoformat(),
        "reason": "请打开已选择的群历史或联系人自己的相册，核对账号与来源后建立本次会话。"})


@app.get("/api/native-sessions/{ident}")
def native_session_detail(ident: str):
    return require("native_sessions", ident)


@app.get("/api/page-observations/{ident}")
def page_observation_detail(ident: str):
    return require("page_observations", ident)


def establish_native_session(ident):
    with ui_lock:
        session = require("native_sessions", ident)
        if session.get("state") != "QUEUED":
            return
        if not foreground_collection_enabled():
            store.put("native_sessions", {**session, "state": "COMPATIBILITY_BLOCKED",
                "stop_code": FOREGROUND_DISABLED_CODE, "reason": FOREGROUND_DISABLED_REASON})
            return
        session = store.put("native_sessions", {**session, "state": "ESTABLISHING", "reason": "正在核对当前微信页面，请勿切换来源。"})
        try:
            time.sleep(session.get("start_delay_seconds", 3))
            if not foreground_collection_enabled():
                from .collectors import CollectorBlocked
                raise CollectorBlocked(FOREGROUND_DISABLED_REASON, FOREGROUND_DISABLED_CODE)
            source = require("sources", session["source_id"])
            account = require("accounts", session["account_id"])
            _session_for_scan(ident, source, require_ready=False)
            try:
                from .collectors.operator_positioned import establish_session
            except ImportError as exc:
                from .collectors import CollectorBlocked
                raise CollectorBlocked("当前微信版本的人工定位自动采集组件尚未适配完成，请由技术人员继续适配。", "NATIVE_DRIVER_UNAVAILABLE") from exc
            staging = store.root / "staging" / "native_sessions" / ident
            staging.mkdir(parents=True, exist_ok=True)
            result = establish_session(source, account, {"operator_acknowledged": True,
                "source_kind": source["kind"], "surface": "contact_album" if source["kind"] == "moments" else "group_history",
                "page_budget": session["page_budget"], "session_id": ident}, staging)
            store.save_session_evidence(session, result, staging)
        except Exception as exc:
            status, code, reason = _native_failure(exc)
            if isinstance(exc, HTTPException):
                status, code, reason = "NEEDS_USER_ACTION", "SESSION_EXPIRED", str(exc.detail)
            current = require("native_sessions", ident)
            store.put("native_sessions", {**current, "state": status, "stop_code": code, "reason": reason})


@app.post("/api/native-sessions/{ident}/establish")
def queue_native_establishment(ident: str, body: dict):
    if not foreground_collection_enabled():
        return _foreground_disabled_response()
    session = require("native_sessions", ident)
    if body.get("operator_acknowledged") is not True:
        raise HTTPException(422, "请确认当前登录账号、来源名称及页面类型与所选来源一致")
    if session.get("state") in {"QUEUED", "ESTABLISHING"}:
        raise HTTPException(409, "正在核对页面，请等待结果")
    if any(job.get("session_id") == ident and job["state"] in {"QUEUED", "RUNNING", "PAUSING"} for job in store.all("jobs")):
        raise HTTPException(409, "本次会话正在采集，请先暂停任务")
    source = require("sources", session["source_id"])
    account = require("accounts", session["account_id"])
    delay = _native_delay(body.get("start_delay_seconds", 3))
    session = store.put("native_sessions", {**session, "state": "QUEUED", "binding": None, "evidence": {}, "preview_url": None,
        "source_snapshot": _identity_snapshot(source), "account_snapshot": _identity_snapshot(account),
        "process_session_id": PROCESS_SESSION_ID, "operator_acknowledged_at": utcnow(), "start_delay_seconds": delay,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=NATIVE_SESSION_SECONDS)).isoformat(),
        "stop_code": None, "reason": "即将核对页面，请切回已打开的微信来源。"})
    wechat_pool.submit(establish_native_session, ident)
    return session


@app.put("/api/settings")
def update_settings(body: dict):
    current = settings()
    tz = body.get("timezone", current["timezone"])
    ZoneInfo(tz)
    provider = {**current.get("provider", {}), **body.get("provider", {})}
    allowed = {"protocol", "base_url", "model", "vision_model", "timeout", "timeout_seconds", "max_concurrency", "structured_output", "verified_capabilities"}
    provider = {key: value for key, value in provider.items() if key in allowed}
    if provider.get("base_url"):
        parsed = urlparse(provider["base_url"])
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(422, "服务地址不能包含密钥、密码或查询参数")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(422, "请输入有效的 HTTP 或 HTTPS 服务地址")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(422, "远程 AI 服务请使用 HTTPS 地址")
    provider["timeout_seconds"] = max(5, min(120, int(provider.get("timeout", provider.get("timeout_seconds", 30)))))
    provider["max_concurrency"] = max(1, min(2, int(provider.get("max_concurrency", 2))))
    # Capability claims are only set by the actual check endpoint.
    provider["verified_capabilities"] = current.get("provider", {}).get("verified_capabilities", {}) if all(provider.get(k) == current.get("provider", {}).get(k) for k in ("base_url", "model", "vision_model")) else {}
    if "api_key" in body:
        set_key(store.root, body["api_key"])
    store.put("settings", {"timezone": tz, "provider": provider}, "main")
    return public_settings()


@app.post("/api/provider/check")
def provider_check():
    from .extraction import check_provider
    result = check_provider(ai_settings(), get_key(store.root))
    current = settings()
    store.put("settings", {**current, "provider": {**current["provider"], "verified_capabilities": result}}, "main")
    return result


@app.post("/api/accounts")
def add_account(body: dict):
    if not body.get("display_name") or not body.get("identity_evidence"):
        raise HTTPException(422, "请填写当前账号名称及可核对的身份信息")
    return store.put("accounts", {"display_name": body["display_name"], "identity_evidence": body["identity_evidence"], "verification_status": "NOT_TESTED", "selected": True})


@app.post("/api/sources")
def add_source(body: dict):
    require("accounts", body.get("account_id"))
    if body.get("kind") not in {"group", "moments"} or not body.get("display_name") or not body.get("identity_evidence"):
        raise HTTPException(422, "请选择来源类型并填写名称及区分同名来源的信息")
    return store.put("sources", {"kind": body["kind"], "account_id": body["account_id"], "display_name": body["display_name"],
                                 "identity_evidence": body["identity_evidence"], "selected": True, "verification_status": "NOT_TESTED", "capabilities": capabilities().get(body["kind"], {})})


def upload_source():
    existing = store.get("sources", "uploads")
    return existing or store.put("sources", {"kind": "upload", "display_name": "用户上传", "account_id": "local", "selected": True}, "uploads")


def new_material(text, supplier, source_note, attachments=None, *, db=None):
    upload_source()
    return store.put("materials", {"source_id": "uploads", "account_id": "local", "text": text, "supplier": supplier or None,
                                  "source_note": source_note, "source_time_raw": None, "source_time": None, "observed_at": utcnow(),
                                  "state": "PENDING_EXTRACTION", "attachments": attachments or [], "extractions": [], "issues": []}, db=db)


def analyze(ident):
    from .extraction import analyze_material, extract_file
    try:
        material = require("materials", ident)
        store.put("materials", {**material, "state": "ANALYZING"})
        segments = [{"location": "原文", "text": material["text"]}] if material.get("text") else []
        issues = []
        local_states = []
        attachments = material.get("attachments", [])
        for attachment in attachments:
            if attachment.get("state") != "SAVED":
                issues.append("附件尚未保存，可稍后重试采集")
                continue
            file_path = store.root / attachment["path"]
            # Content-addressed storage deliberately has no filename extension.
            parsed = extract_file(file_path, attachment.get("mime", ""))
            local_states.append(parsed.get("state"))
            issues.extend(parsed.get("issues", []))
            segments.extend({**s, "attachment_id": attachment["id"], "location": f"{attachment['name']} · {s['location']}"} for s in parsed.get("segments", []))
        text = "\n".join(s["text"] for s in segments)
        payload = {**material, "text": text, "segments": segments, "local_states": local_states, "local_issues": issues, "attachments": [{**a, "path": str(store.root / a["path"])} for a in attachments if a.get("state") == "SAVED"]}
        ai = ai_settings()
        cache_key = hashlib.sha256(encode({"material_id": ident, "supplier": material.get("supplier"), "text": text, "blobs": [a.get("sha256") for a in attachments], "settings": ai, "prompt": "travel-extract-1", "schema": 1}).encode()).hexdigest()
        cached = store.get("analysis_cache", cache_key)
        result = cached["result"] if cached else analyze_material(payload, ai, get_key(store.root))
        if result.get("status") in {"COMPLETED", "SUCCESS", "EXTRACTED", "ANALYZED"}:
            store.put("analysis_cache", {"result": result}, cache_key)
        extraction = store.put("extractions", {"material_id": ident, "cache_key": cache_key, "result": result, "segments": segments, "issues": issues, "origin": "ai"})
        current = require("materials", ident)
        final_state = result.get("status", "NEEDS_CONFIGURATION")
        if not text and "NEEDS_VISION" in local_states and not ai.get("vision_model"):
            final_state = "NEEDS_VISION"
        store.put("materials", {**current, "state": final_state, "extracted_text": text, "segments": segments,
                                "issues": issues + result.get("issues", []), "extractions": current.get("extractions", []) + [extraction]})
        # Reprocessing appends suggestions; it never overwrites human-authored products.
    except Exception:
        current = store.get("materials", ident)
        if current:
            store.put("materials", {**current, "state": "FAILED", "issues": ["分析暂未完成；原始素材已保存，可检查 AI 设置后重试。"]})
    finally:
        with analysis_lock:
            analysis_ids.discard(ident)
            if ident in analysis_dirty:
                analysis_dirty.discard(ident)
                analysis_ids.add(ident)
                analysis_pool.submit(analyze, ident)


def queue_analysis(ident):
    with analysis_lock:
        if ident in analysis_ids:
            analysis_dirty.add(ident)
        else:
            analysis_ids.add(ident)
            analysis_pool.submit(analyze, ident)


@app.post("/api/uploads")
async def uploads(files: list[UploadFile] = File(...), supplier: str = Form(""), source_note: str = Form("")):
    if len(files) > 30:
        raise HTTPException(422, "每次最多导入 30 个文件")
    result = []
    for upload in files:
        content = await upload.read(64 * 1024 * 1024 + 1)
        if len(content) > 64 * 1024 * 1024:
            raise HTTPException(413, "单个文件超过 64 MB，请拆分后导入；此前已导入的文件仍保留。")
        name = Path((upload.filename or "未命名文件").replace("\\", "/")).name
        mime = mimetypes.guess_type(name)[0] or upload.content_type or "application/octet-stream"
        blob = store.save_blob(content)
        aid = uid()
        attachment = {**blob, "id": aid, "name": name, "mime": mime, "quality": "original", "state": "SAVED", "url": f"/api/attachments/{aid}"}
        with store.lock, store.connect() as db:
            material = new_material("", supplier, source_note, [attachment], db=db)
            store.put("attachments", {**attachment, "material_id": material["id"]}, aid, db=db)
        queue_analysis(material["id"])
        result.append(material)
    return {"materials": result, "message": "原始文件已保存，分析状态可在素材详情查看。"}


@app.post("/api/paste")
def paste(body: dict):
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 1000000:
        raise HTTPException(422, "请输入文本，长度不超过一百万字")
    material = new_material(text, body.get("supplier"), body.get("source_note", ""))
    queue_analysis(material["id"])
    return material


@app.get("/api/materials/{ident}")
def material_detail(ident: str):
    material = require("materials", ident)
    return {**material, "products": [p for p in store.all("products") if ident in p.get("source_item_ids", [])]}


@app.post("/api/materials/{ident}/analyze")
def material_analyze(ident: str):
    require("materials", ident)
    queue_analysis(ident)
    return {"id": ident, "state": "QUEUED", "message": "已加入分析队列"}


@app.get("/api/attachments/{ident}")
def attachment(ident: str, preview: bool = False):
    record = require("attachments", ident)
    if record.get("state") != "SAVED" or not record.get("path"):
        raise HTTPException(409, "文件尚未取得或仍在重试；原始引用已保留")
    path = (store.root / record["path"]).resolve()
    if not path.is_relative_to(store.root / "blobs") or not path.exists():
        raise HTTPException(404, "原始文件暂不可用，请检查备份或重新采集")
    safe_inline = preview and record["mime"] in {"image/png", "image/jpeg", "image/webp"}
    return FileResponse(path, media_type=record["mime"], filename=record["name"], content_disposition_type="inline" if safe_inline else "attachment")


def flag_recommendations(product_id=None, case_id=None):
    for recommendation in store.all("recommendations"):
        if (product_id and product_id in recommendation.get("product_ids", [])) or (case_id and case_id == recommendation.get("case_id")):
            if not recommendation.get("stale"):
                store.put("recommendations", {**recommendation, "stale": True, "review_reason": "需求或产品已更新；此版本保留原始内容，请重新核对。"})


def validate_product(body):
    from .extraction import ExtractedProduct
    fields = ExtractedProduct.model_fields
    value = {key: item for key, item in body.items() if key in fields}
    if value.get("shopping") == "unknown":
        value["shopping"] = None
    try:
        product = ExtractedProduct.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise HTTPException(422, "产品字段格式不正确，请检查名称、价格、团期与适用条件")
    for source_id in product["source_item_ids"]:
        require("materials", source_id)
    for offer in product["offers"]:
        offer["id"] = offer.get("id") or uid()
    return product


@app.post("/api/products")
def add_product(body: dict):
    product = validate_product(body)
    return store.put("products", {**product, "origin": "human", "correction_at": utcnow(), "verifications": [], "advisor_judgment": body.get("advisor_judgment")})


@app.put("/api/products/{ident}")
def edit_product(ident: str, body: dict):
    old = require("products", ident)
    product = validate_product({**old, **body})
    result = store.put("products", {**old, **product, "origin": "human", "correction_at": utcnow(), "advisor_judgment": body.get("advisor_judgment", old.get("advisor_judgment"))})
    flag_recommendations(product_id=ident)
    return result


@app.get("/api/products/{ident}/versions")
def product_versions(ident: str):
    require("products", ident)
    return store.versions("products", ident)


@app.post("/api/products/{ident}/confirm")
def confirm(ident: str, body: dict):
    product = require("products", ident)
    if not all(body.get(key) for key in ("field", "scope", "evidence", "confirmed_by")) or "value" not in body:
        raise HTTPException(422, "请填写确认字段、内容、适用团期或人群、供应商回复及确认人")
    verification = store.put("verifications", {"product_id": ident, "field": body["field"], "value": body["value"], "scope": body["scope"], "evidence": body["evidence"], "confirmed_by": body["confirmed_by"], "confirmed_at": utcnow(), "origin": "supplier_confirmation"})
    store.put("products", {**product, "verifications": product.get("verifications", []) + [verification]})
    flag_recommendations(product_id=ident)
    return verification


@app.post("/api/parse-requirements")
def parse(body: dict):
    from .extraction import parse_requirements
    return parse_requirements(str(body.get("text", "")), ai_settings(), get_key(store.root))


@app.post("/api/match")
def match(body: dict):
    from .matching import match_products
    return match_products([product_snapshot(p) for p in store.all("products")], normalize_requirements(body.get("requirements", {})))


def normalize_requirements(value):
    from .extraction import Requirements
    if not isinstance(value, dict):
        raise HTTPException(422, "需求必须包含可编辑的结构化条件")
    explicit_hard = "hard_constraints" in value
    value = value.copy()
    aliases = {"budget_max": "budget", "hotel_preferences": "hotels"}
    for old, new in aliases.items():
        if old in value:
            value[new] = value.pop(old)
    if value.get("shopping") == "any":
        value["shopping"] = None
    for key in ("preferences", "exclusions", "hard_constraints"):
        raw = value.get(key) or []
        value[key] = [s.strip() for s in re.split(r"[,，;；\n]", raw) if s.strip()] if isinstance(raw, str) else raw
    for key in list(value):
        if value[key] == "":
            value[key] = None
    filled_hard = [aliases.get(k, k) for k in value.get("hard_constraints", []) if value.get(aliases.get(k, k)) not in (None, "")]
    value["hard_constraints"] = filled_hard
    try:
        result = Requirements.model_validate({k: v for k, v in value.items() if k in Requirements.model_fields}).model_dump(mode="json")
    except ValidationError:
        raise HTTPException(422, "需求字段格式不正确，请检查日期、人数、预算及条件")
    if result.get("date_start") and result.get("date_end") and result["date_start"] > result["date_end"]:
        raise HTTPException(422, "最晚出发日期不能早于最早日期")
    if not explicit_hard:
        result.pop("hard_constraints", None)
    return result


@app.post("/api/cases")
def add_case(body: dict):
    ident = body.get("id")
    old = require("cases", ident) if ident else {}
    result = store.put("cases", {**old, "name": body.get("name", "未命名接待"), "requirements": normalize_requirements(body.get("requirements", {})), "request_text": body.get("request_text", ""), "notes": body.get("notes", old.get("notes", "")), "outcome": body.get("outcome", old.get("outcome", "跟进中"))}, ident)
    if old and old.get("requirements") != result["requirements"]:
        flag_recommendations(case_id=ident)
    return result


@app.post("/api/recommendations")
def recommendation(body: dict):
    from .exports import recommendation_text
    from .matching import match_products
    products = [product_snapshot(require("products", ident)) for ident in body.get("product_ids", [])]
    if not products:
        raise HTTPException(422, "请先选择要比较的产品")
    if len(products) > 6:
        raise HTTPException(422, "一次最多比较六个产品")
    case = require("cases", body["case_id"]) if body.get("case_id") else None
    requirements = normalize_requirements(body.get("requirements", case.get("requirements", {}) if case else {}))
    requirements = {**requirements, "timezone": settings()["timezone"], "information_date": datetime.now(ZoneInfo(settings()["timezone"])).strftime("%Y-%m-%d %H:%M")}
    matching = match_products(products, requirements)
    if matching["excluded"]:
        raise HTTPException(422, "所选产品存在明确不符合的硬条件，请调整选项后生成推荐")
    by_id = {entry["product"]["id"]: entry for entry in matching["matched"] + matching["needs_verification"]}
    entries = [by_id[p["id"]] for p in products]
    text = body.get("text") or recommendation_text(entries, requirements)
    return store.put("recommendations", {"case_id": case["id"] if case else None, "product_ids": [p["id"] for p in products],
                                        "requirements_snapshot": requirements, "product_snapshots": products, "candidate_snapshots": entries, "text": text, "status": "PREPARED", "stale": False, "exports": []})


@app.put("/api/recommendations/{ident}")
def edit_recommendation(ident: str, body: dict):
    old = require("recommendations", ident)
    # Editing creates another version; previous text and exported assets are retained.
    return store.put("recommendations", {**old, "text": str(body.get("text", old["text"])), "status": "PREPARED"})


@app.get("/api/recommendations/{ident}/versions")
def recommendation_versions(ident: str):
    require("recommendations", ident)
    return store.versions("recommendations", ident)


@app.post("/api/recommendations/{ident}/export")
def export_recommendation(ident: str):
    from .exports import render_comparison
    record = require("recommendations", ident)
    export_id = uid()
    image_path = store.root / "exports" / f"{export_id}.png"
    text_path = store.root / "exports" / f"{export_id}.txt"
    render_comparison(record.get("candidate_snapshots", record["product_snapshots"]), record["requirements_snapshot"], record["text"], image_path)
    text_path.write_text(record["text"], encoding="utf-8", newline="")
    exported = store.put("exports", {"recommendation_id": ident, "recommendation_version": record["version"], "snapshot": record,
                                     "image_path": image_path.relative_to(store.root).as_posix(), "text_path": text_path.relative_to(store.root).as_posix(),
                                     "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(), "text_sha256": hashlib.sha256(text_path.read_bytes()).hexdigest()}, export_id)
    urls = {"image_url": f"/api/exports/{export_id}/image", "text_url": f"/api/exports/{export_id}/text"}
    with store.lock:
        current = require("recommendations", ident)
        # Rendering must never overwrite a concurrent edit or clear a stale flag.
        same_snapshot = current["version"] == record["version"]
        store.put("recommendations", {**current, **(urls if same_snapshot else {}), "exports": current.get("exports", []) + [exported["id"]]})
    return {**urls, "id": export_id, "recommendation_version": record["version"], "current_version_changed": not same_snapshot,
            "message": "已保存生成时的版本；编辑中的内容已更新，请重新生成以导出最新内容。" if not same_snapshot else "已保存此版本，可复制或下载；不会自动发送。"}


@app.get("/api/exports/{ident}/{kind}")
def exported_file(ident: str, kind: str):
    record = require("exports", ident)
    if kind not in {"image", "text"} or f"{kind}_path" not in record:
        raise HTTPException(404, "导出文件不存在")
    path = (store.root / record[f"{kind}_path"]).resolve()
    if not path.is_relative_to(store.root / "exports") or not path.exists():
        raise HTTPException(404, "导出文件不存在，请重新生成")
    return FileResponse(path, media_type="image/png" if kind == "image" else "text/plain; charset=utf-8", filename=f"选团建议-{ident[:8]}{path.suffix}", content_disposition_type="inline" if kind == "image" else "attachment")


@app.post("/api/weekly")
def weekly(body: dict):
    products = [product_snapshot(require("products", ident)) for ident in body.get("product_ids", [])]
    recommendations = [require("recommendations", ident) for ident in body.get("recommendation_ids", [])]
    if not products and not recommendations:
        raise HTTPException(422, "请至少选择一个产品或推荐版本")
    business_timezone = settings()["timezone"]
    reviewed_at = utcnow()
    information_date = datetime.fromisoformat(reviewed_at).astimezone(ZoneInfo(business_timezone)).strftime("%Y-%m-%d %H:%M")
    return store.put("weekly", {"title": body.get("title") or "本周产品资料", "product_snapshots": products, "recommendation_snapshots": recommendations, "product_ids": [p["id"] for p in products], "reviewed_at": reviewed_at,
                                "timezone": business_timezone, "information_date": information_date})


@app.post("/api/weekly/{ident}/export")
def export_weekly(ident: str):
    from .exports import recommendation_text
    record = require("weekly", ident)
    # Legacy records did not freeze a business timezone. Use the documented
    # default and their saved review instant, never the current export clock.
    business_timezone = record.get("timezone") or DEFAULT_SETTINGS["timezone"]
    information_date = record.get("information_date")
    if not information_date:
        try:
            reviewed_at = datetime.fromisoformat(str(record.get("reviewed_at")).replace("Z", "+00:00"))
            if reviewed_at.tzinfo is None:
                raise ValueError("Legacy review instant has no timezone")
            information_date = reviewed_at.astimezone(ZoneInfo(business_timezone)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, KeyError):
            information_date = "未知（旧记录未保存可确认的整理时间）"
        record = {**record, "timezone": business_timezone, "information_date": information_date}
    timezone_label = {"Asia/Shanghai": "中国标准时间", "Asia/Hong_Kong": "香港时间", "UTC": "协调世界时"}.get(business_timezone, business_timezone)
    lines = [record["title"], f"资料整理时间：{information_date}（{timezone_label}）", ""]
    if record.get("product_snapshots"):
        lines.append(recommendation_text(record["product_snapshots"], {"information_date": information_date, "timezone": business_timezone}))
    for rec in record.get("recommendation_snapshots", []):
        lines.extend(["\n接待建议", rec["text"]])
    export_id = uid()
    path = store.root / "exports" / f"{export_id}.txt"
    path.write_text("\n".join(lines), encoding="utf-8", newline="")
    store.put("exports", {"weekly_id": ident, "snapshot": record, "text_path": path.relative_to(store.root).as_posix()}, export_id)
    result = {"text_url": f"/api/exports/{export_id}/text"}
    store.put("weekly", {**record, **result})
    return result


@app.post("/api/backup")
def backup():
    path = store.backup()
    return {"path": str(path), "message": "备份已保存，包含原始文件和导出版本，不包含 AI 密钥。"}


@app.post("/api/restore")
def restore(body: dict):
    return store.restore_test(Path(body.get("path", "")))


def retrieve_media(adapter, source, job_id):
    """Retry media independently of the discovery watermark under UI ownership."""
    from .collectors import CollectorBlocked
    if not foreground_collection_enabled():
        _block_foreground_job(require("jobs", job_id))
        return
    staging = store.root / "staging"
    staging.mkdir(exist_ok=True)
    outstanding = [a for a in store.all("attachments") if a.get("source_id") == source["id"] and a.get("state") != "SAVED" and a.get("acquisition_mode") != "operator_positioned"]
    for attachment in outstanding:
        if not foreground_collection_enabled():
            _block_foreground_job(require("jobs", job_id))
            return
        if require("jobs", job_id)["state"] in {"PAUSING", "CANCELED"}:
            return
        if attachment.get("attempts", 0) >= 3:
            continue
        target = staging / attachment["id"]
        try:
            result = adapter.fetch_attachment(attachment["retrieval_reference"], target)
            if result.get("state") != "SAVED":
                raise ValueError("Attachment unavailable")
            received = Path(result.get("path", target)).resolve()
            if not received.is_relative_to(staging.resolve()) or not received.is_file() or received.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Invalid saved attachment")
            content = received.read_bytes()
            if not content or (result.get("sha256") and hashlib.sha256(content).hexdigest() != result["sha256"]):
                raise ValueError("Attachment checksum mismatch")
            blob = store.save_blob(content)
            attachment = {**attachment, **blob, "state": "SAVED", "quality": result.get("quality", "unknown"), "mime": mimetypes.guess_type(attachment.get("name", ""))[0] or "application/octet-stream", "url": f"/api/attachments/{attachment['id']}", "retrieved_at": utcnow()}
        except CollectorBlocked:
            raise
        except Exception:
            attachment = {**attachment, "state": "RETRY", "last_error": "附件暂未取得，请保留微信来源并稍后重试；未计为已保存。"}
        attachment["attempts"] = attachment.get("attempts", 0) + 1
        store.put("attachments", attachment)
        material = require("materials", attachment["material_id"])
        store.put("materials", {**material, "attachments": [attachment if a["id"] == attachment["id"] else a for a in material.get("attachments", [])]})
        if attachment["state"] == "SAVED":
            queue_analysis(material["id"])


def refresh_counts(job, source):
    items = [m for m in store.all("materials") if m.get("source_id") == source["id"]]
    attachments = [a for a in store.all("attachments") if a.get("source_id") == source["id"]]
    job["counts"].update(saved=sum(a.get("state") == "SAVED" for a in attachments),
                         originals=sum(a.get("state") == "SAVED" and a.get("quality") == "original" for a in attachments),
                         previews=sum(a.get("state") == "SAVED" and a.get("quality") in {"preview", "screenshot"} for a in attachments),
                         media_failures=sum(a.get("state") != "SAVED" for a in attachments),
                         unresolved_dates=sum(m.get("time_decision") == "UNCERTAIN" for m in items),
                         analyzed=sum(m.get("state") == "ANALYZED" for m in items),
                         unsupported=sum(m.get("type") not in {None, "text", "image", "file", "quote", "post", "time"} for m in items))
    times = [m.get("time_evidence", {}).get("start") for m in items if m.get("time_evidence", {}).get("start")]
    job["observed_earliest"] = min(times) if times else None
    job["observed_latest"] = max(times) if times else None
    job["counts_scope"] = "source_total_except_discovered_this_job"
    return job


def refresh_native_counts(job):
    observations = [o for o in store.all("page_observations") if o.get("job_id") == job["id"]]
    items = [m for m in store.all("materials") if m.get("job_id") == job["id"]]
    media = [a for a in store.all("attachments") if a.get("job_id") == job["id"] and a.get("role") == "supplier_media"]
    saved = sum(a.get("state") == "SAVED" for a in media)
    counts = {**job.get("counts", {}), "page_observations": len(observations), "parsed_records": len(items),
              "discovered": len(items), "acquired_attachments": saved, "saved": saved,
              "unresolved_associations": sum(o.get("unresolved_associations", 0) for o in observations) +
                  sum(not a.get("observation_id") and a.get("association_state") != "VERIFIED" for a in media),
              "media_failures": sum(a.get("state") not in {"SAVED", "UNAVAILABLE"} for a in media),
              "media_unavailable": sum(a.get("state") == "UNAVAILABLE" for a in media),
              "unresolved_dates": sum(not m.get("source_time") for m in items),
              "originals": sum(a.get("state") == "SAVED" and a.get("quality") == "original" for a in media),
              "previews": sum(a.get("state") == "SAVED" and a.get("quality") in {"preview", "screenshot"} for a in media)}
    return {**job, "counts": counts, "counts_scope": "this_job"}


def _native_safe_boundary(ident):
    job = require("jobs", ident)
    if job["state"] == "PAUSING":
        if job.get("acquisition_mode") == "operator_positioned":
            job = refresh_native_counts(job)
        store.put("jobs", {**job, "state": "PAUSED", "stop_reason": "已在安全边界暂停；页面、文件和检查点已保留。"})
        return False
    if job["state"] == "RUNNING" and not foreground_collection_enabled():
        _block_foreground_job(job)
        return False
    return job["state"] == "RUNNING"


def retrieve_native_media(adapter, job_id, staging):
    from .collectors import CollectorBlocked
    pending = [a for a in store.all("attachments") if a.get("job_id") == job_id and a.get("role") == "supplier_media"
               and a.get("state") in {"PENDING", "RETRY"} and a.get("attempts", 0) < 3]
    for attachment in pending:
        if not _native_safe_boundary(job_id):
            return
        if not attachment.get("retrieval_reference"):
            continue
        try:
            result = adapter.fetch_attachment(attachment["retrieval_reference"], staging / attachment["id"])
            store.update_native_attachment(attachment, result, staging)
        except CollectorBlocked:
            raise
        except Exception:
            store.update_native_attachment(attachment, {"state": "RETRY", "reason": "附件保存校验未通过，已保留独立重试记录。"}, staging)


def run_positioned_scan(ident, source, account):
    """Run under the existing UI lock; only driver-produced staging files enter storage."""
    from .collectors import CollectorBlocked
    job = require("jobs", ident)
    try:
        session = _session_for_scan(job["session_id"], source)
    except HTTPException as exc:
        raise CollectorBlocked(str(exc.detail), "SESSION_EXPIRED") from exc
    time.sleep(job.get("start_delay_seconds", 3))
    if not _native_safe_boundary(ident):
        return
    try:
        from .collectors.operator_positioned import make_adapter
    except ImportError as exc:
        raise CollectorBlocked("人工定位自动采集组件尚未适配完成，请由技术人员继续适配。", "NATIVE_DRIVER_UNAVAILABLE") from exc
    staging = store.root / "staging" / "native_sessions" / session["id"] / "jobs" / ident
    staging.mkdir(parents=True, exist_ok=True)
    adapter = make_adapter(session, staging)
    adapter.resolve_source(source, account)
    retrieve_native_media(adapter, ident, staging)
    iterator = iter(adapter.iterate_items(source, job["scope"], job.get("checkpoint")))
    pages_this_attempt, yields = 0, 0
    while _native_safe_boundary(ident):
        # A long job cannot continue on an expired operator lease.
        try:
            _session_for_scan(session["id"], source)
        except HTTPException as exc:
            raise CollectorBlocked(str(exc.detail), "SESSION_EXPIRED") from exc
        try:
            page = next(iterator)
        except StopIteration:
            break
        yields += 1
        current = require("jobs", ident)
        store.ingest_native_page(source, page, current, session, staging)
        pages_this_attempt += len(page.get("observations") or [])
        if not _native_safe_boundary(ident):
            return
        retrieve_native_media(adapter, ident, staging)
        if not _native_safe_boundary(ident):
            return
        current = refresh_native_counts(require("jobs", ident))
        coverage = page.get("coverage", "UNKNOWN")
        evidence = page.get("endpoint_evidence") if coverage == "ACCESSIBLE_END_REACHED" else page.get("boundary_evidence")
        proven = coverage in {"ACCESSIBLE_END_REACHED", "REQUESTED_BOUNDARY_REACHED"} and isinstance(evidence, dict) and evidence.get("verified") is True
        if coverage in {"ACCESSIBLE_END_REACHED", "REQUESTED_BOUNDARY_REACHED"} and not proven:
            coverage = "PARTIAL_WITH_GAPS"
        terminal = bool(page.get("terminal")) or pages_this_attempt >= current["page_budget"] or yields >= current["page_budget"] * 5
        current.update(coverage=coverage, stop_reason=page.get("stop_reason") or "正在人工定位后自动采集微信", stop_code=page.get("stop_code"))
        if terminal:
            has_gaps = any(current["counts"].get(key, 0) for key in ("media_failures", "media_unavailable", "unresolved_associations")) or any(
                o.get("parse_state") == "UNPARSED" for o in store.all("page_observations") if o.get("job_id") == ident)
            current["state"] = "COMPLETED" if proven and not has_gaps else "PARTIAL"
            if not proven and coverage == "UNKNOWN":
                current["coverage"] = "PARTIAL_WITH_GAPS"
            if not page.get("terminal"):
                current["stop_reason"] = "本次页数预算已到达；仅保留实际观察结果，尚未证明已读完历史。"
        # The user may pause/cancel while the driver finishes the current page.
        with store.lock:
            latest = require("jobs", ident)
            if latest["state"] in {"PAUSING", "PAUSED", "CANCELED"}:
                current["state"] = latest["state"]
            store.put("jobs", current)
        if terminal:
            _native_safe_boundary(ident)
            return
    current = refresh_native_counts(require("jobs", ident))
    if current["state"] == "RUNNING":
        store.put("jobs", {**current, "state": "PARTIAL", "coverage": "STALLED_UNPROVEN_END",
            "stop_reason": "已保存本轮页面与附件，但没有足够证据证明已到达所选范围终点。"})


def run_scan(ident):
    from .collectors import get_adapter
    with ui_lock:
        job = require("jobs", ident)
        if job["state"] not in {"QUEUED", "RUNNING"}:
            return
        if not foreground_collection_enabled():
            _block_foreground_job(job)
            return
        job = store.put("jobs", {**job, "state": "RUNNING", "stop_reason": "正在采集微信"})
        source = require("sources", job["source_id"])
        account = require("accounts", source["account_id"])
        try:
            if job.get("acquisition_mode") == "operator_positioned":
                run_positioned_scan(ident, source, account)
                return
            adapter = get_adapter(source["kind"])
            adapter.resolve_source(source, account)
            retrieve_media(adapter, source, ident)
            iterator = iter(adapter.iterate_items(source, job["scope"], job.get("checkpoint")))
            while _native_safe_boundary(ident):
                try:
                    page = next(iterator)
                except StopIteration:
                    break
                current = require("jobs", ident)
                if current["state"] in {"PAUSING", "CANCELED"}:
                    if current["state"] == "PAUSING":
                        store.put("jobs", {**current, "state": "PAUSED", "stop_reason": "已在安全边界暂停，检查点已保存"})
                    return
                job = current
                acquired = store.ingest_page(source, page.get("items", []), page.get("checkpoint"), job)
                for item in acquired:
                    queue_analysis(item["id"])
                retrieve_media(adapter, source, ident)
                if not _native_safe_boundary(ident):
                    return
                job = require("jobs", ident)
                if job["state"] in {"PAUSING", "CANCELED"}:
                    if job["state"] == "PAUSING":
                        store.put("jobs", {**job, "state": "PAUSED", "stop_reason": "已在安全边界暂停，检查点已保存"})
                    return
                job = refresh_counts(job, source)
                job["coverage"] = page.get("coverage", "UNKNOWN")
                job["stop_reason"] = page.get("stop_reason", "")
                if page.get("terminal"):
                    proven = job["coverage"] in {"REQUESTED_BOUNDARY_REACHED", "ACCESSIBLE_END_REACHED"}
                    job["state"] = "COMPLETED" if proven and not job["counts"].get("media_failures") else "PARTIAL"
                    if proven:
                        checkpoint = require("checkpoints", source["id"])
                        store.put("checkpoints", {**checkpoint, "last_cutoff": job["scope"]["upper"], "coverage": job["coverage"]})
                    if proven and job["counts"].get("media_failures"):
                        job["coverage"] = "PARTIAL_WITH_GAPS"
                store.put("jobs", job)
                if page.get("terminal"):
                    return
            job = require("jobs", ident)
            if job["state"] == "RUNNING":
                store.put("jobs", {**job, "state": "PARTIAL", "coverage": "STALLED_UNPROVEN_END", "stop_reason": "遍历结束，但未取得可访问历史终点的证据"})
        except Exception as exc:
            status, code, reason = _native_failure(exc)
            current = require("jobs", ident)
            if current.get("acquisition_mode") == "operator_positioned":
                current = refresh_native_counts(current)
                session = store.get("native_sessions", current.get("session_id"))
                if session and code in NATIVE_INVALIDATION_CODES:
                    store.put("native_sessions", {**session, "state": "EXPIRED", "stop_code": code, "reason": reason})
            if current["state"] == "PAUSING":
                store.put("jobs", {**current, "state": "PAUSED", "stop_reason": "已暂停，已采集素材与检查点仍保留。"})
            elif current["state"] != "CANCELED":
                store.put("jobs", {**current, "state": status, "coverage": "PARTIAL_WITH_GAPS" if current.get("counts", {}).get("page_observations") else "UNKNOWN", "stop_reason": reason, "stop_code": code})


@app.post("/api/scans")
def scans(body: dict):
    from .time_semantics import make_scope
    if not foreground_collection_enabled():
        return _foreground_disabled_response()
    if body.get("mode") not in {"ALL_ACCESSIBLE", "SINCE", "INCREMENTAL"}:
        raise HTTPException(422, "请选择全部可访问历史、指定时间起或增量采集")
    if not body.get("source_ids"):
        raise HTTPException(422, "请先选择微信来源")
    sources = [require("sources", ident) for ident in body["source_ids"]]
    if any(s["kind"] == "upload" for s in sources):
        raise HTTPException(422, "上传来源无需微信扫描")
    now = datetime.now(timezone.utc)
    acquisition_mode = body.get("acquisition_mode", "unattended")
    if acquisition_mode not in {"unattended", "operator_positioned"}:
        raise HTTPException(422, "请选择已支持的采集方式")
    if acquisition_mode == "operator_positioned":
        if len(sources) != 1 or not body.get("session_id"):
            raise HTTPException(422, "当前页面试采集每次仅支持一个已确认的来源会话")
        if body["mode"] != "ALL_ACCESSIBLE":
            raise HTTPException(422, "当前页面模式仅进行有限页数试采集，尚不支持以日期或增量完成范围为依据")
        source = sources[0]
        session = _session_for_scan(body["session_id"], source)
        budget = _native_budget(body.get("page_budget", session["page_budget"]))
        if budget > session["page_budget"]:
            raise HTTPException(422, "试采集页数不能超过本次会话确认的预算")
        if any(j.get("session_id") == session["id"] and j["state"] in {"QUEUED", "RUNNING", "PAUSING"} for j in store.all("jobs")):
            raise HTTPException(409, "本次来源会话已有采集任务，请先完成或暂停")
        delay = _native_delay(body.get("start_delay_seconds", 3))
        scope = make_scope("ALL_ACCESSIBLE", timezone=body.get("timezone", settings()["timezone"]), now=now)
        scope.update(page_budget=budget, bounded_operator_positioned=True, requested_surface=session.get("source_kind"))
        job = store.put("jobs", {"source_id": source["id"], "source_name": source["display_name"], "account_id": source["account_id"],
            "acquisition_mode": "operator_positioned", "acquisition_method": "operator_positioned_native", "source_positioning": "operator_assisted",
            "identity_scope": "session", "session_id": session["id"], "mode": "ALL_ACCESSIBLE", "page_budget": budget,
            "scope": scope, "requested_start": None, "cutoff_at": scope["upper"], "checkpoint": None,
            "state": "QUEUED", "coverage": "UNKNOWN", "counts_scope": "this_job", "start_delay_seconds": delay,
            "counts": {"page_observations": 0, "parsed_records": 0, "acquired_attachments": 0, "unresolved_associations": 0,
                       "discovered": 0, "saved": 0, "originals": 0, "previews": 0, "media_failures": 0, "media_unavailable": 0,
                       "unsupported": 0, "unresolved_dates": 0, "analyzed": 0},
            "stop_reason": "人工定位后自动采集：即将核对已打开来源，仅采集本次确认的有限页数。"})
        wechat_pool.submit(run_scan, job["id"])
        return {"jobs": [job]}
    jobs = []
    for source in sources:
        checkpoint = store.get("checkpoints", source["id"])
        if checkpoint and checkpoint["account_id"] != source["account_id"]:
            raise HTTPException(409, "检查点账号不一致，请重新核对账号")
        scope = make_scope(body["mode"], body.get("start"), body.get("timezone", settings()["timezone"]), now, checkpoint)
        job = store.put("jobs", {"source_id": source["id"], "source_name": source["display_name"], "account_id": source["account_id"],
                                 "mode": body["mode"], "scope": scope, "requested_start": scope.get("start"), "cutoff_at": scope["upper"],
                                 "state": "QUEUED", "coverage": "UNKNOWN", "checkpoint": checkpoint.get("cursor") if checkpoint else None,
                                 "counts": {"discovered": 0, "saved": 0, "originals": 0, "previews": 0, "media_failures": 0, "unsupported": 0, "unresolved_dates": 0, "analyzed": 0}, "stop_reason": "等待微信采集窗口"})
        jobs.append(job)
        wechat_pool.submit(run_scan, job["id"])
    return {"jobs": jobs}


@app.post("/api/jobs/{ident}/{action}")
def job_action(ident: str, action: str, body: dict | None = None):
    job = require("jobs", ident)
    if action == "pause":
        if job["state"] not in {"RUNNING", "QUEUED"}:
            raise HTTPException(409, "该任务目前无需暂停")
        return store.put("jobs", {**job, "state": "PAUSING" if job["state"] == "RUNNING" else "PAUSED"})
    if action == "cancel":
        return store.put("jobs", {**job, "state": "CANCELED", "stop_reason": "已取消，已保存的素材仍保留"})
    if action in {"resume", "retry"}:
        if not foreground_collection_enabled():
            return _foreground_disabled_response()
        if job["state"] in {"RUNNING", "QUEUED", "PAUSING"}:
            raise HTTPException(409, "任务已在执行或等待中")
        updates = {}
        if job.get("acquisition_mode") == "operator_positioned":
            body = body or {}
            source = require("sources", job["source_id"])
            session = _session_for_scan(body.get("session_id") or job["session_id"], source)
            if any(other["id"] != ident and other.get("session_id") == session["id"] and other["state"] in {"QUEUED", "RUNNING", "PAUSING"} for other in store.all("jobs")):
                raise HTTPException(409, "本次来源会话已有其他采集任务，请先暂停或完成")
            budget = min(job["page_budget"], session["page_budget"])
            updates = {"session_id": session["id"], "previous_session_id": job.get("session_id"), "page_budget": budget,
                       "scope": {**job["scope"], "page_budget": budget}, "start_delay_seconds": _native_delay(body.get("start_delay_seconds", 3))}
        job = store.put("jobs", {**job, **updates, "state": "QUEUED", "stop_reason": "等待继续采集；恢复时将核对已保存的重叠位置。" if updates else "等待继续采集"})
        if action == "retry":
            for attachment in store.all("attachments"):
                in_scope = attachment.get("job_id") == ident if updates else attachment.get("source_id") == job["source_id"] and attachment.get("acquisition_mode") != "operator_positioned"
                if in_scope and attachment.get("state") in {"PENDING", "RETRY"}:
                    store.put("attachments", {**attachment, "attempts": 0})
        wechat_pool.submit(run_scan, ident)
        return job
    raise HTTPException(404, "不支持的任务操作")


FRONTEND = ROOT / "frontend" / "dist"
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
