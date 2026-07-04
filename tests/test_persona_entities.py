from __future__ import annotations

import asyncio

import pytest

from app.chat_service import ChatService
from app.config import Settings
from app.llm_gateway import DeepSeekGateway, LLMResult
from app.storage import JsonStore


class FakePersonaLearningGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls = []

    async def structured(self, messages, purpose="structured"):
        self.calls.append({"purpose": purpose, "messages": messages})
        return LLMResult(
            text=(
                '{"name":"林夏","relationship_to_user":"长期陪伴型虚拟好友",'
                '"summary":"林夏温柔但会轻轻吐槽，习惯先安慰再分析。",'
                '"traits":["温柔","理性","轻微吐槽"],'
                '"speaking_style":["短句","自然口语"],'
                '"catchphrases":["先别急嘛"],'
                '"habits":["睡前复盘"],'
                '"emotional_style":["先共情","再拆问题"],'
                '"conversation_habits":["先安慰再分析"],'
                '"taboo_phrases":["作为一个AI语言模型"]}'
            ),
            provider="fake",
            model="persona-test",
            degraded=False,
            elapsed_ms=1,
        )

    def debug_requests(self):
        return []


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


def test_import_persona_materials_uses_structured_learning(tmp_path) -> None:
    service = make_service(tmp_path)
    service.gateway = FakePersonaLearningGateway(service.gateway.settings)

    result = asyncio.run(
        service.import_persona_materials(
            "聊天记录：林夏：先别急嘛，我陪你拆。林夏习惯睡前复盘。",
            source_type="chat_log",
        )
    )

    persona = result["persona"]
    assert result["llm"]["degraded"] is False
    assert persona["identity"]["name"] == "林夏"
    assert "轻微吐槽" in persona["personality"]["stable_traits"]
    assert "先别急嘛" in persona["speaking_style"]["catchphrases"]
    assert any("口癖" in memory["content"] for memory in result["created_memories"])
    assert service.status()["persona"]["id"] == persona["id"]


def test_import_persona_materials_names_entity_from_common_background_phrasing(tmp_path) -> None:
    service = make_service(tmp_path)

    asyncio.run(service.import_persona_materials("你的名字是林夏。关系定位：长期陪伴型虚拟好友。性格：温柔、理性。"))

    status = service.status()
    entity = next(item for item in status["persona_entities"] if item["active"])
    assert status["persona"]["identity"]["name"] == "林夏"
    assert entity["name"] == "林夏"
    assert entity["display_name"] == "林夏"


def test_import_without_name_preserves_existing_entity_name(tmp_path) -> None:
    service = make_service(tmp_path)
    entity = service.create_persona_entity("小秋", activate=True)

    asyncio.run(service.import_persona_materials("性格：温柔、理性。口癖：慢慢来。"))

    status_entity = next(item for item in service.status()["persona_entities"] if item["id"] == entity["id"])
    assert status_entity["name"] == "小秋"
    assert status_entity["display_name"] == "小秋"
    assert service.status()["persona"]["identity"]["name"] == "小秋"


def test_persona_entities_isolate_messages_and_memories(tmp_path) -> None:
    service = make_service(tmp_path)

    asyncio.run(service.import_persona_materials("名字：林夏。口癖：先别急嘛。性格：温柔、理性。", source_type="background_story"))
    asyncio.run(service.chat("记住我喜欢安静一点的回复"))
    default_entity_id = service.status()["active_persona_entity_id"]
    default_messages = service.messages()
    default_memories = service.memories()

    second = service.create_persona_entity("周白", activate=True)
    assert service.status()["active_persona_entity_id"] == second["id"]
    assert service.messages() == []
    assert service.memories() == []

    asyncio.run(service.import_persona_materials("名字：周白。口癖：行吧。性格：直接、冷幽默。", source_type="background_story"))
    asyncio.run(service.chat("记住我不喜欢太热闹"))
    second_memories = service.memories()
    assert second_memories
    assert all(memory.get("persona_entity_id") == second["id"] for memory in second_memories)
    assert not any("先别急" in memory["content"] for memory in second_memories)

    service.switch_persona_entity(default_entity_id)
    assert service.messages() == default_messages
    assert service.memories()
    assert all(memory.get("persona_entity_id") == default_entity_id for memory in service.memories())
    assert any(memory["id"] == default_memories[0]["id"] for memory in service.memories())


def test_persona_entity_can_be_renamed(tmp_path) -> None:
    service = make_service(tmp_path)
    asyncio.run(service.import_persona_materials("名字：林夏。性格：温柔、理性。"))
    entity_id = service.status()["active_persona_entity_id"]

    renamed = service.rename_persona_entity(entity_id, "新名字")

    assert renamed is not None
    assert renamed["name"] == "新名字"
    status_entity = next(entity for entity in service.status()["persona_entities"] if entity["id"] == entity_id)
    assert status_entity["name"] == "新名字"
    assert status_entity["display_name"] == "新名字"
    assert service.status()["persona"]["identity"]["name"] == "新名字"
    session = service.store.snapshot()["sessions"][status_entity["active_session_id"]]
    assert session["title"] == "新名字"
    assert service.rename_persona_entity(entity_id, "   ") is None


def test_clear_current_chat_removes_messages_summaries_and_chat_logs_only(tmp_path) -> None:
    service = make_service(tmp_path)
    asyncio.run(service.import_persona_materials("名字：林夏。口癖：先别急嘛。性格：温柔、理性。"))
    asyncio.run(service.chat("记住我喜欢安静一点的回复"))
    state = service.store.snapshot()
    entity_id = service.status()["active_persona_entity_id"]
    state["sessions"][state["active_session_id"]]["summaries"].append({"id": "sum_1", "summary": "旧聊天摘要"})
    service.store.mutate(lambda next_state: next_state.update(state) or None)

    result = service.clear_current_chat()

    assert result["removed_messages"] == 2
    assert result["removed_summaries"] == 1
    assert result["removed_generation_logs"] >= 1
    assert service.messages() == []
    assert service.status()["layers"]["summary"]["count"] == 0
    assert service.status()["persona"] is not None
    assert service.memories()
    logs = service.store.snapshot()["generation_logs"]
    assert not [log for log in logs if log.get("purpose") == "chat" and log.get("persona_entity_id") == entity_id]


def test_delete_persona_entity_removes_scoped_data_and_selects_replacement(tmp_path) -> None:
    service = make_service(tmp_path)
    asyncio.run(service.import_persona_materials("名字：林夏。口癖：先别急嘛。性格：温柔、理性。"))
    asyncio.run(service.chat("记住我喜欢安静一点的回复"))
    first_id = service.status()["active_persona_entity_id"]
    first_session_id = service.status()["session_id"]
    first_memory_ids = {memory["id"] for memory in service.memories()}

    second = service.create_persona_entity("周白", activate=True)
    asyncio.run(service.import_persona_materials("名字：周白。口癖：行吧。性格：直接、冷幽默。"))
    asyncio.run(service.chat("记住我不喜欢太热闹"))

    assert service.delete_persona_entity(second["id"]) is True
    state = service.store.snapshot()
    assert service.status()["active_persona_entity_id"] == first_id
    assert second["id"] not in {entity["id"] for entity in state["persona_entities"]}
    assert all(session.get("persona_entity_id") != second["id"] for session in state["sessions"].values())
    assert all(persona.get("persona_entity_id") != second["id"] for persona in state["persona_versions"])
    assert all(memory.get("persona_entity_id") != second["id"] for memory in state["memories"])
    assert all(log.get("persona_entity_id") != second["id"] for log in state["generation_logs"])
    assert state["active_session_id"] == first_session_id
    assert first_memory_ids <= {memory["id"] for memory in service.memories()}

    assert service.delete_persona_entity(first_id) is True
    state = service.store.snapshot()
    assert len(state["persona_entities"]) == 1
    assert state["active_persona_entity_id"] == state["persona_entities"][0]["id"]
    assert service.messages() == []
    assert service.memories() == []
    assert service.delete_persona_entity("missing") is False


# ── Import Wizard Session Tests ──────────────────────────────────────


class FakeImportGateway:
    """Fake gateway that supports both persona_learn and persona_refine purposes."""

    def __init__(self, settings):
        self.settings = settings
        self.calls: list[dict[str, Any]] = []

    async def structured(self, messages, purpose="structured"):
        self.calls.append({"purpose": purpose, "messages": messages})
        if purpose == "persona_refine":
            return type(
                "LLMResult",
                (),
                {
                    "text": (
                        '{"reply":"好的，我已经更新了设定。",'
                        '"profile_diff":{"traits":["温柔","理性","独立"]},'
                        '"clarifying_questions":[],'
                        '"is_complete":true}'
                    ),
                    "provider": "fake",
                    "model": "import-test",
                    "degraded": False,
                    "elapsed_ms": 1,
                    "error": None,
                    "usage": None,
                },
            )()
        # default: persona_learn
        return type(
            "LLMResult",
            (),
            {
                "text": (
                    '{"name":"林夏","relationship_to_user":"长期陪伴型虚拟好友",'
                    '"summary":"林夏从小跟着外婆长大，经历很多却保持温柔。",'
                    '"traits":["温柔","坚韧","理性"],'
                    '"speaking_style":["短句","自然口语","先安慰"],'
                    '"catchphrases":["先别急嘛"],'
                    '"habits":["睡前复盘"],'
                    '"emotional_style":["先共情","再拆问题"],'
                    '"conversation_habits":["先安慰再分析"],'
                    '"taboo_phrases":["作为一个AI语言模型"],'
                    '"needs_clarification":["relationship_to_user"],'
                    '"clarifying_questions":["她和用户具体是什么关系？"],'
                    '"confidence":0.82}'
                ),
                "provider": "fake",
                "model": "import-test",
                "degraded": False,
                "elapsed_ms": 1,
                "error": None,
                "usage": None,
            },
        )()

    async def chat(self, messages, purpose="chat"):
        return await self.structured(messages, purpose=purpose)

    def debug_requests(self):
        return []


def make_import_service(tmp_path) -> ChatService:
    from app.config import Settings
    from app.llm_gateway import DeepSeekGateway
    from app.storage import JsonStore

    settings = Settings(
        data_dir=tmp_path,
        deepseek_api_base_url="https://api.deepseek.com",
        deepseek_api_key="",
        deepseek_chat_model="deepseek-v4",
        timeout_seconds=1,
        max_retries=0,
    )
    service = ChatService(JsonStore(settings), DeepSeekGateway(settings))
    service.gateway = FakeImportGateway(settings)
    return service


def test_import_session_basic_extraction(tmp_path) -> None:
    """Starting an import session extracts a profile from text."""
    service = make_import_service(tmp_path)

    result = asyncio.run(
        service.start_import_session(
            "林夏从小跟着外婆长大，经历了很多，但始终保持温柔。她说话总是很短，先安慰你再分析问题。",
            source_type="background_story",
        )
    )

    assert result["session_id"].startswith("import_")
    assert result["status"] == "learning"
    profile = result["current_profile"]
    assert profile["name"] == "林夏"
    assert "温柔" in profile["traits"]
    assert "坚韧" in profile["traits"]
    assert len(result["messages"]) == 1
    assert result["messages"][0]["role"] == "assistant"
    assert "林夏" in result["messages"][0]["content"]


def test_import_session_refinement_dialogue(tmp_path) -> None:
    """Multi-turn refinement updates the profile."""
    service = make_import_service(tmp_path)

    start = asyncio.run(
        service.start_import_session("林夏：慢慢来。", source_type="chat_log")
    )
    session_id = start["session_id"]

    result = asyncio.run(
        service.import_session_chat(session_id, "其实她更独立一些，不要总说温柔")
    )

    assert "reply" in result
    assert "profile_diff" in result
    # the fake gateway adds "独立" via profile_diff
    current = result["current_profile"]
    assert "独立" in current.get("traits", [])


def test_import_session_manual_edit(tmp_path) -> None:
    """Manual profile editing through the session."""
    service = make_import_service(tmp_path)

    start = asyncio.run(
        service.start_import_session("林夏：温和但果断。", source_type="background_story")
    )

    updated = service.update_import_session_profile(
        start["session_id"],
        {"traits": ["果断", "温和", "可靠"], "catchphrases": ["行吧"]},
    )
    assert updated is not None
    assert "果断" in updated["traits"]
    assert updated["catchphrases"] == ["行吧"]


def test_import_session_confirm_creates_persona(tmp_path) -> None:
    """Confirming an import session persists persona and memories."""
    service = make_import_service(tmp_path)

    start = asyncio.run(
        service.start_import_session(
            "名字：林夏。关系：长期陪伴型虚拟好友。性格：温柔、理性。口癖：先别急嘛。",
            source_type="background_story",
        )
    )

    final_profile = dict(start["current_profile"])
    final_profile["traits"] = ["温柔", "理性", "有边界感"]

    confirmed = asyncio.run(
        service.confirm_import_session(start["session_id"], final_profile)
    )

    assert confirmed["persona"]["identity"]["name"] == "林夏"
    assert "温柔" in confirmed["persona"]["personality"]["stable_traits"]
    assert len(confirmed["created_memories"]) > 0

    # persona is active on the entity
    status = service.status()
    assert status["persona"] is not None
    assert status["persona"]["identity"]["name"] == "林夏"

    # entity got named
    entity = next(e for e in status["persona_entities"] if e["active"])
    assert entity["name"] == "林夏"


def test_import_session_not_found(tmp_path) -> None:
    """Missing sessions raise KeyError."""
    service = make_import_service(tmp_path)

    with pytest.raises(KeyError):
        asyncio.run(service.confirm_import_session("nonexistent", {}))

    assert service.delete_import_session("nonexistent") is False
    assert service.get_import_session_state("nonexistent") is None


def test_import_session_delete(tmp_path) -> None:
    """Deleting a session cleans it up."""
    service = make_import_service(tmp_path)

    start = asyncio.run(
        service.start_import_session("林夏：温柔。", source_type="background_story")
    )
    session_id = start["session_id"]

    assert service.get_import_session_state(session_id) is not None
    assert service.delete_import_session(session_id) is True
    assert service.get_import_session_state(session_id) is None
    assert service.delete_import_session(session_id) is False


def test_import_session_preserves_entity_name_when_no_name_in_text(tmp_path) -> None:
    """When the text doesn't contain a name, the entity name should be preserved."""
    service = make_import_service(tmp_path)
    service.create_persona_entity("小秋", activate=True)

    start = asyncio.run(
        service.start_import_session(
            "性格：温柔、理性。说话很短，先安慰再分析。",
            source_type="background_story",
        )
    )

    # the entity name flows into the profile
    assert start["current_profile"].get("name") == "小秋"


def test_import_session_handles_llm_failure_gracefully(tmp_path) -> None:
    """When the LLM fails, local fallback still produces a profile."""
    service = make_import_service(tmp_path)

    # replace gateway with one that always fails structured()
    class FailingGateway:
        def __init__(self, settings):
            self.settings = settings

        async def structured(self, messages, purpose="structured"):
            raise RuntimeError("simulated failure")

        def debug_requests(self):
            return []

    service.gateway = FailingGateway(service.gateway.settings)

    start = asyncio.run(
        service.start_import_session(
            "名字：林夏。关系：长期陪伴型虚拟好友。性格：温柔、理性。",
            source_type="background_story",
        )
    )

    # local fallback should still extract name via regex
    assert start["current_profile"]["name"] == "林夏"
