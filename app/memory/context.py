from __future__ import annotations

from typing import Any

from .followup import build_followup_plan, format_followup_plan
from .initiative import build_disclosure_plan, format_disclosure_plan
from .profile import build_user_profile
from .recall import relevant_memories


def build_memory_context(memories: list[dict[str, Any]], user_text: str, limit: int = 8) -> dict[str, Any]:
    profile = build_user_profile(memories)
    recalled = relevant_memories(memories, user_text, limit=limit)
    followup_plan = build_followup_plan(profile, recalled, user_text)
    disclosure_plan = build_disclosure_plan(recalled, user_text, followup_plan)
    return {
        "profile": profile,
        "recalled": recalled,
        "followup_plan": followup_plan,
        "disclosure_plan": disclosure_plan,
        "prompt_text": format_memory_context(profile, recalled, followup_plan, disclosure_plan),
    }


def format_memory_context(
    profile: dict[str, Any],
    recalled: list[dict[str, Any]],
    followup_plan: dict[str, Any] | None = None,
    disclosure_plan: dict[str, Any] | None = None,
) -> str:
    lines = ["用户长期画像："]
    sections = [
        ("偏好", profile["preferences"]),
        ("反感/雷区", profile["dislikes"] + profile["boundaries"]),
        ("希望的回应方式", profile["response_rules"]),
        ("目标/待办", profile["goals"]),
        ("情绪模式", profile["emotion_patterns"]),
        ("稳定印象", profile["stable_impressions"]),
        ("共同经历", profile["shared_experiences"]),
    ]
    for label, items in sections:
        if items:
            lines.append(f"- {label}：" + "；".join(item["content"] for item in items[:4]))
    if profile["open_loops"]:
        lines.append("- 可自然跟进：" + "；".join(item["content"] for item in profile["open_loops"][:3]))
    if profile["tone_guidance"]:
        lines.append("- 语气策略：" + "；".join(profile["tone_guidance"][:5]))
    relationship = profile["relationship_state"]
    lines.append(
        f"- 关系状态：亲密度 {relationship['intimacy_level']}/5，信任 {relationship['trust_level']}/5；{relationship['notes']}"
    )
    if recalled:
        lines.append("本轮相关记忆：")
        for memory in recalled:
            reason = memory.get("recall_reason", "相关")
            policy = memory.get("surface_policy", "use_when_relevant")
            lines.append(f"- [{memory['type']}/{reason}/{policy}] {memory['content']}")
    if followup_plan:
        lines.append(format_followup_plan(followup_plan))
    if disclosure_plan:
        lines.append(format_disclosure_plan(disclosure_plan))
    if len(lines) == 1:
        lines.append("- 暂无稳定画像。")
    return "\n".join(lines)
