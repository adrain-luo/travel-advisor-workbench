"""Conservative applicability matching; uncertainty is never a satisfied constraint."""
from __future__ import annotations

from datetime import date
import math
import re
from typing import Any


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _value_matches(actual: Any, wanted: Any) -> bool:
    aliases = {"无购物": "none", "纯玩": "none", "有购物": "included", "成人": "adult", "儿童": "child"}
    a = aliases.get(str(actual), str(actual)).strip().casefold()
    b = aliases.get(str(wanted), str(wanted)).strip().casefold()
    return a == b


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def _offer_check(offer: dict, req: dict, constraints: set[str]) -> tuple[list[str], list[str], list[str]]:
    failed, unknown, reasons = [], [], []
    if str(offer.get("availability", "")).casefold() in {"sold_out", "unavailable", "售罄", "无位", "已满"}:
        failed.append("供应商资料显示当前无余位")
    if "date_start" in constraints or "date_end" in constraints:
        start, end = _date(req.get("date_start")), _date(req.get("date_end"))
        departure = _date(offer.get("departure_date"))
        invalid_date = (bool(req.get("date_start")) and start is None) or (bool(req.get("date_end")) and end is None)
        if invalid_date or (start and end and start > end):
            unknown.append("客户出行日期无效或范围颠倒，请修正条件")
        elif departure:
            if (start and departure < start) or (end and departure > end):
                failed.append("出发日期不在客户要求范围内")
            else:
                reasons.append("出发日期符合要求")
        else:
            # A price validity interval is not a promise of a departure on each date.
            valid_from, valid_to = _date(offer.get("valid_from")), _date(offer.get("valid_to"))
            if (start and valid_to and valid_to < start) or (end and valid_from and valid_from > end):
                failed.append("报价有效期与出行日期不相交")
            else:
                unknown.append("需确认要求日期有适用团期；报价有效期不等于确定团期")
    for key, label in (("traveler", "旅客类别"), ("occupancy", "入住条件"), ("transport_included", "交通是否包含")):
        if key in constraints:
            if offer.get(key) is None:
                unknown.append(f"{label}未知")
            elif req.get(key) is None:
                unknown.append(f"客户的{label}条件待补充")
            elif not _value_matches(offer[key], req[key]):
                failed.append(f"{label}不符合要求")
            else:
                reasons.append(f"{label}符合要求")
    if "budget" in constraints and req.get("budget") is not None:
        if not offer.get("departure_date") and "date_start" not in constraints and "date_end" not in constraints:
            unknown.append("价格适用团期待确认")
        price = offer.get("price")
        if price is None:
            unknown.append("适用价格未知")
        elif not isinstance(price, (int, float)):
            unknown.append("价格格式需核对")
        else:
            budget = _number(req["budget"])
            comparable = True
            if budget is None:
                unknown.append("客户预算格式无效，请修正条件")
                comparable = False
            if not req.get("budget_unit") or not offer.get("unit"):
                unknown.append("预算或报价计价单位未知")
                comparable = False
            elif req["budget_unit"] != offer["unit"]:
                unknown.append("预算与报价计价单位不同，需按旅客构成核算")
                comparable = False
            currency = req.get("currency", "CNY") or "CNY"
            if not offer.get("currency"):
                unknown.append("报价币种未知")
                comparable = False
            elif offer["currency"].upper() != currency.upper():
                unknown.append("预算与报价币种不同，尚未换算")
                comparable = False
            if not offer.get("traveler"):
                unknown.append("价格适用旅客类别未知")
            if not offer.get("occupancy"):
                unknown.append("价格适用入住条件未知")
            if req.get("children", 0) and offer.get("traveler") != "child":
                unknown.append("同行儿童的价格需单独确认")
            extras = offer.get("extras")
            total = float(price)
            if extras is None:
                unknown.append("必付附加费用未知，不能按零计算")
            else:
                for extra in extras:
                    if extra.get("required") is False or extra.get("state") == "not_applicable":
                        continue
                    if extra.get("required") is None:
                        unknown.append(f"{extra.get('name', '附加费用')}是否必付未知")
                    if extra.get("amount") is None:
                        unknown.append(f"{extra.get('name', '附加费用')}金额未知")
                    elif extra.get("unit", offer.get("unit")) != offer.get("unit") or extra.get("currency", offer.get("currency")) != offer.get("currency"):
                        unknown.append(f"{extra.get('name', '附加费用')}需另行核算")
                    elif extra.get("required") is True:
                        amount = _number(extra["amount"])
                        if amount is None:
                            unknown.append(f"{extra.get('name', '附加费用')}金额格式需核对")
                        else:
                            total += amount
            if comparable:
                if total > budget:
                    failed.append("已知适用费用超过预算")
                elif offer.get("price_kind") != "exact":
                    unknown.append("起价或价格区间不能作为预算内的确定报价")
                elif not unknown:
                    reasons.append("已知必付费用合计在预算内")
    return failed, unknown, reasons


def match_products(products: list[dict], requirements: dict) -> dict:
    req = dict(requirements)
    for list_key in ("hard_constraints", "preferences", "exclusions"):
        if isinstance(req.get(list_key), str):
            req[list_key] = [value.strip() for value in re.split(r"[\n,，;；]+", req[list_key]) if value.strip()]
        elif list_key in req:
            req[list_key] = [value for value in (req.get(list_key) or []) if isinstance(value, str)]
    if req.get("budget") is None:
        req["budget"] = req.get("budget_max")
    if req.get("hotels") is None:
        req["hotels"] = req.get("hotel_preferences")
    if req.get("shopping") == "any":
        req["shopping"] = None
    # An explicitly supplied hard-constraint list is authoritative. Blank form
    # fields do not become constraints merely because their checkboxes are set.
    preference_keys = {p for p in req.get("preferences", []) if isinstance(p, str)}
    known_fields = ("destination", "departure_city", "duration_days", "shopping", "hotels", "pace", "date_start", "date_end", "traveler", "occupancy", "transport_included", "budget")
    aliases = {"budget_max": "budget", "hotel_preferences": "hotels"}
    if "hard_constraints" in req:
        constraints = {aliases.get(k, k) for k in req.get("hard_constraints") or [] if req.get(aliases.get(k, k)) not in (None, "")}
    else:
        constraints = {k for k in known_fields if req.get(k) not in (None, "") and k not in preference_keys}
    if requirements.get("shopping") == "any":
        constraints.discard("shopping")
    result: dict = {"matched": [], "needs_verification": [], "excluded": [], "questions": []}
    labels = {"destination": "目的地", "departure_city": "出发城市", "duration_days": "行程天数", "shopping": "购物安排", "hotels": "酒店要求", "pace": "行程节奏"}
    for product in products:
        failed, unknown, reasons = [], [], []
        for key, label in labels.items():
            if key not in constraints:
                continue
            actual = product.get(key)
            if actual in (None, ""):
                unknown.append(f"{label}未知")
            elif not _value_matches(actual, req.get(key)):
                failed.append(f"{label}不符合要求")
            else:
                reasons.append(f"{label}符合要求")
        for exclusion in req.get("exclusions", []):
            if exclusion in " ".join(str(product.get(k) or "") for k in ("itinerary", "notes", "transport")):
                failed.append(f"素材出现客户排除内容：{exclusion}")
            else:
                unknown.append(f"需核实没有客户排除内容：{exclusion}")
        unsupported = constraints - set(known_fields)
        unknown.extend(f"需人工核实条件：{key}" for key in sorted(unsupported))
        offer_constraints = constraints & {"date_start", "date_end", "budget", "traveler", "occupancy", "transport_included"}
        offers = product.get("offers") or []
        chosen = None
        if offer_constraints:
            checks = [(offer, *_offer_check(offer, req, constraints)) for offer in offers]
            certain = [c for c in checks if not c[1] and not c[2]]
            possible = [c for c in checks if not c[1]]
            if certain:
                chosen = certain[0][0]
                reasons.extend(certain[0][3])
            elif possible:
                best = min(possible, key=lambda c: len(c[2]))
                chosen = best[0]
                unknown.extend(best[2])
                reasons.extend(best[3])
            elif checks:
                failed.extend(sorted({reason for c in checks for reason in c[1]}))
            else:
                unknown.append("尚无可适用的报价和团期，需供应商确认")
        else:
            chosen = offers[0] if len(offers) == 1 else None
        entry = {"product": product, "applicable_offer": chosen, "reasons": list(dict.fromkeys(reasons)), "issues": list(dict.fromkeys(unknown)), "exclusions": list(dict.fromkeys(failed))}
        category = "excluded" if failed else "needs_verification" if unknown else "matched"
        entry["status"] = category
        result[category].append(entry)
    for category in ("matched", "needs_verification"):
        def preference_score(entry):
            product = entry["product"]
            structured = sum(_value_matches(product.get(key), req[key]) for key in labels if key not in constraints and req.get(key) not in (None, ""))
            haystack = " ".join(str(product.get(key) or "") for key in ("title", "destination", "hotels", "itinerary", "notes", "advisor_judgment"))
            return structured + sum(phrase in haystack for phrase in req.get("preferences", []))
        result[category].sort(key=lambda e: (len(e["issues"]), -preference_score(e), -len(e["reasons"]), str(e["product"].get("title", ""))))
    if not req.get("date_start"):
        result["questions"].append("计划哪天或哪个时间段出发？")
    if req.get("budget") is not None and not req.get("budget_unit"):
        result["questions"].append("预算是每人金额还是整团总额？")
    if not result["matched"]:
        result["next_action"] = "没有已确认满足全部条件的产品。请核实待确认候选的关键条件，或补充其他供应商素材。"
    else:
        result["next_action"] = "请比较适用报价和待确认事项，整理客户介绍。"
    result["questions"] = result["questions"][:2]
    return result
