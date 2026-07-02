from __future__ import annotations

from typing import Any

from .schema import parse_time
from .time_reasoning import annotate_time_state


def build_user_profile(memories: list[dict[str, Any]], now: str | None = None) -> dict[str, Any]:
    active = [m for m in memories if m.get("status") == "active"]
    active = [annotate_time_state(memory, now) if memory.get("type") == "goal" else memory for memory in active]
    profile = {
        "preferences": _top_contents(active, "preference", 6),
        "dislikes": _top_contents(active, "dislike", 6),
        "boundaries": _top_contents(active, "boundary", 6),
        "response_rules": _top_contents(active, "response_rule", 6),
        "goals": _top_contents(active, "goal", 6),
        "emotion_patterns": _top_contents(active, "emotion_pattern", 6),
        "stable_impressions": _top_contents(active, "stable_impression", 6),
        "relationship_signals": _top_contents(active, "relationship_signal", 4),
        "shared_experiences": _top_contents(active, "shared_experience", 4),
        "open_loops": [m for m in active if m.get("open")][:8],
    }
    profile["relationship_state"] = _relationship_state(active)
    profile["tone_guidance"] = _tone_guidance(profile)
    return profile


def _top_contents(memories: list[dict[str, Any]], memory_type: str, limit: int) -> list[dict[str, Any]]:
    items = [m for m in memories if m.get("type") == memory_type]
    items.sort(
        key=lambda m: (
            m.get("importance", 0),
            m.get("salience", 0),
            m.get("confidence", 0),
            parse_time(m.get("updated_at")),
        ),
        reverse=True,
    )
    return items[:limit]


def _relationship_state(memories: list[dict[str, Any]]) -> dict[str, Any]:
    positive = len([m for m in memories if m.get("type") == "relationship_signal" and m.get("valence") == "positive"])
    negative = len([m for m in memories if m.get("type") == "relationship_signal" and m.get("valence") == "negative"])
    shared = len([m for m in memories if m.get("type") == "shared_experience"])
    intimacy = min(5, 1 + positive + shared // 2)
    trust = max(1, min(5, 3 + positive - negative))
    return {
        "intimacy_level": intimacy,
        "trust_level": trust,
        "notes": "已有共同经历，可自然接续" if shared else "仍处于早期熟悉阶段",
    }


def _tone_guidance(profile: dict[str, Any]) -> list[str]:
    guidance = ["默认短回复", "先接情绪再回应事实"]
    if profile["response_rules"]:
        guidance.extend(memory["content"] for memory in profile["response_rules"][:3])
    if profile["emotion_patterns"]:
        guidance.append("用户有压力或疲惫信号时，少讲大道理，多陪伴和拆小步。")
    if profile["stable_impressions"]:
        guidance.extend(memory["content"] for memory in profile["stable_impressions"][:2])
    if profile["boundaries"] or profile["dislikes"]:
        guidance.append("避开用户明确反感或标记为雷区的话题。")
    return guidance[:6]
