from __future__ import annotations

from datetime import datetime
from typing import Any

from .params import DEFAULT_MEMORY_PARAMS
from .signals import emotion_tags_for, has_task_signal, has_time_signal, looks_like_casual_chat


PARAMS = DEFAULT_MEMORY_PARAMS.conversation


def build_logical_turn(previous_messages: list[dict[str, Any]], current_user_message: dict[str, Any]) -> dict[str, Any]:
    fragments = [current_user_message]
    current_time = _parse_time(current_user_message.get("created_at"))

    for message in reversed(previous_messages):
        if message.get("role") != "user":
            continue
        if len(fragments) >= PARAMS.logical_turn_max_messages:
            break
        if not _is_cluster_fragment(message.get("content", "")):
            break
        message_time = _parse_time(message.get("created_at"))
        if current_time and message_time:
            delta = abs((current_time - message_time).total_seconds())
            if delta > PARAMS.logical_turn_window_seconds:
                break
        fragments.append(message)

    fragments.reverse()
    text = " ".join(fragment.get("content", "").strip() for fragment in fragments if fragment.get("content", "").strip())
    return {
        "text": text,
        "message_ids": [fragment.get("id") for fragment in fragments if fragment.get("id")],
        "message_count": len(fragments),
        "window_seconds": PARAMS.logical_turn_window_seconds,
        "clustered": len(fragments) > 1,
    }


def _is_cluster_fragment(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    has_progress_signal = has_time_signal(stripped) or has_task_signal(stripped) or bool(emotion_tags_for(stripped))
    if _looks_like_standalone_memory(stripped) and not has_progress_signal:
        return False
    if len(stripped) <= PARAMS.logical_turn_fragment_chars:
        return True
    if len(stripped) <= PARAMS.logical_turn_fragment_chars * 2 and has_progress_signal:
        return True
    return looks_like_casual_chat(stripped)


def _looks_like_standalone_memory(text: str) -> bool:
    return any(word in text for word in ["记住", "喜欢", "希望", "以后", "下次", "别", "不要", "雷区", "不想聊"])


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_local_timezone())
    return parsed.astimezone()


def _local_timezone():
    return datetime.now().astimezone().tzinfo
