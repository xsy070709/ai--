from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..time_context import current_time_context
from .extraction import extract_memory_candidates as rule_based_extract
from .schema import make_memory
from .text import valence_from_text


class MemoryExtractor(Protocol):
    name: str

    def extract(self, user_text: str, assistant_text: str = "", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

    async def extract_async(self, user_text: str, assistant_text: str = "", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


@dataclass
class RuleBasedMemoryExtractor:
    name: str = "rule_based"

    def extract(self, user_text: str, assistant_text: str = "", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        memories = rule_based_extract(user_text, assistant_text)
        for memory in memories:
            memory["extractor"] = self.name
        return memories

    async def extract_async(self, user_text: str, assistant_text: str = "", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.extract(user_text, assistant_text, context)


class StructuredLLMMemoryExtractor:
    """Adapter placeholder for DeepSeek structured extraction.

    The memory package treats this as an injectable boundary. The current app can
    run fully offline with RuleBasedMemoryExtractor, while a DeepSeek-backed
    implementation can later return the same memory dictionaries.
    """

    name = "structured_llm"

    def __init__(self, gateway: Any, fallback: MemoryExtractor | None = None) -> None:
        self.gateway = gateway
        self.fallback = fallback or RuleBasedMemoryExtractor()

    def extract(self, user_text: str, assistant_text: str = "", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.fallback.extract(user_text, assistant_text, context)

    async def extract_async(self, user_text: str, assistant_text: str = "", context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = await self.gateway.structured(_build_messages(user_text, assistant_text, context), purpose="memory_extract")
        if result.degraded:
            memories = self.fallback.extract(user_text, assistant_text, context)
            for memory in memories:
                memory["extractor"] = f"{self.name}_fallback"
                memory["extractor_error"] = result.error
            return memories

        try:
            payload = json.loads(result.text)
            memories = _payload_to_memories(payload, user_text)
        except (TypeError, ValueError, KeyError):
            memories = self.fallback.extract(user_text, assistant_text, context)
            for memory in memories:
                memory["extractor"] = f"{self.name}_parse_fallback"
            return memories

        for memory in memories:
            memory["extractor"] = self.name
            memory["llm_usage"] = result.usage
        return memories


def choose_extractor(settings: Any, gateway: Any) -> MemoryExtractor:
    if getattr(settings, "memory_extractor", "rule") in {"llm", "structured", "deepseek"}:
        return StructuredLLMMemoryExtractor(gateway)
    return RuleBasedMemoryExtractor()


def default_extractor() -> MemoryExtractor:
    return RuleBasedMemoryExtractor()


def _build_messages(user_text: str, assistant_text: str, context: dict[str, Any] | None) -> list[dict[str, str]]:
    profile_text = ""
    if context and context.get("memory_context"):
        profile_text = context["memory_context"].get("prompt_text", "")
    time_context = current_time_context()
    schema = """
返回严格 JSON：
{
  "memories": [
    {
      "type": "preference|dislike|boundary|response_rule|goal|emotion_pattern|relationship_signal|shared_experience|episodic|fact",
      "content": "中文记忆内容",
      "confidence": 0.0-1.0,
      "confirmed": true|false,
      "open": true|false,
      "stability": "low|medium|high",
      "sensitivity_level": "low|medium|high"
    }
  ]
}
只抽取对长期相处有用的记忆；不要把普通寒暄写成记忆；不要编造。
"""
    return [
        {"role": "system", "content": f"你是记忆抽取器，只输出 JSON，不输出解释。\n{time_context['prompt_text']}"},
        {"role": "user", "content": f"{schema}\n已有记忆上下文：\n{profile_text}\n用户消息：{user_text}\nAI 回复：{assistant_text}"},
    ]


def _payload_to_memories(payload: dict[str, Any], evidence_text: str) -> list[dict[str, Any]]:
    memories = []
    for item in payload.get("memories", []):
        memory_type = str(item.get("type", "fact"))
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        confidence = float(item.get("confidence", 0.6))
        confidence = max(0.0, min(confidence, 1.0))
        memories.append(
            make_memory(
                memory_type,
                content,
                confidence,
                bool(item.get("confirmed", False)),
                evidence_text,
                open_item=bool(item.get("open", False)),
                valence=valence_from_text(content),
                stability=str(item.get("stability", "medium")),
                sensitivity_level=str(item.get("sensitivity_level", "low")),
            )
        )
    return memories
