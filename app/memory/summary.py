from __future__ import annotations

from typing import Any

from ..storage import new_id, now_iso
from .text import emotion_tags, topics_from_text, unfinished_items


def work_memory(messages: list[dict[str, Any]], limit: int = 24) -> list[dict[str, str]]:
    recent = messages[-limit:]
    return [{"role": item["role"], "content": item["content"]} for item in recent]


def build_session_summary(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(messages) < 16:
        return None

    recent = messages[-16:]
    user_lines = [m["content"] for m in recent if m["role"] == "user"]
    joined = " ".join(user_lines)
    open_items = unfinished_items(joined)
    emotions = emotion_tags(joined)
    topics = topics_from_text(joined)
    return {
        "id": new_id("summary"),
        "created_at": now_iso(),
        "summary": _summary_sentence(user_lines, topics, emotions, open_items),
        "topics": topics,
        "user_emotion": "、".join(emotions) if emotions else "平稳",
        "unfinished_items": open_items,
        "follow_up_suggestion": _follow_up_suggestion(open_items, emotions),
        "importance": 0.72 if open_items or emotions else 0.48,
    }


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
