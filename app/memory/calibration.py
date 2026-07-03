from __future__ import annotations

from typing import Any

from .audit import audit_memory_use
from .context import build_memory_context
from .extraction import extract_memory_candidates
from .feedback import infer_feedback_signals
from .lifecycle import upsert_memories


def evaluate_calibration_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [_evaluate_case(case) for case in cases]
    total = len(results)
    passed = len([result for result in results if result["passed"]])
    return {
        "total": total,
        "passed": passed,
        "score": round(passed / total, 3) if total else 0.0,
        "results": results,
    }


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    memories = []
    for seed in case.get("seed_memories", []):
        upsert_memories(memories, extract_memory_candidates(seed))

    extracted = extract_memory_candidates(case.get("user_text", ""))
    extracted_types = {memory["type"] for memory in extracted}
    expected_types = set(case.get("expected_memory_types", []))

    intent = case.get("intent")
    context = build_memory_context(memories, case.get("user_text", ""), intent=intent)
    recalled_contents = [memory.get("content", "") for memory in context["recalled"]]
    expected_recall = case.get("expected_recall_contains", [])
    expected_disclosure_mode = case.get("expected_disclosure_mode")
    expected_followup_mode = case.get("expected_followup_mode")
    assistant_reply = case.get("assistant_reply")
    memory_audit = audit_memory_use(assistant_reply, context) if assistant_reply is not None else None
    expected_audit_status = case.get("expected_audit_status")
    expected_audit_issues = set(case.get("expected_audit_issues", []))
    audit_issue_types = {issue["type"] for issue in memory_audit.get("issues", [])} if memory_audit else set()
    previous_log = case.get("previous_log")
    current_manifest = dict(case.get("current_manifest", {}))
    if intent and "intent" not in current_manifest:
        current_manifest["intent"] = intent
    if memory_audit and "memory_audit_status" not in current_manifest:
        current_manifest["memory_audit_status"] = memory_audit["status"]
    feedback_signals = infer_feedback_signals(
        case.get("user_text", ""),
        previous_log=previous_log,
        current_manifest=current_manifest,
    )
    feedback_signal_types = {signal["type"] for signal in feedback_signals}
    expected_feedback_signals = set(case.get("expected_feedback_signals", []))

    checks = {
        "memory_types": expected_types <= extracted_types,
        "recall": all(any(fragment in content for content in recalled_contents) for fragment in expected_recall),
        "disclosure_mode": expected_disclosure_mode in {None, context["disclosure_plan"]["mode"]},
        "followup_mode": expected_followup_mode in {None, context["followup_plan"]["mode"]},
        "memory_audit_status": expected_audit_status is None or bool(memory_audit and memory_audit["status"] == expected_audit_status),
        "memory_audit_issues": expected_audit_issues <= audit_issue_types,
        "feedback_signals": expected_feedback_signals <= feedback_signal_types,
    }
    return {
        "name": case.get("name", "unnamed"),
        "passed": all(checks.values()),
        "checks": checks,
        "extracted_types": sorted(extracted_types),
        "recalled": recalled_contents,
        "disclosure_mode": context["disclosure_plan"]["mode"],
        "followup_mode": context["followup_plan"]["mode"],
        "memory_audit": memory_audit,
        "feedback_signals": sorted(feedback_signal_types),
    }
