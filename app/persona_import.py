"""In-memory import sessions for the persona import wizard.

Import sessions are ephemeral — they live only for the duration of the wizard.
Once the user confirms, the profile is persisted through the normal
``ChatService`` / ``JsonStore`` path and the session is discarded.
"""

from __future__ import annotations

import threading
from typing import Any

from .persona import (
    _fallback_persona_profile,
    _infer_traits_from_narrative,
    _extract_subject_name,
    build_persona_learning_memories,
    learn_persona_profile,
    merge_profile_diff,
    parse_persona_learning_json,
    parse_refine_json,
    persona_from_learned_profile,
    persona_learning_prompt_v2,
    persona_refine_prompt,
)
from .storage import new_id, now_iso


class ImportSession:
    __slots__ = (
        "session_id",
        "entity_id",
        "source_text",
        "source_type",
        "messages",
        "initial_profile",
        "current_profile",
        "status",
        "created_at",
        "llm_error",
    )

    def __init__(
        self,
        session_id: str,
        entity_id: str,
        source_text: str,
        source_type: str,
    ) -> None:
        self.session_id = session_id
        self.entity_id = entity_id
        self.source_text = source_text
        self.source_type = source_type
        self.messages: list[dict[str, str]] = []
        self.initial_profile: dict[str, Any] = {}
        self.current_profile: dict[str, Any] = {}
        self.status = "analyzing"
        self.created_at = now_iso()


class ImportSessionManager:
    """Manages ephemeral import sessions.

    Sessions are kept in memory only.  They are discarded when the user
    confirms the import or closes the wizard without confirming.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway
        self._sessions: dict[str, ImportSession] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def create_session(
        self,
        source_text: str,
        source_type: str,
        entity_id: str,
        persona_name: str,
    ) -> ImportSession:
        """Run initial LLM analysis and return a ready-to-use session."""

        session_id = new_id("import")
        session = ImportSession(session_id, entity_id, source_text, source_type)
        session.status = "analyzing"

        # ── LLM path ──────────────────────────────────────────────
        llm_error: str | None = None
        llm_profile: dict[str, Any] | None = None
        try:
            messages = persona_learning_prompt_v2(source_text, source_type, persona_name or None)
            llm_result = await self._gateway.structured(messages, purpose="persona_learn")
            llm_profile = parse_persona_learning_json(llm_result.text)
        except Exception as exc:
            llm_error = f"{type(exc).__name__}: {exc}"

        # ── local fallback ────────────────────────────────────────
        local_profile = _fallback_persona_profile(source_text, source_type=source_type)

        # augment local profile with narrative inference
        local_profile.setdefault("traits", [])
        inferred = _infer_traits_from_narrative(source_text)
        existing = list(local_profile.get("traits", []))
        local_profile["traits"] = list(dict.fromkeys(existing + inferred))[:8]

        # try extracting a subject name when the entity name is generic
        if not _is_meaningful_name(persona_name):
            extracted = _extract_subject_name(source_text)
            if extracted:
                local_profile["name"] = extracted

        merged = learn_persona_profile(source_text, source_type=source_type, llm_profile=llm_profile)

        # name resolution priority:
        # 1. if entity has a meaningful name AND the LLM name doesn't appear in the source text,
        #    keep the entity name (user already named this persona)
        # 2. if the LLM found a name that appears in the text, use it
        # 3. if neither, keep whatever the merge produced
        llm_name = (llm_profile or {}).get("name", "")
        if _is_meaningful_name(persona_name):
            if not _is_meaningful_name(llm_name) or llm_name.strip() not in source_text:
                merged["name"] = persona_name.strip()
        elif _is_meaningful_name(llm_name) and not _is_meaningful_name(merged.get("name")):
            merged["name"] = llm_name.strip()

        # capture clarifying questions from the LLM response
        clarifying: list[str] = []
        if isinstance(llm_profile, dict):
            clarifying = list(llm_profile.get("clarifying_questions", []) or [])[:3]

        session.initial_profile = dict(merged)
        session.current_profile = dict(merged)
        session.llm_error = llm_error

        # build the first assistant message
        first_message = self._build_greeting(merged, clarifying, bool(llm_error))
        session.messages.append({"role": "assistant", "content": first_message})
        session.status = "learning"

        with self._lock:
            self._sessions[session_id] = session
        return session

    async def send_message(self, session_id: str, user_message: str) -> dict[str, Any]:
        """Process a refinement message and return updated state."""

        session = self._require(session_id)
        session.messages.append({"role": "user", "content": user_message})

        reply: str = "收到，我会根据你说的调整。"
        profile_diff: dict[str, Any] = {}
        clarifying_questions: list[str] = []
        is_complete = False

        try:
            messages = persona_refine_prompt(
                session.current_profile,
                session.messages,
                user_message,
            )
            result = await self._gateway.structured(messages, purpose="persona_refine")
            parsed = parse_refine_json(result.text)
            reply = parsed["reply"]
            profile_diff = parsed["profile_diff"]
            clarifying_questions = parsed["clarifying_questions"]
            is_complete = parsed["is_complete"]
        except Exception:
            # when the LLM is unavailable, still reflect what the user typed
            reply = self._fallback_refine_reply(user_message)

        if profile_diff and isinstance(profile_diff, dict):
            session.current_profile = merge_profile_diff(session.current_profile, profile_diff)

        session.messages.append({"role": "assistant", "content": reply})
        return {
            "reply": reply,
            "profile_diff": profile_diff,
            "clarifying_questions": clarifying_questions,
            "is_complete": is_complete,
            "current_profile": session.current_profile,
        }

    def update_profile(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Apply manual user edits to the current profile."""

        session = self._get(session_id)
        if session is None:
            return None
        session.current_profile = merge_profile_diff(session.current_profile, patch)
        return session.current_profile

    def get_session(self, session_id: str) -> ImportSession | None:
        return self._get(session_id)

    def get_session_state(self, session_id: str) -> dict[str, Any] | None:
        session = self._get(session_id)
        if session is None:
            return None
        return {
            "session_id": session.session_id,
            "entity_id": session.entity_id,
            "source_type": session.source_type,
            "initial_profile": session.initial_profile,
            "current_profile": session.current_profile,
            "messages": session.messages,
            "status": session.status,
            "created_at": session.created_at,
        }

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _get(self, session_id: str) -> ImportSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def _require(self, session_id: str) -> ImportSession:
        session = self._get(session_id)
        if session is None:
            raise KeyError(f"import session not found: {session_id}")
        return session

    @staticmethod
    def _build_greeting(profile: dict[str, Any], clarifying: list[str], degraded: bool) -> str:
        name = profile.get("name") or "该角色"
        traits = profile.get("traits", [])
        style = profile.get("speaking_style", [])

        parts: list[str] = []
        parts.append(f"我已经分析了材料，初步提取了「{name}」的人格设定。")

        if traits:
            parts.append(f"性格方面我识别出：{'、'.join(traits[:6])}。")
        if style:
            parts.append(f"说话风格偏向：{'、'.join(style[:5])}。")

        if degraded:
            parts.append("（注意：当前为本地规则提取，未使用 LLM 深度分析。）")

        parts.append("你可以在右侧面板查看完整设定。如果有什么不对或需要补充的，直接告诉我就好。")

        if clarifying:
            parts.append("另外，我还想确认几点：")
            for idx, question in enumerate(clarifying, 1):
                parts.append(f"  {idx}. {question}")

        return "\n".join(parts)

    @staticmethod
    def _fallback_refine_reply(user_message: str) -> str:
        """Generate a simple reply when the LLM is unavailable."""
        if any(word in user_message for word in ["不", "错", "改", "换", "应该", "其实"]):
            return "明白了，我会根据你说的调整设定。你可以继续补充，或者去右侧面板手动编辑。"
        return "收到补充。你可以在右侧面板查看当前设定，也可以继续告诉我更多信息。"


def _is_meaningful_name(name: str | None) -> bool:
    value = str(name or "").strip()
    return bool(value and value not in {"未命名", "未命名好友", "未命名人格", "默认人格", ""})
