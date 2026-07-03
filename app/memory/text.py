from __future__ import annotations

import re

from .params import DEFAULT_MEMORY_PARAMS
from .signals import emotion_tags_for, has_task_signal, has_time_signal

PARAMS = DEFAULT_MEMORY_PARAMS


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def first_sentence(text: str) -> str:
    parts = [part.strip() for part in re.split(r"[。！？.!?]", text) if part.strip()]
    return parts[0] if parts else text.strip()


def tokens(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+", text)


def topics_from_text(text: str) -> list[str]:
    topics = []
    for keyword in PARAMS.signals.topic_words:
        if keyword in text:
            topics.append(keyword)
    return topics or ["日常聊天"]


def emotion_tags(text: str) -> list[str]:
    return emotion_tags_for(text)


def emotion_cause(text: str) -> str:
    for topic in PARAMS.signals.topic_words:
        if topic in text:
            return topic
    return "当前情境"


def unfinished_items(text: str) -> list[str]:
    items = []
    for sentence in re.split(r"[。！？.!?]", text):
        if has_time_signal(sentence) and has_task_signal(sentence):
            items.append(sentence.strip())
    return items[:5]


def canonical_content(memory: dict) -> str:
    content = memory.get("content", "")
    content = re.sub(r"用户(?:喜欢或偏好|反感或不喜欢)", "", content)
    content = re.sub(r"^和用户互动时", "", content)
    content = content.replace("不要", "别")
    content = re.sub(r"^(?:我)?(?:喜欢|希望|偏好|讨厌|不喜欢)", "", content)
    content = content.replace("回复方式", "回复")
    content = content.replace("安静一点的回复", "安静回复")
    content = re.sub(r"[，,。.!！；;\s]", "", content)
    return content


def normalize_content(memory_type: str, raw: str) -> str:
    raw = first_sentence(raw).strip("，, 。.!！")
    raw = re.sub(r"^(?:我)?(?:很|挺|特别|最|比较|更)?(?:喜欢|希望|偏好)", "", raw).strip("，, ")
    raw = re.sub(r"^我(?:不喜欢|讨厌|受不了)", "", raw).strip("，, ")
    raw = re.sub(r"^你", "", raw).strip("，, ")
    if memory_type == "preference" and not raw.startswith("用户"):
        return f"用户喜欢或偏好{raw}"
    if memory_type == "dislike" and not raw.startswith("用户"):
        return f"用户反感或不喜欢{raw}"
    return raw


def infer_type(content: str) -> str:
    if any(word in content for word in ["喜欢", "偏好", "希望"]):
        return "preference"
    if any(word in content for word in ["讨厌", "不喜欢", "雷区", "别提"]):
        return "dislike"
    if any(word in content for word in ["回复", "说教", "安慰", "叫我", "大道理"]):
        return "response_rule"
    if any(word in content for word in ["明天", "今晚", "下周", "目标", "计划", "要做", "材料"]):
        return "goal"
    return "fact"


def valence_from_text(text: str) -> str:
    emotions = set(emotion_tags(text))
    if emotions & {"脆弱", "压力", "低落"}:
        return "vulnerable"
    if any(word in text for word in ["讨厌", "烦", "生气", "雷区"]):
        return "negative"
    if any(word in text for word in ["开心", "喜欢", "舒服", "顺利"]):
        return "positive"
    return "neutral"
