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
    name_match = re.search(
        r"(?:名字|姓名|称呼)(?:叫做|设定为|叫|是|为)?[:： ]*([^\n，。,.；;]{1,16})",
        text,
    ) or re.search(r"(?:你叫|你是|叫做|称为)[:： ]*([^\n，。,.；;]{1,16})", text)
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


# ---------------------------------------------------------------------------
# improved prompts for multi-person / narrative inference
# ---------------------------------------------------------------------------


def persona_learning_prompt_v2(
    text: str,
    source_type: str = "mixed",
    persona_name: str | None = None,
) -> list[dict[str, str]]:
    """Extended learning prompt that handles multi-person narratives.

    When *persona_name* is provided the LLM uses it to pick the correct
    subject out of a story that mentions several characters.
    """

    name_hint = (
        f"需要分析的主体名字是「{persona_name}」。请在文本中寻找关于这个人物的信息。"
        if persona_name
        else "文本中可能没有直接给出名字，请从代词（她/他/你）或上下文推断谁是主体。"
    )
    return [
        {
            "role": "system",
            "content": (
                "你是人格设定分析器。请从导入的背景故事或聊天记录中提取可扮演的人格设定。\n\n"
                f"{name_hint}\n\n"
                "分析规则：\n"
                "1. 如果文本中有多个人物，根据给定的名字确定主体。如果文本中没有明确名字，"
                "从代词（她/他/你）或上下文中推断谁是核心人物。\n"
                "2. 区分不同类型的描述：\n"
                "   - 直接描述：「她很温柔」→ 特质：温柔\n"
                "   - 经历推断：「她经历过战争，失去了家人」→ 可能特质：坚韧、成熟、有故事\n"
                "   - 行为推断：「她总是先为别人着想」→ 可能特质：善良、体贴\n"
                "   - 对话推断：从聊天记录中的语气、用词推断口癖和表达风格\n"
                "3. 对于从经历/行为推断出的特质，如果不太确定，confidence 可以设为中等。\n"
                "4. 不要复述隐私原文，不要编造材料外的事实。\n"
                "5. 如果某个字段信息不足，留空数组或 null，不要把猜测当事实。\n\n"
                "输出 JSON object，字段包括：\n"
                "- name: 名字（字符串或 null）\n"
                "- relationship_to_user: 与用户的关系（字符串或 null）\n"
                "- summary: 人格摘要（1-3句话）\n"
                "- traits: 性格特征数组（最多 8 项）\n"
                "- speaking_style: 说话方式数组（最多 8 项）\n"
                "- catchphrases: 口癖数组（最多 8 项）\n"
                "- habits: 习惯数组（最多 8 项）\n"
                "- emotional_style: 情绪风格数组（最多 6 项）\n"
                "- conversation_habits: 聊天习惯数组（最多 8 项）\n"
                "- taboo_phrases: 禁忌用语数组（最多 8 项）\n"
                "- needs_clarification: 不确定或缺失的重要字段名数组\n"
                "- clarifying_questions: 想进一步问用户的问题（不超过 3 个）\n"
                "- confidence: 整体信心评分（0-1 的小数）\n"
            ),
        },
        {"role": "user", "content": f"source_type={source_type}\n{text[:12000]}"},
    ]


def persona_refine_prompt(
    current_profile: dict[str, Any],
    conversation_history: list[dict[str, str]],
    user_message: str,
) -> list[dict[str, str]]:
    """Build messages for a refinement turn during the import learning dialogue."""

    system_content = (
        "你是一个人格设定分析器，正在与用户进行对话以完善人格设定。\n\n"
        f"当前人格设定：\n{json.dumps(current_profile, ensure_ascii=False, indent=2)}\n\n"
        "用户会提供反馈、补充信息或纠正。请根据反馈更新设定。\n"
        "输出 JSON object，字段包括：\n"
        "- reply: 你的自然语言回复（1-3 句话，可以确认改动、追问细节或给出建议）\n"
        "- profile_diff: 对当前设定的增量更新（只包含需要修改或新增的字段，未变字段不放入）\n"
        "- clarifying_questions: 还想进一步了解的问题（不超过 2 个，不需要时为空数组）\n"
        "- is_complete: 觉得设定是否已经足够完善（布尔值）\n"
    )
    recent = conversation_history[-8:] if len(conversation_history) > 8 else conversation_history
    return [
        {"role": "system", "content": system_content},
        *recent,
        {"role": "user", "content": user_message},
    ]


def merge_profile_diff(base_profile: dict[str, Any], profile_diff: dict[str, Any]) -> dict[str, Any]:
    """Apply incremental profile updates, replacing list fields when provided."""

    merged = dict(base_profile)
    for key in ("name", "relationship_to_user", "summary"):
        value = profile_diff.get(key)
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
        value = profile_diff.get(key)
        if isinstance(value, list) and value:
            merged[key] = _unique([str(item).strip() for item in value if str(item).strip()])[:8]
    merged["learner"] = profile_diff.get("learner") or merged.get("learner", "structured_llm")
    return merged


def parse_refine_json(text: str) -> dict[str, Any]:
    """Parse the JSON output from a refinement turn.  Returns a dict with safe defaults."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {
            "reply": "明白了，我会根据你的反馈调整设定。",
            "profile_diff": {},
            "clarifying_questions": [],
            "is_complete": False,
        }
    if not isinstance(data, dict):
        return {"reply": str(data), "profile_diff": {}, "clarifying_questions": [], "is_complete": False}
    return {
        "reply": str(data.get("reply") or "收到，设定已更新。"),
        "profile_diff": data.get("profile_diff") if isinstance(data.get("profile_diff"), dict) else {},
        "clarifying_questions": (
            data.get("clarifying_questions")
            if isinstance(data.get("clarifying_questions"), list)
            else []
        )[:2],
        "is_complete": bool(data.get("is_complete", False)),
    }


def build_persona_learning_memories(
    persona: dict[str, Any],
    profile: dict[str, Any],
    source_text: str,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Build memory records from a learned persona profile.

    Extracted from ChatService so the import-session flow can reuse it
    without depending on the service's private methods.
    """

    from .memory.schema import make_memory

    name = persona.get("identity", {}).get("name") or "该人格"
    evidence = source_text[:240]
    memories: list[dict[str, Any]] = []

    if profile.get("traits"):
        memories.append(
            make_memory(
                "stable_impression",
                f"{name}的稳定性格：{'、'.join(profile['traits'][:6])}",
                0.82,
                True,
                evidence,
            )
        )
    style_bits = list(profile.get("speaking_style", []))
    if profile.get("catchphrases"):
        style_bits.append(f"口癖：{'、'.join(profile['catchphrases'][:5])}")
    if style_bits:
        memories.append(
            make_memory(
                "response_rule",
                f"扮演{name}时，说话方式偏：{'、'.join(style_bits[:8])}",
                0.84,
                True,
                evidence,
            )
        )
    habits = list(profile.get("habits", [])) + list(profile.get("conversation_habits", []))
    if habits:
        memories.append(
            make_memory(
                "relationship_signal",
                f"{name}的互动习惯：{'、'.join(habits[:8])}",
                0.78,
                True,
                evidence,
            )
        )
    if profile.get("summary"):
        memories.append(
            make_memory("fact", f"{name}的人格摘要：{profile['summary']}", 0.72, True, evidence)
        )

    for memory in memories:
        memory["persona_entity_id"] = entity_id
        memory["source_type"] = "persona_import"
    return memories


# ---------------------------------------------------------------------------
# improved local-fallback name detection
# ---------------------------------------------------------------------------

_NARRATIVE_TRAIT_PATTERNS: dict[str, list[str]] = {
    "经历了": ["有故事", "成熟", "有阅历"],
    "独自": ["独立", "坚强"],
    "失去": ["敏感", "珍惜当下"],
    "保护": ["可靠", "有担当"],
    "照顾": ["温柔", "有耐心"],
    "坚持": ["坚韧", "有毅力"],
    "旅行": ["开朗", "爱自由"],
    "阅读": ["安静", "有深度"],
    "战争": ["坚韧", "深刻"],
    "病": ["坚强", "敏感"],
    "创业": ["有主见", "抗压"],
    "支教": ["善良", "有理想"],
    "留学": ["独立", "适应力强"],
    "画画": ["细腻", "安静"],
    "写": ["细腻", "有表达欲"],
    "音乐": ["感性", "细腻"],
}


def _infer_traits_from_narrative(text: str) -> list[str]:
    """Heuristic trait inference from narrative keywords — local fallback only."""

    traits: list[str] = []
    for keyword, candidates in _NARRATIVE_TRAIT_PATTERNS.items():
        if keyword in text:
            traits.extend(candidates)
    return _unique(traits)[:6]


def _extract_subject_name(text: str, hint_name: str | None = None) -> str | None:
    """Extract the likely subject name from narrative text.

    If *hint_name* is provided, confirm it appears in the text first.
    Otherwise scans for explicit naming patterns, then sentence-subject names,
    then the most frequent 2–3 character proper noun.
    """

    common_words = {"今天", "明天", "昨天", "以前", "现在", "以后", "然后", "但是", "所以", "因为", "不过", "虽然", "其实", "还好", "总是"}

    if hint_name and hint_name.strip() and hint_name.strip() in text:
        return hint_name.strip()

    # explicit naming patterns
    for pattern in [
        r"(?:名字|姓名|称呼)(?:叫做|设定为|叫|是|为)?[:： ]*([^\n，。,.；;]{1,16})",
        r"(?:你叫|你是|叫做|称为)[:： ]*([^\n，。,.；;]{1,16})",
        r"我叫[:： ]*([^\n，。,.；;]{1,16})",
        r"她叫[:： ]*([^\n，。,.；;]{1,16})",
        r"他叫[:： ]*([^\n，。,.；;]{1,16})",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()

    # sentence-subject pattern: "林夏：" or "林夏走过来" or "林夏从小..."
    subject_match = re.search(r"(?:^|\n|。)([一-鿿]{2,3})(?:[：:，,\s]|[从小跟走说去])", text)
    if subject_match:
        name = subject_match.group(1).strip()
        if name not in common_words:
            return name

    # fallback: most frequent 2-3 char Chinese name-like token
    name_candidates: dict[str, int] = {}
    for match in re.finditer(r"[一-鿿]{2,3}", text):
        token = match.group()
        if token in common_words:
            continue
        if re.search(r"[的了是在不和有就我都要可以没]", token):
            continue
        name_candidates[token] = name_candidates.get(token, 0) + 1
    if name_candidates:
        return max(name_candidates, key=lambda k: name_candidates[k])

    return None
