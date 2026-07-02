from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..time_context import current_time_context
from .signals import emotion_tags_for, has_completion_signal, has_task_signal, has_time_signal, is_high_density, looks_like_casual_chat
from .text import topics_from_text, unfinished_items, valence_from_text


class IntentClassifier(Protocol):
    name: str

    def classify(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ...

    async def classify_async(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


@dataclass
class RuleBasedIntentClassifier:
    name: str = "rule_based_intent"

    def classify(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        emotions = emotion_tags_for(user_text)
        topics = topics_from_text(user_text)
        return {
            "has_completion_signal": has_completion_signal(user_text),
            "completion_target": _completion_target(user_text),
            "has_correction_intent": any(word in user_text for word in ["别记", "不要记", "删掉", "不是", "不对", "错了"]),
            "primary_emotion": emotions[0] if emotions else "平稳",
            "secondary_emotion": emotions[1] if len(emotions) > 1 else None,
            "valence": valence_from_text(user_text),
            "is_casual_chat": looks_like_casual_chat(user_text),
            "has_followup_invitation": any(word in user_text for word in ["还记得", "之前", "上次", "继续", "后来"]),
            "topics": topics,
            "unfinished_items": unfinished_items(user_text),
            "information_density": round(2.0 if is_high_density(user_text) else 0.0, 3),
            "classifier": self.name,
        }

    async def classify_async(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.classify(user_text, context)


class StructuredLLMIntentClassifier:
    name = "structured_llm_intent"

    def __init__(self, gateway: Any, fallback: IntentClassifier | None = None) -> None:
        self.gateway = gateway
        self.fallback = fallback or RuleBasedIntentClassifier()

    def classify(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.fallback.classify(user_text, context)

    async def classify_async(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self.gateway.structured(_build_messages(user_text, context), purpose="memory_intent")
        if result.degraded:
            intent = self.fallback.classify(user_text, context)
            intent["classifier"] = f"{self.name}_fallback"
            intent["classifier_error"] = result.error
            return intent
        try:
            payload = json.loads(result.text)
            intent = _normalize_intent(payload)
        except (TypeError, ValueError):
            intent = self.fallback.classify(user_text, context)
            intent["classifier"] = f"{self.name}_parse_fallback"
            return intent
        intent["classifier"] = self.name
        intent["llm_usage"] = result.usage
        return intent


def choose_intent_classifier(settings: Any, gateway: Any) -> IntentClassifier:
    if getattr(settings, "memory_intent_classifier", "rule") in {"llm", "structured", "deepseek"}:
        return StructuredLLMIntentClassifier(gateway)
    return RuleBasedIntentClassifier()


def _completion_target(user_text: str) -> str | None:
    if not has_completion_signal(user_text):
        return None
    for topic in ["材料", "面试", "考试", "项目", "作业", "报告", "简历", "论文"]:
        if topic in user_text:
            return topic
    return "未指明事项"


def _build_messages(user_text: str, context: dict[str, Any] | None) -> list[dict[str, str]]:
    profile_text = ""
    if context:
        profile_text = context.get("prompt_text", "")
    time_context = current_time_context()
    schema = """
返回严格 JSON：
{
  "has_completion_signal": true,
  "completion_target": "面试",
  "has_correction_intent": false,
  "primary_emotion": "焦虑",
  "secondary_emotion": "疲惫",
  "valence": "negative|positive|neutral|vulnerable",
  "is_casual_chat": false,
  "has_followup_invitation": false,
  "topics": ["面试", "工作"],
  "unfinished_items": ["准备面试材料"],
  "information_density": 0.0
}
只判断用户当前消息，不要编造长期记忆。
"""
    return [
        {"role": "system", "content": f"你是记忆意图分类器，只输出 JSON，不输出解释。\n{time_context['prompt_text']}"},
        {"role": "user", "content": f"{schema}\n已有上下文：\n{profile_text}\n用户消息：{user_text}"},
    ]


def _normalize_intent(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "has_completion_signal": bool(payload.get("has_completion_signal", False)),
        "completion_target": payload.get("completion_target"),
        "has_correction_intent": bool(payload.get("has_correction_intent", False)),
        "primary_emotion": str(payload.get("primary_emotion", "平稳")),
        "secondary_emotion": payload.get("secondary_emotion"),
        "valence": str(payload.get("valence", "neutral")),
        "is_casual_chat": bool(payload.get("is_casual_chat", False)),
        "has_followup_invitation": bool(payload.get("has_followup_invitation", False)),
        "topics": [str(item) for item in payload.get("topics", [])],
        "unfinished_items": [str(item) for item in payload.get("unfinished_items", [])],
        "information_density": float(payload.get("information_density", 0.0)),
    }
