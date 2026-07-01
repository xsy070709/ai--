from __future__ import annotations

from typing import Any

from .schema import make_memory


def generate_reflections(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [m for m in memories if m.get("status") == "active"]
    reflections: list[dict[str, Any]] = []

    if _has_type(active, "emotion_pattern") and _has_response_rule(active, ["安慰", "大道理", "拆"]):
        reflections.append(
            make_memory(
                "stable_impression",
                "用户在压力或焦虑时，更需要先被安慰和理解，再一起拆成小步；不适合一上来讲大道理。",
                0.82,
                False,
                "由情绪模式和回应规则共同巩固",
                valence="vulnerable",
                stability="high",
            )
        )

    if len([m for m in active if m.get("type") == "goal" and m.get("open")]) >= 2:
        reflections.append(
            make_memory(
                "stable_impression",
                "用户经常把未完成事项带进聊天，适合用轻量陪伴式跟进帮助其排序和推进。",
                0.76,
                False,
                "由多个开放待办事项巩固",
                valence="neutral",
                stability="medium",
            )
        )

    if _has_type(active, "shared_experience") and _has_type(active, "relationship_signal"):
        reflections.append(
            make_memory(
                "stable_impression",
                "用户已经开始把 AI 当作可以接续共同话题和情绪状态的长期聊天对象。",
                0.74,
                False,
                "由共同经历和关系信号共同巩固",
                valence="positive",
                stability="medium",
            )
        )

    return _new_reflections_only(active, reflections)


def _has_type(memories: list[dict[str, Any]], memory_type: str) -> bool:
    return any(memory.get("type") == memory_type for memory in memories)


def _has_response_rule(memories: list[dict[str, Any]], keywords: list[str]) -> bool:
    return any(memory.get("type") == "response_rule" and any(keyword in memory.get("content", "") for keyword in keywords) for memory in memories)


def _new_reflections_only(existing: list[dict[str, Any]], reflections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_contents = [memory.get("content", "") for memory in existing if memory.get("type") == "stable_impression"]
    result = []
    for reflection in reflections:
        if not any(reflection["content"] in content or content in reflection["content"] for content in existing_contents):
            result.append(reflection)
    return result
