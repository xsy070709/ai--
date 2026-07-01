from __future__ import annotations

import asyncio

from app.chat_service import ChatService
from app.config import Settings
from app.llm_gateway import DeepSeekGateway
from app.memory import (
    RuleBasedMemoryExtractor,
    StructuredLLMMemoryExtractor,
    apply_user_corrections,
    audit_memory_use,
    build_memory_context,
    close_resolved_open_loops,
    extract_memory_candidates,
    generate_reflections,
    maintain_memories,
    review_memory_candidates,
    upsert_memories,
)
from app.memory.initiative import build_disclosure_plan
from app.memory.schema import make_memory
from app.persona import initialize_persona
from app.storage import JsonStore


class FakeStructuredGateway:
    class Settings:
        memory_extractor = "llm"

    settings = Settings()

    async def structured(self, messages, purpose="structured"):
        from app.llm_gateway import LLMResult

        return LLMResult(
            text='{"memories":[{"type":"preference","content":"用户喜欢先被安慰再分析","confidence":0.86,"confirmed":false,"open":false,"stability":"high","sensitivity_level":"low"}]}',
            provider="fake",
            model="fake",
            degraded=False,
            elapsed_ms=1,
        )


class FakeDegradedGateway(FakeStructuredGateway):
    async def structured(self, messages, purpose="structured"):
        from app.llm_gateway import LLMResult

        return LLMResult(text="{}", provider="fake", model="fake", degraded=True, elapsed_ms=1, error="forced")


def test_initialize_persona_from_background() -> None:
    persona = initialize_persona("名字：林夏。关系定位：长期陪伴型虚拟好友。性格：温柔、理性、少说教。")

    assert persona["identity"]["name"] == "林夏"
    assert "长期陪伴型虚拟好友" in persona["identity"]["relationship_to_user"]
    assert "温柔" in persona["personality"]["stable_traits"]
    assert "林夏" in persona["system_prompt"]["content"]


def test_extract_explicit_memory() -> None:
    memories = extract_memory_candidates("记住我喜欢安静一点的回复")

    assert memories
    assert memories[0]["type"] == "preference"
    assert memories[0]["is_user_confirmed"] is True


def test_rule_based_extractor_marks_source() -> None:
    extractor = RuleBasedMemoryExtractor()
    memories = extractor.extract("记住我喜欢安静一点的回复")

    assert memories
    assert memories[0]["extractor"] == "rule_based"


def test_structured_llm_extractor_maps_json_to_memory() -> None:
    extractor = StructuredLLMMemoryExtractor(FakeStructuredGateway())
    memories = asyncio.run(extractor.extract_async("我喜欢先被安慰再分析"))

    assert memories
    assert memories[0]["type"] == "preference"
    assert memories[0]["extractor"] == "structured_llm"
    assert memories[0]["content"] == "用户喜欢先被安慰再分析"


def test_structured_llm_extractor_falls_back_when_degraded() -> None:
    extractor = StructuredLLMMemoryExtractor(FakeDegradedGateway())
    memories = asyncio.run(extractor.extract_async("记住我喜欢安静一点的回复"))

    assert memories
    assert memories[0]["extractor"] == "structured_llm_fallback"


def test_quality_review_queues_sensitive_boundary() -> None:
    candidates = extract_memory_candidates("这是我的雷区，不要提我家里的事。")
    reviewed = review_memory_candidates(candidates)

    assert reviewed["needs_confirmation"]
    assert reviewed["needs_confirmation"][0]["type"] == "boundary"


def test_extract_richer_memory_layers() -> None:
    memories = extract_memory_candidates("以后别上来就讲大道理，明天下午我要交材料，我现在因为项目有点焦虑。")
    memory_types = {memory["type"] for memory in memories}

    assert "response_rule" in memory_types
    assert "goal" in memory_types
    assert "emotion_pattern" in memory_types
    assert any(memory.get("open") for memory in memories)


def test_memory_upsert_merges_similar_preferences() -> None:
    existing = []
    upsert_memories(existing, extract_memory_candidates("记住我喜欢安静一点的回复"))
    upsert_memories(existing, extract_memory_candidates("我喜欢安静一点的回复方式"))

    preferences = [memory for memory in existing if memory["type"] == "preference"]
    assert len(preferences) == 1
    assert preferences[0]["confidence"] > 0.9


def test_memory_context_prioritizes_open_and_emotional_recall() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("以后别上来就讲大道理，明天下午我要交材料，我现在因为项目有点焦虑。"))
    context = build_memory_context(memories, "我还是有点焦虑，那个材料怎么办")

    recalled_types = {memory["type"] for memory in context["recalled"]}
    assert "goal" in recalled_types
    assert "emotion_pattern" in recalled_types
    assert "待跟进" in context["prompt_text"]


def test_relationship_and_shared_memory_shape_human_context() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("我们约定下次继续把项目拆成小任务。"))
    upsert_memories(memories, extract_memory_candidates("还是你懂我，我想跟你说这些。"))
    context = build_memory_context(memories, "继续上次项目那个小任务")

    assert any(memory["type"] == "shared_experience" for memory in memories)
    assert any(memory["type"] == "relationship_signal" for memory in memories)
    assert "关系状态" in context["prompt_text"]
    assert "共同经历" in context["prompt_text"]


def test_conflicting_preference_supersedes_old_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("我喜欢你多分析一点"))
    upsert_memories(memories, extract_memory_candidates("我不喜欢你多分析一点"))

    active_preferences = [memory for memory in memories if memory["type"] == "preference" and memory["status"] == "active"]
    active_dislikes = [memory for memory in memories if memory["type"] == "dislike" and memory["status"] == "active"]
    superseded = [memory for memory in memories if memory["status"] == "superseded"]
    assert not active_preferences
    assert active_dislikes
    assert superseded


def test_user_correction_replaces_wrong_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("记住我喜欢热闹一点的回复"))

    result = apply_user_corrections(memories, "不是热闹一点的回复，而是安静一点的回复。")
    upsert_memories(memories, result["created"])

    assert result["corrected"]
    assert any(memory["status"] == "corrected" for memory in memories)
    assert any(memory["status"] == "active" and "安静一点" in memory["content"] for memory in memories)


def test_user_can_delete_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("记住我喜欢安静一点的回复"))

    result = apply_user_corrections(memories, "别记我喜欢安静一点的回复")

    assert result["deleted"]
    assert not [memory for memory in memories if memory["status"] == "active"]


def test_recall_cooldown_avoids_repeating_overused_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("我喜欢安静一点的回复方式"))
    memories[0]["use_count"] = 3

    context = build_memory_context(memories, "今天想安静一点")

    assert not context["recalled"]
    assert "用户喜欢或偏好安静一点的回复方式" in context["prompt_text"]


def test_disclosure_plan_keeps_old_memory_quiet_in_casual_chat() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("我们约定下次继续把项目拆成小任务。"))
    context = build_memory_context(memories, "早")

    assert context["disclosure_plan"]["mode"] in {"quiet", "tone_only"}
    assert "不要主动提旧事" in context["prompt_text"] or "只把记忆用于语气" in context["prompt_text"]


def test_disclosure_plan_mentions_when_user_invites_old_topic() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("我们约定下次继续把项目拆成小任务。"))
    context = build_memory_context(memories, "继续上次那个项目")

    assert context["disclosure_plan"]["mode"] == "can_mention"
    assert any(item["action"] == "mention" for item in context["disclosure_plan"]["items"])


def test_boundary_memory_is_obeyed_silently() -> None:
    boundary = make_memory("boundary", "用户不希望提家里的事", 0.9, True, "用户确认", sensitivity_level="medium")
    plan = build_disclosure_plan([boundary], "今天好累", {"mode": "none", "items": [], "instruction": ""})

    assert plan["mode"] == "silent_obey"
    assert plan["items"][0]["action"] == "obey"


def test_emotion_pattern_is_tone_only_not_labeling_user() -> None:
    memory = make_memory("emotion_pattern", "用户在项目相关情境中容易感到压力", 0.8, False, "用户说项目焦虑")
    memory["recall_score"] = 4.5
    plan = build_disclosure_plan([memory], "项目又卡住了", {"mode": "none", "items": [], "instruction": ""})

    assert plan["mode"] == "tone_only"
    assert plan["items"][0]["action"] == "hint"


def test_memory_audit_fails_when_silent_memory_is_surfaced() -> None:
    boundary = make_memory("boundary", "用户不希望提家里的事", 0.9, True, "用户确认", sensitivity_level="medium")
    context = {
        "disclosure_plan": {
            "mode": "silent_obey",
            "items": [{"memory_id": boundary["id"], "type": "boundary", "action": "obey", "content": boundary["content"]}],
        },
        "followup_plan": {"mode": "none"},
    }

    audit = audit_memory_use("我知道你不想提家里的事，所以我不说。", context)

    assert audit["status"] == "fail"
    assert audit["issues"][0]["type"] == "forbidden_memory_surface"


def test_memory_audit_warns_when_tone_memory_is_labeled() -> None:
    memory = make_memory("emotion_pattern", "用户在项目相关情境中容易感到压力", 0.8, False, "用户说项目焦虑")
    context = {
        "disclosure_plan": {
            "mode": "tone_only",
            "items": [{"memory_id": memory["id"], "type": "emotion_pattern", "action": "hint", "content": memory["content"]}],
        },
        "followup_plan": {"mode": "none"},
    }

    audit = audit_memory_use("我记得你在项目相关情境中容易感到压力，我们慢慢来。", context)

    assert audit["status"] == "warn"
    assert audit["issues"][0]["type"] == "over_explicit_tone_memory"


def test_memory_audit_warns_when_allowed_followup_is_missed() -> None:
    memory = make_memory("shared_experience", "共同经历/约定：我们约定下次继续把项目拆成小任务", 0.8, False, "约定")
    context = {
        "disclosure_plan": {
            "mode": "can_mention",
            "items": [{"memory_id": memory["id"], "type": "shared_experience", "action": "mention", "content": memory["content"]}],
        },
        "followup_plan": {"mode": "gentle_follow_up"},
    }

    audit = audit_memory_use("嗯，我在。你现在感觉怎么样？", context)

    assert audit["status"] == "warn"
    assert audit["issues"][0]["type"] == "missed_expected_followup"


def test_memory_audit_ok_for_quiet_plan() -> None:
    audit = audit_memory_use("早，今天醒得还好吗？", {"disclosure_plan": {"mode": "quiet", "items": []}, "followup_plan": {"mode": "none"}})

    assert audit["status"] == "ok"


def test_maintenance_archives_old_ephemeral_memories() -> None:
    memories = [
        make_memory("episodic", f"近期事件：用户今天处理第{index}个项目小事项，感觉有点累。", 0.58, False, f"事件{index}", stability="low")
        for index in range(18)
    ]

    result = maintain_memories(memories, max_ephemeral=4)

    assert result["archived"]
    assert len([memory for memory in memories if memory["status"] == "active" and memory["type"] == "episodic"]) <= 4


def test_reflection_consolidates_human_like_impression() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("以后别上来就讲大道理，我更希望你先安慰我。"))
    upsert_memories(memories, extract_memory_candidates("我现在因为项目有点焦虑。"))

    reflections = generate_reflections(memories)
    upsert_memories(memories, reflections)
    context = build_memory_context(memories, "项目还是有点焦虑")

    assert any(memory["type"] == "stable_impression" for memory in memories)
    assert "稳定印象" in context["prompt_text"]
    assert "先被安慰" in context["prompt_text"]


def test_open_loop_can_be_closed_when_user_reports_completion() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("明天下午我要交材料，现在有点焦虑。"))

    closed = close_resolved_open_loops(memories, "材料已经交完了，终于解决了。")

    assert closed
    assert not closed[0]["open"]
    assert closed[0]["closed_at"]
    context = build_memory_context(memories, "材料已经交完了")
    assert context["followup_plan"]["mode"] == "acknowledge_closure"


def test_chat_service_degraded_flow(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    service.import_background("名字：林夏。关系定位：长期陪伴型虚拟好友。性格：温柔、理性。")
    result = asyncio.run(service.chat("记住我喜欢安静一点的回复"))

    assert result["degraded"] is True
    assert result["new_memories"]
    assert service.messages()[-1]["role"] == "assistant"
    assert service.status()["layers"]["persona"]["count"] == 1
    assert service.status()["profile"]["preferences"]


def test_chat_service_can_use_structured_memory_extractor(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
        memory_extractor="llm",
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))
    service.memory_extractor = StructuredLLMMemoryExtractor(FakeStructuredGateway())

    asyncio.run(service.chat("我喜欢先被安慰再分析"))

    assert [memory for memory in service.memories() if memory.get("extractor") == "structured_llm"]


def test_chat_service_queues_and_confirms_uncertain_memory(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    asyncio.run(service.chat("这是我的雷区，不要提我家里的事。"))
    confirmations = service.memory_confirmations()

    assert confirmations
    assert not [memory for memory in service.memories() if memory["type"] == "boundary"]
    accepted = service.confirm_memory_candidate(confirmations[0]["id"], True)
    assert accepted and accepted["status"] == "accepted"
    assert [memory for memory in service.memories() if memory["type"] == "boundary"]


def test_rejected_confirmation_does_not_enter_memory(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    asyncio.run(service.chat("这是我的雷区，不要提我家里的事。"))
    confirmation = service.memory_confirmations()[0]
    rejected = service.confirm_memory_candidate(confirmation["id"], False)

    assert rejected and rejected["status"] == "rejected"
    assert not [memory for memory in service.memories() if memory["type"] == "boundary"]


def test_chat_service_closes_open_loop_and_generates_reflection(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    asyncio.run(service.chat("以后别上来就讲大道理，我更希望你先安慰我。"))
    asyncio.run(service.chat("明天下午我要交材料，现在因为项目有点焦虑。"))
    asyncio.run(service.chat("材料已经交完了，终于解决了。"))

    memories = service.memories()
    assert any(memory["type"] == "stable_impression" for memory in memories)
    assert not [memory for memory in memories if memory.get("open") and "交材料" in memory["content"]]


def test_summary_after_long_chat(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    for index in range(8):
        asyncio.run(service.chat(f"今天第{index}轮聊天，我在推进项目。"))

    status = service.status()
    assert status["layers"]["work"]["count"] >= 16
    assert status["layers"]["summary"]["count"] >= 1


def test_twenty_turn_single_window_chat(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    for index in range(20):
        result = asyncio.run(service.chat(f"第{index + 1}轮：继续保持这个单窗口聊天。"))
        assert result["reply"]

    messages = service.messages()
    assert len(messages) == 40
    assert messages[0]["role"] == "user"
    assert messages[-1]["role"] == "assistant"
    assert service.status()["layers"]["work"]["count"] == 24
