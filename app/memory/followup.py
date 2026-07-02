from __future__ import annotations

from typing import Any

from ..storage import now_iso
from .params import DEFAULT_MEMORY_PARAMS
from .signals import has_completion_signal, looks_like_casual_chat
from .text import tokens
from .time_reasoning import annotate_time_state


PARAMS = DEFAULT_MEMORY_PARAMS.conversation
COMPLETION_WORDS = PARAMS.completion_words


def close_resolved_open_loops(memories: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
    if not has_completion_signal(user_text):
        return []

    user_tokens = set(tokens(user_text))
    closed = []
    for memory in memories:
        if memory.get("status") != "active" or not memory.get("open"):
            continue
        memory_tokens = set(tokens(memory.get("content", ""))) | set(memory.get("tags", []))
        if user_tokens & memory_tokens or _has_completion_overlap(memory.get("content", ""), user_text):
            memory["open"] = False
            memory["closed_at"] = now_iso()
            memory["outcome"] = user_text
            memory["updated_at"] = now_iso()
            memory.setdefault("evidence", []).append({"text": user_text, "created_at": now_iso(), "kind": "closed_loop"})
            closed.append(memory)
    return closed


def _has_completion_overlap(memory_content: str, user_text: str) -> bool:
    if any(anchor in memory_content and anchor in user_text for anchor in PARAMS.completion_overlap_anchors):
        return True
    memory_compact = memory_content.replace("待跟进：", "")
    return any(len(token) >= 2 and token in user_text for token in tokens(memory_compact))


def build_followup_plan(profile: dict[str, Any], recalled: list[dict[str, Any]], user_text: str, now: str | None = None) -> dict[str, Any]:
    if has_completion_signal(user_text):
        return {"mode": "acknowledge_closure", "items": [], "instruction": "用户可能在汇报事项完成，先回应结果，不要继续追问同一待办。"}

    open_recalled = [annotate_time_state(memory, now) if memory.get("type") == "goal" else memory for memory in recalled if memory.get("open")]
    elapsed_recalled = [memory for memory in open_recalled if memory.get("time_state") == "elapsed"]
    if elapsed_recalled and not _looks_like_casual_chat(user_text):
        return {
            "mode": "elapsed_follow_up",
            "items": elapsed_recalled[:1],
            "instruction": "待跟进事项的约定时间已过，可以像朋友一样轻问结果；不要假装已经知道结果。",
        }
    if elapsed_recalled and _looks_like_casual_chat(user_text):
        return {
            "mode": "elapsed_casual_follow_up",
            "items": elapsed_recalled[:1],
            "instruction": "用户在闲聊，且旧事项时间已过；可以顺口轻问一句结果，也可以先接当前闲聊，不要连环追问。",
        }
    if open_recalled and not _looks_like_casual_chat(user_text):
        return {
            "mode": "gentle_follow_up",
            "items": open_recalled[: PARAMS.followup_item_limit],
            "instruction": "可以自然轻问待跟进事项，但只问一个点，不要像任务管理器。",
        }

    open_profile = profile.get("open_loops", [])
    elapsed_profile = [
        annotate_time_state(memory, now) if memory.get("type") == "goal" else memory
        for memory in open_profile
        if memory.get("time_state") == "elapsed" or annotate_time_state(memory, now).get("time_state") == "elapsed"
    ]
    if elapsed_profile and _looks_like_casual_chat(user_text):
        return {
            "mode": "elapsed_casual_follow_up",
            "items": elapsed_profile[:1],
            "instruction": "用户在闲聊，且旧事项时间已过；可以顺口轻问一句结果，也可以先接当前闲聊，不要连环追问。",
        }
    if open_profile and any(word in user_text for word in ["继续", "后来", "上次", "还记得"]):
        return {
            "mode": "user_invited_follow_up",
            "items": open_profile[: PARAMS.profile_open_loop_limit],
            "instruction": "用户主动提到接续旧事，可以自然接上相关待办。",
        }

    return {"mode": "none", "items": [], "instruction": "不要主动翻旧账。"}


def _looks_like_casual_chat(user_text: str) -> bool:
    return looks_like_casual_chat(user_text, PARAMS.casual_exemption_words, PARAMS.casual_max_chars)


def format_followup_plan(plan: dict[str, Any]) -> str:
    lines = [f"跟进策略：{plan['mode']}。{plan['instruction']}"]
    for item in plan.get("items", []):
        lines.append(f"- 可跟进：{item['content']}")
    return "\n".join(lines)
