from __future__ import annotations

import re


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def tokens(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+", text)


def topics_from_text(text: str) -> list[str]:
    topics = []
    for keyword in ["工作", "学习", "游戏", "朋友", "家庭", "项目", "情绪", "睡眠", "面试", "考试", "回复", "材料", "聊天"]:
        if keyword in text:
            topics.append(keyword)
    return topics or ["日常聊天"]


def emotion_tags(text: str) -> list[str]:
    mapping = {
        "压力": ["压力", "焦虑", "紧张", "拖延", "效率不高"],
        "疲惫": ["累", "困", "疲惫", "没劲"],
        "低落": ["难受", "委屈", "低落", "沮丧"],
        "烦躁": ["烦", "烦躁", "生气", "火大"],
        "积极": ["开心", "高兴", "舒服", "顺利"],
        "脆弱": ["害怕", "崩溃", "撑不住", "想哭"],
    }
    return [label for label, words in mapping.items() if any(word in text for word in words)]


def emotion_cause(text: str) -> str:
    for topic in ["项目", "工作", "学习", "考试", "面试", "朋友", "家庭", "睡眠", "材料"]:
        if topic in text:
            return topic
    return "类似情境"


def unfinished_items(text: str) -> list[str]:
    items = []
    for sentence in re.split(r"[。！？.!?]", text):
        if any(time_word in sentence for time_word in ["明天", "今晚", "下午", "周末", "下周", "月底", "等会"]) and any(
            verb in sentence for verb in ["要", "得", "准备", "提交", "面试", "考试", "开会", "做完", "交材料"]
        ):
            items.append(sentence.strip())
    return items[:5]


def canonical_content(memory: dict) -> str:
    content = memory.get("content", "")
    content = re.sub(r"用户(?:喜欢或偏好|反感或不喜欢)", "", content)
    content = re.sub(r"^(?:我)?(?:喜欢|希望|偏好|讨厌|不喜欢)", "", content)
    content = content.replace("回复方式", "回复")
    content = re.sub(r"[，,。.!！；;\s]", "", content)
    return content


def normalize_content(memory_type: str, raw: str) -> str:
    raw = raw.strip("，, 。.!！")
    raw = re.sub(r"^(?:我)?(?:很|挺|特别|最|比较|更)?(?:喜欢|希望|偏好)", "", raw).strip("，, ")
    raw = re.sub(r"^我(?:不喜欢|讨厌|受不了)", "", raw).strip("，, ")
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
    if any(word in text for word in ["害怕", "崩溃", "难受", "撑不住", "焦虑", "压力"]):
        return "vulnerable"
    if any(word in text for word in ["讨厌", "烦", "生气", "雷区"]):
        return "negative"
    if any(word in text for word in ["开心", "喜欢", "舒服", "顺利"]):
        return "positive"
    return "neutral"
