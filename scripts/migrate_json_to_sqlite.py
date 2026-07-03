from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.storage import migrate_json_to_sqlite


def main() -> None:
    settings = load_settings()
    sqlite_path = migrate_json_to_sqlite(settings)
    print(f"Migrated JSON store to SQLite: {sqlite_path}")
    print(f"JSON backup kept at: {settings.data_dir / 'store.json'}")


if __name__ == "__main__":
    main()
