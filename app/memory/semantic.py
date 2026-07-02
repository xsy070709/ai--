from __future__ import annotations

import hashlib
import math

from .params import DEFAULT_MEMORY_PARAMS
from .signals import emotion_tags_for
from .text import tokens, topics_from_text


PARAMS = DEFAULT_MEMORY_PARAMS.semantic

ALIASES: dict[str, tuple[str, ...]] = {
    "sleep_problem": ("睡不好", "睡不着", "失眠", "熬夜", "睡眠差", "睡眠不好", "睡眠"),
    "anxiety": ("焦虑", "心慌", "紧张", "不安", "压力", "stress", "stressed"),
    "fatigue": ("累", "疲惫", "没劲", "困", "tired", "exhausted"),
    "completion": ("搞定", "收工", "完事", "完成", "交完", "交了", "解决"),
    "interview": ("面试", "自我介绍", "简历", "offer"),
    "project": ("项目", "任务", "材料", "报告", "作业"),
    "breakup": ("分手", "失恋", "吵架", "关系结束"),
}


def semantic_vector(text: str, dimensions: int = PARAMS.vector_dimensions) -> list[float]:
    vector = [0.0 for _ in range(dimensions)]
    for term, weight in semantic_terms(text):
        index = _stable_index(term, dimensions)
        vector[index] += weight
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def semantic_similarity(left: str, right: str) -> float:
    return cosine_similarity(semantic_vector(left), semantic_vector(right))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def semantic_terms(text: str) -> list[tuple[str, float]]:
    lowered = text.lower()
    terms: list[tuple[str, float]] = []
    for token in tokens(text):
        terms.append((f"token:{token.lower()}", 1.0))
    for topic in topics_from_text(text):
        if topic != "日常聊天":
            terms.append((f"topic:{topic}", 1.2))
    for emotion in emotion_tags_for(text):
        terms.append((f"emotion:{emotion}", 1.25))
    for concept, words in ALIASES.items():
        if any(word.lower() in lowered for word in words):
            terms.append((f"concept:{concept}", 2.0))
    compact = "".join(tokens(text))
    for index in range(max(0, len(compact) - 1)):
        terms.append((f"bigram:{compact[index:index + 2].lower()}", 0.25))
    return terms


def _stable_index(term: str, dimensions: int) -> int:
    digest = hashlib.sha256(term.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dimensions
