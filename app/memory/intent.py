from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..time_context import current_time_context
from .params import DEFAULT_MEMORY_PARAMS
from .signals import (
    emotion_tags_for,
    has_completion_signal,
    has_correction_signal,
    has_deletion_signal,
    has_followup_invitation,
    has_task_signal,
    has_time_signal,
    information_density,
    is_high_density,
    looks_like_casual_chat,
)
from .text import topics_from_text, unfinished_items, valence_from_text

PARAMS = DEFAULT_MEMORY_PARAMS.conversation


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
            "has_correction_intent": has_correction_signal(user_text),
            "correction_action": _correction_action(user_text),
            "correction_query": _correction_query(user_text),
            "correction_new_value": _correction_new_value(user_text),
            "primary_emotion": emotions[0] if emotions else "平稳",
            "secondary_emotion": emotions[1] if len(emotions) > 1 else None,
            "valence": valence_from_text(user_text),
            "is_casual_chat": looks_like_casual_chat(user_text),
            "has_followup_invitation": has_followup_invitation(user_text),
            "topics": topics,
            "unfinished_items": unfinished_items(user_text),
            "information_density": round(information_density(user_text), 3),
            "classifier": self.name,
        }

    async def classify_async(self, user_text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.classify(user_text, context)


class StructuredLLMIntentClassifier:
    def __init__(self, gateway: Any, fallback: IntentClassifier | None = None, name: str = "structured_llm_intent") -> None:
        self.name = name
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
        rule_intent = self.fallback.classify(user_text, context)
        intent = _guard_structured_intent(intent, rule_intent)
        intent["classifier"] = self.name
        intent["llm_usage"] = result.usage
        return intent


def choose_intent_classifier(settings: Any, gateway: Any) -> IntentClassifier:
    classifier = getattr(settings, "memory_intent_classifier", "rule")
    if classifier in {"lmstudio", "local"}:
        return StructuredLLMIntentClassifier(gateway, name="structured_lmstudio_intent")
    if classifier in {"llm", "structured", "deepseek"}:
        return StructuredLLMIntentClassifier(gateway)
    return RuleBasedIntentClassifier()


def _completion_target(user_text: str) -> str | None:
    if not has_completion_signal(user_text):
        return None
    for topic in PARAMS.completion_overlap_anchors:
        if topic in user_text:
            return topic
    return "未指明事项"


def _correction_action(user_text: str) -> str | None:
    if has_deletion_signal(user_text):
        return "delete"
    if has_correction_signal(user_text):
        return "correct"
    return None


def _correction_query(user_text: str) -> str | None:
    if not has_correction_signal(user_text):
        return None
    if "不是" in user_text:
        return user_text.split("不是", 1)[1].split("而是", 1)[0].split("，", 1)[0].split(",", 1)[0].strip() or None
    return user_text


def _correction_new_value(user_text: str) -> str | None:
    for marker in ["改成", "其实是", "而是"]:
        if marker in user_text:
            return user_text.split(marker, 1)[1].strip("，, 。.!！") or None
    if "不是" in user_text:
        tail = user_text.split("不是", 1)[1]
        for separator in ["，是", ",是", "，", ","]:
            if separator in tail:
                value = tail.split(separator, 1)[1].strip("，, 。.!！")
                if value.startswith("是"):
                    value = value[1:].strip("，, 。.!！")
                return value or None
    return None


def _build_messages(user_text: str, context: dict[str, Any] | None) -> list[dict[str, str]]:
    profile_text = ""
    if context:
        profile_text = context.get("prompt_text", "")
    time_context = current_time_context()
    time_anchor = f"当前日期：{time_context['date']} {time_context['weekday']}，时区：{time_context['timezone']}。"
    schema = """
返回严格 JSON：
{
  "has_completion_signal": true,
  "completion_target": "面试",
  "has_correction_intent": false,
  "correction_action": "none|delete|correct",
  "correction_query": "要删除或修正的旧记忆线索；没有则为 null",
  "correction_new_value": "修正后的新内容；删除或没有则为 null",
  "primary_emotion": "焦虑",
  "secondary_emotion": "疲惫",
  "valence": "negative|positive|neutral|vulnerable",
  "is_casual_chat": false,
  "has_followup_invitation": false,
  "topics": ["面试", "工作"],
  "unfinished_items": ["准备面试材料"],
  "information_density": 0.0
}
判断规则：
- 只判断用户当前消息，不要编造长期记忆。
- has_completion_signal 只在用户明确表示某件事已经完成、交完、搞定、解决、收工时为 true；“继续准备”“我们继续”不是完成。
- has_followup_invitation 在用户说“上次”“刚才说的”“继续”“还记得”“那个后来”等想接旧话题时为 true。
- has_correction_intent 只在用户明确说旧信息不对、要删除、别记、改成、不是 A 是 B 时为 true。
- correction_action 只能是 delete、correct 或 null；没有纠错时所有 correction_* 字段都为 null。
"""
    return [
        {"role": "system", "content": "你是记忆意图分类器，只输出 JSON，不输出解释。"},
        {"role": "user", "content": f"{time_anchor}\n{schema}\n已有上下文：\n{profile_text}\n用户消息：{user_text}"},
    ]


def _normalize_intent(payload: dict[str, Any]) -> dict[str, Any]:
    correction_action = _normalized_correction_action(payload.get("correction_action"))
    return {
        "has_completion_signal": bool(payload.get("has_completion_signal", False)),
        "completion_target": _optional_string(payload.get("completion_target")),
        "has_correction_intent": bool(payload.get("has_correction_intent", False)) and correction_action is not None,
        "correction_action": correction_action,
        "correction_query": _optional_string(payload.get("correction_query")),
        "correction_new_value": _optional_string(payload.get("correction_new_value")),
        "primary_emotion": str(payload.get("primary_emotion", "平稳")),
        "secondary_emotion": _optional_string(payload.get("secondary_emotion")),
        "valence": str(payload.get("valence", "neutral")),
        "is_casual_chat": bool(payload.get("is_casual_chat", False)),
        "has_followup_invitation": bool(payload.get("has_followup_invitation", False)),
        "topics": [str(item) for item in payload.get("topics", [])],
        "unfinished_items": [str(item) for item in payload.get("unfinished_items", [])],
        "information_density": float(payload.get("information_density", 0.0)),
    }


def _guard_structured_intent(intent: dict[str, Any], rule_intent: dict[str, Any]) -> dict[str, Any]:
    guarded = dict(intent)

    if not rule_intent.get("has_completion_signal"):
        guarded["has_completion_signal"] = False
        guarded["completion_target"] = None
    else:
        guarded["has_completion_signal"] = True
        guarded["completion_target"] = rule_intent.get("completion_target") or guarded.get("completion_target")

    guarded["has_followup_invitation"] = bool(
        guarded.get("has_followup_invitation") or rule_intent.get("has_followup_invitation")
    )

    if rule_intent.get("has_correction_intent"):
        guarded["has_correction_intent"] = True
        guarded["correction_action"] = guarded.get("correction_action") or rule_intent.get("correction_action")
        guarded["correction_query"] = guarded.get("correction_query") or rule_intent.get("correction_query")
        guarded["correction_new_value"] = guarded.get("correction_new_value") or rule_intent.get("correction_new_value")
    elif guarded.get("correction_action") in {"delete", "correct"}:
        guarded["has_correction_intent"] = True
    else:
        guarded["has_correction_intent"] = False
        guarded["correction_action"] = None
        guarded["correction_query"] = None
        guarded["correction_new_value"] = None

    rule_topics = [topic for topic in rule_intent.get("topics", []) if topic not in guarded.get("topics", [])]
    guarded["topics"] = [*guarded.get("topics", []), *rule_topics]
    guarded["information_density"] = max(
        float(guarded.get("information_density") or 0.0),
        float(rule_intent.get("information_density") or 0.0),
    )
    return guarded


def _normalized_correction_action(action: Any) -> str | None:
    normalized = str(action or "").strip().lower()
    if normalized in {"delete", "correct"}:
        return normalized
    return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"none", "null", "nil", "n/a", "na"}:
        return None
    if text in {"无", "没有", "无此项", "未指明"}:
        return None
    return text
