from __future__ import annotations

from typing import Any

from .params import DEFAULT_MEMORY_PARAMS
from .schema import parse_time


PARAMS = DEFAULT_MEMORY_PARAMS.maintenance


def maintain_memories(memories: list[dict[str, Any]], *, max_ephemeral: int = PARAMS.default_max_ephemeral) -> dict[str, list[dict[str, Any]]]:
    decayed = []
    archived = []

    active = [memory for memory in memories if memory.get("status") == "active"]
    episodic = [memory for memory in active if memory.get("type") == "episodic" and not memory.get("open")]
    episodic.sort(key=lambda memory: parse_time(memory.get("updated_at")), reverse=True)
    for memory in episodic[max_ephemeral:]:
        memory["status"] = "archived"
        archived.append(memory)

    for memory in active:
        if memory.get("type") in {"episodic", "fact"} and not memory.get("is_user_confirmed") and not memory.get("open"):
            old_importance = memory.get("importance", 0.5)
            memory["importance"] = max(PARAMS.decay_floor, old_importance * PARAMS.decay_multiplier)
            if memory["importance"] != old_importance:
                decayed.append(memory)

    return {"decayed": decayed, "archived": archived}


def should_apply_recall_cooldown(memory: dict[str, Any]) -> bool:
    if memory.get("open") or memory.get("type") in {"boundary", "response_rule"}:
        return False
    return int(memory.get("use_count", 0)) >= PARAMS.cooldown_use_threshold
