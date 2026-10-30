"""Pure travel-product relevance decisions; never retain source text or access IO.

The caller owns receipts, staging retention, migration exceptions and transactions.
Only current records need a decision; a rule version change does not request a
history replay. Historical product relevance never asserts current bookability.
"""
from __future__ import annotations

import re
import unicodedata


RULE_VERSION = "travel-product-rules-2026-10-28.4"
KEEP_PRODUCT_RELEVANT = "KEEP_PRODUCT_RELEVANT"
SKIP_IRRELEVANT = "SKIP_IRRELEVANT"
PENDING_RELEVANCE = "PENDING_RELEVANCE"
RETRY_ACQUISITION = "RETRY_ACQUISITION"
_POSITIVE = {"travel_promotion", "travel_flyer", "itinerary_quote", "product_relevant"}
_NEGATIVE = {"travel_sharing", "scenic_personal", "other", "irrelevant"}
_TRUSTED = {"manual", "inspection"}
_ANCHOR = re.compile(r"跟团|旅行团|旅游团|旅游产品|旅游线路|旅游报价|旅游套餐|度假套餐|自由行套餐|定制游|行程|线路|团期|团费|出团|发团|成团|收客|全陪班|双飞|双卧|[一二三四五六七八九十\d]+[日天]游|[一二三四五六七八九十\d]+天[一二三四五六七八九十\d]+晚|\b(?:tour|tours|itinerary|holiday package|travel package)\b", re.I)
_STRONG = re.compile(r"跟团游|旅游套餐|度假套餐|全陪班|(?:双飞|双卧|飞机团|专列)[\s\S]{0,18}(?:[一二三四五六七八九十\d]+[天日]|品质游)|(?:[一二三四五六七八九十\d]+[日天]游)[\s\S]{0,24}(?:纯玩|品质|特价|精品|报名)|(?:团期|旅游线路)[\s\S]{0,12}(?:报价|特价|价格|发布)|(?:开始|持续|正常|大量|欢迎|火热)收客", re.I)
_FEATURES = {
    "PRICE_OR_QUOTATION": re.compile(r"(?:报价|团费|费用|成人价|儿童价|价格|售价|优惠价|结算价|同行价|特价|单房差|补差|定金|订金|尾款|[¥￥$])\s*[:：]?\s*\d|\d[\d,.]*\s*(?:元|[¥￥]|USD|EUR|CNY)|(?:费用|报价|团费|价格)(?:包含|不含|含|不包含|调整|更正)|\b(?:price|quote|quotation|deposit)\s*[:：]?\s*[¥￥$]?\d", re.I),
    "DEPARTURE_OR_SCHEDULE": re.compile(r"(?:出发|出团|发团|团期|开班|每周|天天发|每日发)|(?:第[一二三四五六七八九十\d]+天|\bD(?:ay)?\s*[1-9]\b)|\bdepart(?:ure|s)?\s+(?:on\s+)?\d", re.I),
    "INCLUSIONS_OR_CONDITIONS": re.compile(r"(?:含|包含|赠送|安排|入住|住宿|不含|不包含).{0,18}(?:酒店|宾馆|住宿|餐|早餐|午餐|晚餐|门票|机票|高铁|接送|接机|交通|保险|导游)|(?:酒店|交通|住宿|用餐|服务|费用)(?:标准|安排|包含|不含)|(?:报名|预订|预定|订位|报名截止|身份证|护照).{0,16}(?:要求|截止|提供|资料|定金|订金|预付|名额)|\b(?:includes?|excludes?)\b.{0,40}\b(?:hotel|breakfast|meals|transport|flights|guide|insurance)\b", re.I),
    "AVAILABILITY_OR_CHANGE": re.compile(r"(?:余位|余席|剩余|剩|仅剩|还剩|余|尚有|空位).{0,8}\d.{0,3}(?:位|席|座|名额)|(?:满团|已满|售罄|停收|取消|改期|延期|调整|更正|更改|改为|补位|可收|可订|余位)|\b(?:cancelled|canceled|rescheduled|sold out|fully booked)\b|\d+\s+(?:seats|places)\s+(?:left|available)", re.I),
}
_SCHEDULE_LINE = re.compile(r"(?:第[一二三四五六七八九十\d]+天|\bD(?:ay)?\s*[1-9]\b)\s*[:：.、-]?", re.I)
_REPLY_DETAIL = re.compile(r"(?:\d[\d,.]*\s*(?:元|块|位|席|座|人|名额)|[¥￥]\s*\d|^\d[\d,.]*$|余位|余席|满团|已满|售罄|取消|改期|延期|补位|可收|可订|不含|包含|改为|更正|定金|订金|尾款|单房差)", re.I)
_CASUAL = re.compile(r"^(?:你好|您好|早上好|早安|晚安|中午好|下午好|晚上好|谢谢|多谢|辛苦了?|收到|好的?|好嘞|嗯+|哦+|哈哈+|行|可以|没问题|知道了|不客气|再见|在吗|忙吗|吃了吗|祝.{0,8}快乐)[\s!！。.,，~～]*$")
_PERSONAL = re.compile(r"随手拍|随拍|打卡|旅行分享|生活记录|日常记录|分享风景|看看风景|风景真|风景好|心情|朋友圈|好漂亮|太美了|拍照|晨练|早锻炼|生日快乐")
_PLANNING_FRAME = re.compile(r"业务方向|商业模式|创业方向|创业项目|业务规划|产品规划|需求分析|需求文档|功能规划|系统设计|软件开发|软件服务|智能体开发|旅游软件|旅行社管理系统|商业计划|项目规划|变现方向|business plan|software service", re.I)
_META_CONTEXT = re.compile(r"软件|系统|平台|功能|用户|需求|架构|业务|创业|运营|自动化|智能体|SaaS|AI|小程序|工作台|开发|商业|变现|software|business|platform|features", re.I)
_TRIP_DURATION = re.compile(r"[一二三四五六七八九十\d]+[日天]游|[一二三四五六七八九十\d]+天[一二三四五六七八九十\d]+晚|\d+[- ]day\s+tour", re.I)
_DEPARTURE_DATE = re.compile(r"\d{1,2}月\d{1,2}[日号]|\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def _text(value):
    return unicodedata.normalize("NFKC", value if isinstance(value, str) else "").strip()[:100_000]


def _classification(value):
    value = value if isinstance(value, dict) else {}
    return value.get("label"), value.get("origin")


def _nonproduct_planning(text):
    meta_count = len(_META_CONTEXT.findall(text))
    abstract_technology = meta_count >= 3 and re.search(r'软件|开发|智能体|(?<![A-Za-z])AI(?![A-Za-z])|SaaS|software', text, re.I)
    if not (_PLANNING_FRAME.search(text) or abstract_technology) or meta_count < 2:
        return False
    # A real offer embedded in a longer document may still be useful. Generic
    # mentions of itinerary/quote/departure features are not an actual offer.
    concrete = (len(_SCHEDULE_LINE.findall(text)) >= 2 or bool(_TRIP_DURATION.search(text))
        and (bool(_DEPARTURE_DATE.search(text)) or bool(_FEATURES['INCLUSIONS_OR_CONDITIONS'].search(text))
             or bool(_FEATURES['PRICE_OR_QUOTATION'].search(text))))
    return not concrete


def _product_signals(text):
    if _nonproduct_planning(text):
        return []
    anchor = bool(_ANCHOR.search(text))
    details = [name for name, pattern in _FEATURES.items() if pattern.search(text)]
    if _STRONG.search(text):
        return ["EXPLICIT_TOUR_PRODUCT", *details]
    if anchor and details:
        return ["TOUR_CONTEXT", *details]
    if len(_SCHEDULE_LINE.findall(text)) >= 2:
        return ["MULTIDAY_ITINERARY"]
    return []


def _verified_reply(record, context):
    """Require an actual reference and a previously accepted same-source parent.

    reply_context: relationship_verified=True, relationship='explicit_reply',
    parent_event_key, parent_outcome, account_id/source_id/conversation_id matching
    every nonempty corresponding field on record. Either reply_to_event_key must
    match, or record.reply has verified=True/native_id equal parent_native_id.
    The adapter/caller verifies the native relation; timestamps are never used.
    """
    if not isinstance(context, dict) or context.get("relationship_verified") is not True:
        return None
    if context.get("relationship") != "explicit_reply" or context.get("parent_outcome") != KEEP_PRODUCT_RELEVANT:
        return None
    parent = context.get("parent_event_key")
    if not isinstance(parent, str) or not parent or parent == record.get("event_key"):
        return None
    matched_scope = 0
    for field in ("account_id", "source_id", "conversation_id"):
        own = record.get(field)
        if own:
            if context.get(field) != own:
                return None
            matched_scope += 1
    if matched_scope < 2:
        return None
    if record.get("reply_to_event_key") == parent:
        return parent
    reply = record.get("reply") or {}
    if (isinstance(reply, dict) and reply.get("relationship") == "explicit_reply"
            and reply.get("relationship_verified") is True and reply.get("native_server_id")
            and str(reply["native_server_id"]) == str(context.get("parent_native_id", ""))
            and reply.get("account_id") == context.get("account_native_id", context.get("account_id"))
            and reply.get("conversation_id") == context.get("conversation_id")):
        return parent
    if (isinstance(reply, dict) and reply.get("verified") is True and reply.get("native_id")
            and str(reply["native_id"]) == str(context.get("parent_native_id", ""))):
        return parent
    return None


def decide(record, *, inspection=None, reply_context=None):
    """Return a body-free decision; image OCR evidence is transient input only.

    inspection is returned by inspection.inspect_record. Acquisition and OCR
    failures remain distinct. Clear positive text needs no image download for
    relevance, while empty text with media always requests bounded inspection.
    """
    if not isinstance(record, dict):
        raise ValueError("RELEVANCE_RECORD_INVALID")
    text = _text(record.get("text", ""))
    assets = [a for a in record.get("attachments", []) if isinstance(a, dict) and not a.get("retired")]
    metrics = {"classification_operations": 1, "ocr_operations": 0, "media_inspected": 0}
    def result(outcome, *reasons, inspect=False, context=None):
        return {"outcome": outcome, "rule_version": RULE_VERSION, "reason_code": reasons[0],
                "reason_codes": list(dict.fromkeys(reasons)), "needs_inspection": inspect,
                "context_event_key": context, "metrics": dict(metrics)}

    label, origin = _classification(record.get("classification"))
    if origin in _TRUSTED:
        if label in _POSITIVE:
            return result(KEEP_PRODUCT_RELEVANT, "TRUSTED_PRODUCT_CLASSIFICATION")
        if label in _NEGATIVE:
            conflicting = any(_classification(a.get("classification"))[0] in _POSITIVE
                and _classification(a.get("classification"))[1] in _TRUSTED for a in assets)
            if origin == "manual" or not conflicting:
                return result(SKIP_IRRELEVANT, "TRUSTED_NONPRODUCT_CLASSIFICATION")
            return result(PENDING_RELEVANCE, "CONFLICTING_TRUSTED_CLASSIFICATIONS")
        if label == "uncertain" and origin == "manual":
            return result(PENDING_RELEVANCE, "EXPLICIT_UNCERTAIN_CLASSIFICATION")

    signals = _product_signals(text)
    if signals:
        return result(KEEP_PRODUCT_RELEVANT, "TEXT_PRODUCT_EVIDENCE", *signals)
    if label == "uncertain" and origin == "inspection":
        return result(PENDING_RELEVANCE, "TRUSTED_INSPECTION_UNCERTAIN")
    parent = _verified_reply(record, reply_context)
    if parent and _REPLY_DETAIL.search(text):
        return result(KEEP_PRODUCT_RELEVANT, "EXPLICIT_PRODUCT_REPLY", context=parent)
    labels = [_classification(a.get("classification")) for a in assets]
    if any(label in _POSITIVE and origin in _TRUSTED for label, origin in labels):
        return result(KEEP_PRODUCT_RELEVANT, "TRUSTED_PRODUCT_MEDIA")
    if assets and all(label in _NEGATIVE and origin in _TRUSTED for label, origin in labels):
        return result(SKIP_IRRELEVANT, "ALL_MEDIA_CONFIRMED_NONPRODUCT")

    if assets:
        if not isinstance(inspection, dict):
            return result(PENDING_RELEVANCE, "MEDIA_INSPECTION_REQUIRED", inspect=True)
        if inspection.get("event_key") != record.get("event_key"):
            return result(PENDING_RELEVANCE, "INSPECTION_EVENT_MISMATCH", inspect=True)
        current_revision = record.get("source_revision_hash") or record.get("source_revision")
        if current_revision and inspection.get("source_revision_hash") != current_revision:
            return result(PENDING_RELEVANCE, "INSPECTION_REVISION_MISMATCH", inspect=True)
        for key in ("ocr_operations", "media_inspected"):
            value = inspection.get("metrics", {}).get(key, 0)
            metrics[key] = value if type(value) is int and value >= 0 else 0
        expected_hashes = {str(a.get("sha256")) for a in assets if a.get("sha256")}
        planning_hashes = set()
        for image in inspection.get("images", []):
            if (image.get("sha256") in expected_hashes and image.get("state") == "RECOGNIZED"
                    and image.get("trusted_for_rules") is True):
                image_text = _text(image.get("text"))
                if _nonproduct_planning(image_text):
                    planning_hashes.add(image['sha256'])
                recognized = _product_signals(image_text)
                if recognized:
                    return result(KEEP_PRODUCT_RELEVANT, "OCR_PRODUCT_EVIDENCE", *recognized)
        states = {i.get("state") for i in inspection.get("images", [])}
        if "ACQUISITION_FAILED" in states or inspection.get("status") == "ACQUISITION_FAILED":
            return result(RETRY_ACQUISITION, "MEDIA_ACQUISITION_REQUIRED")
        if (len(expected_hashes) > 0 and planning_hashes == expected_hashes
                and all(a.get('sha256') for a in assets)):
            return result(SKIP_IRRELEVANT, 'OCR_NONPRODUCT_PLANNING_EVIDENCE')
        # OCR absence or ordinary words do not establish that an image is scenic.
        # The separate pending path can expire, but may never relabel expiry skip.
        return result(PENDING_RELEVANCE, "MEDIA_RELEVANCE_UNRESOLVED")

    if _nonproduct_planning(text):
        return result(SKIP_IRRELEVANT, 'NONPRODUCT_BUSINESS_OR_SOFTWARE_PLANNING')
    if _CASUAL.fullmatch(text) or not re.search(r"[\w\u3400-\u9fff]", text):
        return result(SKIP_IRRELEVANT, "GREETING_ACKNOWLEDGMENT_OR_EMOJI")
    if _PERSONAL.search(text):
        return result(SKIP_IRRELEVANT, "PERSONAL_OR_SCENIC_SHARING")
    if _ANCHOR.search(text):
        return result(PENDING_RELEVANCE, "INSUFFICIENT_PRODUCT_DETAILS")
    return result(SKIP_IRRELEVANT, "NO_PRODUCT_CONTEXT")


# Explicit alias for integrations that name the operation as classification.
classify_relevance = decide
