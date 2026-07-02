from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.memory.calibration import evaluate_calibration_cases


def main() -> None:
    cases_path = ROOT / "data" / "memory_calibration_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    report = evaluate_calibration_cases(cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
