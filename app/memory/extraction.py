from __future__ import annotations

import re
from typing import Any

from .schema import make_memory
from .signals import has_task_signal, has_time_signal, information_density, is_high_density
from .text import clean_text, emotion_cause, emotion_tags, first_sentence, infer_type, normalize_content, valence_from_text


def extract_memory_candidates(user_text: str, assistant_text: str = "") -> list[dict[str, Any]]:
    text = clean_text(user_text)
    candidates: list[dict[str, Any]] = []
    candidates.extend(_extract_explicit_memory(text))
    candidates.extend(_extract_preferences(text))
    candidates.extend(_extract_response_rules(text))
    candidates.extend(_extract_boundaries(text))
    candidates.extend(_extract_goals_and_tasks(text))
    candidates.extend(_extract_emotion_patterns(text))
    candidates.extend(_extract_relationship_signals(text))
    candidates.extend(_extract_shared_experiences(text))
    candidates.extend(_extract_episodic_memory(text))
    return _dedupe(candidates)


def _extract_explicit_memory(text: str) -> list[dict[str, Any]]:
    candidates = []
    for match in re.finditer(r"(?:记住|帮我记住|你要记得)[：:，, ]*(.+)", text):
        content = first_sentence(match.group(1)).strip("。.!！ ")
        memory_type = infer_type(content)
        candidates.append(
            make_memory(
                memory_type,
                normalize_content(memory_type, content),
                0.92,
                True,
                text,
                open_item=memory_type == "goal",
                valence=valence_from_text(content),
                stability="high",
            )
        )
    return candidates


def _extract_preferences(text: str) -> list[dict[str, Any]]:
    candidates = []
    patterns = [
        ("preference", r"我(?:很|挺|特别|最)?喜欢([^。！？.!?]{1,48})"),
        ("preference", r"我(?:更|比较)?希望([^。！？.!?]{1,48})"),
        ("dislike", r"我(?:很|挺|特别|最)?(?:讨厌|不喜欢|受不了)([^。！？.!?]{1,48})"),
    ]
    for memory_type, pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = match.group(1).strip("，, ")
            candidates.append(
                make_memory(
                    memory_type,
                    normalize_content(memory_type, raw),
                    0.78,
                    False,
                    text,
                    valence=valence_from_text(text),
                    stability="medium",
                )
            )
    return candidates


def _extract_response_rules(text: str) -> list[dict[str, Any]]:
    candidates = []
    rule_patterns = [
        r"(?:以后|下次|和我聊天时)(?:尽量|最好|要)?([^。！？.!?]{1,60})",
        r"((?:别|不要)[^。！？.!?]{1,60})",
    ]
    for pattern in rule_patterns:
        for match in re.finditer(pattern, text):
            raw = match.group(1).strip("，, ")
            if any(word in raw for word in ["回复", "说教", "大道理", "安慰", "分析", "叫我", "催", "问"]):
                content = raw if raw.startswith(("别", "不要")) else f"和用户互动时{raw}"
                candidates.append(
                    make_memory(
                        "response_rule",
                        content,
                        0.84,
                        "以后" in text or "下次" in text,
                        text,
                        valence=valence_from_text(text),
                        stability="high",
                    )
                )
    return candidates


def _extract_boundaries(text: str) -> list[dict[str, Any]]:
    if any(word in text for word in ["雷区", "不要提", "别提", "不想聊"]):
        return [
            make_memory(
                "boundary",
                f"用户当前不希望触碰的话题：{text}",
                0.84,
                True,
                text,
                valence="negative",
                stability="high",
                sensitivity_level="medium",
            )
        ]
    return []


def _extract_goals_and_tasks(text: str) -> list[dict[str, Any]]:
    candidates = []
    has_time = has_time_signal(text)
    has_task = has_task_signal(text)
    if has_time and has_task:
        candidates.append(make_memory("goal", f"待跟进：{text}", 0.78, False, text, open_item=True, valence=valence_from_text(text)))
    if any(word in text for word in ["目标", "计划", "想要", "希望做到"]):
        candidates.append(make_memory("goal", f"用户目标：{text}", 0.72, False, text, open_item=True, valence=valence_from_text(text)))
    return candidates


def _extract_emotion_patterns(text: str) -> list[dict[str, Any]]:
    emotions = emotion_tags(text)
    if emotions == ["烦躁"] and "麻烦" in text and not any(word in text for word in ["烦躁", "烦死", "烦人", "生气", "火大", "崩溃", "破防"]):
        return []
    if not emotions:
        return []
    cause = emotion_cause(text)
    suffix = "中" if cause == "当前情境" else "相关情境中"
    return [
        make_memory(
            "emotion_pattern",
            f"用户在{cause}{suffix}容易感到{'、'.join(emotions)}",
            0.68,
            False,
            text,
            valence=valence_from_text(text),
            stability="medium",
        )
    ]


def _extract_relationship_signals(text: str) -> list[dict[str, Any]]:
    if any(word in text for word in ["你真懂我", "还是你懂我", "你陪我", "我想跟你说", "只想和你聊"]):
        return [make_memory("relationship_signal", f"用户对 AI 的关系信号：{text}", 0.64, False, text, valence="positive")]
    if any(word in text for word in ["你没懂", "你不像朋友", "你太机械", "别像客服"]):
        return [make_memory("relationship_signal", f"用户对互动方式不满意：{text}", 0.74, True, text, valence="negative")]
    return []


def _extract_shared_experiences(text: str) -> list[dict[str, Any]]:
    if any(word in text for word in ["我们约定", "一起", "下次继续", "刚才说好", "以后我们"]):
        return [
            make_memory(
                "shared_experience",
                f"共同经历/约定：{text}",
                0.74,
                False,
                text,
                open_item="下次" in text or "继续" in text,
                valence=valence_from_text(text),
            )
        ]
    return []


def _extract_episodic_memory(text: str) -> list[dict[str, Any]]:
    has_event_context = any(word in text for word in ["今天", "刚才", "昨晚", "这次", "现在", "分手", "失恋"]) and any(
        word in text for word in ["发生", "聊", "做", "遇到", "感觉", "因为", "分手", "失恋"]
    )
    if has_event_context and (len(text) > 18 or is_high_density(text)):
        return [make_memory("episodic", f"近期事件：{text}", 0.58, False, text, valence=valence_from_text(text), stability="low")]
    if information_density(text) >= 2.4 and any(word in text for word in ["分手", "失恋", "被辞", "吵架"]):
        return [make_memory("episodic", f"近期事件：{text}", 0.62, False, text, valence=valence_from_text(text), stability="low")]
    return []


def _dedupe(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = f"{candidate['type']}:{candidate['content'][:24]}"
        if key not in deduped or candidate["confidence"] > deduped[key]["confidence"]:
            deduped[key] = candidate
    return list(deduped.values())
