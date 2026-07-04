# LM Studio 后台智能工作流试点报告

日期：2026-07-04  
分支：`codex/local-model-lmstudio-experiment`  
本地 API：`http://127.0.0.1:7985/v1`  
结构化模型：`google/gemma-4-12b-qat`  
Embedding 模型：`text-embedding-nomic-embed-text-v1.5`

## 目标

本试点验证一件事：能否使用本地模型智能化部分后台工作流，同时不影响前台聊天响应。

本次不把主聊天回复切到本地模型，也不把本地模型默认串进前台聊天请求。试点范围限定为：

- 本地结构化意图分类。
- 本地结构化记忆抽取。
- 本地 embedding 接口验证。
- 前台聊天保护检查：默认聊天路径不调用 LM Studio。

可复现结果文件：

- `docs/lmstudio_backend_pilot_results_2026-07-04.json`

运行命令：

```powershell
python scripts\run_lmstudio_backend_pilot.py --output docs\lmstudio_backend_pilot_results_2026-07-04.json
```

## 实现边界

已新增 `app/local_model.py`，封装 OpenAI-compatible 本地客户端，当前支持：

- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `response_format.type=json_schema`

`app/llm_gateway.py` 的主回复 `chat()` 不变，仍走 DeepSeek 或原本的本地 fallback。只有 `structured()` 在以下条件之一满足时才走 LM Studio：

- `STRUCTURED_PROVIDER=lmstudio`
- `MEMORY_EXTRACTOR=lmstudio`
- `MEMORY_INTENT_CLASSIFIER=lmstudio`

直接打开 `MEMORY_EXTRACTOR=lmstudio` 或 `MEMORY_INTENT_CLASSIFIER=lmstudio` 会让当前聊天请求等待本地模型，适合实验，不适合作为“不影响前台响应”的默认配置。因此本试点的结论是：先把 LM Studio 用作离线/后台评估和候选生成，不直接接入前台响应链路。

## 试点结果

### 1. 服务健康

LM Studio 服务可用，`/v1/models` 返回了目标模型：

- `google/gemma-4-12b-qat`
- `text-embedding-nomic-embed-text-v1.5`

健康检查耗时：51 ms。

### 2. 意图分类

共 3 条样例，LM Studio 加规则护栏后命中 3 条。

| 样例 | 结果 | 观察 |
| --- | --- | --- |
| `材料已经交完了，终于松口气。` | 通过 | 规则确认 completion，本地模型补充更细的情绪和话题 |
| `不是周三，是周五下午面试。` | 通过 | 本地模型与规则都识别纠错；completion 被护栏压成 false |
| `上次说的那个面试准备，我们继续吧。` | 通过 | follow-up invitation 被规则和本地模型共同保留，completion 为 false |

本分支已把意图分类改成“本地模型候选 + 规则护栏”：

- `has_completion_signal` 必须有规则完成信号支撑；本地模型不能单独声明完成。
- 规则识别到 correction 时，即使本地模型漏报，也保留纠错动作、旧值线索和新值。
- `has_followup_invitation` 采用规则和本地模型的并集。
- none/null/无 等占位字符串会归一化为 `None`。

### 3. 记忆抽取

共 3 条样例，LM Studio 命中 3 条。

| 样例 | 结果 | 观察 |
| --- | --- | --- |
| 回应规则：先安慰再分析 | 通过 | 抽出更自然的 `response_rule`，`open=false` |
| 敏感边界：不要提家里的事 | 通过 | 抽出 `boundary`，`open=false`，继续受确认和表露保护约束 |
| 明天下午交材料且焦虑 | 通过 | 抽出 `goal` 和 `emotion_pattern`；只有 `goal` 保持 `open=true` |

本分支已给结构化抽取加了归一化：

- 未确认记忆的 confidence 上限为 `0.92`。
- 未知 memory type 直接丢弃。
- `response_rule`、`boundary`、`emotion_pattern` 默认不能成为 open item。
- `stability`、`sensitivity_level` 只接受白名单值，异常值回落到安全默认。

结论：结构化记忆抽取是当前最值得继续试点的后台智能化方向。它可以生成更自然的中文记忆候选，但仍不能绕过 `review_memory_candidates()`、确认队列、边界表露策略和记忆审计。

### 4. Embedding

`text-embedding-nomic-embed-text-v1.5` endpoint 可用，返回 768 维向量，3 条样例都成功。

| 样例 | LM Studio similarity | local-hash similarity | 观察 |
| --- | ---: | ---: | --- |
| 睡不好 vs 失眠严重 | 0.7625 | 0.8734 | 两者都能识别相关 |
| 材料搞定 vs 完成材料提交 | 0.6496 | 0.8886 | 两者都能识别相关 |
| 睡不好 vs 面试简历 | 0.6885 | 0.0732 | Nomic embedding 对不相关中文主题区分不足 |

结论：embedding endpoint 可用，但当前模型不能直接替换 `local-hash-v1`。原因是负例相似度过高，容易造成不相关召回。短期建议：

- 保留 `local-hash-v1` 作为默认召回信号。
- 将 LM Studio embedding 作为候选特征记录，不参与最终排序。
- 扩展中文正负例后再判断是否换中文/多语 embedding 模型。

### 5. 前台响应保护

脚本用默认前台配置跑了一次 `ChatService.chat()`：

- `structured_provider=deepseek`
- `memory_extractor=rule`
- `memory_intent_classifier=rule`
- `force_local_llm=True`

结果：

- 前台回复耗时：3 ms。
- `lmstudio_request_count=0`。
- `memory_extractor=rule_based`。
- `intent_classifier=rule_based_intent`。

这证明当前默认前台聊天路径不会调用 LM Studio。要保持“不影响前台响应”，本地模型应先通过后台脚本、离线分析或未来后台队列运行，而不是直接在 `ChatService.chat()` 内同步等待。

## 风险与限制

1. 本地结构化调用耗时约 4-9 秒，不适合同步阻塞前台请求。
2. 意图分类的高影响字段仍必须保留规则护栏，不能直接相信模型输出。
3. Nomic embedding 对中文负例区分不够，不能直接替换当前召回。
4. 记忆抽取内容更自然，但仍必须继续过质量审核和确认队列。
5. 当前只是可用试点，不是生产后台队列；还没有异步任务调度、重试队列或结果合并 UI。

## 结论

本地模型接入已经达到“可用试点”状态：配置可切换、失败可降级、默认不影响前台、结构化抽取和意图分类有可复现结果，并且关键误判被规则护栏拦住。

当前最稳的近期方案：

1. `google/gemma-4-12b-qat` 用于结构化记忆抽取 shadow logging。
2. `google/gemma-4-12b-qat` 用于意图分类候选，高影响字段经过规则护栏后再使用。
3. `text-embedding-nomic-embed-text-v1.5` 只作为 embedding 实验特征，不替换召回。
4. 前台聊天默认继续使用规则记忆流程和 DeepSeek/原 fallback，避免本地模型延迟影响响应。

## 建议下一步

1. 增加 `local_shadow_extract` 和 `local_shadow_intent` 到 generation logs，不改变用户可见行为。
2. 建立 20-50 条中文试点样例，重点覆盖 completion、旧事接续、纠错、边界、待办。
3. 对本地模型字段设置采纳策略：低风险字段可试用，高风险字段只记录或经规则护栏采纳。
4. 评估更适合中文的 embedding 模型，再决定是否接入 SQLite 投影表。
