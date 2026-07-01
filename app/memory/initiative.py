from __future__ import annotations

from typing import Any


INVITE_WORDS = ["还记得", "之前", "上次", "继续", "后来", "刚才说", "那个"]


def build_disclosure_plan(recalled: list[dict[str, Any]], user_text: str, followup_plan: dict[str, Any]) -> dict[str, Any]:
    items = []
    for memory in recalled:
        action, reason = _decide_action(memory, user_text, followup_plan)
        items.append(
            {
                "memory_id": memory["id"],
                "type": memory["type"],
                "action": action,
                "reason": reason,
                "content": memory["content"],
            }
        )
    return {
        "mode": _overall_mode(items),
        "items": items,
        "instruction": _instruction(items),
    }


def format_disclosure_plan(plan: dict[str, Any]) -> str:
    lines = [f"记忆表露策略：{plan['mode']}。{plan['instruction']}"]
    for item in plan.get("items", []):
        lines.append(f"- {item['action']} [{item['type']}] {item['reason']}：{item['content']}")
    return "\n".join(lines)


def _decide_action(memory: dict[str, Any], user_text: str, followup_plan: dict[str, Any]) -> tuple[str, str]:
    memory_type = memory.get("type")
    policy = memory.get("surface_policy", "use_when_relevant")
    invited = any(word in user_text for word in INVITE_WORDS)

    if memory_type == "boundary" or policy == "obey_silently":
        return "obey", "只默默遵守边界，不主动复述"
    if policy == "ask_before_surface":
        return "silent", "敏感记忆，除非用户明确问起，否则不表露"
    if memory.get("open") and followup_plan.get("mode") == "user_invited_follow_up":
        return "mention", "当前适合自然跟进未完成事项"
    if memory.get("open") and followup_plan.get("mode") == "gentle_follow_up" and memory.get("recall_score", 0) >= 4.5:
        return "mention", "当前话题强相关，可轻问未完成事项"
    if invited and memory_type in {"shared_experience", "goal", "episodic", "stable_impression"}:
        return "mention", "用户主动邀请接续旧事"
    if memory_type in {"emotion_pattern", "relationship_signal", "stable_impression"}:
        return "hint", "只影响语气，不要贴标签式复述"
    if memory.get("recall_score", 0) >= 4.2 and not _looks_like_casual_chat(user_text):
        return "hint", "相关性较高，可轻描淡写地带入"
    return "silent", "相关但不适合主动提起"


def _overall_mode(items: list[dict[str, Any]]) -> str:
    if any(item["action"] == "mention" for item in items):
        return "can_mention"
    if any(item["action"] == "hint" for item in items):
        return "tone_only"
    if any(item["action"] == "obey" for item in items):
        return "silent_obey"
    return "quiet"


def _instruction(items: list[dict[str, Any]]) -> str:
    if any(item["action"] == "mention" for item in items):
        return "可以自然提一条最相关记忆，但不要列清单。"
    if any(item["action"] == "hint" for item in items):
        return "只把记忆用于语气和措辞，不要说“我记得你……”。"
    if any(item["action"] == "obey" for item in items):
        return "遵守用户边界，不复述敏感内容。"
    return "不要主动提旧事。"


def _looks_like_casual_chat(user_text: str) -> bool:
    return len(user_text) <= 12 and not any(word in user_text for word in ["焦虑", "难受", "怎么办", "继续", "上次", "记得"])
