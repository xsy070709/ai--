from __future__ import annotations

from typing import Any

from ..storage import now_iso
from .text import canonical_content, normalize_content, tokens


def upsert_memories(existing: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for candidate in candidates:
        normalize_memory(candidate)
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
    normalize_memory(target)
    normalize_memory(candidate)
    target["content"] = _merge_content(target, candidate)
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


def _merge_content(target: dict[str, Any], candidate: dict[str, Any]) -> str:
    old = target["content"]
    new = candidate["content"]
    if new in old:
        return old
    if old in new:
        return new
    if target.get("type") in {"preference", "dislike", "response_rule", "emotion_pattern"}:
        old_key = canonical_content(target)
        new_key = canonical_content(candidate)
        if old_key == new_key or old_key in new_key or new_key in old_key:
            return old if len(old) <= len(new) else new
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


def normalize_memory(memory: dict[str, Any]) -> dict[str, Any]:
    memory_type = memory.get("type", "")
    content = str(memory.get("content", "")).strip()
    if memory_type in {"preference", "dislike"}:
        memory["content"] = normalize_content(memory_type, content)
    elif memory_type == "response_rule":
        content = content.strip("，, 。.!！")
        content = content.replace("和用户互动时不要", "不要").replace("和用户互动时别", "别")
        if content.startswith("和用户互动时"):
            content = content.removeprefix("和用户互动时")
        if "上来就讲大道理" in content and not content.startswith(("别", "不要")):
            content = f"别{content}"
        memory["content"] = content
    elif memory_type == "emotion_pattern":
        memory["content"] = content.replace("类似情境相关情境", "当前情境").replace("当前情境相关情境", "当前情境")
    return memory
