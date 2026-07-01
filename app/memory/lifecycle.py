from __future__ import annotations

from typing import Any

from ..storage import now_iso
from .text import canonical_content, tokens


def upsert_memories(existing: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for candidate in candidates:
        _resolve_direct_conflict(existing, candidate)
        match = _find_merge_target(existing, candidate)
        if not match:
            existing.append(candidate)
            continue
        _merge_into(match, candidate)
    return existing


def mark_recalled(memories: list[dict[str, Any]], recalled_ids: list[str]) -> None:
    ids = set(recalled_ids)
    if not ids:
        return
    for memory in memories:
        if memory.get("id") in ids:
            memory["last_used_at"] = now_iso()
            memory["use_count"] = int(memory.get("use_count", 0)) + 1


def _find_merge_target(existing: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_tokens = set(tokens(candidate["content"]))
    candidate_canonical = canonical_content(candidate)
    for memory in existing:
        if memory.get("status") != "active" or memory.get("type") != candidate["type"]:
            continue
        memory_canonical = canonical_content(memory)
        if candidate_canonical and memory_canonical and (
            candidate_canonical in memory_canonical or memory_canonical in candidate_canonical
        ):
            return memory
        memory_tokens = set(tokens(memory.get("content", "")))
        overlap = len(candidate_tokens & memory_tokens)
        if overlap >= max(2, min(len(candidate_tokens), len(memory_tokens)) // 2):
            return memory
    return None


def _merge_into(target: dict[str, Any], candidate: dict[str, Any]) -> None:
    target["content"] = _merge_content(target["content"], candidate["content"])
    target["confidence"] = min(0.98, max(target.get("confidence", 0.5), candidate["confidence"]) + 0.05)
    target["importance"] = min(1.0, max(target.get("importance", 0.5), candidate.get("importance", 0.5)))
    target["salience"] = min(1.0, max(target.get("salience", 0.5), candidate.get("salience", 0.5)))
    target["updated_at"] = now_iso()
    target["last_reinforced_at"] = now_iso()
    target["status"] = "active"
    target["is_user_confirmed"] = target.get("is_user_confirmed", False) or candidate.get("is_user_confirmed", False)
    target["reinforcement_count"] = int(target.get("reinforcement_count", 0)) + 1
    target.setdefault("evidence", []).extend(candidate.get("evidence", []))
    target["evidence"] = target["evidence"][-6:]
    target.setdefault("tags", [])
    for tag in candidate.get("tags", []):
        if tag not in target["tags"]:
            target["tags"].append(tag)
    if candidate.get("open"):
        target["open"] = True
    if candidate.get("surface_policy") == "ask_before_surface":
        target["surface_policy"] = "ask_before_surface"


def _merge_content(old: str, new: str) -> str:
    if new in old:
        return old
    if old in new:
        return new
    return f"{old}；{new}"


def _resolve_direct_conflict(existing: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    if candidate["type"] not in {"preference", "dislike"}:
        return
    candidate_key = canonical_content(candidate)
    opposite = "dislike" if candidate["type"] == "preference" else "preference"
    for memory in existing:
        if memory.get("status") != "active" or memory.get("type") != opposite:
            continue
        memory_key = canonical_content(memory)
        if candidate_key and memory_key and (candidate_key in memory_key or memory_key in candidate_key):
            memory["status"] = "superseded"
            memory["superseded_by"] = candidate["id"]
            memory["updated_at"] = now_iso()
