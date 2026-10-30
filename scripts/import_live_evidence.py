"""Import two selected-source, manually acquired live observations while offline.

This is evidence preservation, not a scanner, upload adapter, fixture seed, or
proof of history coverage. Local IDs below identify this one import only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.extraction import ExtractedProduct
from backend.store import Store, encode, utcnow
from backend.time_semantics import parse_source_time

EVIDENCE_ROOT = PROJECT_ROOT / ".local" / "live-evidence"
METHOD = "assistant_native_ui_manual"
NOTE = "自动采集尚未验证；本条为所选来源实机人工辅助采集证据"
ACCOUNT_ID = "collector-account-001"
GROUP_SOURCE_ID = "local-evidence-20261025-group"
MOMENTS_SOURCE_ID = "local-evidence-20261025-moments"
GROUP_ITEM_ID = "local-evidence-20261025-group-poster"
MOMENTS_ITEM_ID = "local-evidence-20261025-moments-post"
OBSERVATION_DATE = "2026-10-25"
ANCHOR = "2026-10-25T00:00:00+08:00"
FILES = {
    "account-profile.png": "account_identity_screenshot",
    "group-selected-poster.jpg": "client_saved_media",
    "group-selected-page1.png": "selected_group_context_screenshot",
    "group-history-timestamps.png": "selected_group_message_time_screenshot",
    "moments-selected-post.jpg": "client_saved_media",
    "moments-post-detail.png": "selected_contact_post_time_screenshot",
    "moments-album-page1.png": "selected_contact_album_screenshot",
}

GROUP_TRANSCRIPT = """【人工核读所选群海报，保留不确定项】
庐江温泉 特价抢购
汤池一号泉漂浮温泉·矾花源纯玩1日游
活动时间：10月20日—11月8日（海报未标年份）
128，大小同价
马鞍山起止+20元/人
海报角标：LZTS（未据此确认供应商主体）
以上仅为已保存海报的保守文字转录，不是供应商确认。"""

MOMENTS_TRANSCRIPT = """【人工核读所选联系人朋友圈帖子与海报】
发帖联系人：完美新疆西北赵照18552600189
帖子时间原文：昨天 09:07（观察日期：2026年10月25日，中国标准时间）
海报品牌：完美新疆
纯净双湖，双飞8日游—冬季版
纯玩无购物、无自费、无隐形消费（海报原文声明）
乌鲁木齐、二进赛里木湖、喀纳斯、禾木、阿勒泰、S21沙漠高速
6280：11月20日—12月9日
6480：12月10日—12月20日
7980：12月21日—1月4日
三个区间均未标年份，未确认报价单位、旅客类别及入住条件。
2—6人精致小团，优先安排同龄人拼车。
4晚携程四钻+1晚赛里木湖舒适型+1晚喀纳斯景区+1晚禾木景区住宿。
14改7头等舱车型，1+1独立豪华座椅。
以上为原文和海报的人工转录，未将发帖人等同于供应商主体，未作余位或最终报价确认。"""


def build_manifest() -> dict:
    from PIL import Image
    files = []
    for name, role in FILES.items():
        path = EVIDENCE_ROOT / name
        if not path.is_file():
            raise ValueError(f"Required selected-source evidence is missing: {name}")
        content = path.read_bytes()
        with Image.open(path) as image:
            size, image_format = list(image.size), image.format
            image.verify()
        files.append({"name": name, "role": role, "sha256": hashlib.sha256(content).hexdigest(),
                      "bytes": len(content), "dimensions": size, "format": image_format,
                      "quality": "client_saved" if role == "client_saved_media" else "screenshot",
                      "original_verified": False})
    return {"schema_version": 1, "acquisition_method": METHOD, "observation_date": OBSERVATION_DATE,
            "observation_timezone": "Asia/Shanghai", "observation_time_precision": "day",
            "source_record_count": 2, "native_event_ids_verified": False,
            "automatic_scanner_verified": False, "coverage": "UNKNOWN", "files": files,
            "note": NOTE}


def assert_offline(data_dir: Path) -> None:
    """Refuse a known live server for the same dataset; never stop it here."""
    ports = {8765, 8766}
    pid_file = PROJECT_ROOT / ".local" / "server.json"
    if pid_file.is_file():
        try:
            ports.add(int(json.loads(pid_file.read_text(encoding="utf-8-sig"))["port"]))
        except (ValueError, KeyError):
            pass
    for port in ports:
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                state = json.load(response)
        except (URLError, TimeoutError, OSError, ValueError):
            continue
        if state.get("data_dir") and Path(state["data_dir"]).resolve() == data_dir:
            raise RuntimeError(f"The target dataset is served on port {port}. Stop the server before this offline import.")


def product_drafts() -> list[tuple[str, dict]]:
    group_id = "local-evidence-20261025-product-lujiang"
    group = {
        "title": "庐江温泉特价抢购·纯玩一日游（年份待确认）", "supplier": None,
        "destination": "庐江", "departure_city": None, "duration_days": 1,
        "shopping": None, "transport": "海报列出马鞍山起止加价；交通包含范围待确认",
        "hotels": None, "itinerary": "汤池一号泉漂浮温泉、矾花源；海报标注一日游。",
        "notes": "海报标识 LZTS，未确认供应商主体。海报原文活动区间10月20日—11月8日，年份未知。纯玩字样未替代逐项购物确认。",
        "source_item_ids": [GROUP_ITEM_ID],
        "offers": [{"id": f"{group_id}-{traveler}", "price": 128, "price_kind": "exact", "currency": None,
                    "unit": None, "traveler": traveler, "occupancy": None,
                    "departure_date": None, "valid_from": None, "valid_to": None,
                    "extras": [{"name": "马鞍山起止附加费", "amount": 20, "currency": "CNY", "unit": "per_person", "required": None, "conditions": "仅马鞍山起止时适用；须确认客户上下车地点"},
                               {"name": "其他必付费用", "amount": None, "required": None}],
                    "transport_included": None, "availability": None, "confirmed_at": None,
                    "conditions": "海报标注128、大小同价；10月20日—11月8日未注明年份。基础报价币种和计价单位未明确；马鞍山起止另加20元/人。"}
                   for traveler in ("adult", "child")],
        "evidence": [{"field": field, "source_item_id": GROUP_ITEM_ID, "location": "group-selected-poster.jpg", "quote": None}
                     for field in ("title", "duration_days", "offers", "itinerary")],
        "issues": ["需确认活动年份与具体团期", "需确认基础报价单位、币种和费用范围", "供应商主体、购物安排及余位未确认"],
    }
    moments_id = "local-evidence-20261025-product-xinjiang"
    moments = {
        "title": "纯净双湖·新疆双飞八日游冬季版（年份待确认）", "supplier": None,
        "destination": "新疆", "departure_city": None, "duration_days": 8, "shopping": "none",
        "transport": "海报标注双飞、14改7头等舱车型及1+1独立豪华座椅；航班出发城市和适用范围待确认",
        "hotels": "海报：4晚携程四钻+1晚赛里木湖舒适型+1晚喀纳斯景区+1晚禾木景区住宿",
        "itinerary": "乌鲁木齐、二进赛里木湖、喀纳斯、禾木、阿勒泰、S21沙漠高速；2—6人小团，优先安排同龄人拼车。",
        "notes": "海报品牌为完美新疆，发帖人为所选联系人；供应商主体未独立确认。海报声明纯玩无购物、无自费、无隐形消费，适用范围和报价细则待核实。",
        "source_item_ids": [MOMENTS_ITEM_ID],
        "offers": [{"id": f"{moments_id}-{price}", "price": price, "price_kind": "exact", "currency": None,
                    "unit": None, "traveler": None, "occupancy": None, "departure_date": None,
                    "valid_from": None, "valid_to": None, "extras": None, "transport_included": None,
                    "availability": None, "confirmed_at": None,
                    "conditions": f"海报价格区间原文：{period}。年份未知；跨年区间未推定年份。报价币种、计价单位、人群、房型、出发地及附加费用适用条件待确认。"}
                   for price, period in ((6280, "11月20日—12月9日"), (6480, "12月10日—12月20日"), (7980, "12月21日—1月4日"))],
        "evidence": [{"field": field, "source_item_id": MOMENTS_ITEM_ID, "location": "moments-selected-post.jpg", "quote": None}
                     for field in ("title", "duration_days", "shopping", "offers", "hotels", "itinerary")],
        "issues": ["三个报价区间均缺年份，不能据发帖年份自动补全", "币种、计价单位、旅客类别及入住条件未明确", "发帖联系人不等于已核实供应商主体", "余位及最终报价未向供应商确认"],
    }
    return [(group_id, ExtractedProduct.model_validate(group).model_dump(mode="json")),
            (moments_id, ExtractedProduct.model_validate(moments).model_dump(mode="json"))]


def import_evidence(data_dir: Path) -> dict:
    data_dir = data_dir.expanduser().resolve()
    assert_offline(data_dir)
    manifest = build_manifest()
    manifest_hash = hashlib.sha256(encode(manifest).encode()).hexdigest()
    drafts = product_drafts()
    store = Store(data_dir)
    imported_at = utcnow()
    blob_metadata = {name: store.save_blob((EVIDENCE_ROOT / name).read_bytes()) for name in FILES}
    record_id = "local-evidence-20261025-import"
    existing_import = store.get("live_evidence", record_id)
    if existing_import:
        if existing_import.get("manifest_sha256") != manifest_hash:
            raise ValueError("Existing local evidence ID has different bytes; refusing to rewrite the observation.")
        store.validate_references()
        return {"state": "already_imported", "data_dir": str(data_dir), "material_ids": [GROUP_ITEM_ID, MOMENTS_ITEM_ID], "manifest_sha256": manifest_hash}

    plan: list[tuple[str, str, dict]] = []
    account_evidence = "已人工观察账号资料卡：采集账号；地区安徽芜湖。未验证稳定微信账号标识或自动重定位。"
    plan.append(("accounts", ACCOUNT_ID, {"display_name": "采集账号", "identity_evidence": account_evidence,
                "verification_status": "PARTIAL", "selected": True, "native_id": None,
                "native_id_verified": False, "acquisition_method": METHOD,
                "evidence_references": ["collector-account-001-profile"]}))
    for source_id, kind, name, identity in (
        (GROUP_SOURCE_ID, "group", "芜湖联众芜湖同业群（497）", "实机群标题芜湖联众芜湖同业群，截图显示成员数497；海报消息发送人联众吕若兰。成员数是观察证据，不是稳定群ID。"),
        (MOMENTS_SOURCE_ID, "moments", "完美新疆西北赵照18552600189", "实机打开所选联系人的个人朋友圈相册及帖子详情，详情显示完整联系人名称；未验证原生稳定联系人ID。"),
    ):
        plan.append(("sources", source_id, {"kind": kind, "account_id": ACCOUNT_ID, "display_name": name,
                    "identity_evidence": identity, "selected": True, "verification_status": "PARTIAL",
                    "native_id": None, "native_id_verified": False, "acquisition_method": METHOD,
                    "capabilities": {"status": "PARTIAL", "available": False, "reason": NOTE,
                                     "automatic_scanner_verified": False, "coverage": "UNKNOWN"}}))

    attachments = {}
    for name, role in FILES.items():
        ident = "local-evidence-20261025-" + Path(name).stem
        source_id = GROUP_SOURCE_ID if name.startswith("group-") else MOMENTS_SOURCE_ID if name.startswith("moments-") else None
        item_id = GROUP_ITEM_ID if source_id == GROUP_SOURCE_ID else MOMENTS_ITEM_ID if source_id else None
        entry = {"name": name, "mime": "image/jpeg" if name.endswith(".jpg") else "image/png", "state": "SAVED",
                 "account_id": ACCOUNT_ID, "source_id": source_id, "material_id": item_id,
                 "quality": "client_saved" if role == "client_saved_media" else "screenshot",
                 "original_verified": False, "origin": "wechat_client_save" if role == "client_saved_media" else "desktop_screenshot",
                 "acquisition_method": METHOD, "evidence_only": role != "client_saved_media",
                 "attempts": 1, "saved_at": imported_at, **blob_metadata[name]}
        plan.append(("attachments", ident, entry))
        attachments[name] = {**entry, "id": ident}

    for item_id, source_id, author, raw_time, transcript, media, proofs in (
        (GROUP_ITEM_ID, GROUP_SOURCE_ID, "联众吕若兰", "2026年10月25日 21:55", GROUP_TRANSCRIPT, "group-selected-poster.jpg", ["group-selected-page1.png", "group-history-timestamps.png"]),
        (MOMENTS_ITEM_ID, MOMENTS_SOURCE_ID, "完美新疆西北赵照18552600189", "昨天 09:07", MOMENTS_TRANSCRIPT, "moments-selected-post.jpg", ["moments-post-detail.png", "moments-album-page1.png"]),
    ):
        time_evidence = parse_source_time(raw_time, ANCHOR, "Asia/Shanghai")
        time_evidence.update(observation_time_precision="day", anchor_basis="observed_calendar_date_not_exact_observation_instant")
        issues = [NOTE, "所存图片来自微信客户端保存，未验证为原始分辨率原件", "原文为人工转录，产品草稿需逐项复核", "本条不代表已遍历历史，也没有创建扫描检查点"]
        plan.append(("materials", item_id, {"source_id": source_id, "account_id": ACCOUNT_ID, "author": author,
                    "supplier": None, "type": "image" if source_id == GROUP_SOURCE_ID else "post",
                    "text": transcript, "text_origin": "human_transcription", "source_note": NOTE,
                    "source_time_raw": raw_time, "source_time": time_evidence["source_time"], "time_evidence": time_evidence,
                    "observed_at": OBSERVATION_DATE, "observation_time_precision": "day", "imported_at": imported_at,
                    "state": "NEEDS_MANUAL", "review_state": "NEEDS_HUMAN_REVIEW", "extractions": [],
                    "acquisition_method": METHOD, "event_key": None, "native_id": None,
                    "identity_confidence": "local_evidence_only", "identity_uncertain": True,
                    "attachments": [attachments[media]], "media_count_observed": 1, "media_set_complete_verified": False,
                    "evidence_references": [attachments[name]["id"] for name in proofs],
                    "coverage": "UNKNOWN", "issues": issues}))
    for product_id, product in drafts:
        plan.append(("products", product_id, {**product, "origin": "human", "transcription_method": "assistant_visual_review",
                    "review_state": "NEEDS_HUMAN_REVIEW", "verifications": [], "correction_at": imported_at,
                    "acquisition_method": METHOD, "advisor_judgment": "仅根据所选来源已保存海报保守整理；年份、报价适用条件及余位尚待确认。"}))

    # Create records atomically; retrying never overwrites a subsequent human edit.
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for kind, ident, _ in plan:
            if db.execute("SELECT 1 FROM records WHERE kind=? AND id=?", (kind, ident)).fetchone():
                raise ValueError(f"Local evidence record collision: {kind}/{ident}; refusing to overwrite.")
        for kind, ident, record in plan:
            store.put(kind, record, ident, db=db)
        store.put("live_evidence", {"manifest": manifest, "manifest_sha256": manifest_hash,
                  "material_ids": [GROUP_ITEM_ID, MOMENTS_ITEM_ID], "product_ids": [ident for ident, _ in drafts],
                  "acquisition_method": METHOD, "created_jobs": 0, "created_checkpoints": 0,
                  "imported_at": imported_at, "note": NOTE}, record_id, db=db)
    store.validate_references()
    (EVIDENCE_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"state": "imported", "data_dir": str(data_dir), "materials": 2, "products": 2,
            "attachments": len(attachments), "jobs_created": 0, "checkpoints_created": 0,
            "manifest_sha256": manifest_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path,
                        help="Explicit target dataset; its application server must be stopped.")
    args = parser.parse_args()
    print(json.dumps(import_evidence(args.data_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
