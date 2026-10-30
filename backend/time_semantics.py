"""Conservative source-time intervals and frozen scan scopes.

Intervals have an inclusive start and exclusive end. A source separator is never
silently promoted to the exact publication time of every following message.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def _datetime(value, timezone: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    zone = ZoneInfo(timezone)
    if result.tzinfo is None:
        first = result.replace(tzinfo=zone, fold=0)
        second = result.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("该时间在当前时区存在夏令时歧义，请填写明确的 UTC 偏移。")
        result = first
    return result.astimezone(zone)


def make_scope(mode: str, start=None, timezone: str = "Asia/Shanghai", now=None,
               last_checkpoint: dict | None = None, overlap_hours: int = 48) -> dict:
    """Freeze the run cutoff; incremental replay includes an explicit overlap."""
    if mode not in {"ALL_ACCESSIBLE", "SINCE", "INCREMENTAL"}:
        raise ValueError("请选择有效的采集模式。")
    zone = ZoneInfo(timezone)
    upper = _datetime(now or datetime.now(zone), timezone)
    lower = None
    checkpoint = last_checkpoint or {}
    if mode == "SINCE":
        if not start:
            raise ValueError("请选择起始日期或时间。")
        lower = _datetime(start, timezone)
    elif mode == "INCREMENTAL":
        previous = checkpoint.get("last_cutoff") or checkpoint.get("upper")
        if previous:
            lower = _datetime(previous, timezone) - timedelta(hours=overlap_hours)
    if lower and lower > upper:
        raise ValueError("起始时间不能晚于本次采集的截止时间。")
    return {
        "mode": mode, "start": lower.isoformat() if lower else None,
        "upper": upper.isoformat(), "timezone": timezone,
        "start_inclusive": True, "upper_inclusive": True,
        "date_only_start": bool(start and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(start))),
        "overlap_hours": overlap_hours if mode == "INCREMENTAL" else 0,
        "reconcile_old_edits": False,
    }


def parse_source_time(raw: str | None, observed_at=None, timezone="Asia/Shanghai",
                      *, inherited_separator: bool = False) -> dict:
    """Parse only explicit years or anchored relative dates; keep ambiguity."""
    observed = _datetime(observed_at or datetime.now(ZoneInfo(timezone)), timezone)
    value = (raw or "").strip()
    result = {"source_time_raw": raw, "start": None, "end": None,
              "source_time": None, "timezone": timezone, "precision": "unknown",
              "status": "unknown", "observed_at": observed.isoformat(),
              "inherited_separator": inherited_separator}
    if not value:
        return result
    moment, precision, length = None, None, None
    normalized = value.replace("年", "-").replace("月", "-").replace("日", "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", normalized):
            year, month, day = map(int, normalized.split("-"))
            moment = datetime(year, month, day, tzinfo=ZoneInfo(timezone))
            precision, length = "day", timedelta(days=1)
        elif re.match(r"^\d{4}-\d{1,2}-\d{1,2}[ T]", normalized):
            # ISO parsing requires zero-padded month/day, so normalize those first.
            normalized = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})",
                                lambda m: f"{int(m[1]):04}-{int(m[2]):02}-{int(m[3]):02}", normalized)
            moment = _datetime(normalized, timezone)
            has_seconds = bool(re.search(r"\d{2}:\d{2}:\d{2}", normalized))
            precision = "second" if has_seconds else "minute"
            length = timedelta(seconds=1) if has_seconds else timedelta(minutes=1)
        elif re.fullmatch(r"(?:今天|昨天|前天)(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?", value):
            label = next(x for x in ("今天", "昨天", "前天") if value.startswith(x))
            base = observed.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days={"今天": 0, "昨天": 1, "前天": 2}[label])
            time_part = value[len(label):].strip()
            if time_part:
                parts = [int(x) for x in time_part.split(":")]
                moment = base.replace(hour=parts[0], minute=parts[1], second=parts[2] if len(parts) == 3 else 0)
                precision = "second" if len(parts) == 3 else "minute"
                length = timedelta(seconds=1) if len(parts) == 3 else timedelta(minutes=1)
            else:
                moment, precision, length = base, "day", timedelta(days=1)
        elif match := re.fullmatch(r"(\d+)\s*(分钟|小时|天)前", value):
            unit = {"分钟": timedelta(minutes=1), "小时": timedelta(hours=1), "天": timedelta(days=1)}[match[2]]
            moment = observed - (int(match[1]) + 1) * unit
            precision, length = "relative_interval", unit
        elif value == "刚刚":
            moment, precision, length = observed - timedelta(minutes=1), "relative_interval", timedelta(minutes=1)
        else:
            result["status"] = "ambiguous" if re.search(r"\d|星期|周", value) else "unparsed"
            return result
    except (ValueError, OverflowError):
        result["status"] = "invalid"
        return result
    result.update(start=moment.isoformat(), end=(moment + length).isoformat(),
                  source_time=moment.isoformat() if precision == "second" and not inherited_separator else None,
                  precision=precision, status="parsed")
    if inherited_separator:
        # The separator is time evidence, not an exact timestamp or safe boundary.
        result["status"] = "context_only"
    return result


def classify_time(time_evidence: dict, scope: dict) -> str:
    """Return a boundary decision; uncertain items stay visible for review."""
    if time_evidence.get("status") != "parsed" or not time_evidence.get("start"):
        return "UNCERTAIN"
    zone = scope.get("timezone", "Asia/Shanghai")
    item_start = _datetime(time_evidence["start"], zone)
    item_end = _datetime(time_evidence.get("end") or time_evidence["start"], zone)
    lower = _datetime(scope["start"], zone) if scope.get("start") else None
    upper = _datetime(scope["upper"], zone)
    if time_evidence.get("source_time"):
        exact = _datetime(time_evidence["source_time"], zone)
        if exact > upper:
            return "AFTER"
        if lower and exact < lower:
            return "BEFORE"
        return "IN_RANGE"
    if item_start > upper:
        return "AFTER"
    if lower and item_end <= lower:
        return "BEFORE"
    if (lower and item_start < lower) or item_end > upper + timedelta(microseconds=1):
        return "UNCERTAIN"
    return "IN_RANGE"
