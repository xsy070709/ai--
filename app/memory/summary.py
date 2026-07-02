from __future__ import annotations

from typing import Any

from ..storage import new_id, now_iso
from .params import DEFAULT_MEMORY_PARAMS
from .semantic import semantic_similarity
from .signals import is_high_density, looks_like_casual_chat
from .text import emotion_tags, topics_from_text, unfinished_items


PARAMS = DEFAULT_MEMORY_PARAMS.summary


def work_memory(messages: list[dict[str, Any]], user_text: str = "", limit: int | None = None) -> list[dict[str, str]]:
    if limit is None:
        limit = _dynamic_work_memory_limit(messages, user_text)
    recent = messages[-limit:]
    return [{"role": item["role"], "content": item["content"]} for item in recent]


def build_session_summary(messages: list[dict[str, Any]], after_message_count: int = 0) -> dict[str, Any] | None:
    if len(messages) < PARAMS.topic_shift_min_messages:
        return None

    segment = messages[max(0, after_message_count) :]
    if not segment:
        return None
    summary_messages = _previous_topic_messages(segment) if _has_topic_shift(segment) else []
    if not summary_messages:
        window = min(len(segment), PARAMS.min_summary_messages)
        summary_messages = segment[-window:]
    user_lines = [m["content"] for m in summary_messages if m["role"] == "user"]
    joined = " ".join(user_lines)
    open_items = unfinished_items(joined)
    emotions = emotion_tags(joined)
    topics = topics_from_text(joined)
    return {
        "id": new_id("summary"),
        "created_at": now_iso(),
        "message_count": len(messages),
        "covered_message_count": len(summary_messages),
        "summary": _summary_sentence(user_lines, topics, emotions, open_items),
        "topics": topics,
        "user_emotion": "、".join(emotions) if emotions else "平稳",
        "unfinished_items": open_items,
        "follow_up_suggestion": _follow_up_suggestion(open_items, emotions),
        "importance": 0.72 if open_items or emotions else 0.48,
    }


def should_build_session_summary(messages: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> bool:
    count = len(messages)
    if count < PARAMS.topic_shift_min_messages:
        return False
    if summaries and summaries[-1].get("message_count") == count:
        return False
    if not summaries and count >= PARAMS.min_summary_messages:
        return True
    last_summary_count = int(summaries[-1].get("message_count", 0)) if summaries else 0
    if summaries and count - last_summary_count >= PARAMS.max_summary_interval:
        return True
    return _has_topic_shift(messages)


def _dynamic_work_memory_limit(messages: list[dict[str, Any]], user_text: str) -> int:
    if user_text and (is_high_density(user_text) or any(word in user_text for word in ["继续", "上次", "还记得", "后来"])):
        return PARAMS.deep_work_memory_limit
    if user_text and looks_like_casual_chat(user_text):
        return PARAMS.casual_work_memory_limit
    recent_user_text = " ".join(message["content"] for message in messages[-6:] if message.get("role") == "user")
    if recent_user_text and emotion_tags(recent_user_text):
        return PARAMS.deep_work_memory_limit
    return PARAMS.default_work_memory_limit


def _has_topic_shift(messages: list[dict[str, Any]]) -> bool:
    user_lines = [message["content"] for message in messages if message.get("role") == "user"]
    if len(user_lines) < 4:
        return False
    recent_topics = set(topics_from_text(" ".join(user_lines[-2:])))
    previous_text = " ".join(user_lines[-6:-2])
    recent_text = " ".join(user_lines[-2:])
    previous_topics = set(topics_from_text(previous_text))
    if recent_topics == {"日常聊天"} or previous_topics == {"日常聊天"}:
        return False
    if recent_topics & previous_topics:
        return False
    return semantic_similarity(previous_text, recent_text) < PARAMS.topic_shift_similarity_threshold


def _previous_topic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_count = len([message for message in messages if message.get("role") == "user"])
    if user_count < 4:
        return []
    recent_topic_first_user = user_count - 2
    seen_users = 0
    previous: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "user":
            if seen_users >= recent_topic_first_user:
                break
            seen_users += 1
        previous.append(message)
    return previous


def _summary_sentence(user_lines: list[str], topics: list[str], emotions: list[str], open_items: list[str]) -> str:
    recent = "；".join(user_lines[-3:])
    parts = [f"近期话题：{'、'.join(topics)}"]
    if emotions:
        parts.append(f"情绪倾向：{'、'.join(emotions)}")
    if open_items:
        parts.append(f"待跟进：{'；'.join(open_items)}")
    parts.append(f"最近用户提到：{recent}")
    return "。".join(parts)


def _follow_up_suggestion(open_items: list[str], emotions: list[str]) -> str:
    if open_items:
        return f"下次可自然问一句：{open_items[0]}后来怎么样了。"
    if emotions:
        return "下次如果话题相关，先确认用户状态，不要直接讲道理。"
    return "保持轻量接续，不主动翻旧账。"
