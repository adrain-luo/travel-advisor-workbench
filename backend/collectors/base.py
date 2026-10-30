"""Acquisition adapters. Live UI drivers remain separate from business storage.

The caller must commit each page's items and retry records before persisting its
checkpoint. Yielding a page does not mean it has been committed. Native traversal
never equates an empty/repeated viewport with a proven history endpoint.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from backend.time_semantics import classify_time, parse_source_time


class CollectorBlocked(RuntimeError):
    def __init__(self, message: str, code: str = "NEEDS_USER_ACTION"):
        super().__init__(message)
        self.code = code
        self.message = message


class DesktopDriver(Protocol):
    """Read-oriented selected-window route; all actions share the UI worker lock."""
    def probe(self, kind: str) -> dict: ...
    def resolve(self, source: dict, account: dict) -> dict: ...
    def verify(self, source: dict, account: dict) -> None: ...
    def read_page(self, source: dict) -> dict: ...
    def previous_page(self, source: dict) -> None: ...
    def fetch(self, reference: dict, destination: Path) -> dict: ...


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def normalize_item(raw: dict, source: dict, observed_at: str, position: int, scope: dict) -> dict:
    evidence = raw.get("time_evidence") or parse_source_time(
        raw.get("source_time_raw"), observed_at, scope.get("timezone", "Asia/Shanghai"),
        inherited_separator=raw.get("inherited_separator", False))
    content = {"account_id": source.get("account_id"), "source_id": source["id"],
               "author": raw.get("author"), "text": raw.get("text", ""),
               "type": raw.get("type", "text"), "time": evidence,
               "attachments": [{k: x.get(k) for k in ("name", "type", "media_index", "source_url")}
                               for x in raw.get("attachments", [])]}
    # Observation time is not an event identity. Repeated legitimate source posts
    # still need sequence/overlap evidence before any candidate can be merged.
    content["time"] = {k: evidence.get(k) for k in ("source_time_raw", "start", "end", "precision", "status")}
    fingerprint = _fingerprint(content)
    stable = bool(raw.get("native_id_verified") and raw.get("native_id"))
    event_key = _fingerprint({"source": source["id"], "account": source.get("account_id"),
                              "id": raw["native_id"]}) if stable else None
    result = {
        **raw, "source_id": source["id"], "account_id": source.get("account_id"),
        "text": raw.get("text", ""), "author": raw.get("author"), "type": raw.get("type", "text"),
        "observed_at": observed_at, "time_evidence": evidence,
        "source_time_raw": evidence.get("source_time_raw"),
        "source_time": evidence.get("source_time"), "time_decision": classify_time(evidence, scope),
        "fingerprint": fingerprint, "event_key": event_key, "sequence_position": position,
        "identity_confidence": "verified_native" if stable else "overlap_required",
        "attachments": raw.get("attachments", []),
        "issues": list(raw.get("issues", [])),
    }
    if result["type"] not in {"text", "image", "file", "quote", "post", "time"}:
        result["issues"].append("已保留此类型的原始记录；尚不支持完整内容解析。")
    if result["type"] in {"quote", "merge"} and not raw.get("nested_content_complete"):
        result["issues"].append("引用或合并内容未完整展开；不能视为已分析全部附件。")
    return result


class WeChatAdapter:
    kind = "wechat"

    def __init__(self, driver: DesktopDriver | None = None):
        if driver is None:
            from .native_uia import NativeUIADriver
            driver = NativeUIADriver()
        self.driver = driver
        self.source = None
        self.account = None

    def probe_capabilities(self) -> dict:
        return self.driver.probe(self.kind)

    def resolve_source(self, source: dict, account: dict | None = None) -> dict:
        account = account or source.get("account") or {}
        if not source.get("id") or not source.get("display_name"):
            raise CollectorBlocked("请先在素材中心选择一个具体微信来源。", "SOURCE_NOT_SELECTED")
        if source.get("kind") != self.kind:
            raise CollectorBlocked("来源类型与采集器不一致，请重新选择。", "SOURCE_TYPE_MISMATCH")
        if not account.get("id") or source.get("account_id") != account.get("id"):
            raise CollectorBlocked("请先绑定当前登录账号；不能使用其他账号的来源或进度。", "ACCOUNT_NOT_BOUND")
        capability = self.probe_capabilities()
        if not capability.get("available"):
            raise CollectorBlocked(capability["reason"], capability.get("code", "ADAPTER_BLOCKED"))
        resolved = self.driver.resolve(source, account)
        self.source, self.account = source, account
        return resolved

    def iterate_items(self, source: dict, scope: dict, checkpoint: dict | None = None):
        """Traverse real pages, stopping conservatively on repeated views or caps.

        Resume reopens the verified target and replays loaded pages; it never trusts
        stale UI handles as durable cursors. Storage reconciles events separately.
        """
        account = self.account or source.get("account") or {}
        if self.source != source:
            self.resolve_source(source, account)
        checkpoint = checkpoint or {}
        if checkpoint.get("account_id") not in (None, account.get("id")):
            raise CollectorBlocked("采集进度属于其他微信账号，请为当前账号新建采集。", "CHECKPOINT_ACCOUNT_MISMATCH")
        if checkpoint.get("source_id") not in (None, source["id"]):
            raise CollectorBlocked("采集进度属于其他来源，已暂停以避免混采。", "CHECKPOINT_SOURCE_MISMATCH")
        seen_viewports = set()
        previous_context = []
        previous_runtime_ids = set()
        pages = 0
        new_pages = 0
        replayed_pages = 0
        limit = min(max(int(scope.get("page_budget", 100)), 1), 10000)
        # A new scan has a different frozen cutoff and must not inherit a prior
        # run's cursor. Only continuation of this exact scope searches an anchor.
        anchor = checkpoint.get("overlap_context") or []
        prior_anchor = checkpoint.get("prior_overlap_context") or []
        resume_pending = bool(anchor and checkpoint.get("run_cutoff") == scope["upper"])
        replay_limit = max(1, int(scope.get("replay_budget", max(100, int(checkpoint.get("pages_observed", 0)) + 50))))
        while new_pages < limit:
            self.driver.verify(source, account)
            page = self.driver.read_page(source)
            self.driver.verify(source, account)
            observed = page.get("observed_at") or datetime.now(timezone.utc).isoformat()
            items = [normalize_item(raw, source, observed, index, scope)
                     for index, raw in enumerate(page.get("items", []))]
            viewport = _fingerprint([{"fingerprint": item["fingerprint"], "runtime": item.get("ui_runtime_id")} for item in items])
            pages += 1
            current_context = [item["fingerprint"] for item in items]
            replayed = resume_pending
            if replayed:
                replayed_pages += 1
                # This is traversal alignment, not cross-run event deduplication.
                # A repeated identical block or changed context is not evidence
                # that the saved position has been reached.
                anchor_matches = (len(set(anchor)) >= 2 and current_context == anchor
                                  and (not prior_anchor or previous_context == prior_anchor))
                if anchor_matches:
                    resume_pending = False
            else:
                new_pages += 1
            current_cp = {"account_id": account["id"], "source_id": source["id"],
                  "pages_observed": pages, "viewport": viewport,
                  "overlap_context": current_context, "prior_overlap_context": previous_context,
                  "run_cutoff": scope["upper"], "resume_strategy": "reopen_and_reconcile",
                  "new_pages_observed": new_pages, "replay_pages_observed": replayed_pages,
                  "resume_anchor_status": "SEARCHING" if resume_pending else "MATCHED_CONTEXT" if replayed_pages else "NOT_REQUIRED",
                  "ordering_proven": bool(page.get("ordering_proven", False))}
            # Pausing while replaying must not replace the previously committed
            # frontier with an earlier page and lose forward progress.
            cp = {**checkpoint, "replay_pages_observed": replayed_pages, "resume_anchor_status": "SEARCHING"} if resume_pending else current_cp
            discovered = len(items)
            # Runtime IDs are used only inside this uninterrupted traversal. They
            # are never promoted to cross-navigation persistent event identity.
            fresh = []
            for item in items:
                item["target_identity_verified"] = True
                item["identity_verified"] = item["identity_confidence"] == "verified_native"
                runtime_id = tuple(item.get("ui_runtime_id") or ())
                if runtime_id and runtime_id in previous_runtime_ids:
                    continue
                if item["time_decision"] not in {"AFTER", "BEFORE"}:
                    fresh.append(item)
            next_runtime_ids = {tuple(item["ui_runtime_id"]) for item in items if item.get("ui_runtime_id")}
            if not previous_runtime_ids and previous_context:
                fresh = reconcile_adjacent_page(previous_context, items, fresh)
            endpoint = page.get("endpoint_evidence")
            # An enrolled source-specific endpoint control is stronger than a
            # scrollbar position. The driver must retain its observed text.
            if endpoint and endpoint.get("verified") and endpoint.get("text"):
                cp = current_cp
                cp["last_cutoff"] = scope["upper"]
                yield {"items": fresh, "checkpoint": cp, "coverage": "ACCESSIBLE_END_REACHED", "discovered": discovered,
                       "stop_reason": "已到达该来源当前可访问的界面终点。", "terminal": True,
                       "endpoint_evidence": endpoint, "previous_context": previous_context, "replayed": replayed}
                return
            if viewport in seen_viewports or not items:
                yield {"items": [], "checkpoint": cp, "coverage": "STALLED_UNPROVEN_END", "discovered": discovered,
                       "stop_reason": "界面重复或为空，无法证明已读完；已保留进度，可重试或指定日期重扫。",
                       "terminal": True, "previous_context": previous_context}
                return
            seen_viewports.add(viewport)
            yield {"items": fresh, "checkpoint": cp, "coverage": "UNKNOWN", "terminal": False, "discovered": discovered,
                   "stop_reason": None, "previous_context": previous_context, "replayed": replayed}
            previous_context = current_context
            previous_runtime_ids = next_runtime_ids
            if resume_pending and replayed_pages >= replay_limit:
                yield {"items": [], "checkpoint": cp, "coverage": "PARTIAL_WITH_GAPS", "terminal": True,
                       "stop_reason": "重放预算内无法确认上次采集位置；原检查点已保留，请核对来源或进行指定日期重扫。",
                       "resource_cap": True, "resume_anchor_missing": True}
                return
            if new_pages >= limit:
                break
            self.driver.verify(source, account)
            self.driver.previous_page(source)
        yield {"items": [], "checkpoint": cp, "coverage": "PARTIAL_WITH_GAPS", "terminal": True,
               "stop_reason": "本轮资源预算已到达，采集尚未完成；请继续采集。", "resource_cap": True}

    def fetch_attachment(self, reference: dict, destination: Path) -> dict:
        if not self.source or not self.account:
            raise CollectorBlocked("请重新验证来源后重试附件下载。", "TARGET_NOT_VERIFIED")
        self.driver.verify(self.source, self.account)
        return self.driver.fetch(reference, Path(destination))


class WeChatGroupAdapter(WeChatAdapter):
    kind = "group"


class WeChatMomentsAdapter(WeChatAdapter):
    kind = "moments"

    def resolve_source(self, source, account=None):
        resolved = super().resolve_source(source, account)
        if resolved.get("surface") != "contact_album":
            self.source = None
            raise CollectorBlocked("当前界面不是该联系人自己的朋友圈历史；综合动态流不能替代联系人历史。", "CONTACT_ALBUM_REQUIRED")
        return resolved


class UploadAdapter:
    kind = "upload"

    def probe_capabilities(self):
        return {"kind": "upload", "status": "PASS", "available": True,
                "reason": "支持用户主动上传的文件和粘贴文字。", "features": {"text": True, "files": True}}

    def resolve_source(self, source, account=None):
        if not source.get("id"):
            raise CollectorBlocked("请创建上传来源。", "SOURCE_NOT_SELECTED")
        return source

    def iterate_items(self, source, scope, checkpoint=None):
        self.resolve_source(source)
        now = datetime.now(timezone.utc).isoformat()
        items = []
        for index, entry in enumerate(source.get("items", [])):
            raw = {"text": entry.get("text", ""), "type": "text" if "text" in entry else "file",
                   "author": entry.get("supplier"), "source_time_raw": entry.get("source_time_raw"),
                   "attachments": []}
            if entry.get("path"):
                path = Path(entry["path"])
                raw["attachments"].append({"name": path.name, "path": str(path), "quality": "original",
                                           "state": "PENDING", "type": mimetypes.guess_type(path.name)[0]})
            items.append(normalize_item(raw, source, now, index, scope))
        yield {"items": items, "checkpoint": {"source_id": source["id"], "last_cutoff": scope["upper"]},
               "coverage": "REQUESTED_BOUNDARY_REACHED", "terminal": True, "stop_reason": "所选上传内容已登记。"}

    def fetch_attachment(self, reference, destination):
        source = Path(reference["path"])
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        shutil.copyfile(source, partial)
        digest = hashlib.sha256(partial.read_bytes()).hexdigest()
        if partial.stat().st_size != source.stat().st_size:
            return {"state": "RETRY", "quality": "original", "reason": "文件复制未完成，请重试。"}
        os.replace(partial, destination)
        return {"state": "SAVED", "quality": "original", "path": str(destination), "sha256": digest}


def get_adapter(kind: str, driver: DesktopDriver | None = None):
    classes = {"group": WeChatGroupAdapter, "moments": WeChatMomentsAdapter, "upload": UploadAdapter}
    if kind not in classes:
        raise ValueError("不支持的来源类型。")
    return classes[kind]() if kind == "upload" else classes[kind](driver)


def reconcile_adjacent_page(previous: list[str], current: list[dict], retained: list[dict]) -> list[dict]:
    """Reconcile only unique, multi-item overlap across adjacent traversal pages.

    A singleton or repeated identical block cannot distinguish a repeated post
    from overlapping UI content and is deliberately retained with uncertainty.
    """
    values = [item["fingerprint"] for item in current]
    candidates = []
    for size in range(2, min(len(previous), len(values)) + 1):
        if previous[-size:] == values[:size] and len(set(values[:size])) >= 2:
            candidates.append(set(range(size)))
        if previous[:size] == values[-size:] and len(set(values[-size:])) >= 2:
            candidates.append(set(range(len(values) - size, len(values))))
    if not candidates:
        return retained
    maximum = max(len(x) for x in candidates)
    best = [x for x in candidates if len(x) == maximum]
    if len(best) != 1:
        return retained
    overlap = best[0]
    # Require an anchor fingerprint unique in both pages. Repeated blocks remain
    # uncertain even if a longest common sequence happens to exist.
    if not any(previous.count(values[index]) == values.count(values[index]) == 1 for index in overlap):
        return retained
    return [item for item in retained if item["sequence_position"] not in overlap]
