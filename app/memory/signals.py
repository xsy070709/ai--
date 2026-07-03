from __future__ import annotations

import re

from .params import DEFAULT_MEMORY_PARAMS


PARAMS = DEFAULT_MEMORY_PARAMS

EMOTION_GROUPS: dict[str, tuple[str, ...]] = {
    "压力": ("压力", "焦虑", "紧张", "拖延", "效率不高", "心慌", "不安", "慌", "压力山大", "stress", "stressed"),
    "疲惫": ("累", "困", "疲惫", "没劲", "很 tired", "very tired", "tired", "exhausted", "burnt out"),
    "低落": ("难受", "委屈", "低落", "沮丧", "emo", "emo了", "失落", "空落", "分手", "失恋", "麻了"),
    "烦躁": ("烦", "烦躁", "生气", "火大", "崩溃", "破防", "心态炸", "炸了"),
    "积极": ("开心", "高兴", "舒服", "顺利", "爽", "轻松", "一身轻松"),
    "脆弱": ("害怕", "崩溃", "撑不住", "想哭", "破防", "顶不住", "绷不住", "心态炸"),
}


def contains_any(text: str, words: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def emotion_tags_for(text: str) -> list[str]:
    return [label for label, words in EMOTION_GROUPS.items() if contains_any(text, words)]


def has_completion_signal(text: str) -> bool:
    return contains_any(text, PARAMS.conversation.completion_words)


def has_correction_signal(text: str) -> bool:
    return contains_any(text, PARAMS.signals.correction_words) or has_deletion_signal(text)


def has_deletion_signal(text: str) -> bool:
    return contains_any(text, PARAMS.signals.deletion_words)


def has_time_signal(text: str) -> bool:
    return contains_any(text, PARAMS.signals.time_words) or bool(_NUMERIC_TIME_RE.search(text))


def has_task_signal(text: str) -> bool:
    return contains_any(text, PARAMS.signals.task_words)


def information_density(text: str) -> float:
    stripped = text.strip()
    score = 0.0
    if emotion_tags_for(stripped):
        score += 1.0
    if has_time_signal(stripped):
        score += 0.75
    if has_task_signal(stripped):
        score += 0.75
    if contains_any(stripped, PARAMS.signals.vulnerable_events):
        score += 1.25
    if contains_any(stripped, ("记住", "雷区", "别提", "不想聊")) or has_correction_signal(stripped):
        score += 1.0
    if contains_any(stripped, ("我们约定", "一起", "下次继续", "刚才说好", "以后我们")):
        score += 0.9
    if re.search(r"\d|[一二三四五六七八九十]点|周[一二三四五六日天]", stripped):
        score += 0.4
    if len(stripped) >= 18 and not _mostly_filler(stripped):
        score += 0.35
    if _mostly_filler(stripped):
        score -= 0.7
    return max(score, 0.0)


def is_high_density(text: str) -> bool:
    return information_density(text) >= PARAMS.conversation.high_density_threshold


def looks_like_casual_chat(text: str, exemption_words: tuple[str, ...] | None = None, max_chars: int | None = None) -> bool:
    stripped = text.strip()
    exemptions = exemption_words or PARAMS.conversation.casual_exemption_words
    limit = max_chars if max_chars is not None else PARAMS.conversation.casual_max_chars
    if is_high_density(stripped) or contains_any(stripped, exemptions):
        return False
    if len(stripped) <= limit:
        return True
    return _mostly_filler(stripped) and information_density(stripped) < 1.0


def _mostly_filler(text: str) -> bool:
    compact = re.sub(r"[\s，,。.!！?？~～]+", "", text.lower())
    if not compact:
        return True
    if contains_any(compact, PARAMS.signals.low_density_fillers):
        return True
    repeated = re.sub(r"(哈|啊|嗯|哦|嘿|hh|哈)+", "", compact)
    return len(repeated) <= max(1, len(compact) // 4)


_NUMERIC_TIME_RE = re.compile(r"\d{1,2}[/-]\d{1,2}|\d{1,2}[点:：]\d{0,2}|周[一二三四五六日天]")
