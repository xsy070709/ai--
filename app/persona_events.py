"""Persona event system — offline events that affect personality and behavior.

Events represent things that happen to the persona outside of chat.
They can temporarily or permanently modify traits, become conversation
topics, or create sensitive taboos.
"""

from __future__ import annotations

from typing import Any

from .storage import new_id, now_iso


# ---------------------------------------------------------------------------
# event creation
# ---------------------------------------------------------------------------


def create_event(
    content: str,
    *,
    persona_entity_id: str,
    event_type: str = "neutral",
    impact_scope: str = "temporary",
    expires_at: str | None = None,
    trait_effects: list[dict[str, Any]] | None = None,
    becomes_topic: bool = True,
    topic_trigger_words: list[str] | None = None,
    becomes_taboo: bool = False,
    taboo_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Build a persona event dict ready for storage."""

    return {
        "id": new_id("evt"),
        "persona_entity_id": persona_entity_id,
        "content": content.strip(),
        "event_type": event_type,
        "impact_scope": impact_scope,
        "created_at": now_iso(),
        "expires_at": expires_at,
        "trait_effects": _normalize_trait_effects(trait_effects or []),
        "becomes_topic": bool(becomes_topic),
        "topic_trigger_words": list(topic_trigger_words or []),
        "becomes_taboo": bool(becomes_taboo),
        "taboo_keywords": list(taboo_keywords or []),
        "status": "active",
        "acknowledged": False,
        "acknowledged_at": None,
        "resolution_note": "",
    }


def _normalize_trait_effects(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    valid_directions = {"add", "weaken", "strengthen", "remove"}
    for effect in raw:
        trait = str(effect.get("trait", "")).strip()
        direction = str(effect.get("direction", "add")).strip()
        if not trait or direction not in valid_directions:
            continue
        result.append(
            {
                "trait": trait,
                "direction": direction,
                "strength": float(effect.get("strength", 0.5)),
            }
        )
    return result[:6]


# ---------------------------------------------------------------------------
# trait modulation
# ---------------------------------------------------------------------------


def apply_event_trait_effects(
    base_traits: list[str],
    events: list[dict[str, Any]],
) -> list[str]:
    """Compute the active trait list after applying all event effects.

    Does NOT modify the stored persona dict — returns a computed list
    for use in prompt generation.
    """

    traits = list(base_traits)
    for event in events:
        if event.get("status") not in {"active", "fading"}:
            continue
        effects = event.get("trait_effects") or []
        multiplier = 0.5 if event.get("status") == "fading" else 1.0
        for effect in effects:
            trait = effect["trait"]
            direction = effect["direction"]
            strength = effect["strength"] * multiplier

            if strength < 0.25:
                continue  # too weak to matter

            if direction == "add":
                if trait not in traits:
                    traits.append(trait)
            elif direction == "remove":
                if trait in traits:
                    traits.remove(trait)
            elif direction == "strengthen":
                if trait in traits:
                    traits.remove(trait)
                    traits.insert(0, trait)  # move to front
                elif strength > 0.5:
                    traits.insert(0, trait)  # add at front
            elif direction == "weaken":
                if trait in traits and strength > 0.5:
                    traits.remove(trait)
                    traits.append(trait)  # move to end (lower prominence)

    return traits


def describe_trait_changes(events: list[dict[str, Any]]) -> str:
    """Build a short human-readable summary of active trait changes."""

    active = [e for e in events if e.get("status") in {"active", "fading"}]
    if not active:
        return ""

    lines: list[str] = []
    for event in active:
        effects = event.get("trait_effects") or []
        if not effects:
            continue
        multiplier = 0.5 if event.get("status") == "fading" else 1.0
        changes: list[str] = []
        for effect in effects:
            if effect["strength"] * multiplier < 0.25:
                continue
            direction = effect["direction"]
            trait = effect["trait"]
            if direction == "add":
                changes.append(f"新增「{trait}」")
            elif direction == "weaken":
                changes.append(f"「{trait}」暂时减弱")
            elif direction == "strengthen":
                changes.append(f"「{trait}」更加突出")
            elif direction == "remove":
                changes.append(f"「{trait}」暂时隐藏")
        if changes:
            fading_note = "（逐渐消退中）" if event.get("status") == "fading" else ""
            lines.append(f"因「{event['content']}」：{'、'.join(changes)}{fading_note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# prompt context builders
# ---------------------------------------------------------------------------


def build_event_context(events: list[dict[str, Any]]) -> str:
    """Build the '近期经历' and topic sections for the system prompt.

    Returns empty string if no active events have topic or trait effects.
    """

    active = _active_events(events)
    if not active:
        return ""

    parts: list[str] = []

    # topic events — the persona may bring these up
    topic_events = [e for e in active if e.get("becomes_topic")]
    if topic_events:
        lines = ["她近期经历（可以自然提及，但不要刻意）："]
        for event in topic_events:
            fading = "（逐渐淡出，提及时应更含蓄）" if event.get("status") == "fading" else ""
            lines.append(f"- {event['content']}{fading}")
        parts.append("\n".join(lines))

    # trait change summary
    trait_desc = describe_trait_changes(active)
    if trait_desc:
        parts.append(f"当前性格受事件影响：\n{trait_desc}")

    return "\n\n".join(parts)


def build_event_taboo_context(events: list[dict[str, Any]]) -> str:
    """Build the taboo/sensitive topics section.

    Returns empty string if no active events have taboo keywords.
    """

    taboo_events = [e for e in _active_events(events) if e.get("becomes_taboo") and e.get("taboo_keywords")]
    if not taboo_events:
        return ""

    lines = ["当前敏感话题（不要主动提及，如果用户提起则简短回应后自然转移话题）："]
    for event in taboo_events:
        keywords = "、".join(event["taboo_keywords"][:6])
        lines.append(f"- 关于 {keywords} 的话题")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# taboo detection
# ---------------------------------------------------------------------------


def check_taboo_triggers(user_text: str, events: list[dict[str, Any]]) -> list[str]:
    """Return IDs of taboo events whose keywords appear in the user text."""

    triggered: list[str] = []
    text = user_text.lower()
    for event in _active_events(events):
        if not event.get("becomes_taboo"):
            continue
        keywords = event.get("taboo_keywords") or []
        if any(kw.lower() in text for kw in keywords):
            triggered.append(event["id"])
    return triggered


# ---------------------------------------------------------------------------
# lifecycle management
# ---------------------------------------------------------------------------


def maintain_events(events: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    """Check all events and return mutation ops for status transitions.

    Called during each chat turn.  The caller should apply these mutations
    to the stored event list.
    """

    ops: list[dict[str, Any]] = []
    for event in events:
        current_status = event.get("status", "active")

        # expiry-based transitions
        expires = event.get("expires_at")
        if expires and now >= expires:
            if current_status == "active":
                ops.append({"event_id": event["id"], "field": "status", "value": "fading"})
            elif current_status == "fading":
                ops.append({"event_id": event["id"], "field": "status", "value": "resolved"})

        # acknowledged → absorbed for permanent events
        if current_status == "acknowledged" and event.get("impact_scope") == "permanent":
            if event.get("acknowledged_at"):
                # after 7 days, absorb
                ack_time = _parse_iso(event["acknowledged_at"])
                now_time = _parse_iso(now)
                if ack_time and now_time and (now_time - ack_time) > 7 * 86400:
                    ops.append({"event_id": event["id"], "field": "status", "value": "absorbed"})

    return ops


def mark_event_acknowledged(event: dict[str, Any]) -> dict[str, Any]:
    """Mark an event as acknowledged (discussed in chat)."""

    event["acknowledged"] = True
    event["acknowledged_at"] = now_iso()
    event["status"] = "acknowledged"
    return event


def resolve_event(event: dict[str, Any], note: str = "") -> dict[str, Any]:
    """Resolve an event — effects removed, becomes a memory."""

    event["status"] = "resolved"
    event["resolution_note"] = note.strip()
    return event


# ---------------------------------------------------------------------------
# memory bridge
# ---------------------------------------------------------------------------


def event_to_memory(event: dict[str, Any]) -> dict[str, Any]:
    """Convert an event into a memory record for the recall system.

    Uses the ``shared_experience`` type so it participates in memory
    recall like any other past shared experience.
    """

    from .memory.schema import make_memory

    content = event["content"]
    if event.get("resolution_note"):
        content = f"{content}（结果：{event['resolution_note']}）"

    memory = make_memory(
        memory_type="shared_experience",
        content=f"她经历过：{content}",
        confidence=0.9,
        confirmed=True,
        evidence_text=event["content"],
        open_item=event.get("status") in {"active", "acknowledged"},
        valence=event.get("event_type", "neutral"),
        stability="high",
        sensitivity_level="medium" if event.get("becomes_taboo") else "low",
    )
    memory["source_event_id"] = event["id"]
    memory["persona_entity_id"] = event["persona_entity_id"]
    return memory


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _active_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("status") in {"active", "fading"}]


def _parse_iso(value: str) -> float | None:
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None
