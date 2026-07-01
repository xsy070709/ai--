from __future__ import annotations

from datetime import datetime
from typing import Any

from ..storage import new_id, now_iso
from .text import emotion_tags, tokens, topics_from_text


LONG_TERM_TYPES = {
    "fact",
    "preference",
    "dislike",
    "boundary",
    "response_rule",
    "goal",
    "emotion_pattern",
    "relationship_signal",
    "stable_impression",
}

HUMAN_MEMORY_TYPES = LONG_TERM_TYPES | {"shared_experience", "episodic"}


def make_memory(
    memory_type: str,
    content: str,
    confidence: float,
    confirmed: bool,
    evidence_text: str,
    *,
    open_item: bool = False,
    valence: str = "neutral",
    stability: str = "medium",
    sensitivity_level: str = "low",
) -> dict[str, Any]:
    tags = sorted(set(tokens(content)) | set(topics_from_text(content)) | set(emotion_tags(content)))
    now = now_iso()
    return {
        "id": new_id("mem"),
        "type": memory_type,
        "content": content,
        "confidence": confidence,
        "importance": importance(memory_type, confirmed, open_item, valence),
        "salience": salience(memory_type, open_item, valence),
        "valence": valence,
        "stability": stability,
        "source_type": "chat",
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
        "last_reinforced_at": now if confirmed else None,
        "use_count": 0,
        "reinforcement_count": 1 if confirmed else 0,
        "sensitivity_level": sensitivity_level,
        "is_user_confirmed": confirmed,
        "status": "active",
        "open": bool(open_item),
        "tags": tags[:16],
        "evidence": [{"text": evidence_text, "created_at": now}],
        "surface_policy": surface_policy(memory_type, sensitivity_level, open_item),
    }


def importance(memory_type: str, confirmed: bool, open_item: bool, valence: str = "neutral") -> float:
    base = {
        "boundary": 0.94,
        "response_rule": 0.88,
        "goal": 0.84,
        "preference": 0.76,
        "dislike": 0.8,
        "emotion_pattern": 0.72,
        "relationship_signal": 0.7,
        "stable_impression": 0.82,
        "shared_experience": 0.74,
        "episodic": 0.66,
        "fact": 0.62,
    }.get(memory_type, 0.5)
    if confirmed:
        base += 0.08
    if open_item:
        base += 0.09
    if valence in {"negative", "vulnerable"}:
        base += 0.04
    return min(base, 1.0)


def salience(memory_type: str, open_item: bool, valence: str = "neutral") -> float:
    base = 0.5
    if memory_type in {"boundary", "goal", "response_rule"}:
        base += 0.22
    if memory_type in {"shared_experience", "episodic", "emotion_pattern"}:
        base += 0.14
    if memory_type == "stable_impression":
        base += 0.2
    if open_item:
        base += 0.16
    if valence in {"negative", "vulnerable"}:
        base += 0.08
    return min(base, 1.0)


def surface_policy(memory_type: str, sensitivity_level: str, open_item: bool) -> str:
    if sensitivity_level != "low":
        return "ask_before_surface"
    if memory_type == "boundary":
        return "obey_silently"
    if open_item:
        return "natural_follow_up"
    if memory_type in {"emotion_pattern", "relationship_signal"}:
        return "use_as_tone_guidance"
    return "use_when_relevant"


def parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0
