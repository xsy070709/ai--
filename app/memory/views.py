from __future__ import annotations

from typing import Any

from .schema import LONG_TERM_TYPES


def memory_layers(state: dict[str, Any]) -> dict[str, Any]:
    personas = state.get("persona_versions", [])
    entity_id = state.get("active_persona_entity_id") or "entity_default"
    active_persona = next((p for p in personas if p["id"] == state.get("active_persona_id")), None)
    session = state["sessions"][state["active_session_id"]]
    memories = [
        m
        for m in state.get("memories", [])
        if m.get("status") == "active" and (m.get("persona_entity_id") or "entity_default") == entity_id
    ]
    return {
        "work": {"name": "工作记忆", "count": min(len(session.get("messages", [])), 24)},
        "summary": {"name": "会话摘要", "count": len(session.get("summaries", []))},
        "long_term": {"name": "长期记忆", "count": len([m for m in memories if m["type"] in LONG_TERM_TYPES])},
        "persona": {"name": "人格记忆", "count": 1 if active_persona else 0},
        "shared": {"name": "共同经历", "count": len([m for m in memories if m["type"] == "shared_experience"])},
        "open_loops": {"name": "待跟进事项", "count": len([m for m in memories if m.get("open")])},
        "relationship": {"name": "关系信号", "count": len([m for m in memories if m["type"] == "relationship_signal"])},
        "impression": {"name": "稳定印象", "count": len([m for m in memories if m["type"] == "stable_impression"])},
    }
