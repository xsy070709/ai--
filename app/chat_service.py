from __future__ import annotations

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
    should_build_session_summary,
    tidy_memories,
    upsert_memories,
    work_memory,
    DEFAULT_MEMORY_PROFILE,
)
from .persona import active_persona_text, initialize_persona
from .storage import StorageBackend, new_id, now_iso
from .time_context import current_time_context


class ChatService:
    def __init__(self, store: StorageBackend, gateway: DeepSeekGateway) -> None:
        self.store = store
        self.gateway = gateway
        self.memory_extractor = choose_extractor(gateway.settings, gateway)
        self.intent_classifier = choose_intent_classifier(gateway.settings, gateway)

    def status(self) -> dict[str, Any]:
        state = self.store.snapshot()
        persona = self._active_persona(state)
        return {
            "session_id": state["active_session_id"],
            "persona": persona,
            "layers": memory_layers(state),
            "profile": build_user_profile(state.get("memories", [])),
            "memory_confirmations": pending_confirmations(state),
            "llm": {
                "provider": "deepseek",
                "configured": self.gateway.settings.has_deepseek_key,
                "model": self.gateway.settings.deepseek_chat_model,
            },
            "memory_params": {"profile": DEFAULT_MEMORY_PROFILE},
            "time": current_time_context(),
        }

    def messages(self) -> list[dict[str, Any]]:
        session = self.store.session()
        return session.get("messages", [])

    def memories(self) -> list[dict[str, Any]]:
        return self.store.snapshot().get("memories", [])

    def memory_confirmations(self) -> list[dict[str, Any]]:
        return pending_confirmations(self.store.snapshot())

    def debug_snapshot(self) -> dict[str, Any]:
        state = self.store.snapshot()
        memories = state.get("memories", [])
        grouped_memories: dict[str, list[dict[str, Any]]] = {}
        for memory in memories:
            grouped_memories.setdefault(memory.get("type", "unknown"), []).append(memory)
        session = state["sessions"][state["active_session_id"]]
        generation_logs = state.get("generation_logs", [])[-80:]
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
            "memory_confirmations": pending_confirmations(state),
            "generation_logs": generation_logs,
            "api_requests": api_requests,
            "raw_flow": self._debug_raw_flow(session, memories, generation_logs, api_requests),
            "status": self.status(),
        }

    def import_background(self, text: str, confirm: bool = True) -> dict[str, Any]:
        persona = initialize_persona(text)
        if confirm:
            persona["status"] = "active"

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            old_versions = state.get("persona_versions", [])
            persona["version"] = len(old_versions) + 1
            old_versions.append(persona)
            state["persona_versions"] = old_versions
            if confirm:
                state["active_persona_id"] = persona["id"]
            return persona

        return self.store.mutate(mutate)

    def confirm_persona(self, persona_id: str) -> dict[str, Any] | None:
        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            for persona in state.get("persona_versions", []):
                if persona["id"] == persona_id:
                    persona["status"] = "active"
                    state["active_persona_id"] = persona_id
                    return persona
            return None

        return self.store.mutate(mutate)

    async def chat(self, user_text: str) -> dict[str, Any]:
        user_message = {"id": new_id("msg"), "role": "user", "content": user_text, "created_at": now_iso()}

        state = self.store.snapshot()
        session = state["sessions"][state["active_session_id"]]
        persona = self._active_persona(state)
        time_context = current_time_context()
        logical_turn = build_logical_turn(session.get("messages", []), user_message)
        memory_user_text = logical_turn["text"]
        memory_context = build_memory_context(state.get("memories", []), memory_user_text, now=time_context["iso"])
        intent = await self.intent_classifier.classify_async(memory_user_text, memory_context)
        extraction_text = user_text if intent.get("has_completion_signal") else memory_user_text
        memories = memory_context["recalled"]
        prompt_summaries = session.get("summaries", [])
        model_messages = self._build_prompt(
            session.get("messages", []),
            persona,
            memory_context,
            user_text,
            time_context,
            prompt_summaries,
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
        extracted = await self.memory_extractor.extract_async(extraction_text, result.text, {"memory_context": memory_context, "intent": intent, "logical_turn": logical_turn})
        reviewed = review_memory_candidates(extracted)

        def mutate(next_state: dict[str, Any]) -> dict[str, Any]:
            active_session = next_state["sessions"][next_state["active_session_id"]]
            active_session["messages"].extend([user_message, assistant_message])
            active_session["updated_at"] = now_iso()
            summaries = active_session.setdefault("summaries", [])
            last_summary_count = int(summaries[-1].get("message_count", 0)) if summaries else 0
            summary = build_session_summary(active_session["messages"], after_message_count=last_summary_count)
            if summary and should_build_session_summary(active_session["messages"], summaries):
                active_session.setdefault("summaries", []).append(summary)
            current_memories = next_state.setdefault("memories", [])
            correction_result = apply_user_corrections(current_memories, memory_user_text)
            closed_memories = close_resolved_open_loops(current_memories, memory_user_text)
            mark_recalled(current_memories, [m["id"] for m in memories])
            upsert_memories(current_memories, correction_result["created"])
            upsert_memories(current_memories, reviewed["accepted"])
            queued_confirmations = enqueue_confirmation(next_state, reviewed["needs_confirmation"])
            reflections = generate_reflections(current_memories)
            reviewed_reflections = review_memory_candidates(reflections)
            upsert_memories(current_memories, reviewed_reflections["accepted"])
            queued_reflections = enqueue_confirmation(next_state, reviewed_reflections["needs_confirmation"])
            maintenance_result = maintain_memories(current_memories)
            prompt_manifest = {
                "work_memory_count": len(work_memory(active_session["messages"], memory_user_text)),
                "session_summary_count": len(prompt_summaries),
                "used_session_summary_ids": [summary.get("id") for summary in prompt_summaries[-3:]],
                "logical_turn": logical_turn,
                "used_memory_ids": [m["id"] for m in memories],
                "used_memory_reasons": {m["id"]: m.get("recall_reason") for m in memories},
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
                "intent_classifier": intent.get("classifier", getattr(self.intent_classifier, "name", "unknown")),
                "intent": intent,
                "has_persona": persona is not None,
                "time_context": time_context,
            }
            previous_log = next_state.get("generation_logs", [])[-1] if next_state.get("generation_logs") else None
            feedback_signals = infer_feedback_signals(memory_user_text, previous_log=previous_log, current_manifest=prompt_manifest)
            next_state.setdefault("generation_logs", []).append(
                {
                    "id": new_id("gen"),
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
            return tidy_memories(state.setdefault("memories", []))

        return self.store.mutate(mutate)

    def confirm_memory_candidate(self, confirmation_id: str, accept: bool) -> dict[str, Any] | None:
        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            for item in state.get("memory_confirmations", []):
                if item["id"] != confirmation_id or item.get("status") != "pending":
                    continue
                item["status"] = "accepted" if accept else "rejected"
                item["resolved_at"] = now_iso()
                candidate = item["candidate"]
                if accept:
                    candidate["is_user_confirmed"] = True
                    candidate["quality_decision"] = "accept"
                    upsert_memories(state.setdefault("memories", []), [candidate])
                state.setdefault("generation_logs", []).append(
                    {
                        "id": new_id("gen"),
                        "created_at": now_iso(),
                        "purpose": "memory_confirmation",
                        "provider": "local",
                        "model": "user_feedback",
                        "degraded": False,
                        "elapsed_ms": 0,
                        "error": None,
                        "usage": None,
                        "prompt_manifest": {
                            "confirmation_id": confirmation_id,
                            "candidate_memory_id": candidate.get("id"),
                            "candidate_type": candidate.get("type"),
                            "accepted": accept,
                        },
                        "feedback_signals": [
                            {
                                "type": "confirmation_accepted" if accept else "confirmation_rejected",
                                "reason": "用户处理了记忆确认队列",
                                "parameters": ["quality.auto_accept_min_confidence"],
                            }
                        ],
                    }
                )
                return item
            return None

        return self.store.mutate(mutate)

    def _active_persona(self, state: dict[str, Any]) -> dict[str, Any] | None:
        active_id = state.get("active_persona_id")
        return next((p for p in state.get("persona_versions", []) if p["id"] == active_id), None)

    def _build_prompt(
        self,
        messages: list[dict[str, Any]],
        persona: dict[str, Any] | None,
        memory_context: dict[str, Any],
        user_text: str,
        time_context: dict[str, str] | None = None,
        summaries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        time_context = time_context or current_time_context()
        dynamic_context = "\n".join(
            [
                "运行时上下文：",
                time_context["prompt_text"],
                _format_session_summaries(summaries or []),
                "记忆系统给出的长期画像和本轮相关记忆如下。只在自然、有帮助时使用，不要机械复述。",
                memory_context["prompt_text"],
            ]
        )
        return [
            {"role": "system", "content": _stable_system_prompt(persona)},
            {"role": "system", "content": dynamic_context},
            *work_memory(messages, user_text),
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
