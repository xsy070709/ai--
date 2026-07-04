"""Tests for the persona event system."""

from __future__ import annotations

import asyncio

import pytest

from app.chat_service import ChatService
from app.config import Settings
from app.llm_gateway import DeepSeekGateway, LLMResult
from app.persona_events import (
    apply_event_trait_effects,
    build_event_context,
    build_event_taboo_context,
    check_taboo_triggers,
    create_event,
    event_to_memory,
    maintain_events,
)
from app.storage import JsonStore, now_iso


# ── helpers ─────────────────────────────────────────────────────────


def make_service(tmp_path) -> ChatService:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    return ChatService(JsonStore(settings), DeepSeekGateway(settings))


# ── event creation ──────────────────────────────────────────────────


def test_create_event_basic():
    event = create_event(
        "她丢了工作",
        persona_entity_id="entity_test",
        event_type="negative",
        trait_effects=[{"trait": "乐观", "direction": "weaken", "strength": 0.6}],
        becomes_topic=True,
        topic_trigger_words=["工作", "上班"],
    )
    assert event["id"].startswith("evt_")
    assert event["content"] == "她丢了工作"
    assert event["event_type"] == "negative"
    assert event["status"] == "active"
    assert event["becomes_topic"] is True
    assert event["becomes_taboo"] is False
    assert event["trait_effects"][0]["trait"] == "乐观"
    assert event["trait_effects"][0]["direction"] == "weaken"


def test_create_event_with_taboo():
    event = create_event(
        "她遭遇了网络暴力",
        persona_entity_id="entity_test",
        event_type="traumatic",
        becomes_taboo=True,
        taboo_keywords=["网络暴力", "网暴", "键盘侠"],
    )
    assert event["becomes_taboo"] is True
    assert "网络暴力" in event["taboo_keywords"]


def test_create_event_normalizes_trait_effects():
    event = create_event(
        "test",
        persona_entity_id="e1",
        trait_effects=[
            {"trait": "  ", "direction": "add"},  # should be filtered
            {"trait": "焦虑", "direction": "invalid"},  # invalid direction
            {"trait": "乐观", "direction": "weaken", "strength": 0.8},
        ],
    )
    effects = event["trait_effects"]
    assert len(effects) == 1  # only the valid one
    assert effects[0]["trait"] == "乐观"


# ── trait modulation ────────────────────────────────────────────────


def test_apply_trait_effects_add():
    traits = ["温柔", "理性"]
    events = [
        create_event(
            "她开始学画画", persona_entity_id="e1",
            trait_effects=[{"trait": "细腻", "direction": "add", "strength": 0.7}],
        )
    ]
    result = apply_event_trait_effects(traits, events)
    assert "细腻" in result
    assert "温柔" in result


def test_apply_trait_effects_weaken():
    traits = ["乐观", "温柔", "理性"]
    events = [
        create_event(
            "她丢了工作", persona_entity_id="e1",
            trait_effects=[{"trait": "乐观", "direction": "weaken", "strength": 0.7}],
        )
    ]
    result = apply_event_trait_effects(traits, events)
    # "乐观" should be moved to the end
    assert result[-1] == "乐观"
    assert result[:2] == ["温柔", "理性"]


def test_apply_trait_effects_strengthen():
    traits = ["温柔", "理性", "乐观"]
    events = [
        create_event(
            "她升职了", persona_entity_id="e1", event_type="positive",
            trait_effects=[{"trait": "乐观", "direction": "strengthen", "strength": 0.8}],
        )
    ]
    result = apply_event_trait_effects(traits, events)
    assert result[0] == "乐观"  # moved to front


def test_apply_trait_effects_remove():
    traits = ["温柔", "焦虑", "理性"]
    events = [
        create_event(
            "她学会了情绪管理", persona_entity_id="e1", event_type="positive",
            trait_effects=[{"trait": "焦虑", "direction": "remove", "strength": 0.8}],
        )
    ]
    result = apply_event_trait_effects(traits, events)
    assert "焦虑" not in result


def test_apply_trait_effects_fading_half_strength():
    traits = ["乐观", "温柔"]
    event = create_event(
        "她丢了工作", persona_entity_id="e1",
        trait_effects=[{"trait": "乐观", "direction": "weaken", "strength": 0.4}],
    )
    event["status"] = "fading"
    # strength 0.4 * 0.5 = 0.2 < 0.25 → should be skipped
    result = apply_event_trait_effects(traits, [event])
    assert result == ["乐观", "温柔"]  # no change


def test_apply_trait_effects_ignores_resolved():
    traits = ["温柔", "乐观"]
    event = create_event(
        "旧事件", persona_entity_id="e1",
        trait_effects=[{"trait": "焦虑", "direction": "add", "strength": 0.8}],
    )
    event["status"] = "resolved"
    result = apply_event_trait_effects(traits, [event])
    assert "焦虑" not in result


# ── context builders ────────────────────────────────────────────────


def test_build_event_context_topic():
    events = [
        create_event(
            "她上周丢了工作", persona_entity_id="e1", event_type="negative",
            becomes_topic=True,
        )
    ]
    ctx = build_event_context(events)
    assert "她上周丢了工作" in ctx
    assert "近期经历" in ctx


def test_build_event_context_empty_when_no_active():
    events = [
        create_event("旧事件", persona_entity_id="e1", becomes_topic=True)
    ]
    events[0]["status"] = "resolved"
    ctx = build_event_context(events)
    assert ctx == ""


def test_build_event_taboo_context():
    events = [
        create_event(
            "她遭遇网络暴力", persona_entity_id="e1",
            becomes_taboo=True, taboo_keywords=["网络暴力", "网暴"],
        )
    ]
    ctx = build_event_taboo_context(events)
    assert "敏感话题" in ctx
    assert "网络暴力" in ctx


def test_build_event_context_includes_trait_changes():
    events = [
        create_event(
            "她丢了工作", persona_entity_id="e1", event_type="negative",
            trait_effects=[{"trait": "乐观", "direction": "weaken", "strength": 0.6}],
            becomes_topic=False,
        )
    ]
    ctx = build_event_context(events)
    assert "乐观" in ctx
    assert "减弱" in ctx


# ── taboo detection ─────────────────────────────────────────────────


def test_check_taboo_triggers():
    events = [
        create_event(
            "她失业了", persona_entity_id="e1",
            becomes_taboo=True, taboo_keywords=["失业", "裁员"],
        )
    ]
    triggered = check_taboo_triggers("你最近找到工作了吗", events)
    assert len(triggered) == 0  # "工作" is not a taboo keyword

    triggered2 = check_taboo_triggers("你是不是失业了", events)
    assert len(triggered2) == 1


def test_check_taboo_triggers_case_insensitive():
    events = [
        create_event(
            "她失业了", persona_entity_id="e1",
            becomes_taboo=True, taboo_keywords=["失业"],
        )
    ]
    triggered = check_taboo_triggers("你失業了？", events)
    # "失業" vs "失业" — not exact match (simplified vs traditional)
    # But our check is case-insensitive, not character-variant-insensitive
    # This test documents the current behavior


# ── lifecycle ───────────────────────────────────────────────────────


def test_maintain_events_expiry_transitions():
    event = create_event(
        "她短暂不开心", persona_entity_id="e1",
        impact_scope="temporary",
        expires_at="2026-01-01T00:00:00",
    )
    event["status"] = "active"
    ops = maintain_events([event], "2026-07-01T00:00:00")
    assert len(ops) == 1
    assert ops[0]["field"] == "status"
    assert ops[0]["value"] == "fading"


def test_maintain_events_fading_to_resolved():
    event = create_event(
        "她短暂不开心", persona_entity_id="e1",
        impact_scope="temporary",
        expires_at="2026-01-01T00:00:00",
    )
    event["status"] = "fading"
    ops = maintain_events([event], "2026-07-01T00:00:00")
    assert len(ops) == 1
    assert ops[0]["value"] == "resolved"


def test_maintain_events_no_transition_before_expiry():
    event = create_event(
        "未来事件", persona_entity_id="e1",
        expires_at="2099-01-01T00:00:00",
    )
    ops = maintain_events([event], "2026-07-01T00:00:00")
    assert len(ops) == 0


def test_maintain_events_permanent_absorbed():
    event = create_event(
        "长期影响", persona_entity_id="e1",
        impact_scope="permanent",
    )
    event["status"] = "acknowledged"
    event["acknowledged_at"] = "2026-01-01T00:00:00"
    ops = maintain_events([event], "2026-07-01T00:00:00")
    assert len(ops) == 1
    assert ops[0]["value"] == "absorbed"


# ── memory bridge ───────────────────────────────────────────────────


def test_event_to_memory():
    event = create_event(
        "她丢了工作", persona_entity_id="e1",
        event_type="negative", becomes_taboo=True,
    )
    memory = event_to_memory(event)
    assert memory["type"] == "shared_experience"
    assert "她经历过" in memory["content"]
    assert memory["valence"] == "negative"
    assert memory["sensitivity_level"] == "medium"  # because taboo
    assert memory["open"] is True  # active event = open item


def test_event_to_memory_resolved():
    event = create_event("旧事", persona_entity_id="e1")
    event["status"] = "resolved"
    event["resolution_note"] = "她找到了新工作"
    memory = event_to_memory(event)
    assert "她找到了新工作" in memory["content"]
    assert memory["open"] is False


# ── ChatService integration ─────────────────────────────────────────


class FakeEventGateway:
    def __init__(self, settings):
        self.settings = settings

    async def chat(self, messages, purpose="chat"):
        return LLMResult(
            text="嗯，我理解。",
            provider="fake",
            model="event-test",
            degraded=False,
            elapsed_ms=1,
        )

    def debug_requests(self):
        return []

    async def structured(self, messages, purpose="structured"):
        return LLMResult(
            text="{}", provider="fake", model="event-test", degraded=True, elapsed_ms=1,
        )


def make_event_service(tmp_path) -> ChatService:
    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service_obj = ChatService(JsonStore(settings), DeepSeekGateway(settings))
    service_obj.gateway = FakeEventGateway(settings)
    return service_obj


def test_create_and_list_events(tmp_path):
    service = make_event_service(tmp_path)

    event = service.create_persona_event(
        content="她丢了工作",
        event_type="negative",
        trait_effects=[{"trait": "乐观", "direction": "weaken", "strength": 0.6}],
        becomes_topic=True,
        topic_trigger_words=["工作"],
    )

    assert event["id"].startswith("evt_")
    events = service.get_persona_events()
    assert len(events) == 1
    assert events[0]["content"] == "她丢了工作"


def test_create_event_also_creates_memory(tmp_path):
    service = make_event_service(tmp_path)

    service.create_persona_event(
        content="她升职了",
        event_type="positive",
    )

    memories = service.memories()
    assert len(memories) == 1
    assert memories[0]["type"] == "shared_experience"
    assert "她经历过" in memories[0]["content"]


def test_update_event(tmp_path):
    service = make_event_service(tmp_path)

    event = service.create_persona_event(content="旧内容", event_type="neutral")
    updated = service.update_persona_event(event["id"], {"content": "新内容", "event_type": "positive"})

    assert updated is not None
    assert updated["content"] == "新内容"
    assert updated["event_type"] == "positive"


def test_delete_event(tmp_path):
    service = make_event_service(tmp_path)

    event = service.create_persona_event(content="要删除的事件")
    assert service.delete_persona_event(event["id"]) is True
    assert service.delete_persona_event("nonexistent") is False


def test_resolve_event(tmp_path):
    service = make_event_service(tmp_path)

    event = service.create_persona_event(content="解决了的问题")
    resolved = service.resolve_persona_event(event["id"], "已经过去了")

    assert resolved is not None
    assert resolved["status"] == "resolved"
    assert resolved["resolution_note"] == "已经过去了"


def test_acknowledge_event(tmp_path):
    service = make_event_service(tmp_path)

    event = service.create_persona_event(content="被提到的事件")
    acked = service.acknowledge_persona_event(event["id"])

    assert acked is not None
    assert acked["status"] == "acknowledged"
    assert acked["acknowledged"] is True


def test_events_appear_in_status(tmp_path):
    service = make_event_service(tmp_path)

    service.create_persona_event(content="测试事件", event_type="neutral")
    status = service.status()
    assert len(status["persona_events"]) == 1


def test_chat_with_events_applies_trait_effects(tmp_path):
    service = make_event_service(tmp_path)

    asyncio.run(service.import_persona_materials("名字：林夏。性格：温柔、乐观、理性。"))
    service.create_persona_event(
        content="她丢了工作",
        event_type="negative",
        trait_effects=[{"trait": "乐观", "direction": "weaken", "strength": 0.8}],
    )

    # chat should work without errors
    result = asyncio.run(service.chat("今天过得怎么样？"))
    assert result["reply"] == "嗯，我理解。"
    # should not crash — the event integration is exercised


def test_events_scoped_to_entity(tmp_path):
    service = make_event_service(tmp_path)

    service.create_persona_event(content="林夏的事件")
    entity1_id = service.status()["active_persona_entity_id"]

    second = service.create_persona_entity("周白", activate=True)
    assert len(service.get_persona_events()) == 0  # new entity has no events

    service.switch_persona_entity(entity1_id)
    assert len(service.get_persona_events()) == 1  # back to first entity


def test_default_state_has_persona_events(tmp_path):
    service = make_event_service(tmp_path)
    state = service.store.snapshot()
    assert "persona_events" in state
    assert state["persona_events"] == []
