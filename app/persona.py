from __future__ import annotations

import json
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


def learn_persona_profile(
    text: str,
    *,
    source_type: str = "background_story",
    llm_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize imported materials into a persona profile.

    The LLM path can provide a profile with the same keys. The local learner is
    deliberately conservative so imports work without network access.
    """

    local_profile = _fallback_persona_profile(text, source_type=source_type)
    if not llm_profile:
        return local_profile
    return _merge_profile(local_profile, llm_profile)


def persona_from_learned_profile(
    text: str,
    profile: dict[str, Any],
    *,
    source_type: str = "background_story",
) -> dict[str, Any]:
    persona = initialize_persona(text)
    identity = persona.setdefault("identity", {})
    personality = persona.setdefault("personality", {})
    speaking_style = persona.setdefault("speaking_style", {})
    behavior_rules = persona.setdefault("behavior_rules", {})

    if profile.get("name"):
        identity["name"] = profile["name"]
    if profile.get("relationship_to_user"):
        identity["relationship_to_user"] = profile["relationship_to_user"]
    identity["self_description"] = profile.get("summary") or identity.get("self_description", "")

    personality["stable_traits"] = _unique(profile.get("traits") or personality.get("stable_traits", []))[:8]
    personality["habits"] = _unique(profile.get("habits", []))[:8]
    personality["emotional_style"] = _unique(profile.get("emotional_style", []) or personality.get("emotional_style", []))[:6]
    speaking_style["tone"] = _unique(profile.get("speaking_style", []) or speaking_style.get("tone", []))[:8]
    speaking_style["catchphrases"] = _unique(profile.get("catchphrases", []))[:8]
    speaking_style["taboo_phrases"] = _unique(
        profile.get("taboo_phrases", []) or speaking_style.get("taboo_phrases", [])
    )[:8]
    behavior_rules["conversation_habits"] = _unique(profile.get("conversation_habits", []))[:8]

    name = identity.get("name") or "未命名好友"
    relationship = identity.get("relationship_to_user") or "长期陪伴型虚拟好友"
    system_lines = [
        f"你是{name}，定位是{relationship}。",
        f"人格摘要：{profile.get('summary') or identity.get('self_description')}",
        f"稳定性格：{'、'.join(personality.get('stable_traits', [])) or '真诚、有边界感'}。",
        f"说话方式：{'、'.join(speaking_style.get('tone', [])) or '自然口语、先回应情绪'}。",
    ]
    if speaking_style.get("catchphrases"):
        system_lines.append(f"可自然使用的口癖：{'、'.join(speaking_style['catchphrases'])}。")
    if personality.get("habits"):
        system_lines.append(f"习惯和互动偏好：{'、'.join(personality['habits'])}。")
    system_lines.extend(
        [
            "你需要像熟悉的虚拟好友一样聊天，默认短回复，先接住情绪，再回应事实。",
            "导入材料是人格学习来源，不要逐字背诵或暴露原始聊天记录。",
            "你可以持续学习风格和关系细节，但不能随意改变核心人格边界。",
        ]
    )
    persona["source"] = {"type": source_type, "content": text}
    persona["learned_profile"] = profile
    persona["system_prompt"] = {"version": "learned", "content": "\n".join(system_lines)}
    return persona


def persona_learning_prompt(text: str, source_type: str = "mixed") -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是人格设定分析器。请从导入的背景故事或聊天记录中总结可扮演的人格设定。"
                "只输出 JSON object，字段包括：name, relationship_to_user, summary, traits, "
                "speaking_style, catchphrases, habits, emotional_style, conversation_habits, taboo_phrases。"
                "数组字段最多 8 项，不要复述隐私原文，不要编造材料外事实。"
            ),
        },
        {"role": "user", "content": f"source_type={source_type}\n{text[:12000]}"},
    ]


def parse_persona_learning_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def active_persona_text(persona: dict[str, Any] | None) -> str:
    if not persona:
        return "你是一个有边界感的虚拟好友，正在等待用户导入背景设定。"
    return persona.get("system_prompt", {}).get("content", "")


def _fallback_persona_profile(text: str, *, source_type: str) -> dict[str, Any]:
    content = text.strip()
    base = initialize_persona(content)
    identity = base["identity"]
    traits = _unique(
        base["personality"]["stable_traits"]
        + _list_from_keywords(
            content,
            ["傲娇", "嘴硬心软", "慢热", "粘人", "独立", "敏锐", "靠谱", "认真", "随性", "耐心", "强势", "温和"],
            [],
        )
    )
    speaking_style = _unique(
        base["speaking_style"]["tone"]
        + _list_from_keywords(
            content,
            ["省略号", "反问", "短促", "软一点", "冷幽默", "直球", "碎碎念", "不端着", "像朋友", "少表情"],
            [],
        )
    )
    catchphrases = _extract_labeled_list(content, ["口癖", "常说", "常用语", "招牌话"])
    catchphrases.extend(_extract_quoted_phrases(content))
    habits = _extract_labeled_list(content, ["习惯", "日常", "经常", "喜欢做"])
    conversation_habits = _extract_labeled_list(content, ["聊天习惯", "回复习惯", "互动方式"])
    if "先安慰" in content or "先共情" in content:
        conversation_habits.append("先安慰或共情，再分析问题")
    if "不说教" in content or "少说教" in content:
        conversation_habits.append("避免上来就讲大道理")

    summary_bits = []
    if traits:
        summary_bits.append(f"性格偏{'、'.join(traits[:4])}")
    if speaking_style:
        summary_bits.append(f"表达偏{'、'.join(speaking_style[:4])}")
    if habits:
        summary_bits.append(f"习惯包括{'、'.join(habits[:3])}")
    summary = "；".join(summary_bits) or identity["self_description"]
    if source_type == "chat_log":
        summary = f"根据聊天记录学习到：{summary}"

    return {
        "name": identity.get("name"),
        "relationship_to_user": identity.get("relationship_to_user"),
        "summary": summary,
        "traits": traits[:8],
        "speaking_style": speaking_style[:8],
        "catchphrases": _unique(catchphrases)[:8],
        "habits": _unique(habits)[:8],
        "emotional_style": base["personality"].get("emotional_style", []),
        "conversation_habits": _unique(conversation_habits)[:8],
        "taboo_phrases": base["speaking_style"].get("taboo_phrases", []),
        "source_type": source_type,
        "learner": "local_rule",
    }


def _merge_profile(local: dict[str, Any], learned: dict[str, Any]) -> dict[str, Any]:
    merged = dict(local)
    for key in ("name", "relationship_to_user", "summary"):
        value = learned.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    for key in (
        "traits",
        "speaking_style",
        "catchphrases",
        "habits",
        "emotional_style",
        "conversation_habits",
        "taboo_phrases",
    ):
        values = learned.get(key)
        if isinstance(values, list):
            merged[key] = _unique([str(item).strip() for item in values if str(item).strip()])[:8] or merged.get(key, [])
    merged["learner"] = learned.get("learner") or "structured_llm"
    return merged


def _extract_labeled_list(text: str, labels: list[str]) -> list[str]:
    values: list[str] = []
    for label in labels:
        for match in re.finditer(rf"{label}[：: ]*([^\n。；;]+)", text):
            values.extend(_split_items(match.group(1)))
    return values


def _extract_quoted_phrases(text: str) -> list[str]:
    phrases = []
    for match in re.finditer(r"[“\"']([^“”\"'\n]{2,24})[”\"']", text):
        phrase = match.group(1).strip()
        if any(word in phrase for word in ["我", "你", "啦", "嘛", "呀", "呢", "好"]):
            phrases.append(phrase)
    return phrases


def _split_items(value: str) -> list[str]:
    return [item.strip(" ，、,;；。") for item in re.split(r"[、,，/；;]", value) if item.strip(" ，、,;；。")]


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result
