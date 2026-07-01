from __future__ import annotations

from typing import Any

from .text import tokens


def audit_memory_use(reply: str, memory_context: dict[str, Any]) -> dict[str, Any]:
    disclosure_plan = memory_context.get("disclosure_plan", {})
    followup_plan = memory_context.get("followup_plan", {})
    issues: list[dict[str, Any]] = []

    for item in disclosure_plan.get("items", []):
        action = item.get("action")
        if action in {"silent", "obey"} and _content_surface_detected(reply, item.get("content", "")):
            issues.append(
                {
                    "severity": "fail",
                    "type": "forbidden_memory_surface",
                    "memory_id": item.get("memory_id"),
                    "message": "回复疑似表露了应该沉默或只遵守的记忆。",
                }
            )
        if action == "hint" and _labeling_phrase_detected(reply, item):
            issues.append(
                {
                    "severity": "warn",
                    "type": "over_explicit_tone_memory",
                    "memory_id": item.get("memory_id"),
                    "message": "回复疑似把只应用于语气的记忆贴标签说出。",
                }
            )

    mention_items = [item for item in disclosure_plan.get("items", []) if item.get("action") == "mention"]
    if mention_items and followup_plan.get("mode") in {"gentle_follow_up", "user_invited_follow_up"}:
        if not any(_content_surface_detected(reply, item.get("content", "")) for item in mention_items):
            issues.append(
                {
                    "severity": "warn",
                    "type": "missed_expected_followup",
                    "memory_id": mention_items[0].get("memory_id"),
                    "message": "本轮允许自然接续，但回复没有明显使用相关记忆。",
                }
            )

    status = "ok"
    if any(issue["severity"] == "fail" for issue in issues):
        status = "fail"
    elif issues:
        status = "warn"

    return {
        "status": status,
        "issues": issues,
        "checked_items": len(disclosure_plan.get("items", [])),
        "disclosure_mode": disclosure_plan.get("mode", "quiet"),
        "followup_mode": followup_plan.get("mode", "none"),
    }


def _content_surface_detected(reply: str, content: str) -> bool:
    content_tokens = [token for token in tokens(content) if len(token) >= 2]
    if not content_tokens:
        return False
    hits = sum(1 for token in content_tokens if token in reply)
    if hits >= min(2, len(content_tokens)):
        return True
    anchors = ["家里", "家庭", "项目", "压力", "焦虑", "材料", "面试", "考试", "安静", "热闹", "大道理"]
    anchor_hits = sum(1 for anchor in anchors if anchor in content and anchor in reply)
    return anchor_hits >= 1 and any(phrase in reply for phrase in ["我记得", "我知道", "你不想", "你容易", "你之前", "上次"])


def _labeling_phrase_detected(reply: str, item: dict[str, Any]) -> bool:
    if not any(phrase in reply for phrase in ["我记得", "我知道你", "你总是", "你容易", "你的模式"]):
        return False
    return _content_surface_detected(reply, item.get("content", ""))
