from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import Settings


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class JsonStore:
    def __init__(self, settings: Settings) -> None:
        self.path = settings.data_dir / "store.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write(self._default_state())

    def _default_state(self) -> dict[str, Any]:
        session_id = "default"
        return {
            "active_session_id": session_id,
            "sessions": {
                session_id: {
                    "id": session_id,
                    "title": "长期聊天",
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "messages": [],
                    "summaries": [],
                }
            },
            "persona_versions": [],
            "active_persona_id": None,
            "memories": [],
            "generation_logs": [],
        }

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return self._default_state()

    def _write(self, state: dict[str, Any]) -> None:
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read())

    def mutate(self, fn):
        with self._lock:
            state = self._read()
            result = fn(state)
            self._write(state)
            return result

    def session(self, session_id: str = "default") -> dict[str, Any]:
        state = self.snapshot()
        sessions = state.setdefault("sessions", {})
        return sessions.get(session_id) or sessions[state["active_session_id"]]
