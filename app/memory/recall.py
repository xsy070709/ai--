from __future__ import annotations

from typing import Any

from .maintenance import should_apply_recall_cooldown
from .params import DEFAULT_MEMORY_PARAMS
from .semantic import semantic_similarity
from .text import emotion_tags, tokens


PARAMS = DEFAULT_MEMORY_PARAMS.recall


def relevant_memories(memories: list[dict[str, Any]], user_text: str, limit: int = PARAMS.default_limit) -> list[dict[str, Any]]:
    active = [m for m in memories if m.get("status") == "active"]
    query_tokens = set(tokens(user_text))
    query_emotions = set(emotion_tags(user_text))
    scored: list[tuple[float, dict[str, Any]]] = []

    for memory in active:
        score, reasons = _score_memory(memory, user_text, query_tokens, query_emotions)
        if score >= PARAMS.min_score_threshold:
            recalled = dict(memory)
            recalled["recall_score"] = round(score, 3)
            recalled["recall_reason"] = "、".join(reasons[:4]) or "重要"
            scored.append((score, recalled))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def _score_memory(memory: dict[str, Any], user_text: str, query_tokens: set[str], query_emotions: set[str]) -> tuple[float, list[str]]:
    content = memory.get("content", "")
    memory_tokens = set(tokens(content)) | set(memory.get("tags", []))
    overlap = len(query_tokens & memory_tokens)
    score = overlap * PARAMS.token_overlap_multiplier
    reasons: list[str] = []

    if overlap:
        reasons.append("语义相关")
    if memory.get("is_user_confirmed"):
        score += PARAMS.confirmed_bonus
        reasons.append("用户确认")
    if memory.get("open"):
        score += PARAMS.open_item_bonus
        reasons.append("待跟进")
    if query_emotions and memory.get("type") in {"emotion_pattern", "response_rule"}:
        score += PARAMS.emotion_match_bonus
        reasons.append("情绪相关")
    if any(word in user_text for word in PARAMS.continuation_words):
        score += PARAMS.history_continuation_bonus
        reasons.append("旧事接续")
    if memory.get("type") == "boundary":
        score += PARAMS.boundary_bonus
        reasons.append("边界约束")
    if memory.get("surface_policy") == "use_as_tone_guidance":
        score += PARAMS.tone_guidance_bonus
    similarity = semantic_similarity(user_text, content)
    if similarity >= PARAMS.semantic_similarity_threshold:
        score += similarity * PARAMS.semantic_similarity_weight
        reasons.append("语义近似")
    if should_apply_recall_cooldown(memory) and not any(word in user_text for word in PARAMS.continuation_words):
        score -= PARAMS.cooldown_penalty
        reasons.append("冷却降权")

    score += memory.get("importance", 0.5) * PARAMS.importance_weight
    score += memory.get("salience", 0.5) * PARAMS.salience_weight
    score += memory.get("confidence", 0.5) * PARAMS.confidence_weight
    return score, reasons
