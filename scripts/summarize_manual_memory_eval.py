from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ISSUE_TO_SUGGESTION = {
    "missed_recall": ("recall.min_score_threshold", "decrease", "应召回的记忆经常缺失。"),
    "irrelevant_recall": ("recall.min_score_threshold", "increase", "召回了不相关旧事。"),
    "too_explicit": ("disclosure.mention_recall_threshold", "increase", "记忆表露太直白。"),
    "too_quiet": ("disclosure.mention_recall_threshold", "decrease", "该接旧事时过于沉默。"),
    "nagging_followup": ("recall.open_item_bonus", "decrease", "待跟进显得催促。"),
    "missed_followup": ("recall.open_item_bonus", "increase", "明显待办没有自然跟进。"),
    "wrong_extraction": ("quality.auto_accept_min_confidence", "increase", "抽取或接受了不该记的内容。"),
    "missed_extraction": ("quality.auto_accept_min_confidence", "decrease", "高价值信息没有进入记忆流程。"),
    "privacy_surface": ("disclosure.mention_recall_threshold", "increase", "敏感或边界记忆被表露。"),
    "repetitive_memory": ("recall.cooldown_penalty", "increase", "旧记忆重复出现。"),
}


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    parameter_counts: Counter[str] = Counter()
    rating_totals: defaultdict[str, list[float]] = defaultdict(list)

    for record in records:
        scenario_counts[record.get("scenario", "unknown")] += 1
        for issue in record.get("issues", []):
            issue_counts[issue] += 1
        for parameter in record.get("parameters", []):
            parameter_counts[parameter] += 1
        for key, value in record.get("ratings", {}).items():
            if isinstance(value, int | float):
                rating_totals[key].append(float(value))

    suggestions = []
    for issue, count in issue_counts.most_common():
        if issue not in ISSUE_TO_SUGGESTION:
            continue
        parameter, direction, reason = ISSUE_TO_SUGGESTION[issue]
        suggestions.append(
            {
                "issue": issue,
                "count": count,
                "parameter": parameter,
                "direction": direction,
                "reason": reason,
            }
        )

    return {
        "total_records": len(records),
        "scenario_counts": dict(scenario_counts),
        "issue_counts": dict(issue_counts),
        "parameter_mentions": dict(parameter_counts),
        "average_ratings": {
            key: round(sum(values) / len(values), 2)
            for key, values in sorted(rating_totals.items())
            if values
        },
        "suggestions": suggestions,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/summarize_manual_memory_eval.py <manual_eval.jsonl>")
    path = Path(sys.argv[1])
    report = summarize(load_records(path))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
