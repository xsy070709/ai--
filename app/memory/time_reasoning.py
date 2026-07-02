from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any


def infer_deadline(text: str, reference: datetime | str | None = None) -> dict[str, Any] | None:
    ref = _coerce_datetime(reference) or datetime.now().astimezone()
    date = ref.date()
    confidence = 0.0

    if "后天" in text:
        date = date + timedelta(days=2)
        confidence = 0.72
    elif "明天" in text:
        date = date + timedelta(days=1)
        confidence = 0.76
    elif "今天" in text or "今晚" in text:
        confidence = 0.68
    elif "昨天" in text:
        date = date - timedelta(days=1)
        confidence = 0.62
    else:
        match = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            date = date.replace(month=month, day=day)
            if date < ref.date():
                date = date.replace(year=date.year + 1)
            confidence = 0.7

    if confidence <= 0:
        return None

    hour, minute, grain = _time_of_day(text)
    due = datetime.combine(date, datetime.min.time(), tzinfo=ref.tzinfo).replace(hour=hour, minute=minute)
    return {
        "due_at": due.isoformat(timespec="seconds"),
        "due_grain": grain,
        "deadline_confidence": confidence,
        "deadline_source": "relative_time",
    }


def annotate_time_state(memory: dict[str, Any], now: datetime | str | None = None) -> dict[str, Any]:
    annotated = dict(memory)
    due_at = annotated.get("due_at")
    if not due_at:
        inferred = infer_deadline(annotated.get("content", ""), _memory_reference_time(annotated))
        if inferred:
            annotated.update(inferred)
            due_at = inferred["due_at"]
    due = _coerce_datetime(due_at)
    current = _coerce_datetime(now) or datetime.now().astimezone()
    if not due:
        annotated["time_state"] = "unknown"
        return annotated

    minutes = int((due - current).total_seconds() // 60)
    annotated["minutes_until_due"] = minutes
    if minutes < 0:
        annotated["time_state"] = "elapsed"
        annotated["time_reason"] = "约定时间已经过去，可以自然询问结果"
    elif minutes <= 180:
        annotated["time_state"] = "soon"
        annotated["time_reason"] = "约定时间临近，避免打断，必要时轻提醒"
    else:
        annotated["time_state"] = "upcoming"
        annotated["time_reason"] = "约定时间未到，不要假定已经结束"
    return annotated


def _time_of_day(text: str) -> tuple[int, int, str]:
    explicit = re.search(r"(\d{1,2})[点:：](\d{1,2})?", text)
    if explicit:
        hour = int(explicit.group(1))
        minute = int(explicit.group(2) or 0)
        if "下午" in text and hour < 12:
            hour += 12
        if "晚上" in text and hour < 12:
            hour += 12
        return min(hour, 23), min(minute, 59), "explicit"
    if "中午" in text:
        return 13, 0, "noon"
    if "上午" in text or "早上" in text:
        return 11, 0, "morning"
    if "下午" in text:
        return 18, 0, "afternoon"
    if "晚上" in text or "今晚" in text:
        return 22, 0, "evening"
    return 23, 59, "day"


def _memory_reference_time(memory: dict[str, Any]) -> str | None:
    evidence = memory.get("evidence") or []
    if evidence and isinstance(evidence[0], dict):
        return evidence[0].get("created_at")
    return memory.get("created_at")


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone() if value.tzinfo else value.astimezone()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone()
    except ValueError:
        return None
