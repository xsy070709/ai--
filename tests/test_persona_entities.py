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
