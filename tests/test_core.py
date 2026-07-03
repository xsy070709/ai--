from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

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
    parameter_metadata,
    relevant_memories,
    review_memory_candidates,
    tidy_memories,
    upsert_memories,
)
from app.memory.text import unfinished_items
from app.memory.text import emotion_cause, topics_from_text
from app.memory.initiative import build_disclosure_plan
from app.memory.schema import make_memory
from app.memory.semantic import semantic_similarity, semantic_vector
from app.memory.signals import has_followup_invitation, information_density, looks_like_casual_chat
from app.memory.summary import should_build_session_summary, work_memory
from app.memory.time_reasoning import annotate_time_state, infer_deadline
from app.persona import initialize_persona
from app.storage import JsonStore, SqliteStore, create_store, migrate_json_to_sqlite
from scripts.evaluate_memory_calibration import exit_code_for_report


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
            text='{"has_completion_signal":true,"completion_target":"面试","has_correction_intent":true,"correction_action":"correct","correction_query":"旧面试时间","correction_new_value":"周五下午面试","primary_emotion":"焦虑","secondary_emotion":null,"valence":"vulnerable","is_casual_chat":false,"has_followup_invitation":false,"topics":["面试"],"unfinished_items":["准备面试材料"],"information_density":2.2}',
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
    assert description["range"] == [0.5, 2.0]


def test_memory_parameter_metadata_includes_current_values() -> None:
    metadata = parameter_metadata()

    assert metadata["recall.open_item_bonus"]["value"] == DEFAULT_MEMORY_PARAMS.recall.open_item_bonus
    assert metadata["maintenance.cooldown_use_threshold"]["value"] == DEFAULT_MEMORY_PARAMS.maintenance.cooldown_use_threshold
    assert metadata["disclosure.mention_recall_threshold"]["range"] == [3.0, 6.0]


def test_feedback_signals_detect_followup_engagement_and_corrections() -> None:
    previous_log = {"prompt_manifest": {"followup_mode": "gentle_follow_up", "used_memory_reasons": {"mem_1": "待跟进"}}}
    current_manifest = {"corrected_memory_ids": ["mem_1"], "memory_audit_status": "ok"}

    signals = infer_feedback_signals("材料搞定了，刚交完。", previous_log=previous_log, current_manifest=current_manifest)
    signal_types = {signal["type"] for signal in signals}

    assert "followup_resolved" in signal_types
    assert "memory_correction" in signal_types


def test_feedback_signals_use_intent_completion() -> None:
    previous_log = {"prompt_manifest": {"followup_mode": "gentle_follow_up", "used_memory_reasons": {"mem_1": "待跟进"}}}
    current_manifest = {"intent": {"has_completion_signal": True, "information_density": 0.0}}

    signals = infer_feedback_signals("材料递上去了", previous_log=previous_log, current_manifest=current_manifest)
    signal_types = {signal["type"] for signal in signals}

    assert "followup_resolved" in signal_types


def test_feedback_signals_use_intent_invitation_and_density() -> None:
    previous_log = {"prompt_manifest": {"disclosure_mode": "can_mention", "used_memory_reasons": {"mem_1": "语义近似"}}}
    current_manifest = {
        "intent": {
            "has_followup_invitation": True,
            "is_casual_chat": True,
            "information_density": 2.3,
        }
    }

    signals = infer_feedback_signals("那个", previous_log=previous_log, current_manifest=current_manifest)
    signal_types = {signal["type"] for signal in signals}

    assert "user_invited_recall" in signal_types
    assert "disclosure_engaged" in signal_types
    assert "disclosure_not_engaged" not in signal_types


def test_feedback_signals_use_configured_invitation_words() -> None:
    signals = infer_feedback_signals("刚才说那个后来呢", current_manifest={})

    assert has_followup_invitation("刚才说那个后来呢")
    assert {signal["type"] for signal in signals} == {"user_invited_recall"}


def test_feedback_signals_emit_confirmation_results() -> None:
    accepted = infer_feedback_signals("", current_manifest={"confirmation_id": "conf_1", "accepted": True})
    rejected = infer_feedback_signals("", current_manifest={"confirmation_id": "conf_2", "accepted": False})

    assert {signal["type"] for signal in accepted} == {"confirmation_accepted"}
    assert {signal["type"] for signal in rejected} == {"confirmation_rejected"}
    assert accepted[0]["parameters"] == ["quality.auto_accept_min_confidence"]
    assert rejected[0]["parameters"] == ["quality.auto_accept_min_confidence"]


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
    assert report["parameter_evidence"]["recall.open_item_bonus"]["negative"] == 2
    assert report["parameter_evidence"]["quality.auto_accept_min_confidence"]["negative"] == 2
    assert report["parameter_evidence"]["recall.cooldown_penalty"]["signals"]["followup_topic_shift"] == 2
    assert report["parameter_metadata"]["recall.open_item_bonus"]["value"] == DEFAULT_MEMORY_PARAMS.recall.open_item_bonus
    assert "effect_of_increasing" in report["parameter_metadata"]["recall.cooldown_penalty"]

    conservative_report = analyze_feedback(
        [
            {"feedback_signals": [{"type": "confirmation_accepted"}]},
            {"feedback_signals": [{"type": "confirmation_accepted"}]},
            {"feedback_signals": [{"type": "confirmation_accepted"}]},
        ]
    )
    conservative_suggestions = {item["parameter"]: item["direction"] for item in conservative_report["suggestions"]}
    assert conservative_suggestions["quality.auto_accept_min_confidence"] == "decrease"
    assert conservative_report["parameter_evidence"]["quality.auto_accept_min_confidence"]["positive"] == 3


def test_memory_calibration_cases_pass_current_baseline() -> None:
    cases_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "memory_calibration_cases.json"
    cases = __import__("json").loads(cases_path.read_text(encoding="utf-8"))

    report = evaluate_calibration_cases(cases)

    assert report["score"] == 1.0


def test_memory_calibration_exit_code_tracks_failures() -> None:
    assert exit_code_for_report({"total": 2, "passed": 2}) == 0
    assert exit_code_for_report({"total": 2, "passed": 1}) == 1


def test_calibration_cases_can_check_followup_and_feedback() -> None:
    report = evaluate_calibration_cases(
        [
            {
                "name": "intent completion",
                "seed_memories": ["明天下午我要交材料，现在有点焦虑。"],
                "user_text": "材料递上去了",
                "intent": {"has_completion_signal": True, "is_casual_chat": False, "information_density": 2.2},
                "expected_followup_mode": "acknowledge_closure",
                "previous_log": {"prompt_manifest": {"followup_mode": "gentle_follow_up", "used_memory_reasons": {"mem_1": "待跟进"}}},
                "expected_feedback_signals": ["followup_resolved"],
            }
        ]
    )

    assert report["score"] == 1.0
    assert report["results"][0]["checks"]["followup_mode"] is True
    assert report["results"][0]["checks"]["feedback_signals"] is True


def test_calibration_cases_can_check_memory_audit() -> None:
    report = evaluate_calibration_cases(
        [
            {
                "name": "over explicit boundary",
                "seed_memories": ["以后不要提家里的事。"],
                "user_text": "家里的事我不想聊",
                "assistant_reply": "我知道你不想提家里的事，所以我不说。",
                "expected_audit_status": "fail",
                "expected_audit_issues": ["forbidden_memory_surface"],
                "expected_feedback_signals": ["memory_surface_issue"],
            }
        ]
    )

    result = report["results"][0]
    assert report["score"] == 1.0
    assert result["checks"]["memory_audit_status"] is True
    assert result["checks"]["memory_audit_issues"] is True
    assert result["checks"]["feedback_signals"] is True


def test_calibration_cases_can_check_absent_outputs() -> None:
    report = evaluate_calibration_cases(
        [
            {
                "name": "casual shift should not engage followup",
                "user_text": "哈哈哈",
                "previous_log": {"prompt_manifest": {"followup_mode": "gentle_follow_up", "used_memory_reasons": {"mem_1": "待跟进：材料"}}},
                "expected_feedback_signals": ["followup_topic_shift"],
                "unexpected_feedback_signals": ["followup_engaged"],
                "unexpected_memory_types": ["goal"],
            },
            {
                "name": "negative guard fails when forbidden signal appears",
                "user_text": "哈哈哈",
                "previous_log": {"prompt_manifest": {"followup_mode": "gentle_follow_up", "used_memory_reasons": {"mem_1": "待跟进：材料"}}},
                "unexpected_feedback_signals": ["followup_topic_shift"],
            },
        ]
    )

    assert report["results"][0]["passed"] is True
    assert report["results"][0]["checks"]["unexpected_feedback_signals"] is True
    assert report["results"][1]["passed"] is False
    assert report["results"][1]["checks"]["unexpected_feedback_signals"] is False


def test_calibration_cases_can_check_correction_results() -> None:
    report = evaluate_calibration_cases(
        [
            {
                "name": "paraphrased correction mutates memory",
                "seed_memories": ["明天周三下午要面试。"],
                "user_text": "不是周三，是周五下午面试",
                "expected_corrected_contains": ["周三"],
                "expected_created_memory_types": ["goal"],
            },
            {
                "name": "delete correction mutates memory",
                "seed_memories": ["记住我喜欢深夜复盘"],
                "user_text": "这条别存了，深夜复盘那个",
                "intent": {
                    "has_correction_intent": True,
                    "correction_action": "delete",
                    "correction_query": "深夜复盘",
                },
                "expected_deleted_contains": ["深夜复盘"],
                "unexpected_created_memory_types": ["goal"],
            },
        ]
    )

    assert report["score"] == 1.0
    assert report["results"][0]["checks"]["corrected_memories"] is True
    assert report["results"][0]["checks"]["created_memory_types"] is True
    assert report["results"][1]["checks"]["deleted_memories"] is True
    assert report["results"][1]["checks"]["unexpected_created_memory_types"] is True


def test_semantic_similarity_handles_synonyms_without_token_overlap() -> None:
    assert semantic_similarity("我最近睡不好", "用户最近失眠严重") > 0.2
    assert semantic_similarity("秋招自我介绍还没准备好", "明天面试要准备简历") > 0.2
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


def test_rule_based_intent_reports_actual_information_density() -> None:
    intent = RuleBasedIntentClassifier().classify("7/8 15:00要面试")

    assert 0 < intent["information_density"] < DEFAULT_MEMORY_PARAMS.conversation.high_density_threshold
    assert intent["unfinished_items"]


def test_rule_based_intent_uses_configured_invitation_words() -> None:
    intent = RuleBasedIntentClassifier().classify("刚才说那个后来呢")

    assert intent["has_followup_invitation"] is True


def test_rule_based_intent_uses_configured_completion_targets() -> None:
    intent = RuleBasedIntentClassifier().classify("汇报搞定了，终于收工")

    assert intent["completion_target"] == "汇报"


def test_rule_based_intent_handles_expanded_completion_and_deletion_phrases() -> None:
    completion = RuleBasedIntentClassifier().classify("材料忙完了，终于搞完")
    deletion = RuleBasedIntentClassifier().classify("这条不用存，深夜复盘那个")

    assert completion["has_completion_signal"] is True
    assert completion["completion_target"] == "材料"
    assert deletion["has_correction_intent"] is True
    assert deletion["correction_action"] == "delete"


def test_rule_based_intent_extracts_comma_correction_new_value() -> None:
    intent = RuleBasedIntentClassifier().classify("不是周三，是周五下午面试")

    assert intent["correction_query"] == "周三"
    assert intent["correction_new_value"] == "周五下午面试"


def test_topics_use_configured_topic_words() -> None:
    intent = RuleBasedIntentClassifier().classify("实习答辩材料还没准备好")

    assert "实习" in topics_from_text("实习答辩材料还没准备好")
    assert "答辩" in intent["topics"]
    assert emotion_cause("实习压力有点大") == "实习"


def test_topics_use_configured_alias_words() -> None:
    intent = RuleBasedIntentClassifier().classify("秋招自我介绍还没准备好")

    assert "面试" in topics_from_text("秋招自我介绍还没准备好")
    assert "面试" in intent["topics"]
    assert emotion_cause("毕设压力有点大") == "论文"


def test_structured_llm_intent_classifier_maps_json() -> None:
    gateway = FakeIntentGateway()
    intent = asyncio.run(StructuredLLMIntentClassifier(gateway).classify_async("明天面试"))

    assert intent["classifier"] == "structured_llm_intent"
    assert intent["completion_target"] == "面试"
    assert intent["correction_action"] == "correct"
    assert intent["correction_query"] == "旧面试时间"
    assert intent["correction_new_value"] == "周五下午面试"
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


def test_slang_and_mixed_language_emotions_are_not_treated_as_casual() -> None:
    assert information_density("我摆烂了") >= 2.0
    assert not looks_like_casual_chat("我摆烂了")
    assert not looks_like_casual_chat("今天 very anxious")
    assert any(memory["type"] == "emotion_pattern" for memory in extract_memory_candidates("我摆烂了"))
    assert any(memory["type"] == "emotion_pattern" for memory in extract_memory_candidates("今天 very anxious"))


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


def test_logical_turn_handles_mixed_naive_and_aware_timestamps() -> None:
    previous = [{"id": "u1", "role": "user", "content": "明天", "created_at": "2026-07-02T10:00:00"}]
    current = {"id": "u2", "role": "user", "content": "面试", "created_at": "2026-07-02T10:00:20+08:00"}

    turn = build_logical_turn(previous, current)

    assert turn["clustered"] is True
    assert turn["message_ids"] == ["u1", "u2"]


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


def test_intent_completion_signal_closes_open_loop() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("明天下午我要交材料，现在有点焦虑。"))

    closed = close_resolved_open_loops(memories, "材料递上去了，松口气。", intent={"has_completion_signal": True})

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


def test_numeric_date_task_extracts_goal() -> None:
    memories = extract_memory_candidates("7/8 15:00要面试，今晚得准备自我介绍。")

    assert any(memory["type"] == "goal" and memory.get("due_at") for memory in memories)
    assert unfinished_items("7/8 15:00要面试，今晚得准备自我介绍。")


def test_time_reasoning_ignores_invalid_numeric_dates() -> None:
    deadline = infer_deadline("2/30要交材料", datetime(2026, 1, 1, 9, 0))

    assert deadline is None


def test_time_reasoning_falls_back_to_day_month_numeric_dates() -> None:
    deadline = infer_deadline("13/1要交材料", datetime(2026, 1, 1, 9, 0))

    assert deadline
    assert deadline["due_at"].startswith("2026-01-13")


def test_time_reasoning_handles_naive_datetimes_consistently() -> None:
    memory = {
        "type": "goal",
        "content": "待跟进：今天下午要交材料",
        "created_at": datetime(2026, 1, 1, 9, 0).isoformat(),
    }

    annotated = annotate_time_state(memory, now=datetime(2026, 1, 1, 20, 0))

    assert annotated["time_state"] == "elapsed"


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


def test_intent_delete_correction_removes_matching_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("记住我喜欢深夜复盘"))

    result = apply_user_corrections(
        memories,
        "这条不用保留",
        intent={"has_correction_intent": True, "correction_action": "delete", "correction_query": "深夜复盘"},
    )

    assert result["deleted"]
    assert result["deleted"][0]["status"] == "deleted_by_user"


def test_intent_correct_correction_replaces_matching_memory() -> None:
    memories = []
    upsert_memories(memories, extract_memory_candidates("记住我喜欢深夜复盘"))

    result = apply_user_corrections(
        memories,
        "我刚才说法不准确",
        intent={
            "has_correction_intent": True,
            "correction_action": "correct",
            "correction_query": "深夜复盘",
            "correction_new_value": "我喜欢早上复盘",
        },
    )

    assert result["corrected"]
    assert result["corrected"][0]["status"] == "corrected"
    assert result["created"]
    assert "早上复盘" in result["created"][0]["content"]


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


def test_memory_context_respects_empty_recall_candidates() -> None:
    memory = make_memory("emotion_pattern", "用户最近失眠严重", 0.8, False, "睡眠")

    context = build_memory_context([memory], "我最近睡不好", recall_memories=[])

    assert not context["recalled"]
    assert context["profile"]["emotion_patterns"]


def test_memory_context_uses_intent_to_override_casual_followup() -> None:
    memory = make_memory("goal", "待跟进：整理项目材料", 0.8, False, "整理项目材料", open_item=True)
    memory["recall_score"] = 4.8
    intent = {
        "is_casual_chat": False,
        "has_followup_invitation": False,
        "has_completion_signal": False,
        "has_correction_intent": False,
        "information_density": 2.2,
    }

    context = build_memory_context([memory], "还行", intent=intent)

    assert context["followup_plan"]["mode"] == "gentle_follow_up"


def test_memory_context_uses_intent_completion_for_closure_plan() -> None:
    memory = make_memory("goal", "待跟进：整理项目材料", 0.8, False, "整理项目材料", open_item=True)
    intent = {
        "is_casual_chat": False,
        "has_followup_invitation": False,
        "has_completion_signal": True,
        "has_correction_intent": False,
        "information_density": 2.4,
    }

    context = build_memory_context([memory], "材料递上去了", intent=intent)

    assert context["followup_plan"]["mode"] == "acknowledge_closure"


def test_memory_context_uses_intent_followup_invitation() -> None:
    memory = make_memory("goal", "待跟进：准备面试自我介绍", 0.8, False, "准备面试自我介绍", open_item=True)
    memory["recall_score"] = 4.8
    intent = {
        "is_casual_chat": True,
        "has_followup_invitation": True,
        "has_completion_signal": False,
        "has_correction_intent": False,
        "information_density": 0.2,
    }

    context = build_memory_context([memory], "那个", intent=intent)
    disclosure = build_disclosure_plan([memory], "那个", {"mode": "user_invited_follow_up"}, intent=intent)

    assert context["followup_plan"]["mode"] == "gentle_follow_up"
    assert disclosure["mode"] == "can_mention"


def test_elapsed_open_loop_stays_quiet_during_low_density_casual_chat() -> None:
    memory = make_memory("goal", "待跟进：明天中午要汇报材料", 0.8, False, "明天中午要汇报材料", open_item=True)
    memory["created_at"] = "2026-07-01T10:00:00+08:00"
    memory["evidence"][0]["created_at"] = "2026-07-01T10:00:00+08:00"

    context = build_memory_context([memory], "下午好呀", now="2026-07-02T15:30:00+08:00")

    assert context["followup_plan"]["mode"] == "none"
    assert "不要主动翻旧账" in context["prompt_text"]


def test_elapsed_open_loop_can_be_followed_up_when_user_invites_old_topic() -> None:
    memory = make_memory("goal", "待跟进：明天中午要汇报材料", 0.8, False, "明天中午要汇报材料", open_item=True)
    memory["created_at"] = "2026-07-01T10:00:00+08:00"
    memory["evidence"][0]["created_at"] = "2026-07-01T10:00:00+08:00"

    context = build_memory_context([memory], "继续上次那个汇报", now="2026-07-02T15:30:00+08:00")

    assert context["followup_plan"]["mode"] == "elapsed_follow_up"
    assert context["followup_plan"]["items"][0]["time_state"] == "elapsed"


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


def test_memory_audit_uses_configured_surface_anchors() -> None:
    context = {
        "disclosure_plan": {
            "mode": "quiet",
            "items": [
                {
                    "memory_id": "m1",
                    "type": "boundary",
                    "action": "silent",
                    "content": "用户不想聊实习压力",
                }
            ],
        },
        "followup_plan": {"mode": "none"},
    }

    audit = audit_memory_use("我知道你不想聊实习，这个我不提。", context)

    assert audit["status"] == "fail"


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


def test_memory_audit_warns_when_tone_memory_uses_pattern_label() -> None:
    memory = make_memory("emotion_pattern", "用户在项目相关情境中容易感到压力", 0.8, False, "用户说项目焦虑")
    context = {
        "disclosure_plan": {
            "mode": "tone_only",
            "items": [{"memory_id": memory["id"], "type": "emotion_pattern", "action": "hint", "content": memory["content"]}],
        },
        "followup_plan": {"mode": "none"},
    }

    audit = audit_memory_use("你的模式是项目一受阻就容易压力上来，我们先拆一步。", context)

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
    assert "当前真实时间" in logs[-1]["api_messages"][3]["content"]
    assert logs[-1]["prompt_manifest"]["time_context"]["date"]
    assert logs[-1]["prompt_manifest"]["api_message_count"] == len(logs[-1]["api_messages"])
    assert logs[-1]["prompt_manifest"]["prompt_segments"][0]["name"] == "stable_persona"
    assert logs[-1]["prompt_manifest"]["prompt_segments"][1]["name"] == "session_summaries"
    assert logs[-1]["prompt_manifest"]["prompt_segments"][3]["name"] == "time_context"
    assert logs[-1]["prompt_manifest"]["work_memory_count"] == len(logs[-1]["api_messages"]) - 5


def test_chat_service_falls_back_when_intent_classifier_raises(tmp_path) -> None:
    class FailingIntentClassifier:
        name = "failing_intent"

        async def classify_async(self, user_text, context=None):
            raise RuntimeError("intent boom")

    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))
    service.intent_classifier = FailingIntentClassifier()

    result = asyncio.run(service.chat("记住我喜欢安静一点的回复"))

    latest_log = service.store.snapshot()["generation_logs"][-1]
    assert result["reply"]
    assert result["intent"]["classifier"] == "rule_based_intent_exception_fallback"
    assert "intent boom" in result["intent"]["classifier_error"]
    assert latest_log["prompt_manifest"]["intent_classifier"] == "rule_based_intent_exception_fallback"
    assert "intent boom" in latest_log["prompt_manifest"]["intent_classifier_error"]


def test_chat_service_keeps_reply_when_memory_extractor_raises(tmp_path) -> None:
    class FailingMemoryExtractor:
        name = "failing_extractor"

        async def extract_async(self, user_text, assistant_text="", context=None):
            raise RuntimeError("extract boom")

    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))
    service.memory_extractor = FailingMemoryExtractor()

    result = asyncio.run(service.chat("记住我喜欢安静一点的回复"))

    latest_log = service.store.snapshot()["generation_logs"][-1]
    assert result["reply"]
    assert result["new_memories"] == []
    assert service.messages()[-1]["role"] == "assistant"
    assert latest_log["prompt_manifest"]["memory_extractor"] == "failing_extractor"
    assert "extract boom" in latest_log["prompt_manifest"]["memory_extraction_error"]


def test_chat_service_falls_back_when_memory_factories_raise(tmp_path, monkeypatch) -> None:
    def raise_extractor(settings, gateway):
        raise RuntimeError("extractor init boom")

    def raise_classifier(settings, gateway):
        raise RuntimeError("classifier init boom")

    monkeypatch.setattr("app.chat_service.choose_extractor", raise_extractor)
    monkeypatch.setattr("app.chat_service.choose_intent_classifier", raise_classifier)
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )

    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))
    result = asyncio.run(service.chat("记住我喜欢安静一点的回复"))

    latest_log = service.store.snapshot()["generation_logs"][-1]
    assert result["reply"]
    assert result["intent"]["classifier"] == "rule_based_intent"
    assert latest_log["prompt_manifest"]["memory_extractor"] == "rule_based"
    assert "extractor init boom" in latest_log["prompt_manifest"]["memory_extractor_init_error"]
    assert "classifier init boom" in latest_log["prompt_manifest"]["intent_classifier_init_error"]


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


def test_chat_service_memories_uses_projection_interface(tmp_path) -> None:
    class ProjectionOnlyStore(JsonStore):
        def snapshot(self):
            raise AssertionError("memories should use list_memories, not snapshot")

        def list_memories(self, status: str | None = None):
            return [make_memory("preference", "用户喜欢安静一点的回复", 0.9, True, "记住")]

    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(ProjectionOnlyStore(settings), DeepSeekGateway(settings))

    assert service.memories()[0]["content"] == "用户喜欢安静一点的回复"


def test_chat_service_debug_uses_generation_log_projection(tmp_path) -> None:
    class ProjectionLogStore(JsonStore):
        def list_generation_logs(self, limit: int | None = None, purpose: str | None = None):
            return [{"id": "log_projection", "purpose": "chat", "created_at": "2026-07-03T10:00:00+08:00"}]

    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(ProjectionLogStore(settings), DeepSeekGateway(settings))

    debug = service.debug_snapshot()

    assert debug["generation_logs"][0]["id"] == "log_projection"


def test_chat_service_uses_storage_search_for_recall_candidates(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))

    def seed_memory(state):
        state.setdefault("memories", []).append(
            make_memory("emotion_pattern", "用户最近失眠严重", 0.8, False, "睡眠")
        )
        return None

    service.store.mutate(seed_memory)
    result = asyncio.run(service.chat("我最近睡不好"))

    latest_log = service.store.snapshot()["generation_logs"][-1]
    assert result["used_memories"]
    assert latest_log["prompt_manifest"]["recall_candidate_source"] == "storage_search_plus_priority"
    assert set(result["used_memories"]).issubset(set(latest_log["prompt_manifest"]["recall_candidate_ids"]))


def test_chat_service_keeps_priority_memories_when_search_misses(tmp_path) -> None:
    class SearchMissJsonStore(JsonStore):
        def search_memories(self, query: str, limit: int = 8):
            return []

    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(SearchMissJsonStore(settings), DeepSeekGateway(settings))

    def seed_memory(state):
        state.setdefault("memories", []).append(
            make_memory("goal", "待跟进：整理项目材料", 0.8, False, "整理项目材料", open_item=True)
        )
        return None

    service.store.mutate(seed_memory)
    result = asyncio.run(service.chat("项目后来怎么样"))

    latest_log = service.store.snapshot()["generation_logs"][-1]
    assert result["used_memories"]
    assert "待跟进" in next(iter(latest_log["prompt_manifest"]["used_memory_reasons"].values()))


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
    summary_system = latest_log["api_messages"][1]["content"]
    assert "会话摘要" in summary_system
    assert "项目材料推进卡住了" in summary_system
    assert latest_log["prompt_manifest"]["work_memory_after_message_count"] == 16
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


def test_storage_session_lookup_does_not_treat_empty_session_as_missing(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    json_store = JsonStore(settings)

    def add_empty_session(state):
        state.setdefault("sessions", {})["empty"] = {}
        return None

    json_store.mutate(add_empty_session)
    assert json_store.session("empty") == {}

    sqlite_settings = Settings(
        data_dir=tmp_path / "sqlite",
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
        storage_backend="sqlite",
    )
    sqlite_store = SqliteStore(sqlite_settings)
    sqlite_store.mutate(add_empty_session)
    assert sqlite_store.session("empty") == {}


def test_sqlite_projection_tolerates_duplicate_entity_ids(tmp_path) -> None:
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

    duplicate_memory = make_memory("preference", "用户喜欢安静一点的回复", 0.9, True, "记住")
    duplicate_memory["id"] = "mem_duplicate"
    duplicate_message = {"id": "msg_duplicate", "role": "user", "content": "你好", "created_at": "2026-07-03T10:00:00+08:00"}

    def mutate(state):
        session = state["sessions"][state["active_session_id"]]
        session["messages"].extend([duplicate_message, dict(duplicate_message)])
        state.setdefault("memories", []).extend([duplicate_memory, dict(duplicate_memory)])
        return "ok"

    assert store.mutate(mutate) == "ok"
    assert store.search_memories("安静")
    with store._connect() as db:
        message_count = db.execute("SELECT COUNT(*) AS count FROM messages WHERE id = 'msg_duplicate'").fetchone()["count"]
        memory_count = db.execute("SELECT COUNT(*) AS count FROM memories WHERE id = 'mem_duplicate'").fetchone()["count"]

    assert message_count == 1
    assert memory_count == 1


def test_sqlite_lists_memories_from_projection(tmp_path) -> None:
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

    active_memory = make_memory("preference", "用户喜欢安静一点的回复", 0.9, True, "记住")
    archived_memory = make_memory("fact", "用户以前提过一个临时信息", 0.5, False, "临时")
    archived_memory["status"] = "archived"

    def mutate(state):
        state.setdefault("memories", []).extend([active_memory, archived_memory])
        return "ok"

    assert store.mutate(mutate) == "ok"
    assert len(store.list_memories()) == 2
    active = store.list_memories(status="active")
    assert len(active) == 1
    assert active[0]["content"] == "用户喜欢安静一点的回复"


def test_sqlite_lists_generation_logs_from_projection(tmp_path) -> None:
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
        state.setdefault("generation_logs", []).extend(
            [
                {"id": "log_1", "purpose": "chat", "created_at": "2026-07-03T10:00:00+08:00"},
                {"id": "log_2", "purpose": "memory_extract", "created_at": "2026-07-03T10:01:00+08:00"},
                {"id": "log_3", "purpose": "chat", "created_at": "2026-07-03T10:02:00+08:00"},
            ]
        )
        return "ok"

    assert store.mutate(mutate) == "ok"
    assert [log["id"] for log in store.list_generation_logs(limit=2)] == ["log_2", "log_3"]
    assert [log["id"] for log in store.list_generation_logs(purpose="chat")] == ["log_1", "log_3"]


def test_sqlite_search_falls_back_to_semantic_match(tmp_path) -> None:
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
        state.setdefault("memories", []).append(
            make_memory("emotion_pattern", "用户最近失眠严重", 0.8, False, "睡眠")
        )
        return "ok"

    assert store.mutate(mutate) == "ok"
    assert store.search_memories("我最近睡不好")


def test_sqlite_search_fills_exact_results_with_semantic_matches(tmp_path) -> None:
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
        state.setdefault("memories", []).extend(
            [
                make_memory("emotion_pattern", "用户最近工作压力很大", 0.8, False, "工作压力"),
                make_memory("emotion_pattern", "用户最近失眠严重", 0.8, False, "睡眠"),
            ]
        )
        return "ok"

    assert store.mutate(mutate) == "ok"
    results = store.search_memories("压力 睡不好", limit=2)
    contents = [memory["content"] for memory in results]

    assert any("压力" in content for content in contents)
    assert any("失眠" in content for content in contents)


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


def test_json_store_exposes_memory_search_backend_interface(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    store = create_store(settings)

    def mutate(state):
        state.setdefault("memories", []).append(make_memory("emotion_pattern", "用户最近失眠严重", 0.8, False, "睡眠"))
        return "ok"

    assert store.mutate(mutate) == "ok"
    assert store.search_memories("失眠")
    assert store.search_memories("我最近睡不好")


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


def test_migrate_json_to_sqlite_refuses_to_overwrite_existing_state(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )

    def seed_json(state):
        state.setdefault("memories", []).append(make_memory("preference", "用户喜欢安静一点的回复", 0.9, True, "记住"))
        return state

    def seed_sqlite(state):
        state.setdefault("memories", []).append(make_memory("fact", "已有 SQLite 记忆", 0.7, False, "已有"))
        return state

    JsonStore(settings).mutate(seed_json)
    sqlite_store = SqliteStore(settings)
    sqlite_store.mutate(seed_sqlite)

    with pytest.raises(FileExistsError):
        migrate_json_to_sqlite(settings)

    assert sqlite_store.snapshot()["memories"][0]["content"] == "已有 SQLite 记忆"
    migrate_json_to_sqlite(settings, overwrite=True)
    assert SqliteStore(settings).snapshot()["memories"][0]["content"] == "用户喜欢安静一点的回复"


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
    logs = service.store.snapshot()["generation_logs"]
    assert logs[-1]["feedback_signals"][0]["type"] == "confirmation_rejected"


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


def test_work_memory_starts_after_summary_boundary() -> None:
    messages = [{"role": "user", "content": f"消息 {index}"} for index in range(20)]

    memory = work_memory(messages, "继续", after_message_count=16)

    assert [item["content"] for item in memory] == ["消息 16", "消息 17", "消息 18", "消息 19"]


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
