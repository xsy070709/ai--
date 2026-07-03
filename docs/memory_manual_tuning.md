# 记忆算法人工测试与调参设计

本文档定义人工测试如何为记忆算法调参提供证据。目标不是让人工测试替代自动校准集，而是补上自动测试难以判断的体验问题：该不该主动提旧事、是否太像任务管理器、记忆是否显得突兀、短消息是否被正确理解。

## 一、测试原则

人工测试只评价一次聊天决策，不评价模型文风好不好。每条测试记录必须能落到一个或多个可调参数，否则不能用于调参。

人工标注分三层：

1. 算法事实：应该抽取什么、召回什么、是否关闭待办、是否进入确认队列。
2. 表露体验：这条记忆应该明说、轻轻暗示、只影响语气，还是完全不提。
3. 用户感受：当前回复是否贴心、是否冒犯、是否重复、是否打断当前话题。

最小有效样本量：

- 每个参数至少覆盖 12 条人工样例，且正反样例都要有。
- 每个场景至少两名标注者；分歧样例保留，不强行改成一致。
- 只在同一类信号连续出现时调参，单条主观差评不直接改阈值。

## 二、场景矩阵

优先人工测试这些场景，因为它们直接影响“像真人”的感觉：

| 场景 | 目的 | 主要参数 |
| --- | --- | --- |
| 短高密度消息 | 验证“我分手了”“明天面试”不会被当寒暄 | `conversation.high_density_threshold`, `conversation.casual_max_chars` |
| 连续短消息 | 验证 60 秒内碎片消息是否合并成一个逻辑话轮 | `conversation.logical_turn_window_seconds`, `conversation.logical_turn_fragment_chars` |
| 待跟进事项 | 判断跟进是贴心还是催促 | `recall.open_item_bonus`, `conversation.followup_item_limit` |
| 旧事接续 | 判断用户说“上次/继续”时是否能自然接上 | `recall.history_continuation_bonus`, `maintenance.cooldown_use_threshold` |
| 敏感边界 | 验证边界记忆被遵守但不被复述 | `quality.auto_accept_min_confidence`, `disclosure.mention_recall_threshold` |
| 情绪语气记忆 | 验证只影响语气，不贴标签式说“你总是” | `disclosure.hint_recall_threshold`, `disclosure.mention_recall_threshold` |
| 记忆纠错 | 验证“不是 A，是 B”“别记这个”不会留下旧错记忆 | `quality.auto_accept_min_confidence` |
| 重复旧记忆 | 验证经常用过的记忆会冷却 | `recall.cooldown_penalty`, `maintenance.cooldown_use_threshold` |
| 同义召回 | 验证“睡不好”能召回“失眠”，“搞定”能关闭“待办” | `recall.semantic_similarity_threshold`, `recall.semantic_similarity_weight` |
| 话题切换摘要 | 验证换话题时产生摘要，持续话题不被硬切 | `summary.topic_shift_similarity_threshold`, `summary.topic_shift_min_messages` |

## 三、人工测试记录格式

人工测试记录使用 JSONL，一行一个聊天决策。推荐放在本地未提交文件，例如 `data/manual_memory_eval.local.jsonl`。

字段说明：

```json
{
  "id": "followup-001",
  "scenario": "followup",
  "user_text": "材料还没弄完，明天要交",
  "seed_memories": ["待跟进：明天下午要交材料"],
  "system_result": {
    "extracted_types": ["goal"],
    "recalled_contains": ["材料"],
    "disclosure_mode": "can_mention",
    "followup_mode": "gentle_follow_up"
  },
  "human_expected": {
    "memory_types": ["goal"],
    "recall_should_contain": ["材料"],
    "disclosure_mode": "hint",
    "followup_mode": "gentle_follow_up"
  },
  "ratings": {
    "recall_relevance": 4,
    "disclosure_naturalness": 2,
    "followup_helpfulness": 3,
    "privacy_safety": 5,
    "non_repetition": 4
  },
  "issues": ["too_explicit"],
  "parameters": ["disclosure.mention_recall_threshold"],
  "notes": "能接材料，但不该直接说记得你明天要交。"
}
```

评分统一为 1 到 5：

- 1：明显错误，会让用户不舒服或误记。
- 2：能看出意图，但体验别扭。
- 3：可接受，但没有明显优势。
- 4：基本自然。
- 5：很自然，像真实朋友会做的事。

## 四、问题标签

人工标注必须从固定标签中选择，便于聚合：

| 标签 | 含义 | 常见调参方向 |
| --- | --- | --- |
| `missed_recall` | 应该想起但没想起 | 降低 `recall.min_score_threshold`，提高相关召回权重 |
| `irrelevant_recall` | 想起了不相关旧事 | 提高 `recall.min_score_threshold`，提高 `recall.cooldown_penalty` |
| `too_explicit` | 记忆说得太直白 | 提高 `disclosure.mention_recall_threshold` 或 `hint_recall_threshold` |
| `too_quiet` | 该接旧事却没接 | 降低表露阈值，提高 `history_continuation_bonus` |
| `nagging_followup` | 跟进像催任务 | 降低 `recall.open_item_bonus`，降低 `followup_item_limit` |
| `missed_followup` | 明显待办没跟进 | 提高 `recall.open_item_bonus` |
| `wrong_extraction` | 抽取了不该记的内容 | 提高 `quality.auto_accept_min_confidence` |
| `missed_extraction` | 漏记高价值信息 | 降低相关置信阈值或增强关键词/语义规则 |
| `privacy_surface` | 边界或敏感记忆被复述 | 提高表露阈值，敏感类型只允许 obey/silent |
| `repetitive_memory` | 反复提同一条记忆 | 提高 `recall.cooldown_penalty`，降低冷却阈值 |

## 五、调参决策规则

每周或每 50 条人工样例汇总一次。调参只按趋势做小步修改：

| 条件 | 动作 |
| --- | --- |
| `missed_recall` 占某场景样例超过 30% | `recall.min_score_threshold` 下调 0.05，或提高该场景权重 0.1 |
| `irrelevant_recall` 超过 20% | `recall.min_score_threshold` 上调 0.05，或 `cooldown_penalty` 上调 0.1 |
| `nagging_followup` 多于 `missed_followup` 两倍 | `recall.open_item_bonus` 下调 0.1 |
| `missed_followup` 多于 `nagging_followup` 两倍 | `recall.open_item_bonus` 上调 0.1 |
| `too_explicit` 或 `privacy_surface` 连续出现 | `disclosure.mention_recall_threshold` 上调 0.2 |
| `too_quiet` 在旧事接续场景超过 30% | `history_continuation_bonus` 上调 0.1，表露阈值下调 0.1 |
| `wrong_extraction` 连续出现 | `quality.auto_accept_min_confidence` 上调 0.05 |
| `missed_extraction` 连续出现且人工认为应记 | 增加样例到校准集，再补规则或调低阈值 |

每次只改 1 到 2 个参数。改完必须重新跑：

```powershell
python scripts/evaluate_memory_calibration.py
python scripts/summarize_manual_memory_eval.py data/manual_memory_eval.local.jsonl
python -m pytest -q
```

## 六、人工测试流程

1. 先从场景矩阵选一个目标参数，例如 `recall.open_item_bonus`。
2. 写 12 到 20 条测试聊天，刻意包含正例和反例。
3. 运行当前系统，记录 `system_result`。
4. 人工填写期望、评分、问题标签和关联参数。
5. 用汇总脚本看问题分布，不看单条样例做决定。
6. 小步调参，重新运行自动校准集和人工汇总。
7. 如果人工样例暴露的是明确规则缺口，把样例沉淀到 `data/memory_calibration_cases.json`。

## 七、什么不能用于调参

- “我感觉不喜欢”但没有问题标签和目标参数。
- 只测试主动型人格，却拿结果去调默认平衡型参数。
- 只用单轮孤立消息测试跟进体验。
- 模型回复文风不好，但记忆召回和表露决策正确。
- 样例太接近生产隐私数据，无法长期保留为校准资产。
