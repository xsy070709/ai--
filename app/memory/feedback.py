from __future__ import annotations

from collections import Counter
from typing import Any

from .params import DEFAULT_MEMORY_PARAMS, parameter_metadata
from .signals import (
    has_completion_signal,
    has_followup_invitation,
    has_task_signal,
    has_time_signal,
    is_high_density,
    looks_like_casual_chat,
)
from .text import topics_from_text


PARAMS = DEFAULT_MEMORY_PARAMS

POSITIVE_SIGNALS = {
    "followup_resolved",
    "followup_engaged",
    "open_loop_closed",
    "user_invited_recall",
    "disclosure_engaged",
    "tone_guidance_engaged",
    "confirmation_accepted",
}
NEGATIVE_SIGNALS = {
    "followup_topic_shift",
    "memory_correction",
    "memory_surface_issue",
    "disclosure_not_engaged",
    "confirmation_rejected",
}
SIGNAL_PARAMETERS = {
    "followup_resolved": ["recall.open_item_bonus"],
    "followup_engaged": ["recall.open_item_bonus"],
    "followup_topic_shift": ["recall.open_item_bonus", "recall.cooldown_penalty"],
    "memory_correction": ["quality.auto_accept_min_confidence"],
    "confirmation_requested": ["quality.auto_accept_min_confidence"],
    "confirmation_accepted": ["quality.auto_accept_min_confidence"],
    "confirmation_rejected": ["quality.auto_accept_min_confidence"],
    "open_loop_closed": ["recall.open_item_bonus"],
    "user_invited_recall": ["maintenance.cooldown_use_threshold", "recall.cooldown_penalty"],
    "memory_surface_issue": ["disclosure.mention_recall_threshold"],
    "disclosure_not_engaged": ["disclosure.mention_recall_threshold"],
    "disclosure_engaged": ["disclosure.mention_recall_threshold"],
    "tone_guidance_engaged": ["disclosure.mention_recall_threshold"],
}


def infer_feedback_signals(
    user_text: str,
    *,
    previous_log: dict[str, Any] | None = None,
    current_manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    current_manifest = current_manifest or {}
    intent = current_manifest.get("intent") or {}
    previous_manifest = (previous_log or {}).get("prompt_manifest", {})

    if previous_manifest.get("followup_mode") in {"gentle_follow_up", "user_invited_follow_up"}:
        if _has_completion_signal(user_text, intent):
            signals.append(_signal("followup_resolved", "用户在跟进后汇报事项完成", ["recall.open_item_bonus"]))
        elif _is_high_density(user_text, intent) or _topic_continues(user_text, previous_manifest, intent):
            signals.append(_signal("followup_engaged", "用户在跟进后继续回应相关话题", ["recall.open_item_bonus"]))
        elif _topic_shifted(user_text, previous_manifest, intent):
            signals.append(_signal("followup_topic_shift", "用户在跟进后转移话题", ["recall.open_item_bonus", "recall.cooldown_penalty"]))

    if current_manifest.get("corrected_memory_ids") or current_manifest.get("deleted_memory_ids"):
        signals.append(_signal("memory_correction", "用户修正或删除了记忆", ["quality.auto_accept_min_confidence"]))
    if current_manifest.get("queued_memory_ids"):
        signals.append(_signal("confirmation_requested", "本轮产生了需要用户确认的记忆", ["quality.auto_accept_min_confidence"]))
    if current_manifest.get("confirmation_id") and "accepted" in current_manifest:
        if current_manifest.get("accepted"):
            signals.append(_signal("confirmation_accepted", "用户接受了记忆确认项", ["quality.auto_accept_min_confidence"]))
        else:
            signals.append(_signal("confirmation_rejected", "用户拒绝了记忆确认项", ["quality.auto_accept_min_confidence"]))
    if current_manifest.get("closed_memory_ids"):
        signals.append(_signal("open_loop_closed", "待跟进事项被关闭", ["recall.open_item_bonus"]))
    if _has_followup_invitation(user_text, intent):
        signals.append(_signal("user_invited_recall", "用户主动邀请回忆旧事", ["maintenance.cooldown_use_threshold", "recall.cooldown_penalty"]))

    audit_status = current_manifest.get("memory_audit_status")
    if audit_status in {"warn", "fail"}:
        signals.append(_signal("memory_surface_issue", "记忆表露审计发现问题", ["disclosure.mention_recall_threshold"]))

    if previous_manifest.get("disclosure_mode") == "can_mention":
        if _looks_like_casual_chat(user_text, intent) or _topic_shifted(user_text, previous_manifest, intent):
            signals.append(_signal("disclosure_not_engaged", "AI 表露记忆后用户没有接续相关话题", ["disclosure.mention_recall_threshold"]))
        elif _is_high_density(user_text, intent) or _topic_continues(user_text, previous_manifest, intent):
            signals.append(_signal("disclosure_engaged", "AI 表露记忆后用户继续深入回应", ["disclosure.mention_recall_threshold"]))
    if previous_manifest.get("disclosure_mode") == "tone_only":
        if _is_high_density(user_text, intent) or _topic_continues(user_text, previous_manifest, intent):
            signals.append(_signal("tone_guidance_engaged", "AI 只调整语气后用户继续深入回应", ["disclosure.mention_recall_threshold"]))

    return _dedupe_signals(signals)


def analyze_feedback(logs: list[dict[str, Any]]) -> dict[str, Any]:
    signals = [signal for log in logs for signal in log.get("feedback_signals", [])]
    counts = Counter(signal.get("type", "unknown") for signal in signals)
    parameter_evidence = _parameter_evidence(signals)
    metadata = parameter_metadata()
    suggestions = []

    if counts["followup_topic_shift"] > counts["followup_engaged"] + counts["followup_resolved"]:
        suggestions.append(
            {
                "parameter": "recall.open_item_bonus",
                "direction": "decrease",
                "reason": "跟进后转移话题多于有效接续，当前待跟进加分可能偏高。",
            }
        )
    if counts["followup_engaged"] + counts["followup_resolved"] >= max(2, counts["followup_topic_shift"] * 2):
        suggestions.append(
            {
                "parameter": "recall.open_item_bonus",
                "direction": "keep_or_increase",
                "reason": "跟进后用户持续回应或关闭事项，待跟进加分有效。",
            }
        )
    if counts["memory_correction"] >= 2:
        suggestions.append(
            {
                "parameter": "quality.auto_accept_min_confidence",
                "direction": "increase",
                "reason": "用户多次修正或删除记忆，自动接受阈值可能偏松。",
            }
        )
    if counts["confirmation_accepted"] >= 3 and counts["confirmation_rejected"] == 0:
        suggestions.append(
            {
                "parameter": "quality.auto_accept_min_confidence",
                "direction": "decrease",
                "reason": "用户连续接受确认项，质量审核可能偏保守。",
            }
        )
    if counts["user_invited_recall"] >= 2:
        suggestions.append(
            {
                "parameter": "maintenance.cooldown_use_threshold",
                "direction": "increase",
                "reason": "用户多次主动邀请旧事，召回冷却可能偏激进。",
            }
        )
    if counts["memory_surface_issue"] or counts["disclosure_not_engaged"] > counts["disclosure_engaged"]:
        suggestions.append(
            {
                "parameter": "disclosure.mention_recall_threshold",
                "direction": "increase",
                "reason": "记忆表露出现审计问题或表露后未接续，应更克制。",
            }
        )

    return {
        "total_logs": len(logs),
        "total_signals": len(signals),
        "signal_counts": dict(counts),
        "parameter_evidence": parameter_evidence,
        "parameter_metadata": {name: metadata[name] for name in parameter_evidence if name in metadata},
        "suggestions": suggestions,
    }


def _parameter_evidence(signals: list[dict[str, Any]]) -> dict[str, Any]:
    evidence: dict[str, dict[str, Any]] = {}
    for signal in signals:
        signal_type = signal.get("type", "unknown")
        parameters = signal.get("parameters") or SIGNAL_PARAMETERS.get(signal_type, [])
        for parameter in parameters:
            item = evidence.setdefault(
                parameter,
                {
                    "total": 0,
                    "positive": 0,
                    "negative": 0,
                    "signals": {},
                    "reasons": [],
                },
            )
            item["total"] += 1
            if signal_type in POSITIVE_SIGNALS:
                item["positive"] += 1
            if signal_type in NEGATIVE_SIGNALS:
                item["negative"] += 1
            item["signals"][signal_type] = item["signals"].get(signal_type, 0) + 1
            reason = signal.get("reason")
            if reason and reason not in item["reasons"]:
                item["reasons"].append(reason)
    return evidence


def _signal(signal_type: str, reason: str, parameters: list[str]) -> dict[str, Any]:
    return {"type": signal_type, "reason": reason, "parameters": parameters}


def _topic_continues(user_text: str, manifest: dict[str, Any], intent: dict[str, Any] | None = None) -> bool:
    reasons = " ".join(str(value) for value in manifest.get("used_memory_reasons", {}).values())
    if has_time_signal(user_text) or has_task_signal(user_text):
        return True
    if _has_followup_invitation(user_text, intent) and not _looks_like_casual_chat(user_text, intent):
        return True
    intent_topics = {str(topic) for topic in (intent or {}).get("topics", [])}
    user_topics = intent_topics or set(topics_from_text(user_text))
    reason_topics = set(topics_from_text(reasons))
    return user_topics != {"日常聊天"} and bool(user_topics & reason_topics)


def _topic_shifted(user_text: str, manifest: dict[str, Any], intent: dict[str, Any] | None = None) -> bool:
    if _looks_like_casual_chat(user_text, intent):
        return True
    if _is_high_density(user_text, intent):
        return False
    return not _topic_continues(user_text, manifest, intent)


def _has_completion_signal(user_text: str, intent: dict[str, Any] | None = None) -> bool:
    return has_completion_signal(user_text) or bool(intent and intent.get("has_completion_signal"))


def _has_followup_invitation(user_text: str, intent: dict[str, Any] | None = None) -> bool:
    return bool(intent and intent.get("has_followup_invitation")) or has_followup_invitation(user_text)


def _is_high_density(user_text: str, intent: dict[str, Any] | None = None) -> bool:
    if intent and float(intent.get("information_density") or 0.0) >= PARAMS.conversation.high_density_threshold:
        return True
    return is_high_density(user_text)


def _looks_like_casual_chat(user_text: str, intent: dict[str, Any] | None = None) -> bool:
    if intent:
        if intent.get("has_completion_signal") or intent.get("has_correction_intent") or intent.get("has_followup_invitation"):
            return False
        if _is_high_density(user_text, intent):
            return False
        if "is_casual_chat" in intent:
            return bool(intent["is_casual_chat"])
    return looks_like_casual_chat(user_text)


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for signal in signals:
        key = (signal["type"], signal.get("reason"), tuple(signal.get("parameters") or []))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
    return deduped
