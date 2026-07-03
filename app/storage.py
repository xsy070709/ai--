from __future__ import annotations

import json
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .config import Settings


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def default_state() -> dict[str, Any]:
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


class StorageBackend(Protocol):
    def snapshot(self) -> dict[str, Any]:
        ...

    def mutate(self, fn):
        ...

    def session(self, session_id: str = "default") -> dict[str, Any]:
        ...

    def search_memories(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        ...

    def search_memories_semantic(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        ...

    def list_memories(self, status: str | None = None) -> list[dict[str, Any]]:
        ...

    def list_generation_logs(self, limit: int | None = None, purpose: str | None = None) -> list[dict[str, Any]]:
        ...


class JsonStore:
    def __init__(self, settings: Settings) -> None:
        self.path = settings.data_dir / "store.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write(self._default_state())

    def _default_state(self) -> dict[str, Any]:
        return default_state()

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
        return _session_from_state(state, session_id)

    def search_memories(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        memories = [
            memory
            for memory in self.snapshot().get("memories", [])
            if memory.get("status") == "active" and query in memory.get("content", "")
        ]
        memories.sort(
            key=lambda memory: (memory.get("importance", 0), memory.get("updated_at", "")),
            reverse=True,
        )
        if len(memories) >= limit:
            return memories[:limit]
        seen_ids = {memory.get("id") for memory in memories}
        for memory in self.search_memories_semantic(query, limit=limit):
            if memory.get("id") in seen_ids:
                continue
            memories.append(memory)
            seen_ids.add(memory.get("id"))
            if len(memories) >= limit:
                break
        return memories

    def search_memories_semantic(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        from .memory.semantic import cosine_similarity, semantic_vector

        query_vector = semantic_vector(query)
        scored = []
        for memory in self.snapshot().get("memories", []):
            if memory.get("status") != "active":
                continue
            vector = semantic_vector(memory.get("content", ""))
            scored.append((cosine_similarity(query_vector, vector), memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [memory for score, memory in scored[:limit] if score > 0]

    def list_memories(self, status: str | None = None) -> list[dict[str, Any]]:
        memories = self.snapshot().get("memories", [])
        if status is None:
            return memories
        return [memory for memory in memories if memory.get("status") == status]

    def list_generation_logs(self, limit: int | None = None, purpose: str | None = None) -> list[dict[str, Any]]:
        logs = self.snapshot().get("generation_logs", [])
        if purpose is not None:
            logs = [log for log in logs if log.get("purpose") == purpose]
        if limit is not None:
            return logs[-limit:]
        return logs


class SqliteStore:
    def __init__(self, settings: Settings, *, seed_state: dict[str, Any] | None = None) -> None:
        self.path = settings.data_dir / "store.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connect().close()
        with self._lock:
            self._initialize()
            if seed_state is not None:
                self._write_state(seed_state)
            elif self._read_state() is None:
                self._write_state(default_state())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    summary_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT,
                    meta_json TEXT
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at)")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    type TEXT,
                    content TEXT NOT NULL,
                    importance REAL,
                    salience REAL,
                    confidence REAL,
                    status TEXT,
                    open INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    last_used_at TEXT,
                    tags_json TEXT,
                    evidence_json TEXT,
                    full_json TEXT NOT NULL
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_memories_status_type ON memories(status, type)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_memories_open ON memories(open)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)")
            db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    content,
                    tags
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS persona_versions (
                    id TEXT PRIMARY KEY,
                    status TEXT,
                    version INTEGER,
                    full_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_logs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT,
                    purpose TEXT,
                    provider TEXT,
                    model TEXT,
                    degraded INTEGER,
                    elapsed_ms INTEGER,
                    error TEXT,
                    prompt_manifest_json TEXT,
                    feedback_signals_json TEXT,
                    full_json TEXT NOT NULL
                )
                """
            )

    def _read_state(self) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT state_json FROM app_state WHERE id = 1").fetchone()
        if not row:
            return None
        try:
            return json.loads(row["state_json"])
        except json.JSONDecodeError:
            return default_state()

    def _write_state(self, state: dict[str, Any]) -> None:
        normalized = _normalize_state(state)
        with self._connect() as db:
            db.execute("BEGIN")
            db.execute(
                "INSERT OR REPLACE INTO app_state (id, state_json, updated_at) VALUES (1, ?, ?)",
                (json.dumps(normalized, ensure_ascii=False), now_iso()),
            )
            _sync_projection_tables(db, normalized)
            db.commit()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read_state() or default_state())

    def mutate(self, fn):
        with self._lock:
            state = self._read_state() or default_state()
            result = fn(state)
            self._write_state(state)
            return result

    def session(self, session_id: str = "default") -> dict[str, Any]:
        state = self.snapshot()
        return _session_from_state(state, session_id)

    def search_memories(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = []
            fts_query = _fts_query(query)
            if fts_query:
                rows = db.execute(
                    """
                    SELECT memories.full_json
                    FROM memory_fts
                    JOIN memories ON memories.id = memory_fts.memory_id
                    WHERE memory_fts MATCH ? AND memories.status = 'active'
                    ORDER BY bm25(memory_fts)
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
            if not rows:
                rows = db.execute(
                    """
                    SELECT full_json
                    FROM memories
                    WHERE status = 'active' AND content LIKE ?
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", limit),
                ).fetchall()
        memories = [json.loads(row["full_json"]) for row in rows]
        if len(memories) >= limit:
            return memories[:limit]
        seen_ids = {memory.get("id") for memory in memories}
        for memory in self.search_memories_semantic(query, limit=limit):
            if memory.get("id") in seen_ids:
                continue
            memories.append(memory)
            seen_ids.add(memory.get("id"))
            if len(memories) >= limit:
                break
        return memories

    def search_memories_semantic(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        from .memory.semantic import cosine_similarity, semantic_vector

        query_vector = semantic_vector(query)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT memories.full_json, memory_embeddings.vector_json
                FROM memory_embeddings
                JOIN memories ON memories.id = memory_embeddings.memory_id
                WHERE memories.status = 'active'
                """
            ).fetchall()
        scored = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            scored.append((cosine_similarity(query_vector, vector), json.loads(row["full_json"])))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [memory for score, memory in scored[:limit] if score > 0]

    def list_memories(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if status is None:
                rows = db.execute(
                    """
                    SELECT full_json
                    FROM memories
                    ORDER BY updated_at DESC, created_at DESC
                    """
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT full_json
                    FROM memories
                    WHERE status = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (status,),
                ).fetchall()
        return [json.loads(row["full_json"]) for row in rows]

    def list_generation_logs(self, limit: int | None = None, purpose: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT full_json FROM generation_logs"
        params: list[Any] = []
        if purpose is not None:
            query += " WHERE purpose = ?"
            params.append(purpose)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        logs = [json.loads(row["full_json"]) for row in rows]
        logs.reverse()
        return logs


def _normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(default_state())
    normalized.update(state)
    normalized.setdefault("sessions", {})
    normalized.setdefault("persona_versions", [])
    normalized.setdefault("memories", [])
    normalized.setdefault("generation_logs", [])
    normalized.setdefault("memory_confirmations", [])
    return normalized


def _session_from_state(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    sessions = state.setdefault("sessions", {})
    session = sessions.get(session_id)
    if session is not None:
        return session
    return sessions[state["active_session_id"]]


def _sync_projection_tables(db: sqlite3.Connection, state: dict[str, Any]) -> None:
    for table in ["sessions", "messages", "memories", "memory_fts", "memory_embeddings", "persona_versions", "generation_logs"]:
        db.execute(f"DELETE FROM {table}")

    sessions = state.get("sessions", {})
    for session in sessions.values():
        messages = session.get("messages", [])
        summaries = session.get("summaries", [])
        db.execute(
            """
            INSERT OR REPLACE INTO sessions (id, title, created_at, updated_at, message_count, summary_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.get("id"),
                session.get("title"),
                session.get("created_at"),
                session.get("updated_at"),
                len(messages),
                len(summaries),
            ),
        )
        for message in messages:
            db.execute(
                """
                INSERT OR REPLACE INTO messages (id, session_id, role, content, created_at, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.get("id"),
                    session.get("id"),
                    message.get("role"),
                    message.get("content", ""),
                    message.get("created_at"),
                    json.dumps(message.get("meta", {}), ensure_ascii=False),
                ),
            )

    for memory in state.get("memories", []):
        db.execute(
            """
            INSERT OR REPLACE INTO memories (
                id, type, content, importance, salience, confidence, status, open,
                created_at, updated_at, last_used_at, tags_json, evidence_json, full_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.get("id"),
                memory.get("type"),
                memory.get("content", ""),
                memory.get("importance"),
                memory.get("salience"),
                memory.get("confidence"),
                memory.get("status"),
                1 if memory.get("open") else 0,
                memory.get("created_at"),
                memory.get("updated_at"),
                memory.get("last_used_at"),
                json.dumps(memory.get("tags", []), ensure_ascii=False),
                json.dumps(memory.get("evidence", []), ensure_ascii=False),
                json.dumps(memory, ensure_ascii=False),
            ),
        )
        db.execute(
            "INSERT INTO memory_fts (memory_id, content, tags) VALUES (?, ?, ?)",
            (memory.get("id"), memory.get("content", ""), " ".join(memory.get("tags", []))),
        )
        from .memory.semantic import semantic_vector

        vector = semantic_vector(memory.get("content", ""))
        db.execute(
            "INSERT OR REPLACE INTO memory_embeddings (memory_id, model, dimensions, vector_json) VALUES (?, ?, ?, ?)",
            (memory.get("id"), "local-hash-v1", len(vector), json.dumps(vector)),
        )

    for persona in state.get("persona_versions", []):
        db.execute(
            "INSERT OR REPLACE INTO persona_versions (id, status, version, full_json) VALUES (?, ?, ?, ?)",
            (persona.get("id"), persona.get("status"), persona.get("version"), json.dumps(persona, ensure_ascii=False)),
        )

    for log in state.get("generation_logs", []):
        db.execute(
            """
            INSERT OR REPLACE INTO generation_logs (
                id, created_at, purpose, provider, model, degraded, elapsed_ms,
                error, prompt_manifest_json, feedback_signals_json, full_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.get("id"),
                log.get("created_at"),
                log.get("purpose"),
                log.get("provider"),
                log.get("model"),
                1 if log.get("degraded") else 0,
                log.get("elapsed_ms"),
                log.get("error"),
                json.dumps(log.get("prompt_manifest", {}), ensure_ascii=False),
                json.dumps(log.get("feedback_signals", []), ensure_ascii=False),
                json.dumps(log, ensure_ascii=False),
            ),
        )


def _fts_query(query: str) -> str:
    terms = [term.replace('"', "") for term in query.split() if term.strip()]
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms)


def migrate_json_to_sqlite(settings: Settings, *, overwrite: bool = False) -> Path:
    json_store = JsonStore(settings)
    sqlite_path = settings.data_dir / "store.sqlite3"
    if not overwrite and _sqlite_has_app_state(sqlite_path):
        raise FileExistsError(f"SQLite store already has app_state: {sqlite_path}")
    sqlite_store = SqliteStore(settings, seed_state=json_store.snapshot())
    return sqlite_store.path


def _sqlite_has_app_state(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path) as db:
            table = db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_state'"
            ).fetchone()
            if table is None:
                return False
            row = db.execute("SELECT COUNT(*) FROM app_state").fetchone()
            return bool(row and row[0] > 0)
    except sqlite3.DatabaseError as exc:
        raise FileExistsError(f"SQLite store exists but cannot be inspected safely: {path}") from exc


def create_store(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "sqlite":
        return SqliteStore(settings)
    return JsonStore(settings)
