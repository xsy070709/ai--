from __future__ import annotations

import asyncio

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
    entity_id = service.status()["active_persona_entity_id"]

    renamed = service.rename_persona_entity(entity_id, "新名字")

    assert renamed is not None
    assert renamed["name"] == "新名字"
    status_entity = next(entity for entity in service.status()["persona_entities"] if entity["id"] == entity_id)
    assert status_entity["name"] == "新名字"
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
