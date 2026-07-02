from __future__ import annotations

from typing import Any

from ..storage import now_iso
from .lifecycle import normalize_memory
from .text import canonical_content, infer_type, tokens


def tidy_memories(memories: list[dict[str, Any]]) -> dict[str, Any]:
    report = {"normalized": [], "merged": [], "archived": []}
    active = [memory for memory in memories if memory.get("status", "active") == "active"]

    for memory in active:
        before = memory.get("content", "")
        normalize_memory(memory)
        if memory.get("content") != before:
            memory["updated_at"] = now_iso()
            report["normalized"].append({"id": memory.get("id"), "before": before, "after": memory.get("content")})

    _archive_low_value_facts(active, report)
    _archive_redundant_preferences(active, report)
    _archive_generic_emotion_patterns(active, report)
    _merge_duplicates(active, report)
    return report


def _archive_low_value_facts(memories: list[dict[str, Any]], report: dict[str, Any]) -> None:
    active_preferences = [memory for memory in memories if memory.get("status") == "active" and memory.get("type") == "preference"]
    preference_keys = {canonical_content(memory) for memory in active_preferences}
    for memory in memories:
        if memory.get("status") != "active" or memory.get("type") != "fact":
            continue
        content = memory.get("content", "")
        key = canonical_content(memory)
        looks_like_preference = infer_type(content) == "preference" or "喜欢" in content or "偏好" in content
        if looks_like_preference and any(key and (key in pref_key or pref_key in key) for pref_key in preference_keys):
            _archive(memory, "fact_duplicate_of_preference", report)
        elif "今天有点累" in content and len(tokens(content)) <= 4:
            _archive(memory, "low_value_ephemeral_fact", report)


def _archive_redundant_preferences(memories: list[dict[str, Any]], report: dict[str, Any]) -> None:
    response_keys = [
        canonical_content(memory)
        for memory in memories
        if memory.get("status") == "active" and memory.get("type") == "response_rule"
    ]
    for memory in memories:
        if memory.get("status") != "active" or memory.get("type") != "preference":
            continue
        key = canonical_content(memory)
        if key and any(key in response_key for response_key in response_keys):
            _archive(memory, "preference_redundant_with_response_rule", report)


def _archive_generic_emotion_patterns(memories: list[dict[str, Any]], report: dict[str, Any]) -> None:
    for memory in memories:
        if memory.get("status") != "active" or memory.get("type") != "emotion_pattern":
            continue
        content = memory.get("content", "")
        if "当前情境" in content and not memory.get("is_user_confirmed"):
            _archive(memory, "generic_emotion_pattern", report)


def _merge_duplicates(memories: list[dict[str, Any]], report: dict[str, Any]) -> None:
    keepers: dict[tuple[str, str], dict[str, Any]] = {}
    for memory in memories:
        if memory.get("status") != "active":
            continue
        key = (memory.get("type", ""), canonical_content(memory))
        if not key[1]:
            continue
        keeper = keepers.get(key)
        if not keeper:
            keepers[key] = memory
            continue
        _merge_into_keeper(keeper, memory)
        _archive(memory, f"merged_into:{keeper.get('id')}", report)
        report["merged"].append({"source_id": memory.get("id"), "target_id": keeper.get("id"), "type": memory.get("type")})


def _merge_into_keeper(keeper: dict[str, Any], duplicate: dict[str, Any]) -> None:
    keeper["confidence"] = max(float(keeper.get("confidence", 0.5)), float(duplicate.get("confidence", 0.5)))
    keeper["importance"] = max(float(keeper.get("importance", 0.5)), float(duplicate.get("importance", 0.5)))
    keeper["salience"] = max(float(keeper.get("salience", 0.5)), float(duplicate.get("salience", 0.5)))
    keeper["use_count"] = int(keeper.get("use_count", 0)) + int(duplicate.get("use_count", 0))
    keeper["is_user_confirmed"] = bool(keeper.get("is_user_confirmed")) or bool(duplicate.get("is_user_confirmed"))
    keeper["updated_at"] = now_iso()
    keeper.setdefault("evidence", [])
    keeper["evidence"].extend(duplicate.get("evidence", []))
    keeper["evidence"] = keeper["evidence"][-8:]
    keeper.setdefault("tags", [])
    for tag in duplicate.get("tags", []):
        if tag not in keeper["tags"]:
            keeper["tags"].append(tag)
    keeper["tags"] = keeper["tags"][:16]


def _archive(memory: dict[str, Any], reason: str, report: dict[str, Any]) -> None:
    if memory.get("status") != "active":
        return
    memory["status"] = "archived"
    memory["archive_reason"] = reason
    memory["updated_at"] = now_iso()
    report["archived"].append({"id": memory.get("id"), "type": memory.get("type"), "content": memory.get("content"), "reason": reason})
