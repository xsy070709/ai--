from __future__ import annotations

import re
from typing import Any

from .storage import new_id, now_iso


def _list_from_keywords(text: str, keywords: list[str], fallback: list[str]) -> list[str]:
    found = [keyword for keyword in keywords if keyword in text]
    return found[:5] or fallback


def initialize_persona(background_text: str) -> dict[str, Any]:
    text = background_text.strip()
    name_match = re.search(r"(?:名字|姓名|称呼)[:： ]*([^\n，。,.]{1,16})", text)
    relation_match = re.search(r"(?:关系|定位)[:： ]*([^\n。]{1,40})", text)
    name = name_match.group(1).strip() if name_match else "未命名好友"
    relationship = relation_match.group(1).strip() if relation_match else "长期陪伴型虚拟好友"

    stable_traits = _list_from_keywords(
        text,
        ["温柔", "理性", "活泼", "毒舌", "安静", "可靠", "敏感", "坦率", "幽默", "克制"],
        ["稳定", "真诚", "有边界感"],
    )
    speaking_style = _list_from_keywords(
        text,
        ["短句", "口语", "撒娇", "认真", "吐槽", "轻松", "直接", "少说教"],
        ["自然口语", "先回应情绪", "避免长篇说教"],
    )
    boundaries = _list_from_keywords(
        text,
        ["不泄露隐私", "不伪装真人", "不替用户做决定", "不强迫", "不过度依赖"],
        ["不伪装真人", "不泄露第三方隐私", "不承诺现实身份"],
    )

    system_prompt = "\n".join(
        [
            f"你是{name}，定位是{relationship}。",
            f"你的稳定性格包括：{'、'.join(stable_traits)}。",
            f"你的说话方式：{'、'.join(speaking_style)}。",
            f"你的边界：{'、'.join(boundaries)}。",
            "你需要像熟悉的虚拟好友一样聊天，默认短回复，先接住情绪，再回应事实。",
            "你可以学习用户偏好和共同经历，但不能随意改变核心人格。",
        ]
    )

    return {
        "id": new_id("persona"),
        "version": 1,
        "status": "draft",
        "created_at": now_iso(),
        "source": {"type": "background_text", "content": text},
        "identity": {
            "name": name,
            "role": "virtual_friend",
            "relationship_to_user": relationship,
            "self_description": f"{name}是{relationship}。",
        },
        "personality": {
            "stable_traits": stable_traits,
            "emotional_style": ["先共情", "再追问", "不过度说教"],
            "humor_style": ["轻微打趣", "不攻击用户"],
            "conflict_style": ["温和确认", "必要时说明边界"],
        },
        "speaking_style": {
            "tone": speaking_style,
            "sentence_length": "short_to_medium",
            "emoji_policy": "少量使用，默认不用",
            "taboo_phrases": ["根据系统显示", "作为一个AI语言模型"],
        },
        "behavior_rules": {
            "comfort_user": ["先承认感受", "避免立刻讲大道理", "必要时陪用户拆问题"],
            "ask_follow_up": ["信息不足时追问一个具体问题"],
            "proactive_topics": ["近期未完成事项", "用户明确喜欢的话题"],
            "forbidden_behaviors": boundaries,
        },
        "boundaries": {
            "privacy_rules": ["不泄露第三方隐私", "不把历史原文随意复述给用户"],
            "dependency_boundaries": ["不鼓励用户只依赖 AI", "重大决定建议用户联系现实支持"],
            "safety_rules": boundaries,
        },
        "system_prompt": {"version": "initial", "content": system_prompt},
    }


def active_persona_text(persona: dict[str, Any] | None) -> str:
    if not persona:
        return "你是一个有边界感的虚拟好友，正在等待用户导入背景设定。"
    return persona.get("system_prompt", {}).get("content", "")
