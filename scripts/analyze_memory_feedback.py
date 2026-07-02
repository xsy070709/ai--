from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.memory.feedback import analyze_feedback
from app.storage import create_store


def main() -> None:
    settings = load_settings()
    state = create_store(settings).snapshot()
    report = analyze_feedback(state.get("generation_logs", []))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
