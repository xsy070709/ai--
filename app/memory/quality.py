from __future__ import annotations

from typing import Any


AUTO_ACCEPT_TYPES = {
    "preference",
    "response_rule",
    "goal",
    "emotion_pattern",
    "shared_experience",
    "relationship_signal",
    "stable_impression",
}
CONFIRM_TYPES = {"fact", "episodic", "boundary", "dislike"}
REJECT_MIN_CONFIDENCE = 0.45


def review_memory_candidates(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    needs_confirmation: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for candidate in candidates:
        decision, reason = review_memory(candidate)
        candidate["quality_decision"] = decision
        candidate["quality_reason"] = reason
        if decision == "accept":
            accepted.append(candidate)
        elif decision == "confirm":
            needs_confirmation.append(candidate)
        else:
            rejected.append(candidate)

    return {"accepted": accepted, "needs_confirmation": needs_confirmation, "rejected": rejected}


def review_memory(memory: dict[str, Any]) -> tuple[str, str]:
    content = memory.get("content", "").strip()
    memory_type = memory.get("type", "")
    confidence = float(memory.get("confidence", 0))

    if not content or len(content) < 4:
        return "reject", "内容过短"
    if confidence < REJECT_MIN_CONFIDENCE:
        return "reject", "置信度过低"
    if memory.get("sensitivity_level") not in {"low", None}:
        return "confirm", "涉及较高敏感度，需要确认"
    if memory.get("is_user_confirmed"):
        return "accept", "用户明确要求记住"
    if memory_type in AUTO_ACCEPT_TYPES and confidence >= 0.62:
        return "accept", "低风险且足够明确"
    if memory_type in CONFIRM_TYPES:
        return "confirm", "可能影响长期画像，需要确认"
    if memory.get("stability") == "low" and confidence < 0.7:
        return "confirm", "短期事件不应直接沉淀为稳定记忆"
    return "accept", "默认接受"


def enqueue_confirmation(state: dict[str, Any], memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue = state.setdefault("memory_confirmations", [])
    existing_keys = {item.get("candidate", {}).get("content") for item in queue if item.get("status") == "pending"}
    added = []
    for memory in memories:
        if memory.get("content") in existing_keys:
            continue
        item = {
            "id": f"confirm_{memory['id']}",
            "status": "pending",
            "candidate": memory,
            "reason": memory.get("quality_reason", "需要确认"),
            "created_at": memory.get("created_at"),
        }
        queue.append(item)
        added.append(item)
    return added


def pending_confirmations(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in state.get("memory_confirmations", []) if item.get("status") == "pending"]
