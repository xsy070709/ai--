from __future__ import annotations

from copy import deepcopy
from typing import Any

from .llm_gateway import DeepSeekGateway
from .memory import (
    apply_user_corrections,
    audit_memory_use,
    build_memory_context,
    build_logical_turn,
    build_session_summary,
    build_user_profile,
    choose_extractor,
    choose_intent_classifier,
    close_resolved_open_loops,
    enqueue_confirmation,
    generate_reflections,
    infer_feedback_signals,
    maintain_memories,
    mark_recalled,
    memory_layers,
    pending_confirmations,
    review_memory_candidates,
    RuleBasedMemoryExtractor,
    RuleBasedIntentClassifier,
    should_build_session_summary,
    tidy_memories,
    upsert_memories,
    work_memory,
    DEFAULT_MEMORY_PARAMS,
    DEFAULT_MEMORY_PROFILE,
    PARAMETER_LOAD_WARNINGS,
)
from .memory.schema import make_memory
from .persona import (
    active_persona_text,
    initialize_persona,
    learn_persona_profile,
    parse_persona_learning_json,
    persona_from_learned_profile,
    persona_learning_prompt,
)
from .storage import StorageBackend, new_id, now_iso
from .time_context import current_time_context


class ChatService:
    def __init__(self, store: StorageBackend, gateway: DeepSeekGateway) -> None:
        self.store = store
        self.gateway = gateway
        self.memory_extractor_init_error = None
        self.intent_classifier_init_error = None
        try:
            self.memory_extractor = choose_extractor(gateway.settings, gateway)
        except Exception as exc:
            self.memory_extractor_init_error = f"{type(exc).__name__}: {exc}"
            self.memory_extractor = RuleBasedMemoryExtractor()
        try:
            self.intent_classifier = choose_intent_classifier(gateway.settings, gateway)
        except Exception as exc:
            self.intent_classifier_init_error = f"{type(exc).__name__}: {exc}"
            self.intent_classifier = RuleBasedIntentClassifier()

    def status(self) -> dict[str, Any]:
        state = self.store.snapshot()
        persona = self._active_persona(state)
        return {
            "session_id": state["active_session_id"],
            "active_persona_entity_id": self._active_entity_id(state),
            "persona_entities": self.persona_entities(),
            "persona": persona,
            "layers": memory_layers(state),
            "profile": build_user_profile(self.store.list_memories(status="active")),
            "memory_confirmations": self.memory_confirmations(),
            "llm": {
                "provider": "deepseek",
                "configured": self.gateway.settings.has_deepseek_key,
                "model": self.gateway.settings.deepseek_chat_model,
            },
            "memory_params": {"profile": DEFAULT_MEMORY_PROFILE, "warnings": PARAMETER_LOAD_WARNINGS},
            "time": current_time_context(),
        }

    def messages(self) -> list[dict[str, Any]]:
        state = self.store.snapshot()
        session = state["sessions"][state["active_session_id"]]
        return session.get("messages", [])

    def memories(self) -> list[dict[str, Any]]:
        return self.store.list_memories()

    def memory_confirmations(self) -> list[dict[str, Any]]:
        state = self.store.snapshot()
        entity_id = self._active_entity_id(state)
        return [
            item
            for item in pending_confirmations(state)
            if self._item_in_entity(item, entity_id) or self._item_in_entity(item.get("candidate", {}), entity_id)
        ]

    def persona_entities(self) -> list[dict[str, Any]]:
        state = self.store.snapshot()
        active_id = self._active_entity_id(state)
        return [
            {
                **entity,
                "active": entity.get("id") == active_id,
                "persona": self._active_persona_for_entity(state, entity.get("id", "")),
                "message_count": len(
                    state.get("sessions", {}).get(entity.get("active_session_id"), {}).get("messages", [])
                ),
            }
            for entity in state.get("persona_entities", [])
        ]

    def create_persona_entity(self, name: str | None = None, *, activate: bool = True) -> dict[str, Any]:
        entity_id = new_id("entity")
        session_id = new_id("session")
        now = now_iso()

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            entity = {
                "id": entity_id,
                "name": name.strip() if name and name.strip() else "未命名人格",
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "active_session_id": session_id,
                "active_persona_id": None,
            }
            state.setdefault("persona_entities", []).append(entity)
            state.setdefault("sessions", {})[session_id] = {
                "id": session_id,
                "persona_entity_id": entity_id,
                "title": entity["name"],
                "created_at": now,
                "updated_at": now,
                "messages": [],
                "summaries": [],
            }
            if activate:
                self._activate_entity_in_state(state, entity_id)
            return entity

        return self.store.mutate(mutate)

    def switch_persona_entity(self, entity_id: str) -> dict[str, Any] | None:
        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            entity = self._activate_entity_in_state(state, entity_id)
            return entity

        return self.store.mutate(mutate)

    def debug_snapshot(self) -> dict[str, Any]:
        state = self.store.snapshot()
        entity_id = self._active_entity_id(state)
        memories = self.store.list_memories()
        grouped_memories: dict[str, list[dict[str, Any]]] = {}
        for memory in memories:
            grouped_memories.setdefault(memory.get("type", "unknown"), []).append(memory)
        session = state["sessions"][state["active_session_id"]]
        generation_logs = [
            log
            for log in self.store.list_generation_logs(limit=160)
            if self._item_in_entity(log, entity_id) or not log.get("persona_entity_id")
        ][-80:]
        api_requests = self.gateway.debug_requests()
        return {
            "session": {
                "id": session.get("id"),
                "title": session.get("title"),
                "message_count": len(session.get("messages", [])),
                "summary_count": len(session.get("summaries", [])),
                "summaries": session.get("summaries", []),
            },
            "memories": memories,
            "memories_by_type": grouped_memories,
            "memory_confirmations": self.memory_confirmations(),
            "generation_logs": generation_logs,
            "api_requests": api_requests,
            "raw_flow": self._debug_raw_flow(session, memories, generation_logs, api_requests),
            "status": self.status(),
            "persona_entities": self.persona_entities(),
            "active_persona_entity_id": entity_id,
        }

    def import_background(self, text: str, confirm: bool = True) -> dict[str, Any]:
        persona = initialize_persona(text)
        state = self.store.snapshot()
        entity_id = self._active_entity_id(state)
        persona["persona_entity_id"] = entity_id
        if confirm:
            persona["status"] = "active"

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            old_versions = state.get("persona_versions", [])
            entity_versions = [p for p in state.get("persona_versions", []) if self._item_in_entity(p, entity_id)]
            persona["version"] = len(entity_versions) + 1
            old_versions.append(persona)
            state["persona_versions"] = old_versions
            if confirm:
                state["active_persona_id"] = persona["id"]
                entity = self._entity_by_id(state, entity_id)
                if entity is not None:
                    entity["active_persona_id"] = persona["id"]
                    entity["name"] = persona.get("identity", {}).get("name") or entity.get("name")
                    entity["updated_at"] = now_iso()
            return persona

        return self.store.mutate(mutate)

    async def import_persona_materials(
        self,
        text: str,
        *,
        source_type: str = "mixed",
        persona_entity_id: str | None = None,
        confirm: bool = True,
    ) -> dict[str, Any]:
        state = self.store.snapshot()
        entity_id = persona_entity_id or self._active_entity_id(state)
        if self._entity_by_id(state, entity_id) is None:
            entity_id = self.create_persona_entity("未命名人格", activate=False)["id"]

        llm_profile = None
        llm_result = None
        try:
            llm_result = await self.gateway.structured(persona_learning_prompt(text, source_type), purpose="persona_learn")
            llm_profile = parse_persona_learning_json(llm_result.text)
        except Exception as exc:  # noqa: BLE001 - keep import usable when model is unavailable
            llm_result = type(
                "PersonaLearningError",
                (),
                {
                    "provider": "local",
                    "model": "fallback",
                    "degraded": True,
                    "elapsed_ms": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "usage": None,
                },
            )()
        learned_profile = learn_persona_profile(text, source_type=source_type, llm_profile=llm_profile)
        persona = persona_from_learned_profile(text, learned_profile, source_type=source_type)
        persona["status"] = "active" if confirm else "draft"
        persona["persona_entity_id"] = entity_id
        learned_memories = self._persona_learning_memories(persona, learned_profile, text, entity_id)

        def mutate(next_state: dict[str, Any]) -> dict[str, Any]:
            entity = self._entity_by_id(next_state, entity_id)
            if entity is None:
                return {}
            versions = next_state.setdefault("persona_versions", [])
            entity_versions = [p for p in versions if self._item_in_entity(p, entity_id)]
            persona["version"] = len(entity_versions) + 1
            versions.append(persona)
            all_memories = next_state.setdefault("memories", [])
            self._upsert_entity_memories(all_memories, learned_memories, entity_id)
            if confirm:
                entity["active_persona_id"] = persona["id"]
                next_state["active_persona_id"] = persona["id"]
            entity["name"] = persona.get("identity", {}).get("name") or entity.get("name")
            entity["updated_at"] = now_iso()
            next_state.setdefault("generation_logs", []).append(
                {
                    "id": new_id("gen"),
                    "persona_entity_id": entity_id,
                    "created_at": now_iso(),
                    "purpose": "persona_learn",
                    "provider": getattr(llm_result, "provider", "local"),
                    "model": getattr(llm_result, "model", "fallback"),
                    "degraded": getattr(llm_result, "degraded", True),
                    "elapsed_ms": getattr(llm_result, "elapsed_ms", 0),
                    "error": getattr(llm_result, "error", None),
                    "usage": getattr(llm_result, "usage", None),
                    "prompt_manifest": {
                        "source_type": source_type,
                        "persona_id": persona["id"],
                        "persona_entity_id": entity_id,
                        "learner": learned_profile.get("learner"),
                        "created_memory_ids": [memory["id"] for memory in learned_memories],
                    },
                    "feedback_signals": [],
                }
            )
            return {"entity": deepcopy(entity), "persona": persona, "created_memories": learned_memories}

        result = self.store.mutate(mutate)
        return {
            **result,
            "learned_profile": learned_profile,
            "llm": {
                "provider": getattr(llm_result, "provider", "local"),
                "model": getattr(llm_result, "model", "fallback"),
                "degraded": getattr(llm_result, "degraded", True),
                "error": getattr(llm_result, "error", None),
            },
        }

    def confirm_persona(self, persona_id: str) -> dict[str, Any] | None:
        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            entity_id = self._active_entity_id(state)
            for persona in state.get("persona_versions", []):
                if persona["id"] == persona_id and self._item_in_entity(persona, entity_id):
                    persona["status"] = "active"
                    state["active_persona_id"] = persona_id
                    entity = self._entity_by_id(state, entity_id)
                    if entity is not None:
                        entity["active_persona_id"] = persona_id
                        entity["updated_at"] = now_iso()
                    return persona
            return None

        return self.store.mutate(mutate)

    async def chat(self, user_text: str) -> dict[str, Any]:
        user_message = {"id": new_id("msg"), "role": "user", "content": user_text, "created_at": now_iso()}

        state = self.store.snapshot()
        snapshot_entity_id = self._active_entity_id(state)
        snapshot_session_id = state["active_session_id"]
        snapshot_state_revision = _state_revision(state)
        session = state["sessions"][snapshot_session_id]
        persona = self._active_persona(state)
        time_context = current_time_context()
        logical_turn = build_logical_turn(session.get("messages", []), user_message)
        memory_user_text = logical_turn["text"]
        all_memories = self._entity_memories(state, snapshot_entity_id)
        recall_candidates = self._memory_recall_candidates(all_memories, memory_user_text)
        memory_context = build_memory_context(
            all_memories,
            memory_user_text,
            now=time_context["iso"],
            recall_memories=recall_candidates,
        )
        intent_error = None
        try:
            intent = await self.intent_classifier.classify_async(memory_user_text, memory_context)
        except Exception as exc:
            intent_error = f"{type(exc).__name__}: {exc}"
            intent = RuleBasedIntentClassifier().classify(memory_user_text, memory_context)
            intent["classifier"] = "rule_based_intent_exception_fallback"
            intent["classifier_error"] = intent_error
        memory_context = build_memory_context(
            all_memories,
            memory_user_text,
            now=time_context["iso"],
            intent=intent,
            recall_memories=recall_candidates,
        )
        extraction_text = user_text if intent.get("has_completion_signal") else memory_user_text
        memories = memory_context["recalled"]
        prompt_summaries = session.get("summaries", [])
        prompt_summary_boundary = int(prompt_summaries[-1].get("message_count", 0)) if prompt_summaries else 0
        prompt_work_memory = work_memory(session.get("messages", []), user_text, after_message_count=prompt_summary_boundary)
        model_messages = self._build_prompt(
            persona,
            memory_context,
            user_text,
            time_context,
            prompt_summaries,
            prompt_work_memory,
        )
        result = await self.gateway.chat(model_messages, purpose="chat")
        memory_audit = audit_memory_use(result.text, memory_context)
        assistant_message = {
            "id": new_id("msg"),
            "role": "assistant",
            "content": result.text,
            "created_at": now_iso(),
            "meta": {
                "provider": result.provider,
                "model": result.model,
                "degraded": result.degraded,
                "used_memories": [m["id"] for m in memories],
                "memory_audit": memory_audit,
            },
        }
        extraction_error = None
        try:
            extracted = await self.memory_extractor.extract_async(
                extraction_text,
                result.text,
                {"memory_context": memory_context, "intent": intent, "logical_turn": logical_turn},
            )
        except Exception as exc:
            extraction_error = f"{type(exc).__name__}: {exc}"
            extracted = []
        reviewed = review_memory_candidates(extracted)
        self._tag_memories(reviewed["accepted"] + reviewed["needs_confirmation"] + reviewed["rejected"], snapshot_entity_id)

        def mutate(next_state: dict[str, Any]) -> dict[str, Any]:
            write_session_id = snapshot_session_id if snapshot_session_id in next_state["sessions"] else next_state["active_session_id"]
            write_entity_id = self._session_entity_id(next_state, write_session_id)
            active_session = next_state["sessions"][write_session_id]
            commit_state_revision = _state_revision(next_state)
            active_session_changed = next_state.get("active_session_id") != snapshot_session_id
            user_message["meta"] = {"persona_entity_id": write_entity_id}
            assistant_message["meta"]["persona_entity_id"] = write_entity_id
            active_session["messages"].extend([user_message, assistant_message])
            active_session["updated_at"] = now_iso()
            summaries = active_session.setdefault("summaries", [])
            last_summary_count = int(summaries[-1].get("message_count", 0)) if summaries else 0
            summary = build_session_summary(active_session["messages"], after_message_count=last_summary_count)
            if summary and should_build_session_summary(active_session["messages"], summaries):
                active_session.setdefault("summaries", []).append(summary)
            all_state_memories = next_state.setdefault("memories", [])
            current_memories = [memory for memory in all_state_memories if self._item_in_entity(memory, write_entity_id)]
            correction_result = apply_user_corrections(current_memories, memory_user_text, intent=intent)
            closed_memories = close_resolved_open_loops(current_memories, memory_user_text, intent=intent)
            mark_recalled(current_memories, [m["id"] for m in memories])
            self._upsert_entity_memories(all_state_memories, correction_result["created"], write_entity_id)
            self._upsert_entity_memories(all_state_memories, reviewed["accepted"], write_entity_id)
            queued_confirmations = enqueue_confirmation(next_state, reviewed["needs_confirmation"])
            reflections = generate_reflections(current_memories)
            reviewed_reflections = review_memory_candidates(reflections)
            self._tag_memories(
                reviewed_reflections["accepted"] + reviewed_reflections["needs_confirmation"] + reviewed_reflections["rejected"],
                write_entity_id,
            )
            self._upsert_entity_memories(all_state_memories, reviewed_reflections["accepted"], write_entity_id)
            queued_reflections = enqueue_confirmation(next_state, reviewed_reflections["needs_confirmation"])
            maintenance_result = maintain_memories(current_memories)
            prompt_manifest = {
                "api_message_count": len(model_messages),
                "work_memory_count": len(prompt_work_memory),
                "work_memory_after_message_count": prompt_summary_boundary,
                "session_summary_count": len(prompt_summaries),
                "used_session_summary_ids": [summary.get("id") for summary in prompt_summaries[-3:]],
                "prompt_segments": _prompt_segments(model_messages),
                "logical_turn": logical_turn,
                "snapshot_session_id": snapshot_session_id,
                "snapshot_persona_entity_id": snapshot_entity_id,
                "write_persona_entity_id": write_entity_id,
                "write_session_id": write_session_id,
                "active_session_changed": active_session_changed,
                "snapshot_state_revision": snapshot_state_revision,
                "commit_state_revision": commit_state_revision,
                "state_revision_changed": commit_state_revision != snapshot_state_revision,
                "used_memory_ids": [m["id"] for m in memories],
                "used_memory_reasons": {m["id"]: m.get("recall_reason") for m in memories},
                "recall_candidate_count": len(recall_candidates),
                "recall_candidate_ids": [m.get("id") for m in recall_candidates],
                "recall_candidate_source": "storage_search_plus_priority",
                "new_memory_ids": [m["id"] for m in reviewed["accepted"]],
                "corrected_memory_ids": [m["id"] for m in correction_result["corrected"]],
                "deleted_memory_ids": [m["id"] for m in correction_result["deleted"]],
                "correction_created_ids": [m["id"] for m in correction_result["created"]],
                "queued_memory_ids": [item["id"] for item in queued_confirmations + queued_reflections],
                "rejected_memory_ids": [m["id"] for m in reviewed["rejected"] + reviewed_reflections["rejected"]],
                "closed_memory_ids": [m["id"] for m in closed_memories],
                "decayed_memory_ids": [m["id"] for m in maintenance_result["decayed"]],
                "archived_memory_ids": [m["id"] for m in maintenance_result["archived"]],
                "reflection_ids": [m["id"] for m in reviewed_reflections["accepted"]],
                "followup_mode": memory_context.get("followup_plan", {}).get("mode"),
                "disclosure_mode": memory_context.get("disclosure_plan", {}).get("mode"),
                "memory_audit_status": memory_audit["status"],
                "memory_audit_issues": memory_audit["issues"],
                "memory_extractor": getattr(self.memory_extractor, "name", "unknown"),
                "memory_extractor_init_error": self.memory_extractor_init_error,
                "memory_extraction_error": extraction_error,
                "intent_classifier": intent.get("classifier", getattr(self.intent_classifier, "name", "unknown")),
                "intent_classifier_init_error": self.intent_classifier_init_error,
                "intent_classifier_error": intent_error,
                "intent": intent,
                "has_persona": persona is not None,
                "time_context": time_context,
            }
            previous_log = next_state.get("generation_logs", [])[-1] if next_state.get("generation_logs") else None
            feedback_signals = infer_feedback_signals(memory_user_text, previous_log=previous_log, current_manifest=prompt_manifest)
            next_state.setdefault("generation_logs", []).append(
                {
                    "id": new_id("gen"),
                    "persona_entity_id": write_entity_id,
                    "created_at": now_iso(),
                    "purpose": "chat",
                    "provider": result.provider,
                    "model": result.model,
                    "degraded": result.degraded,
                    "elapsed_ms": result.elapsed_ms,
                    "error": result.error,
                    "usage": result.usage,
                    "api_messages": model_messages,
                    "prompt_manifest": prompt_manifest,
                    "feedback_signals": feedback_signals,
                }
            )
            return {"messages": active_session["messages"], "layers": memory_layers(next_state)}

        updated = self.store.mutate(mutate)
        return {
            "reply": result.text,
            "message": assistant_message,
            "used_memories": [m["id"] for m in memories],
            "new_memories": reviewed["accepted"],
            "queued_memories": reviewed["needs_confirmation"],
            "rejected_memories": reviewed["rejected"],
            "memory_profile": memory_context["profile"],
            "followup_plan": memory_context.get("followup_plan"),
            "disclosure_plan": memory_context.get("disclosure_plan"),
            "memory_audit": memory_audit,
            "intent": intent,
            "logical_turn": logical_turn,
            "degraded": result.degraded,
            "llm": {"provider": result.provider, "model": result.model, "elapsed_ms": result.elapsed_ms, "error": result.error, "usage": result.usage},
            "layers": updated["layers"],
        }

    def delete_memory(self, memory_id: str) -> bool:
        def mutate(state: dict[str, Any]) -> bool:
            for memory in state.get("memories", []):
                if memory["id"] == memory_id:
                    memory["status"] = "deleted"
                    memory["updated_at"] = now_iso()
                    return True
            return False

        return self.store.mutate(mutate)

    def tidy_memory_store(self) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            entity_id = self._active_entity_id(state)
            return tidy_memories([memory for memory in state.setdefault("memories", []) if self._item_in_entity(memory, entity_id)])

        return self.store.mutate(mutate)

    def confirm_memory_candidate(self, confirmation_id: str, accept: bool) -> dict[str, Any] | None:
        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            for item in state.get("memory_confirmations", []):
                if item["id"] != confirmation_id or item.get("status") != "pending":
                    continue
                item["status"] = "accepted" if accept else "rejected"
                item["resolved_at"] = now_iso()
                candidate = item["candidate"]
                entity_id = candidate.get("persona_entity_id") or self._active_entity_id(state)
                if accept:
                    candidate["is_user_confirmed"] = True
                    candidate["quality_decision"] = "accept"
                    self._upsert_entity_memories(state.setdefault("memories", []), [candidate], entity_id)
                prompt_manifest = {
                    "confirmation_id": confirmation_id,
                    "candidate_memory_id": candidate.get("id"),
                    "candidate_type": candidate.get("type"),
                    "persona_entity_id": entity_id,
                    "accepted": accept,
                }
                state.setdefault("generation_logs", []).append(
                    {
                        "id": new_id("gen"),
                        "persona_entity_id": entity_id,
                        "created_at": now_iso(),
                        "purpose": "memory_confirmation",
                        "provider": "local",
                        "model": "user_feedback",
                        "degraded": False,
                        "elapsed_ms": 0,
                        "error": None,
                        "usage": None,
                        "prompt_manifest": prompt_manifest,
                        "feedback_signals": infer_feedback_signals("", current_manifest=prompt_manifest),
                    }
                )
                return item
            return None

        return self.store.mutate(mutate)

    def _active_persona(self, state: dict[str, Any]) -> dict[str, Any] | None:
        active_id = state.get("active_persona_id")
        return next((p for p in state.get("persona_versions", []) if p["id"] == active_id), None)

    def _active_persona_for_entity(self, state: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
        entity = self._entity_by_id(state, entity_id)
        if entity is None:
            return None
        active_id = entity.get("active_persona_id")
        return next(
            (p for p in state.get("persona_versions", []) if p.get("id") == active_id and self._item_in_entity(p, entity_id)),
            None,
        )

    def _active_entity_id(self, state: dict[str, Any]) -> str:
        entities = state.get("persona_entities") or []
        return state.get("active_persona_entity_id") or (entities[0].get("id") if entities else "entity_default")

    def _entity_by_id(self, state: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
        return next((entity for entity in state.get("persona_entities", []) if entity.get("id") == entity_id), None)

    def _activate_entity_in_state(self, state: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
        entity = self._entity_by_id(state, entity_id)
        if entity is None:
            return None
        state["active_persona_entity_id"] = entity_id
        state["active_session_id"] = entity.get("active_session_id") or state.get("active_session_id", "default")
        state["active_persona_id"] = entity.get("active_persona_id")
        entity["updated_at"] = now_iso()
        return entity

    def _session_entity_id(self, state: dict[str, Any], session_id: str) -> str:
        session = state.get("sessions", {}).get(session_id, {})
        return session.get("persona_entity_id") or self._active_entity_id(state)

    def _item_in_entity(self, item: dict[str, Any] | None, entity_id: str) -> bool:
        if not isinstance(item, dict):
            return False
        return (item.get("persona_entity_id") or "entity_default") == entity_id

    def _entity_memories(self, state: dict[str, Any], entity_id: str) -> list[dict[str, Any]]:
        return [memory for memory in state.get("memories", []) if self._item_in_entity(memory, entity_id)]

    def _tag_memories(self, memories: list[dict[str, Any]], entity_id: str) -> None:
        for memory in memories:
            memory["persona_entity_id"] = entity_id

    def _upsert_entity_memories(
        self,
        all_memories: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        entity_id: str,
    ) -> None:
        self._tag_memories(candidates, entity_id)
        scoped = [memory for memory in all_memories if self._item_in_entity(memory, entity_id)]
        before_objects = {id(memory) for memory in all_memories}
        upsert_memories(scoped, candidates)
        for memory in scoped:
            if id(memory) not in before_objects:
                all_memories.append(memory)

    def _persona_learning_memories(
        self,
        persona: dict[str, Any],
        profile: dict[str, Any],
        source_text: str,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        name = persona.get("identity", {}).get("name") or "该人格"
        evidence = source_text[:240]
        memories: list[dict[str, Any]] = []
        if profile.get("traits"):
            memories.append(
                make_memory(
                    "stable_impression",
                    f"{name}的稳定性格：{'、'.join(profile['traits'][:6])}",
                    0.82,
                    True,
                    evidence,
                )
            )
        style_bits = list(profile.get("speaking_style", []))
        if profile.get("catchphrases"):
            style_bits.append(f"口癖：{'、'.join(profile['catchphrases'][:5])}")
        if style_bits:
            memories.append(
                make_memory(
                    "response_rule",
                    f"扮演{name}时，说话方式偏：{'、'.join(style_bits[:8])}",
                    0.84,
                    True,
                    evidence,
                )
            )
        if profile.get("habits") or profile.get("conversation_habits"):
            habits = profile.get("habits", []) + profile.get("conversation_habits", [])
            memories.append(
                make_memory(
                    "relationship_signal",
                    f"{name}的互动习惯：{'、'.join(habits[:8])}",
                    0.78,
                    True,
                    evidence,
                )
            )
        if profile.get("summary"):
            memories.append(make_memory("fact", f"{name}的人格摘要：{profile['summary']}", 0.72, True, evidence))
        self._tag_memories(memories, entity_id)
        for memory in memories:
            memory["source_type"] = "persona_import"
        return memories

    def _memory_recall_candidates(self, memories: list[dict[str, Any]], user_text: str) -> list[dict[str, Any]]:
        limit = max(DEFAULT_MEMORY_PARAMS.recall.default_limit * 4, DEFAULT_MEMORY_PARAMS.recall.default_limit)
        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def add(memory: dict[str, Any]) -> None:
            memory_id = memory.get("id")
            if not memory_id or memory_id in seen_ids or memory.get("status") != "active":
                return
            candidates.append(memory)
            seen_ids.add(memory_id)

        for memory in self.store.search_memories(user_text, limit=limit):
            add(memory)
        for memory in memories:
            if memory.get("open") or memory.get("type") in {"boundary", "response_rule"} or memory.get("is_user_confirmed"):
                add(memory)
        return candidates

    def _build_prompt(
        self,
        persona: dict[str, Any] | None,
        memory_context: dict[str, Any],
        user_text: str,
        time_context: dict[str, str] | None = None,
        summaries: list[dict[str, Any]] | None = None,
        prompt_work_memory: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        time_context = time_context or current_time_context()
        prompt_work_memory = prompt_work_memory or []
        summary_context = _format_session_summaries(summaries or [])
        memory_runtime_context = "\n".join(
            [
                "记忆上下文：",
                "记忆系统给出的长期画像和本轮相关记忆如下。只在自然、有帮助时使用，不要机械复述。",
                memory_context["prompt_text"],
            ]
        )
        time_runtime_context = "\n".join(["运行时上下文：", time_context["prompt_text"]])
        return [
            {"role": "system", "content": _stable_system_prompt(persona)},
            {"role": "system", "content": summary_context},
            {"role": "system", "content": memory_runtime_context},
            {"role": "system", "content": time_runtime_context},
            *prompt_work_memory,
            {"role": "user", "content": user_text},
        ]

    def _debug_raw_flow(
        self,
        session: dict[str, Any],
        memories: list[dict[str, Any]],
        generation_logs: list[dict[str, Any]],
        api_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "description": "Raw debug data. generation_logs are persisted. api_requests are in-process only since the latest server restart.",
            "current_session_messages": session.get("messages", []),
            "current_session_summaries": session.get("summaries", []),
            "current_memories": memories,
            "persisted_generation_logs": generation_logs,
            "in_process_api_requests": api_requests,
            "latest_chat": _latest_chat_flow(generation_logs, api_requests),
        }


def _state_revision(state: dict[str, Any]) -> int:
    try:
        return int(state.get("state_revision", 0))
    except (TypeError, ValueError):
        return 0


def _latest_chat_flow(generation_logs: list[dict[str, Any]], api_requests: list[dict[str, Any]]) -> dict[str, Any]:
    latest_log = next((log for log in reversed(generation_logs) if log.get("purpose") == "chat"), None)
    if not latest_log:
        return {}
    return {
        "chat_generation_log": latest_log,
        "chat_api_messages": latest_log.get("api_messages", []),
        "prompt_manifest": latest_log.get("prompt_manifest", {}),
        "feedback_signals": latest_log.get("feedback_signals", []),
        "nearby_api_requests": [
            request
            for request in api_requests[-12:]
            if request.get("purpose") in {"chat", "memory_intent", "memory_extract", "structured"}
        ],
        "note": "chat_api_messages is the persisted chat-completion prompt. nearby_api_requests are live process request/response records.",
    }


def _stable_system_prompt(persona: dict[str, Any] | None = None) -> str:
    return "\n".join(
        [
            "你需要作为拟人虚拟好友进行自然中文聊天。",
            active_persona_text(persona),
            "回复原则：默认简短，先回应情绪，再回应事实；像熟悉的朋友一样自然接话。",
            "时间原则：必须使用运行时上下文里的当前真实时间理解今天、明天、昨天、今晚、下周等相对时间。",
            "记忆原则：长期记忆只在自然、有帮助时使用；不要机械复述；不要说出内部字段名。",
            "跟进原则：如果上下文提示某个待办 time_state=elapsed，可以轻问结果，但不能假装已经知道结果。",
            "边界原则：不要编造历史；不要泄露第三方隐私；不伪装真人；不承诺现实身份。",
        ]
    )


def _format_session_summaries(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "会话摘要：暂无。"
    lines = ["会话摘要（只用于理解较早上下文，不要机械复述）："]
    for summary in summaries[-3:]:
        text = summary.get("summary", "")
        suggestion = summary.get("follow_up_suggestion")
        marker = f"#{summary.get('message_count', '?')}"
        if suggestion:
            lines.append(f"- {marker} {text}；{suggestion}")
        else:
            lines.append(f"- {marker} {text}")
    return "\n".join(lines)


def _prompt_segments(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    system_index = 0
    system_names = ["stable_persona", "session_summaries", "memory_context", "time_context"]
    for index, message in enumerate(messages):
        role = message.get("role", "")
        if role == "system":
            name = system_names[system_index] if system_index < len(system_names) else f"system_{system_index + 1}"
            volatile = name == "time_context"
            system_index += 1
        elif role == "user" and index == len(messages) - 1:
            name = "current_user_message"
            volatile = True
        else:
            name = "work_memory"
            volatile = True
        segments.append(
            {
                "index": index,
                "role": role,
                "name": name,
                "chars": len(message.get("content", "")),
                "volatile": volatile,
            }
        )
    return segments
