"""Chinese customer drafts and deterministic comparison image rendering."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _display(value, fallback="待确认") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, list):
        return "、".join(str(v) for v in value) if value else "无（资料明确列出）"
    return str(value)


def _product(entry: dict) -> dict:
    return entry.get("product", entry)


def _offers(entry: dict) -> list[dict]:
    return [entry["applicable_offer"]] if entry.get("applicable_offer") else (_product(entry).get("offers") or [])


def _currency(value) -> str:
    return {"CNY": "元", "RMB": "元", "USD": "美元", "EUR": "欧元", "JPY": "日元", "HKD": "港元"}.get(value, value or "（币种待确认）")


def _unit(value) -> str:
    return {"per_person": "/人", "per_party": "/团", "per_room": "/间"}.get(value, "（计价单位待确认）")


def source_evidence_lines(product: dict) -> list[str]:
    """Render saved publication evidence; collection/update clocks are not substitutes."""
    sources = product.get("source_snapshots") or []
    if not sources:
        return ["资料更新时间：" + _display(product.get("source_updated_at") or product.get("source_time"), "来源时间未知")]
    lines = []
    for source in sources:
        evidence = source.get("time_evidence") or {}
        raw = source.get("source_time_raw") or evidence.get("source_time_raw")
        precision = evidence.get("precision")
        status = evidence.get("status")
        zone = evidence.get("timezone") or "Asia/Shanghai"
        zone_label = {"Asia/Shanghai": "中国标准时间", "Asia/Hong_Kong": "香港时间", "UTC": "协调世界时"}.get(zone, zone)
        name = source.get("source_name") or {"group": "微信群", "moments": "联系人朋友圈", "upload": "上传素材"}.get(source.get("source_kind"), "来源素材")
        author = source.get("author")
        prefix = f"来源发布时间证据｜{name}" + (f" · {author}" if author and author != name else "") + "："

        def format_value(value, date_only=False):
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo:
                    parsed = parsed.astimezone(ZoneInfo(zone))
                if date_only or precision == "day":
                    return parsed.strftime("%Y-%m-%d")
                return parsed.strftime("%Y-%m-%d %H:%M:%S" if precision == "second" else "%Y-%m-%d %H:%M")
            except (ValueError, TypeError, KeyError):
                return str(value)

        if raw:
            text = f"原文“{raw}”"
            if re.search(r"今天|昨天|前天|刚刚|\d+\s*(?:分钟|小时|天)前|星期|周[一二三四五六日天]", str(raw)):
                observed = source.get("observed_at") or evidence.get("observed_at")
                text += f"；观察日期 {format_value(observed, True)}（{zone_label}）" if observed else "；观察日期未知，不能确定实际日期"
                if status == "parsed" and evidence.get("start") and precision in {"day", "minute", "second"}:
                    text += "；对应 " + format_value(evidence["start"])
            if status in {"unknown", "ambiguous", "unparsed", "invalid"}:
                text += "（时间待核对）"
            elif status == "context_only":
                text += "（仅为上下文时间，具体发布时间待核对）"
            elif precision == "minute":
                text += "（分钟级时间证据）"
            elif precision == "day":
                text += "（日期级时间证据）"
            elif precision == "relative_interval":
                text += "（相对时间区间，不能视为准确时刻）"
        elif status == "parsed" and evidence.get("start"):
            if precision == "relative_interval":
                text = f"时间区间 {format_value(evidence['start'])} 至 {format_value(evidence.get('end'))}（{zone_label}）"
            else:
                text = format_value(evidence["start"]) + f"（{zone_label}；" + {"minute": "分钟级", "second": "秒级", "day": "日期级"}.get(precision, "精度待核对") + "）"
        else:
            text = "来源时间未知"
        lines.append(prefix + text)
    return lines


def price_text(offer: dict) -> str:
    if offer.get("price") is None:
        return "价格待确认"
    value = f"{offer['price']:g}" if isinstance(offer["price"], (float, int)) else str(offer["price"])
    currency = _currency(offer.get("currency"))
    if offer.get("price_kind") == "from":
        value += " 起"
    elif offer.get("price_kind") == "range":
        value += "～" + _display(offer.get("price_max"), "上限待确认")
    elif offer.get("price_kind") != "exact":
        value += "（价格性质待确认）"
    unit = _unit(offer.get("unit"))
    return f"{value} {currency}{unit}"


def offer_lines(offer: dict) -> list[str]:
    traveler = {"adult": "成人", "child": "儿童", "infant": "婴儿"}.get(offer.get("traveler"), offer.get("traveler"))
    dates = _display(offer.get("departure_date"))
    if not offer.get("departure_date") and (offer.get("valid_from") or offer.get("valid_to")):
        dates = f"报价有效期 {_display(offer.get('valid_from'))} 至 {_display(offer.get('valid_to'))}；具体团期待确认"
    extras = offer.get("extras")
    if extras is None:
        extras_text = "必付附加费用未知，不按零计算"
    elif not extras:
        extras_text = "资料注明无必付附加费用"
    else:
        details = []
        for extra in extras:
            required = "必付" if extra.get("required") is True else "可选" if extra.get("required") is False else "是否必付待确认"
            if extra.get("state") == "not_applicable":
                detail = f"{extra.get('name', '费用')}：不适用"
            else:
                detail = f"{extra.get('name', '附加费用')}：{_display(extra.get('amount'), '金额待确认')} {_currency(extra.get('currency'))}{_unit(extra.get('unit'))}（{required}）"
            if extra.get("conditions"):
                detail += "；适用条件：" + str(extra["conditions"])
            details.append(detail)
        extras_text = "；".join(details)
    transport = "已包含" if offer.get("transport_included") is True else "不包含" if offer.get("transport_included") is False else "待确认"
    return [f"报价：{price_text(offer)}", f"日期：{dates}", f"适用：{_display(traveler)}；入住 {_display(offer.get('occupancy'))}", f"交通：{transport}", f"附加费用：{extras_text}", f"包含：{_display(offer.get('inclusions'))}", f"不含：{_display(offer.get('exclusions'))}", f"适用条件：{_display(offer.get('conditions'))}", f"余位：{_display(offer.get('availability'))}；供应商确认时间：{_display(offer.get('confirmed_at'), '尚未确认')}"]


def _information_date(requirements: dict) -> str:
    value = requirements.get("information_date")
    if value:
        return str(value)
    return datetime.now(ZoneInfo(requirements.get("timezone") or "Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def recommendation_text(products: list[dict], requirements: dict) -> str:
    information_date = _information_date(requirements)
    if not products:
        return f"目前还没有可推荐的候选产品。我们将继续核实团期、适用价格和您的关键要求后提供方案。\n信息整理时间：{information_date}"
    lines = ["为您整理了以下出游备选方案，供您比较。未确认的团期、价格条件及余位会单独注明。", ""]
    requested = []
    for key, label in (("departure_city", "出发"), ("destination", "目的地"), ("date_start", "最早出发"), ("date_end", "最晚出发")):
        if requirements.get(key):
            requested.append(f"{label}：{requirements[key]}")
    budget = requirements.get("budget", requirements.get("budget_max"))
    if budget is not None:
        currency = {"CNY": "元", "USD": "美元", "EUR": "欧元", "JPY": "日元"}.get(requirements.get("currency", "CNY"), requirements.get("currency") or "（币种待确认）")
        requested.append(f"预算：{budget} {currency}" + {"per_person": "/人", "per_party": "/团"}.get(requirements.get("budget_unit"), "（单位待确认）"))
    if requested:
        lines.extend(["您的需求：" + "；".join(requested), ""])
    for index, entry in enumerate(products, 1):
        product = _product(entry)
        shopping = {"none": "无购物", "included": "含购物安排", "optional": "可选购物"}.get(product.get("shopping"), "购物安排待确认")
        lines.append(f"方案 {index}｜{product.get('title') or '待命名产品'}")
        lines.append(f"目的地：{_display(product.get('destination'))}；行程：{_display(product.get('duration_days'))} 天；出发地：{_display(product.get('departure_city'))}")
        lines.append(f"供应商：{_display(product.get('supplier'))}；酒店：{_display(product.get('hotels'))}；{shopping}")
        offers = _offers(entry)
        if not offers:
            lines.append("尚无适用报价，团期、费用和余位待供应商确认。")
        for offer_index, offer in enumerate(offers, 1):
            if len(offers) > 1:
                lines.append(f"报价选项 {offer_index}（不同适用条件，请分别核对）：")
            lines.extend(offer_lines(offer))
        if entry.get("reasons"):
            lines.append("适合之处：" + "；".join(entry["reasons"]))
        if product.get("itinerary"):
            lines.append("行程概要：" + product["itinerary"])
        notes = product.get("advisor_judgment") or product.get("advisor_notes") or product.get("notes")
        if notes:
            lines.append("顾问说明：" + str(notes))
        issues = entry.get("issues", []) + product.get("issues", [])
        if issues:
            lines.append("待确认：" + "；".join(dict.fromkeys(issues)))
        lines.extend(source_evidence_lines(product))
        lines.append("")
    lines.append(f"信息整理时间：{information_date}。此介绍为备选方案，最终团期、报价适用条件及余位以供应商逐项确认为准。")
    return "\n".join(lines)


def supplier_questions(products: list[dict], requirements: dict) -> list[dict]:
    result = []
    for entry in products:
        product = _product(entry)
        date_text = " 至 ".join(filter(None, [requirements.get("date_start"), requirements.get("date_end")])) or "客户计划日期"
        questions = list(entry.get("issues", [])) or ["请确认适用团期、旅客类别、入住条件和余位。", "请列明必付附加费用及交通是否包含。"]
        result.append({"supplier": product.get("supplier"), "product_id": product.get("id"), "text": f"您好，想核实《{product.get('title', '此产品')}》在 {date_text} 的情况：\n" + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions)) + "\n请注明确认适用的日期、人数及报价条件，谢谢。"})
    return result


def _font(size: int):
    from PIL import ImageFont
    candidates = [os.environ.get("TRAVEL_CJK_FONT", ""), "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    for filename in candidates:
        if filename and Path(filename).is_file():
            return ImageFont.truetype(filename, size=size)
    raise ValueError("未找到中文字体，请安装中文字体或配置 TRAVEL_CJK_FONT 后重试。")


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines = []
    for paragraph in str(text).split("\n"):
        current = ""
        if not paragraph:
            lines.append("")
        for character in paragraph:
            if current and draw.textlength(current + character, font=font) > width:
                lines.append(current)
                current = character
            else:
                current += character
        if current:
            lines.append(current)
    return lines


def render_comparison(products: list[dict], requirements: dict, text: str, path: Path) -> None:
    """Render every selected offer and the exact editable draft without clipping."""
    from PIL import Image, ImageDraw
    path = Path(path)
    title_font, heading_font, body_font, small_font = _font(36), _font(26), _font(22), _font(19)
    width, pad, gap = 1440, 48, 24
    scratch = ImageDraw.Draw(Image.new("RGB", (width, 10)))
    columns = min(max(len(products), 1), 3)
    column_width = (width - pad * 2 - gap * (columns - 1)) // columns
    cards = []
    for index, entry in enumerate(products, 1):
        product = _product(entry)
        body = [f"目的地：{_display(product.get('destination'))}", f"出发：{_display(product.get('departure_city'))} · {_display(product.get('duration_days'))} 天", f"酒店：{_display(product.get('hotels'))}", "购物：" + {"none": "无购物", "included": "含购物安排", "optional": "可选购物"}.get(product.get("shopping"), "待确认")]
        offers = _offers(entry)
        if not offers:
            body.append("团期、报价和余位待确认")
        for offer_index, offer in enumerate(offers, 1):
            if len(offers) > 1:
                body.append(f"报价选项 {offer_index}")
            body += offer_lines(offer)
        if entry.get("reasons"):
            body.append("适合：" + "；".join(entry["reasons"]))
        if entry.get("issues"):
            body.append("待确认：" + "；".join(entry["issues"]))
        body.extend(source_evidence_lines(product))
        heading_lines = _wrap(scratch, f"{index}. {product.get('title') or '待命名产品'}", heading_font, column_width - 36)
        body_lines = _wrap(scratch, "\n".join(body), body_font, column_width - 36)
        cards.append((heading_lines, body_lines, 38 * len(heading_lines) + 32 * len(body_lines) + 48))
    row_heights = [max(card[2] for card in cards[start:start + columns]) for start in range(0, len(cards), columns)]
    draft_lines = _wrap(scratch, text, body_font, width - 2 * pad - 40)
    height = 180 + sum(row_heights) + gap * len(row_heights) + 104 + len(draft_lines) * 32 + 86
    if height > 60000:
        raise ValueError("对比图内容过长，请减少同时选择的产品，或导出文字版本。")
    image = Image.new("RGB", (width, max(height, 600)), "#f3f5f1")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 132), fill="#143d33")
    draw.text((pad, 30), "出游方案对比", font=title_font, fill="white")
    draw.text((pad, 85), "信息整理：" + _information_date(requirements) + " · 团期与费用适用条件请逐项核实", font=small_font, fill="#d7e7df")
    y = 158
    for row_index, start in enumerate(range(0, len(cards), columns)):
        row_height = row_heights[row_index]
        for col, card in enumerate(cards[start:start + columns]):
            x = pad + col * (column_width + gap)
            draw.rounded_rectangle((x, y, x + column_width, y + row_height), radius=14, fill="white", outline="#d9e1da", width=2)
            cy = y + 20
            for line in card[0]:
                draw.text((x + 18, cy), line, font=heading_font, fill="#143d33")
                cy += 38
            cy += 10
            for line in card[1]:
                draw.text((x + 18, cy), line, font=body_font, fill="#303e37")
                cy += 32
        y += row_height + gap
    draw.text((pad, y + 8), "顾问介绍", font=heading_font, fill="#143d33")
    y += 54
    draft_height = len(draft_lines) * 32 + 40
    draw.rounded_rectangle((pad, y, width - pad, y + draft_height), radius=12, fill="white")
    y += 20
    for line in draft_lines:
        draw.text((pad + 20, y), line, font=body_font, fill="#303e37")
        y += 32
    draw.text((pad, y + 34), "选团助手 · 此图片为方案介绍，未自动发送或预订", font=small_font, fill="#657267")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
