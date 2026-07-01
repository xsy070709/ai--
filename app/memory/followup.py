from __future__ import annotations

from typing import Any

from ..storage import now_iso
from .text import tokens


COMPLETION_WORDS = ["交完", "做完", "完成", "结束", "面完", "考完", "提交了", "弄完", "解决了", "已经好了"]


def close_resolved_open_loops(memories: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
    if not any(word in user_text for word in COMPLETION_WORDS):
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
    anchors = ["材料", "面试", "考试", "项目", "开会", "作业", "报告", "任务"]
    if any(anchor in memory_content and anchor in user_text for anchor in anchors):
        return True
    memory_compact = memory_content.replace("待跟进：", "")
    return any(len(token) >= 2 and token in user_text for token in tokens(memory_compact))


def build_followup_plan(profile: dict[str, Any], recalled: list[dict[str, Any]], user_text: str) -> dict[str, Any]:
    if any(word in user_text for word in COMPLETION_WORDS):
        return {"mode": "acknowledge_closure", "items": [], "instruction": "用户可能在汇报事项完成，先回应结果，不要继续追问同一待办。"}

    open_recalled = [memory for memory in recalled if memory.get("open")]
    if open_recalled and not _looks_like_casual_chat(user_text):
        return {
            "mode": "gentle_follow_up",
            "items": open_recalled[:2],
            "instruction": "可以自然轻问待跟进事项，但只问一个点，不要像任务管理器。",
        }

    open_profile = profile.get("open_loops", [])
    if open_profile and any(word in user_text for word in ["继续", "后来", "上次", "还记得"]):
        return {
            "mode": "user_invited_follow_up",
            "items": open_profile[:2],
            "instruction": "用户主动提到接续旧事，可以自然接上相关待办。",
        }

    return {"mode": "none", "items": [], "instruction": "不要主动翻旧账。"}


def _looks_like_casual_chat(user_text: str) -> bool:
    return len(user_text.strip()) <= 12 and not any(word in user_text for word in ["继续", "后来", "上次", "还记得", "怎么办", "焦虑", "难受"])


def format_followup_plan(plan: dict[str, Any]) -> str:
    lines = [f"跟进策略：{plan['mode']}。{plan['instruction']}"]
    for item in plan.get("items", []):
        lines.append(f"- 可跟进：{item['content']}")
    return "\n".join(lines)
