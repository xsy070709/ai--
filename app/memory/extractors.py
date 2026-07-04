from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..time_context import current_time_context
from .extraction import extract_memory_candidates as rule_based_extract
from .schema import HUMAN_MEMORY_TYPES, make_memory
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

    def __init__(self, gateway: Any, fallback: MemoryExtractor | None = None, name: str = "structured_llm") -> None:
        self.name = name
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
    extractor = getattr(settings, "memory_extractor", "rule")
    if extractor in {"lmstudio", "local"}:
        return StructuredLLMMemoryExtractor(gateway, name="structured_lmstudio")
    if extractor in {"llm", "structured", "deepseek"}:
        return StructuredLLMMemoryExtractor(gateway)
    return RuleBasedMemoryExtractor()


def default_extractor() -> MemoryExtractor:
    return RuleBasedMemoryExtractor()


def _build_messages(user_text: str, assistant_text: str, context: dict[str, Any] | None) -> list[dict[str, str]]:
    profile_text = ""
    if context and context.get("memory_context"):
        profile_text = context["memory_context"].get("prompt_text", "")
    time_context = current_time_context()
    time_anchor = f"当前日期：{time_context['date']} {time_context['weekday']}，时区：{time_context['timezone']}。"
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
抽取规则：
- 只抽取对长期相处有用的记忆；不要把普通寒暄写成记忆；不要编造。
- type 只能使用 schema 中列出的值。
- open 只用于还没完成、后续需要自然跟进的 goal；response_rule、boundary、emotion_pattern 默认 open=false。
- boundary、dislike、fact、episodic 需要用户确认，confirmed 通常为 false。
- confidence 不要虚高；不确定的候选应低于 0.7。
"""
    return [
        {"role": "system", "content": "你是记忆抽取器，只输出 JSON，不输出解释。"},
        {"role": "user", "content": f"{time_anchor}\n{schema}\n已有记忆上下文：\n{profile_text}\n用户消息：{user_text}\nAI 回复：{assistant_text}"},
    ]


def _payload_to_memories(payload: dict[str, Any], evidence_text: str) -> list[dict[str, Any]]:
    memories = []
    for item in payload.get("memories", []):
        memory_type = _normalized_memory_type(item.get("type"))
        content = str(item.get("content", "")).strip()
        if memory_type is None or not content:
            continue
        confirmed = bool(item.get("confirmed", False))
        confidence = _normalized_confidence(item.get("confidence", 0.6), confirmed=confirmed)
        memories.append(
            make_memory(
                memory_type,
                content,
                confidence,
                confirmed,
                evidence_text,
                open_item=_normalized_open_item(memory_type, item.get("open"), content),
                valence=valence_from_text(content),
                stability=_normalized_choice(item.get("stability"), {"low", "medium", "high"}, "medium"),
                sensitivity_level=_normalized_choice(item.get("sensitivity_level"), {"low", "medium", "high"}, "low"),
            )
        )
    return memories


def _normalized_memory_type(value: Any) -> str | None:
    memory_type = str(value or "fact").strip()
    if memory_type in HUMAN_MEMORY_TYPES:
        return memory_type
    return None


def _normalized_confidence(value: Any, *, confirmed: bool) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.6
    confidence = max(0.0, min(confidence, 1.0))
    if not confirmed:
        confidence = min(confidence, 0.92)
    return confidence


def _normalized_open_item(memory_type: str, value: Any, content: str) -> bool:
    if memory_type == "goal":
        return bool(value)
    if memory_type == "shared_experience" and any(marker in content for marker in ("下次", "继续", "约定")):
        return bool(value)
    return False


def _normalized_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default
