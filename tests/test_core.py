from __future__ import annotations

import asyncio

from app.chat_service import ChatService
from app.config import Settings
from app.llm_gateway import DeepSeekGateway, LLMResult
from app.memory import (
    DEFAULT_MEMORY_PARAMS,
    PARAMETER_DESCRIPTIONS,
    RuleBasedMemoryExtractor,
    RuleBasedIntentClassifier,
    StructuredLLMMemoryExtractor,
    StructuredLLMIntentClassifier,
    apply_user_corrections,
    audit_memory_use,
    analyze_feedback,
    build_memory_context,
    build_logical_turn,
    build_session_summary,
    close_resolved_open_loops,
    extract_memory_candidates,
    evaluate_calibration_cases,
    generate_reflections,
    infer_feedback_signals,
    maintain_memories,
    memory_params_for_profile,
    memory_params_from_file,
    relevant_memories,
    review_memory_candidates,
    tidy_memories,
    upsert_memories,
)
from app.memory.initiative import build_disclosure_plan
from app.memory.schema import make_memory
from app.memory.semantic import semantic_similarity, semantic_vector
from app.memory.signals import information_density, looks_like_casual_chat
from app.memory.summary import should_build_session_summary, work_memory
from app.persona import initialize_persona
from app.storage import JsonStore, SqliteStore, create_store, migrate_json_to_sqlite


class FakeStructuredGateway:
    class Settings:
        memory_extractor = "llm"

    settings = Settings()

    def __init__(self) -> None:
        self.calls = []

    async def structured(self, messages, purpose="structured"):
        from app.llm_gateway import LLMResult

        self.calls.append({"purpose": purpose, "messages": messages})
        return LLMResult(
            text='{"memories":[{"type":"preference","content":"用户喜欢先被安慰再分析","confidence":0.86,"confirmed":false,"open":false,"stability":"high","sensitivity_level":"low"}]}',
            provider="fake",
            model="fake",
            degraded=False,
            elapsed_ms=1,
        )


class FakeIntentGateway(FakeStructuredGateway):
    async def structured(self, messages, purpose="structured"):
        from app.llm_gateway import LLMResult

        self.calls.append({"purpose": purpose, "messages": messages})
        return LLMResult(
            text='{"has_completion_signal":true,"completion_target":"面试","has_correction_intent":false,"primary_emotion":"焦虑","secondary_emotion":null,"valence":"vulnerable","is_casual_chat":false,"has_followup_invitation":false,"topics":["面试"],"unfinished_items":["准备面试材料"],"information_density":2.2}',
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


def test_deepseek_gateway_uses_flash_payload_defaults(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="key",
        deepseek_chat_model="deepseek-v4-flash",
        timeout_seconds=1,
        max_retries=0,
    )
    gateway = DeepSeekGateway(settings)

    chat_payload = gateway._payload([{"role": "user", "content": "你好"}], purpose="chat", structured=False)
    structured_payload = gateway._payload([{"role": "system", "content": "只输出 JSON"}], purpose="memory_intent", structured=True)

    assert chat_payload["model"] == "deepseek-v4-flash"
    assert chat_payload["thinking"] == {"type": "disabled"}
    assert chat_payload["temperature"] == 0.7
    assert structured_payload["response_format"] == {"type": "json_object"}
    assert structured_payload["max_tokens"] == 900
    assert "json" in structured_payload["messages"][0]["content"].lower()


def test_deepseek_structured_client_cache_short_circuits_network(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="key",
        deepseek_chat_model="deepseek-v4-flash",
        timeout_seconds=1,
        max_retries=0,
    )
    gateway = DeepSeekGateway(settings)
    messages = [{"role": "system", "content": "只输出 JSON"}, {"role": "user", "content": "返回 {}"}]
    payload = gateway._payload(messages, purpose="memory_intent", structured=True)
    gateway._structured_cache[gateway._structured_cache_key(payload)] = LLMResult(
        text="{}",
        provider="deepseek",
        model="deepseek-v4-flash",
        degraded=False,
        elapsed_ms=10,
        usage={"prompt_cache_hit_tokens": 12},
    )

    result = asyncio.run(gateway.structured(messages, purpose="memory_intent"))

    assert result.text == "{}"
    assert result.usage["client_cache_hit"] is True


def test_memory_params_centralize_tunable_defaults() -> None:
    params = DEFAULT_MEMORY_PARAMS

    assert params.recall.open_item_bonus == 1.18
    assert params.recall.cooldown_penalty == 1.20
    assert params.quality.auto_accept_min_confidence == 0.62
    assert params.maintenance.decay_multiplier == 0.96
    assert params.disclosure.mention_recall_threshold == 4.5


def test_memory_param_profiles_adjust_behavioral_direction() -> None:
    balanced = memory_params_for_profile("balanced")
    cautious = memory_params_for_profile("cautious")
    proactive = memory_params_for_profile("proactive")
    nostalgic = memory_params_for_profile("nostalgic")

    assert cautious.quality.auto_accept_min_confidence > balanced.quality.auto_accept_min_confidence
    assert cautious.disclosure.mention_recall_threshold > balanced.disclosure.mention_recall_threshold
    assert proactive.recall.open_item_bonus > balanced.recall.open_item_bonus
    assert proactive.disclosure.mention_recall_threshold < balanced.disclosure.mention_recall_threshold
    assert nostalgic.maintenance.cooldown_use_threshold > balanced.maintenance.cooldown_use_threshold


def test_memory_params_can_be_overridden_from_file(tmp_path) -> None:
    params_file = tmp_path / "memory_params.json"
    params_file.write_text('{"recall":{"open_item_bonus":0.9},"quality":{"auto_accept_min_confidence":0.7}}', encoding="utf-8")

    params = memory_params_from_file(params_file)

    assert params.recall.open_item_bonus == 0.9
    assert params.quality.auto_accept_min_confidence == 0.7
    assert params.recall.cooldown_penalty == 1.20


def test_memory_params_explain_high_impact_knobs() -> None:
    description = PARAMETER_DESCRIPTIONS["recall.open_item_bonus"]

    assert description["sensitivity"] == "high"
    assert "待跟进" in description["description"]


def test_feedback_signals_detect_followup_engagement_and_corrections() -> None:
    previous_log = {"prompt_manifest": {"followup_mode": "gentle_follow_up", "used_memory_reasons": {"mem_1": "待跟进"}}}
    current_manifest = {"corrected_memory_ids": ["mem_1"], "memory_audit_status": "ok"}

    signals = infer_feedback_signals("材料搞定了，刚交完。", previous_log=previous_log, current_manifest=current_manifest)
    signal_types = {signal["type"] for signal in signals}

    assert "followup_resolved" in signal_types
    assert "memory_correction" in signal_types


def test_feedback_analysis_suggests_parameter_adjustments() -> None:
    report = analyze_feedback(
        [
            {"feedback_signals": [{"type": "followup_topic_shift"}, {"type": "memory_correction"}]},
            {"feedback_signals": [{"type": "followup_topic_shift"}, {"type": "memory_correction"}]},
        ]
    )

    suggestions = {item["parameter"]: item["direction"] for item in report["suggestions"]}
    assert suggestions["recall.open_item_bonus"] == "decrease"
    assert suggestions["quality.auto_accept_min_confidence"] == "increase"

    conservative_report = analyze_feedback(
        [
            {"feedback_signals": [{"type": "confirmation_accepted"}]},
            {"feedback_signals": [{"type": "confirmation_accepted"}]},
            {"feedback_signals": [{"type": "confirmation_accepted"}]},
        ]
    )
    conservative_suggestions = {item["parameter"]: item["direction"] for item in conservative_report["suggestions"]}
    assert conservative_suggestions["quality.auto_accept_min_confidence"] == "decrease"


def test_memory_calibration_cases_pass_current_baseline() -> None:
    cases_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "memory_calibration_cases.json"
    cases = __import__("json").loads(cases_path.read_text(encoding="utf-8"))

    report = evaluate_calibration_cases(cases)

    assert report["score"] == 1.0


def test_semantic_similarity_handles_synonyms_without_token_overlap() -> None:
    assert semantic_similarity("我最近睡不好", "用户最近失眠严重") > 0.2
    assert len(semantic_vector("我最近睡不好")) == DEFAULT_MEMORY_PARAMS.semantic.vector_dimensions


def test_recall_uses_semantic_similarity_when_keywords_do_not_overlap() -> None:
    memory = make_memory("emotion_pattern", "用户最近失眠严重", 0.8, False, "失眠")

    recalled = relevant_memories([memory], "我最近睡不好")

    assert recalled
    assert "语义近似" in recalled[0]["recall_reason"]


def test_extract_explicit_memory() -> None:
    memories = extract_memory_candidates("记住我喜欢安静一点的回复")

    assert memories
    assert memories[0]["type"] == "preference"
    assert memories[0]["is_user_confirmed"] is True


def test_explicit_preference_does_not_absorb_ephemeral_sentence() -> None:
    memories = extract_memory_candidates("记住我喜欢安静一点的回复。今天有点累。")

    assert memories[0]["type"] == "preference"
    assert memories[0]["content"] == "用户喜欢或偏好安静一点的回复"
    assert "今天有点累" not in memories[0]["content"]


def test_rule_based_extractor_marks_source() -> None:
    extractor = RuleBasedMemoryExtractor()
    memories = extractor.extract("记住我喜欢安静一点的回复")

    assert memories
    assert memories[0]["extractor"] == "rule_based"


def test_structured_llm_extractor_maps_json_to_memory() -> None:
    gateway = FakeStructuredGateway()
    extractor = StructuredLLMMemoryExtractor(gateway)
    memories = asyncio.run(extractor.extract_async("我喜欢先被安慰再分析"))

    assert memories
    assert memories[0]["type"] == "preference"
    assert memories[0]["extractor"] == "structured_llm"
    assert memories[0]["content"] == "用户喜欢先被安慰再分析"
    assert "当前日期" in gateway.calls[-1]["messages"][1]["content"]


def test_structured_llm_extractor_falls_back_when_degraded() -> None:
    extractor = StructuredLLMMemoryExtractor(FakeDegradedGateway())
    memories = asyncio.run(extractor.extract_async("记住我喜欢安静一点的回复"))

    assert memories
    assert memories[0]["extractor"] == "structured_llm_fallback"


def test_rule_based_intent_classifier_extracts_high_value_signals() -> None:
    intent = RuleBasedIntentClassifier().classify("材料搞定了，但是我还是有点焦虑")

    assert intent["has_completion_signal"] is True
    assert intent["primary_emotion"] == "压力"
    assert intent["is_casual_chat"] is False


def test_structured_llm_intent_classifier_maps_json() -> None:
    gateway = FakeIntentGateway()
    intent = asyncio.run(StructuredLLMIntentClassifier(gateway).classify_async("明天面试"))

    assert intent["classifier"] == "structured_llm_intent"
    assert intent["completion_target"] == "面试"
    assert intent["topics"] == ["面试"]
    assert "当前日期" in gateway.calls[-1]["messages"][1]["content"]


def test_structured_llm_intent_classifier_falls_back_when_degraded() -> None:
    intent = asyncio.run(StructuredLLMIntentClassifier(FakeDegradedGateway()).classify_async("明天面试有点焦虑"))

    assert intent["classifier"] == "structured_llm_intent_fallback"
    assert intent["primary_emotion"] == "压力"


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


def test_high_density_short_text_is_not_treated_as_casual() -> None:
    assert information_density("我分手了") >= 2.0
    assert not looks_like_casual_chat("我分手了")
    assert looks_like_casual_chat("哈哈哈哈今天真的太搞笑了")


def test_logical_turn_clusters_recent_short_user_fragments() -> None:
    previous = [
        {"id": "u1", "role": "user", "content": "明天", "created_at": "2026-07-02T10:00:00+08:00"},
        {"id": "a1", "role": "assistant", "content": "嗯。", "created_at": "2026-07-02T10:00:01+08:00"},
        {"id": "u2", "role": "user", "content": "面试", "created_at": "2026-07-02T10:00:10+08:00"},
    ]
    current = {"id": "u3", "role": "user", "content": "有点焦虑", "created_at": "2026-07-02T10:00:20+08:00"}

    turn = build_logical_turn(previous, current)

    assert turn["clustered"] is True
    assert turn["message_ids"] == ["u1", "u2", "u3"]
    assert turn["text"] == "明天 面试 有点焦虑"


def test_logical_turn_does_not_cluster_stale_fragments() -> None:
    previous = [{"id": "u1", "role": "user", "content": "明天", "created_at": "2026-07-02T10:00:00+08:00"}]
    current = {"id": "u2", "role": "user", "content": "面试", "created_at": "2026-07-02T10:02:30+08:00"}

    turn = build_logical_turn(previous, current)

    assert turn["clustered"] is False
    assert turn["message_ids"] == ["u2"]


def test_short_high_density_event_extracts_episodic_memory() -> None:
    memories = extract_memory_candidates("我分手了")

    assert any(memory["type"] == "emotion_pattern" for memory in memories)
    assert any(memory["type"] == "episodic" for memory in memories)


def test_semantic_completion_words_close_open_loop() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("明天下午我要交材料，现在有点焦虑。"))

    closed = close_resolved_open_loops(memories, "材料搞定了，收工。")

    assert closed
    assert closed[0]["open"] is False


def test_expanded_completion_words_close_open_loop() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("明天中午要汇报材料。"))

    closed = close_resolved_open_loops(memories, "材料处理好了，一身轻松。")

    assert closed
    assert closed[0]["open"] is False


def test_expanded_task_words_extract_goal() -> None:
    memories = extract_memory_candidates("后天上午要答辩，还得复习。")

    assert any(memory["type"] == "goal" and memory.get("due_at") for memory in memories)


def test_short_new_slang_emotion_is_high_density() -> None:
    memories = extract_memory_candidates("心态炸了")

    assert any(memory["type"] == "emotion_pattern" for memory in memories)
    assert not looks_like_casual_chat("心态炸了")


def test_long_shared_experience_is_not_dropped_by_length() -> None:
    text = "我们约定下次继续把项目拆成小任务，然后每次只检查一个最卡住的地方，不要一下子铺开太多细节，避免我压力太大。"

    memories = extract_memory_candidates(text)

    assert any(memory["type"] == "shared_experience" for memory in memories)


def test_memory_upsert_merges_similar_preferences() -> None:
    existing = []
    upsert_memories(existing, extract_memory_candidates("记住我喜欢安静一点的回复"))
    upsert_memories(existing, extract_memory_candidates("我喜欢安静一点的回复方式"))

    preferences = [memory for memory in existing if memory["type"] == "preference"]
    assert len(preferences) == 1
    assert preferences[0]["confidence"] > 0.9


def test_memory_tidy_archives_duplicate_fact_and_normalizes_rules() -> None:
    memories = [
        make_memory("fact", "我喜欢安静一点的回复。今天有点累", 0.9, True, "old"),
        make_memory("preference", "用户喜欢安静一点的回复。今天有点累；用户喜欢或偏好安静一点的回复", 0.8, True, "old"),
        make_memory("preference", "用户喜欢或偏好你先安慰我", 0.8, True, "old"),
        make_memory("response_rule", "和用户互动时上来就讲大道理，我更希望你先安慰我", 0.8, True, "old"),
        make_memory("response_rule", "别上来就讲大道理，我更希望你先安慰我", 0.8, True, "old"),
        make_memory("emotion_pattern", "用户在类似情境相关情境中容易感到烦躁", 0.7, False, "old"),
    ]

    report = tidy_memories(memories)
    active = [memory for memory in memories if memory["status"] == "active"]

    assert any(item["type"] == "fact" for item in report["archived"])
    assert len([memory for memory in active if memory["type"] == "response_rule"]) == 1
    assert any(memory["content"] == "用户喜欢安静一点的回复" for memory in active)
    assert not any(memory["content"] == "用户喜欢或偏好你先安慰我" for memory in active)
    assert not any(memory["content"] == "用户在当前情境中容易感到烦躁" for memory in active)


def test_memory_context_prioritizes_open_and_emotional_recall() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("以后别上来就讲大道理，明天下午我要交材料，我现在因为项目有点焦虑。"))
    context = build_memory_context(memories, "我还是有点焦虑，那个材料怎么办")

    recalled_types = {memory["type"] for memory in context["recalled"]}
    assert "goal" in recalled_types
    assert "emotion_pattern" in recalled_types
    assert "待跟进" in context["prompt_text"]


def test_elapsed_open_loop_can_be_followed_up_during_casual_chat() -> None:
    memory = make_memory("goal", "待跟进：明天中午要汇报材料", 0.8, False, "明天中午要汇报材料", open_item=True)
    memory["created_at"] = "2026-07-01T10:00:00+08:00"
    memory["evidence"][0]["created_at"] = "2026-07-01T10:00:00+08:00"

    context = build_memory_context([memory], "下午好呀", now="2026-07-02T15:30:00+08:00")

    assert context["followup_plan"]["mode"] == "elapsed_casual_follow_up"
    assert context["followup_plan"]["items"][0]["time_state"] == "elapsed"
    assert "time_state=elapsed" in context["prompt_text"]


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


def test_user_can_delete_memory_with_expanded_phrasing() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("记住我喜欢安静一点的回复"))

    result = apply_user_corrections(memories, "这条不用记，我喜欢安静一点的回复")

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


def test_high_density_short_chat_can_surface_relevant_tone_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("我现在因为项目有点焦虑。"))

    context = build_memory_context(memories, "emo了")

    assert context["disclosure_plan"]["mode"] == "tone_only"


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
    assert result["intent"]["classifier"] == "rule_based_intent"
    assert result["new_memories"]
    assert service.messages()[-1]["role"] == "assistant"
    assert service.status()["layers"]["persona"]["count"] == 1
    assert service.status()["profile"]["preferences"]
    logs = service.store.snapshot()["generation_logs"]
    assert "当前真实时间" in logs[-1]["api_messages"][0]["content"]
    assert logs[-1]["prompt_manifest"]["time_context"]["date"]
    assert logs[-1]["prompt_manifest"]["api_message_count"] == len(logs[-1]["api_messages"])
    assert logs[-1]["prompt_manifest"]["work_memory_count"] == len(logs[-1]["api_messages"]) - 3


def test_chat_service_degraded_flow_with_sqlite_backend(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
        storage_backend="sqlite",
    )
    service = ChatService(create_store(settings), DeepSeekGateway(settings))

    result = asyncio.run(service.chat("记住我喜欢安静一点的回复"))

    assert result["degraded"] is True
    assert service.memories()
    assert (tmp_path / "store.sqlite3").exists()


def test_chat_service_injects_session_summaries_into_prompt(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    def seed_summary(state):
        session = state["sessions"][state["active_session_id"]]
        session["summaries"] = [
            {
                "id": "summary_1",
                "message_count": 16,
                "summary": "近期话题：项目。最近用户提到：项目材料推进卡住了",
                "follow_up_suggestion": "下次可自然问一句：项目材料后来怎么样了。",
            }
        ]
        return None

    service.store.mutate(seed_summary)
    asyncio.run(service.chat("继续刚才那个"))

    latest_log = service.store.snapshot()["generation_logs"][-1]
    dynamic_system = latest_log["api_messages"][1]["content"]
    assert "会话摘要" in dynamic_system
    assert "项目材料推进卡住了" in dynamic_system
    assert latest_log["prompt_manifest"]["used_session_summary_ids"] == ["summary_1"]
    assert latest_log["prompt_manifest"]["api_message_count"] == len(latest_log["api_messages"])


def test_chat_service_records_feedback_signals(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    asyncio.run(service.chat("明天下午我要交材料，现在有点焦虑。"))
    asyncio.run(service.chat("材料搞定了，收工。"))

    logs = service.store.snapshot()["generation_logs"]
    assert logs[-1]["prompt_manifest"]["intent"]["classifier"] == "rule_based_intent"
    assert any(log.get("feedback_signals") for log in logs)


def test_chat_service_uses_logical_turn_for_memory_extraction(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    asyncio.run(service.chat("明天"))
    asyncio.run(service.chat("面试"))
    result = asyncio.run(service.chat("有点焦虑"))

    assert result["logical_turn"]["clustered"] is True
    assert "明天 面试 有点焦虑" == result["logical_turn"]["text"]
    assert any(memory["type"] == "goal" for memory in service.memories())
    assert any(memory["type"] == "emotion_pattern" for memory in service.memories())


def test_sqlite_store_implements_snapshot_mutate_and_search(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
        storage_backend="sqlite",
    )
    store = SqliteStore(settings)

    def mutate(state):
        state.setdefault("memories", []).append(make_memory("emotion_pattern", "用户在项目相关情境中容易焦虑", 0.8, False, "项目焦虑"))
        return "ok"

    assert store.mutate(mutate) == "ok"
    assert store.snapshot()["memories"]
    assert store.search_memories("焦虑")
    assert store.search_memories_semantic("项目压力")

    with store._connect() as db:
        embedding_count = db.execute("SELECT COUNT(*) AS count FROM memory_embeddings").fetchone()["count"]
    assert embedding_count == 1


def test_create_store_uses_configured_backend(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
        storage_backend="sqlite",
    )

    assert isinstance(create_store(settings), SqliteStore)


def test_migrate_json_to_sqlite_keeps_json_backup_and_imports_state(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    json_store = JsonStore(settings)
    json_store.mutate(lambda state: state.setdefault("memories", []).append(make_memory("preference", "用户喜欢安静一点的回复", 0.9, True, "记住")) or state)

    sqlite_path = migrate_json_to_sqlite(settings)
    sqlite_store = SqliteStore(settings)

    assert sqlite_path.exists()
    assert (tmp_path / "store.json").exists()
    assert sqlite_store.snapshot()["memories"][0]["content"] == "用户喜欢安静一点的回复"


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
    logs = service.store.snapshot()["generation_logs"]
    assert logs[-1]["feedback_signals"][0]["type"] == "confirmation_accepted"


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


def test_work_memory_window_is_dynamic() -> None:
    messages = [{"role": "user", "content": f"第{index}轮普通聊天"} for index in range(40)]

    assert len(work_memory(messages, "早")) == 8
    assert len(work_memory(messages, "我现在因为项目很焦虑，继续上次")) == 36


def test_casual_work_memory_stays_short_after_recent_emotion() -> None:
    messages = [{"role": "user", "content": f"第{index}轮普通聊天"} for index in range(32)]
    messages.extend(
        [
            {"role": "user", "content": "刚才有点焦虑"},
            {"role": "assistant", "content": "我陪你慢慢捋。"},
        ]
    )

    assert len(work_memory(messages, "晚上好")) == 8


def test_topic_shift_can_trigger_summary_before_fixed_interval() -> None:
    messages = [
        {"role": "user", "content": "项目推进有点卡"},
        {"role": "assistant", "content": "先拆一下。"},
        {"role": "user", "content": "项目材料还没整理"},
        {"role": "assistant", "content": "我们列清单。"},
        {"role": "user", "content": "项目今天继续做"},
        {"role": "assistant", "content": "可以。"},
        {"role": "user", "content": "明天面试有点紧张"},
        {"role": "assistant", "content": "先稳住。"},
        {"role": "user", "content": "面试还要准备自我介绍"},
        {"role": "assistant", "content": "我们先写一版。"},
    ]

    assert should_build_session_summary(messages, []) is True


def test_topic_shift_summary_covers_previous_topic_only() -> None:
    messages = [
        {"role": "user", "content": "项目推进有点卡"},
        {"role": "assistant", "content": "先拆一下。"},
        {"role": "user", "content": "项目材料还没整理"},
        {"role": "assistant", "content": "我们列清单。"},
        {"role": "user", "content": "项目今天继续做"},
        {"role": "assistant", "content": "可以。"},
        {"role": "user", "content": "明天面试有点紧张"},
        {"role": "assistant", "content": "先稳住。"},
        {"role": "user", "content": "面试还要准备自我介绍"},
        {"role": "assistant", "content": "我们先写一版。"},
    ]

    summary = build_session_summary(messages)

    assert summary is not None
    assert "项目材料还没整理" in summary["summary"]
    assert "面试还要准备自我介绍" not in summary["summary"]
    assert summary["message_count"] == 6
    assert summary["covered_message_count"] == 6


def test_summary_after_existing_summary_starts_from_last_boundary() -> None:
    messages = []
    for index in range(8):
        messages.extend(
            [
                {"role": "user", "content": f"学习计划第{index}步"},
                {"role": "assistant", "content": "继续。"},
            ]
        )
    messages.extend(
        [
            {"role": "user", "content": "项目材料有点卡"},
            {"role": "assistant", "content": "先拆。"},
            {"role": "user", "content": "项目今天继续推进"},
            {"role": "assistant", "content": "好。"},
            {"role": "user", "content": "明天面试有点紧张"},
            {"role": "assistant", "content": "先稳住。"},
            {"role": "user", "content": "面试还要准备自我介绍"},
            {"role": "assistant", "content": "我们写一版。"},
        ]
    )

    summary = build_session_summary(messages, after_message_count=16)

    assert summary is not None
    assert "学习计划" not in summary["summary"]
    assert "项目今天继续推进" in summary["summary"]
    assert "面试还要准备自我介绍" not in summary["summary"]
    assert summary["message_count"] == 20


def test_topic_shift_trigger_ignores_already_summarized_history() -> None:
    messages = [
        {"role": "user", "content": "项目推进有点卡"},
        {"role": "assistant", "content": "先拆一下。"},
        {"role": "user", "content": "项目材料还没整理"},
        {"role": "assistant", "content": "我们列清单。"},
        {"role": "user", "content": "明天面试有点紧张"},
        {"role": "assistant", "content": "先稳住。"},
        {"role": "user", "content": "面试还要准备自我介绍"},
        {"role": "assistant", "content": "我们先写一版。"},
        {"role": "user", "content": "面试简历再改一下"},
        {"role": "assistant", "content": "可以。"},
        {"role": "user", "content": "面试问题再练一遍"},
        {"role": "assistant", "content": "来。"},
    ]
    summaries = [{"message_count": 8}]

    assert should_build_session_summary(messages, summaries) is False


def test_same_topic_does_not_create_fixed_interval_summary() -> None:
    messages = []
    for index in range(16):
        messages.extend(
            [
                {"role": "user", "content": f"项目材料继续推进第{index}步"},
                {"role": "assistant", "content": "继续拆小步。"},
            ]
        )
    summaries = [{"message_count": 16}]

    assert should_build_session_summary(messages, summaries) is False


def test_summary_has_long_interval_backstop() -> None:
    messages = []
    for index in range(40):
        messages.extend(
            [
                {"role": "user", "content": f"项目材料继续推进第{index}步"},
                {"role": "assistant", "content": "继续拆小步。"},
            ]
        )
    summaries = [{"message_count": 16}]

    assert should_build_session_summary(messages, summaries) is True


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
