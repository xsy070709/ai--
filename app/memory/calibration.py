from __future__ import annotations

from typing import Any

from .context import build_memory_context
from .extraction import extract_memory_candidates
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

    context = build_memory_context(memories, case.get("user_text", ""))
    recalled_contents = [memory.get("content", "") for memory in context["recalled"]]
    expected_recall = case.get("expected_recall_contains", [])
    expected_disclosure_mode = case.get("expected_disclosure_mode")

    checks = {
        "memory_types": expected_types <= extracted_types,
        "recall": all(any(fragment in content for content in recalled_contents) for fragment in expected_recall),
        "disclosure_mode": expected_disclosure_mode in {None, context["disclosure_plan"]["mode"]},
    }
    return {
        "name": case.get("name", "unnamed"),
        "passed": all(checks.values()),
        "checks": checks,
        "extracted_types": sorted(extracted_types),
        "recalled": recalled_contents,
        "disclosure_mode": context["disclosure_plan"]["mode"],
    }
