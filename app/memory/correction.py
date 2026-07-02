from __future__ import annotations

import re
from typing import Any

from ..storage import now_iso
from .schema import make_memory
from .signals import has_correction_signal, has_deletion_signal
from .text import canonical_content, infer_type, normalize_content, tokens, valence_from_text


def apply_user_corrections(memories: list[dict[str, Any]], user_text: str) -> dict[str, Any]:
    if not has_correction_signal(user_text):
        return {"corrected": [], "deleted": [], "created": []}

    deleted = _delete_requested(memories, user_text)
    corrected, created = _correct_not_but(memories, user_text)
    return {"corrected": corrected, "deleted": deleted, "created": created}


def _delete_requested(memories: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
    if not has_deletion_signal(user_text):
        return []
    query = _correction_query(user_text)
    deleted = []
    for memory in memories:
        if memory.get("status") != "active":
            continue
        if _matches_query(memory, query):
            memory["status"] = "deleted_by_user"
            memory["updated_at"] = now_iso()
            memory["correction_note"] = user_text
            deleted.append(memory)
    return deleted


def _correct_not_but(memories: list[dict[str, Any]], user_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    match = re.search(r"不是([^，。！？.!?]{1,40})(?:，|,|而是|是)([^。！？.!?]{1,60})", user_text)
    if not match and "记错" not in user_text and "改成" not in user_text and "其实是" not in user_text:
        return [], []

    old_raw = match.group(1).strip() if match else _correction_query(user_text)
    new_raw = match.group(2).strip() if match else _new_value(user_text)
    corrected = []
    created = []

    for memory in memories:
        if memory.get("status") != "active":
            continue
        if _matches_query(memory, old_raw):
            memory["status"] = "corrected"
            memory["updated_at"] = now_iso()
            memory["correction_note"] = user_text
            corrected.append(memory)

    if new_raw:
        memory_type = infer_type(new_raw)
        created.append(
            make_memory(
                memory_type,
                normalize_content(memory_type, new_raw),
                0.94,
                True,
                user_text,
                open_item=memory_type == "goal",
                valence=valence_from_text(new_raw),
                stability="high",
            )
        )
    return corrected, created


def _matches_query(memory: dict[str, Any], query: str) -> bool:
    if not query:
        return False
    memory_key = canonical_content(memory)
    query_type = infer_type(query)
    normalized_query = normalize_content(query_type, query)
    compact_query = canonical_content({"content": normalized_query})
    if compact_query and (compact_query in memory_key or memory_key in compact_query):
        return True
    query_tokens = set(tokens(query)) | set(tokens(normalized_query))
    memory_tokens = set(tokens(memory.get("content", ""))) | set(memory.get("tags", []))
    return bool(query_tokens & memory_tokens)


def _correction_query(user_text: str) -> str:
    cleaned = re.sub(r"(你)?记错了|别记|不要记|不用记|忘掉|删掉|删了|别存|不要存|忽略这条|这个|这条|记忆", "", user_text)
    return cleaned.strip("，, 。.!！")


def _new_value(user_text: str) -> str:
    for marker in ["改成", "其实是", "而是"]:
        if marker in user_text:
            return user_text.split(marker, 1)[1].strip("，, 。.!！")
    return ""
