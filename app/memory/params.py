from __future__ import annotations

import json
import os
from dataclasses import fields, is_dataclass
from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RecallParams:
    min_score_threshold: float = 1.05
    token_overlap_multiplier: float = 1.75
    confirmed_bonus: float = 0.55
    open_item_bonus: float = 1.18
    emotion_match_bonus: float = 1.05
    history_continuation_bonus: float = 0.90
    boundary_bonus: float = 0.45
    tone_guidance_bonus: float = 0.25
    cooldown_penalty: float = 1.20
    importance_weight: float = 0.78
    salience_weight: float = 0.46
    confidence_weight: float = 0.35
    semantic_similarity_weight: float = 1.15
    semantic_similarity_threshold: float = 0.24
    default_limit: int = 8
    continuation_words: tuple[str, ...] = ("还记得", "之前", "上次", "继续", "后来")


@dataclass(frozen=True)
class QualityParams:
    reject_min_confidence: float = 0.45
    auto_accept_min_confidence: float = 0.62
    low_stability_confirm_threshold: float = 0.70
    min_content_length: int = 4


@dataclass(frozen=True)
class MaintenanceParams:
    default_max_ephemeral: int = 16
    decay_floor: float = 0.20
    decay_multiplier: float = 0.96
    cooldown_use_threshold: int = 2


@dataclass(frozen=True)
class SummaryParams:
    default_work_memory_limit: int = 24
    casual_work_memory_limit: int = 8
    deep_work_memory_limit: int = 36
    min_summary_messages: int = 16
    topic_shift_min_messages: int = 8
    fixed_summary_interval: int = 16
    max_summary_interval: int = 64
    topic_shift_similarity_threshold: float = 0.35


@dataclass(frozen=True)
class ConversationParams:
    completion_words: tuple[str, ...] = (
        "交完",
        "做完",
        "办完",
        "处理完",
        "完成",
        "结束",
        "面完",
        "考完",
        "提交了",
        "弄完",
        "弄好了",
        "处理好了",
        "解决了",
        "已经好了",
        "搞定",
        "收工",
        "完事",
        "办妥",
        "OK了",
        "ok了",
        "交了",
        "交上去了",
    )
    completion_overlap_anchors: tuple[str, ...] = ("材料", "面试", "考试", "项目", "开会", "作业", "报告", "任务", "简历", "论文", "汇报")
    audit_surface_anchors: tuple[str, ...] = (
        "家里",
        "家庭",
        "项目",
        "压力",
        "焦虑",
        "材料",
        "面试",
        "考试",
        "安静",
        "热闹",
        "大道理",
        "实习",
        "答辩",
        "汇报",
        "简历",
        "论文",
    )
    casual_max_chars: int = 12
    casual_exemption_words: tuple[str, ...] = ("继续", "后来", "上次", "还记得", "怎么办", "焦虑", "难受")
    followup_item_limit: int = 2
    profile_open_loop_limit: int = 2
    high_density_threshold: float = 2.0
    logical_turn_window_seconds: int = 60
    logical_turn_max_messages: int = 5
    logical_turn_fragment_chars: int = 24


@dataclass(frozen=True)
class SignalParams:
    topic_words: tuple[str, ...] = (
        "工作",
        "学习",
        "游戏",
        "朋友",
        "家庭",
        "项目",
        "情绪",
        "睡眠",
        "面试",
        "考试",
        "回复",
        "材料",
        "聊天",
        "实习",
        "答辩",
        "汇报",
        "简历",
        "论文",
        "作业",
    )
    time_words: tuple[str, ...] = ("明天", "今晚", "下午", "周末", "下周", "月底", "等会", "早上", "晚上", "今天", "刚才", "昨晚", "这次", "现在", "后天", "中午")
    task_words: tuple[str, ...] = ("要", "得", "准备", "提交", "面试", "考试", "开会", "交材料", "做完", "投简历", "写论文", "交作业", "汇报", "答辩", "实习", "复习")
    vulnerable_events: tuple[str, ...] = ("分手", "失恋", "被辞", "吵架", "崩了", "破防", "撑不住", "绷不住", "心态炸")
    low_density_fillers: tuple[str, ...] = ("哈哈", "嘿嘿", "笑死", "天气不错", "还行", "没事", "早", "晚安", "嗯嗯")
    correction_words: tuple[str, ...] = ("不是", "记错", "不对", "错了", "改成", "其实是", "应该是")
    deletion_words: tuple[str, ...] = ("别记", "不要记", "不用记", "忘掉", "删掉", "删了", "别存", "不要存", "忽略这条")


@dataclass(frozen=True)
class SemanticParams:
    vector_dimensions: int = 64


@dataclass(frozen=True)
class DisclosureParams:
    invite_words: tuple[str, ...] = ("还记得", "之前", "上次", "继续", "后来", "刚才说", "那个")
    mention_recall_threshold: float = 4.5
    hint_recall_threshold: float = 4.2
    casual_max_chars: int = 12
    casual_exemption_words: tuple[str, ...] = ("焦虑", "难受", "怎么办", "继续", "上次", "记得")


@dataclass(frozen=True)
class MemoryParams:
    recall: RecallParams = field(default_factory=RecallParams)
    quality: QualityParams = field(default_factory=QualityParams)
    maintenance: MaintenanceParams = field(default_factory=MaintenanceParams)
    summary: SummaryParams = field(default_factory=SummaryParams)
    conversation: ConversationParams = field(default_factory=ConversationParams)
    disclosure: DisclosureParams = field(default_factory=DisclosureParams)
    signals: SignalParams = field(default_factory=SignalParams)
    semantic: SemanticParams = field(default_factory=SemanticParams)


PARAMETER_DESCRIPTIONS = {
    "recall.open_item_bonus": {
        "description": "待跟进事项的召回加分。",
        "sensitivity": "high",
        "effect_of_increasing": "更频繁地提及未完成事项，更贴心但也更可能显得催促。",
        "effect_of_decreasing": "更少主动跟进，用户需要自己提起旧事。",
    },
    "recall.cooldown_penalty": {
        "description": "近期反复使用过的记忆降权。",
        "sensitivity": "medium",
        "effect_of_increasing": "更少重复旧记忆，但可能错过用户想接续的内容。",
        "effect_of_decreasing": "更容易接上旧事，但也更容易重复。",
    },
    "quality.auto_accept_min_confidence": {
        "description": "低风险记忆自动接受所需置信度。",
        "sensitivity": "high",
        "effect_of_increasing": "更多记忆进入确认队列，降低误记风险。",
        "effect_of_decreasing": "更多记忆自动沉淀，减少打扰但提高误记风险。",
    },
    "disclosure.mention_recall_threshold": {
        "description": "允许主动明说某条记忆的召回分阈值。",
        "sensitivity": "high",
        "effect_of_increasing": "更克制，更少显得突兀。",
        "effect_of_decreasing": "更主动，更像会接旧事，但可能过度表露。",
    },
}


def memory_params_for_profile(profile: str = "balanced") -> MemoryParams:
    profile = profile.lower().strip()
    base = MemoryParams()
    if profile == "cautious":
        return replace(
            base,
            recall=replace(base.recall, open_item_bonus=0.95, default_limit=6, cooldown_penalty=1.45),
            quality=replace(base.quality, auto_accept_min_confidence=0.72, low_stability_confirm_threshold=0.8),
            disclosure=replace(base.disclosure, mention_recall_threshold=4.9, hint_recall_threshold=4.5),
        )
    if profile == "proactive":
        return replace(
            base,
            recall=replace(base.recall, open_item_bonus=1.35, default_limit=10, cooldown_penalty=0.95),
            quality=replace(base.quality, auto_accept_min_confidence=0.58),
            disclosure=replace(base.disclosure, mention_recall_threshold=4.2, hint_recall_threshold=3.9),
        )
    if profile == "nostalgic":
        return replace(
            base,
            recall=replace(base.recall, history_continuation_bonus=1.2, cooldown_penalty=0.7, default_limit=10),
            maintenance=replace(base.maintenance, cooldown_use_threshold=4),
            disclosure=replace(base.disclosure, mention_recall_threshold=4.1, hint_recall_threshold=3.8),
        )
    return base


def memory_params_from_file(path: str | Path, profile: str = "balanced") -> MemoryParams:
    params = memory_params_for_profile(profile)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _apply_overrides(params, data)


def _apply_overrides(instance: Any, overrides: dict[str, Any]) -> Any:
    if not is_dataclass(instance):
        return instance
    known = {field.name for field in fields(instance)}
    changes = {}
    for key, value in overrides.items():
        if key not in known:
            continue
        current = getattr(instance, key)
        if is_dataclass(current) and isinstance(value, dict):
            changes[key] = _apply_overrides(current, value)
        else:
            changes[key] = value
    return replace(instance, **changes)


DEFAULT_MEMORY_PROFILE = os.getenv("MEMORY_PARAM_PROFILE", "balanced").lower()
if os.getenv("MEMORY_PARAMS_FILE"):
    DEFAULT_MEMORY_PARAMS = memory_params_from_file(os.environ["MEMORY_PARAMS_FILE"], DEFAULT_MEMORY_PROFILE)
else:
    DEFAULT_MEMORY_PARAMS = memory_params_for_profile(DEFAULT_MEMORY_PROFILE)
