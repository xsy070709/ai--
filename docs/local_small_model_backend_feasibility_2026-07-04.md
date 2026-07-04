# 本地小模型接管后端智能工作流可行性调研

日期：2026-07-04  
仓库：`C:\Users\32988\Documents\ai聊天`

## 结论

可行，但不建议先让本地小模型接管主聊天回复。这个项目最适合的落点是“后端智能工作流”：embedding、记忆抽取、意图分类、摘要、反思、审计辅助。这些任务输入短、输出结构化、可回退、可离线评估，正好匹配本地量化模型的能力边界。

建议路线是：

1. 先引入本地 embedding，替换或并行校验当前 `local-hash-v1` 语义 fallback。
2. 再把本地小模型接到结构化 JSON 工作流，先 shadow logging，不直接改写行为。
3. 最后再考虑摘要、反思、审计重写等更影响体验的链路。

主聊天回复继续保留 DeepSeek 或远端强模型，因为虚拟好友的自然表达、情绪回应和长期人格一致性对小模型更苛刻。小模型在后台做“判断和整理”，大模型在前台做“表达和陪伴”，是当前阶段更稳的架构。

## 本机 LM Studio 目标方案

用户提供的本地资源与运行方式：

- 本地 API：LM Studio，端口 `7985`。
- 可分配资源：16G 内存、8G 显存。
- 结构化模型：Gemma4-12b 量化版。
- 本轮探测到的可用模型 ID：
  - `google/gemma-4-12b-qat`
  - `google/gemma-4-12b`
  - `google/gemma-4-e4b`
  - `qwen/qwen3-vl-4b`
  - `deepseek-ocr-2`
  - `text-embedding-nomic-embed-text-v1.5`

本轮本地 smoke test 结果：

- `GET http://127.0.0.1:7985/v1/models` 成功返回模型列表。
- `POST http://127.0.0.1:7985/v1/chat/completions` 使用 `google/gemma-4-12b-qat` 和 `response_format.type=json_schema` 成功返回可解析 JSON。
- `POST http://127.0.0.1:7985/v1/embeddings` 使用 `text-embedding-nomic-embed-text-v1.5` 成功返回 768 维 embedding。

因此当前推荐不再以 Ollama 为首选，而是：

| 后端工作流 | 当前推荐模型 | 说明 |
| --- | --- | --- |
| 结构化记忆抽取 | `google/gemma-4-12b-qat` | 12B 量化模型适合做 JSON schema 约束下的候选抽取，先 shadow |
| 结构化意图分类 | `google/gemma-4-12b-qat` | 本轮 smoke test 已验证 completion/emotion 这类短 schema 可用 |
| 真实语义 embedding | `text-embedding-nomic-embed-text-v1.5` | 已验证 768 维输出；先替换/并行校验 `local-hash-v1` |
| 摘要/反思草稿 | `google/gemma-4-12b-qat` | 可试，但必须保留来源证据与规则边界 |
| 主聊天回复 | 继续 DeepSeek/远端强模型 | Gemma4-12b 可做本地降级或开发模式，不建议第一阶段接管前台体验 |

LM Studio 官方文档说明其 OpenAI-compatible API 支持 `/v1/chat/completions`、`/v1/embeddings` 等端点；结构化输出通过给 `/v1/chat/completions` 传 `response_format.type=json_schema` 实现，并建议检查模型是否支持结构化输出，尤其是 7B 以下模型。本机使用的 12B 量化模型已通过最小 JSON schema smoke test。

参考：

- [LM Studio OpenAI Compatibility Endpoints](https://lmstudio.ai/docs/developer/openai-compat)
- [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- [LM Studio Embeddings](https://lmstudio.ai/docs/developer/openai-compat/embeddings)
- [LM Studio Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)

## 当前项目接入条件

现有代码已经具备大部分接入点：

- `app/llm_gateway.py` 有 `chat()` 和 `structured()` 两条路径，结构化调用已经单独缓存、单独 max tokens、单独 purpose 记录。
- `app/memory/extractors.py` 的 `StructuredLLMMemoryExtractor` 已经通过 `gateway.structured(..., purpose="memory_extract")` 接入 LLM 抽取，并在 degraded 或解析失败时回退规则抽取。
- `app/memory/intent.py` 的 `StructuredLLMIntentClassifier` 同样通过 `gateway.structured(..., purpose="memory_intent")` 接入 LLM 意图分类，并保留规则回退。
- `app/storage.py` 已有 `memory_embeddings` 表，但当前写入的是 `local-hash-v1` 确定性向量。
- `app/memory/semantic.py` 当前是零依赖 hash 语义 fallback，适合保留为本地模型不可用时的回退。
- `generation_logs` 已记录 provider、model、degraded、usage、prompt_manifest、feedback_signals，足够支持 shadow 对比和回归分析。

因此需要新增的不是一套完整 agent 框架，而是一个小的 provider 抽象和本地推理适配器。

## 外部方案现状

### LM Studio

LM Studio 是当前实际选型。它已经在本机端口 `7985` 提供 OpenAI-compatible API，可以复用现有 `httpx` 风格网关，不需要引入额外 SDK。对这个项目最重要的是两个端点：

- `POST /v1/chat/completions`：用于结构化抽取、意图分类、摘要草稿、审计辅助。
- `POST /v1/embeddings`：用于真实语义向量，替代或并行验证当前 `local-hash-v1`。

建议统一使用 base URL：

```text
http://127.0.0.1:7985/v1
```

结构化输出建议使用 OpenAI-compatible `response_format`：

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "memory_intent",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "has_completion_signal": {"type": "boolean"},
        "primary_emotion": {"type": "string"}
      },
      "required": ["has_completion_signal", "primary_emotion"]
    }
  }
}
```

参考：

- [LM Studio OpenAI Compatibility Endpoints](https://lmstudio.ai/docs/developer/openai-compat)
- [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- [LM Studio Embeddings](https://lmstudio.ai/docs/developer/openai-compat/embeddings)

优点：

- 本机服务已经可用，不需要再选型。
- OpenAI-compatible API 与现有 DeepSeek 网关形态接近。
- 结构化输出和 embedding 都已通过最小 smoke test。
- 模型列表可通过 `/v1/models` 动态读取，避免硬编码错误模型名。

风险：

- Gemma4-12b-QAT 虽能输出 schema JSON，但语义判断仍需要校准集验证。
- 16G 内存和 8G 显存能跑 12B 量化，但并发和长上下文要克制。
- Embedding 应使用 `text-embedding-nomic-embed-text-v1.5`，不要让聊天模型承担向量任务。
- 本地服务应只绑定可信地址，不要让前端直接访问 LM Studio API。

### Ollama

Ollama 仍可作为备用方案。它同样提供 OpenAI compatibility、结构化 JSON 和 embedding API，但在本机 LM Studio 已经跑通的情况下，不建议第一阶段再引入第二套本地模型服务。

### llama.cpp server

llama.cpp server 更底层，适合以后需要精细控制 GGUF、量化、GPU offload 或 embedding pooling 的情况。它提供 OpenAI-compatible `/v1/embeddings`，也支持非 OpenAI 的 `/embeddings` 接口。

参考：

- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

优点：

- 资源占用和模型加载可控。
- 更适合固定部署和性能调优。
- 不依赖 Ollama 的模型封装。

风险：

- 安装、模型管理和 Windows 调试成本高于 Ollama。
- 对当前 MVP 来说集成面偏重。

### 模型选择

基于本机 LM Studio 已加载模型，首选按任务分开：

| 任务 | 建议模型 | 原因 |
| --- | --- | --- |
| 中文 embedding / 语义召回 | `text-embedding-nomic-embed-text-v1.5` | 本机 LM Studio 已验证 `/v1/embeddings` 返回 768 维向量，适合先做真实 embedding 试点 |
| 通用结构化抽取/意图 | `google/gemma-4-12b-qat` | 本机已验证 JSON schema 输出可用；12B 量化比 1-4B 更适合复杂中文语义判断 |
| 更强后台摘要/反思 | `google/gemma-4-12b-qat` | 摘要和反思需要上下文理解，但必须作为草稿并保留来源验证 |
| 本地降级聊天 | `google/gemma-4-12b-qat` 或 `google/gemma-4-12b` | 可作为 DeepSeek 不可用时的开发模式，不建议第一阶段替代前台主回复 |

参考：

- [Qwen3-Embedding-0.6B model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Qwen3 Embedding paper](https://arxiv.org/abs/2506.05176)
- [LM Studio OpenAI Compatibility Endpoints](https://lmstudio.ai/docs/developer/openai-compat)

## 适合交给本地小模型的工作流

### 1. 真实 embedding

优先级最高。

当前 `memory_embeddings` 表已经存在，但存的是 `local-hash-v1`。引入本地 embedding 后，收益直接落在：

- 同义召回：例如“睡不好”召回“失眠严重”。
- topic shift 判断。
- 旧事接续。
- SQLite 混合检索：FTS/LIKE 先粗召回，embedding 再补足。

建议实现：

- 新增 `EmbeddingProvider` 协议：`embed(texts: list[str]) -> list[list[float]]`。
- 实现 `LocalHashEmbeddingProvider` 保留现状。
- 实现 `OpenAICompatibleEmbeddingProvider`，默认调 `POST http://127.0.0.1:7985/v1/embeddings`。
- `memory_embeddings.model` 从 `local-hash-v1` 扩展为 `lmstudio:text-embedding-nomic-embed-text-v1.5:768` 这类 provider/model/dimension 标识。
- 当 embedding provider 变更时，只重算缺失或模型不匹配的向量。
- 查询时如果本地模型不可用，自动回退 `local-hash-v1`。

不建议第一步就上 sqlite-vec。当前记忆规模还是 MVP，先用 SQLite 表内 JSON 向量 + Python cosine 足够验证质量。

### 2. 结构化记忆抽取

优先级高，但必须 shadow 运行。

当前规则抽取可解释、稳定，但覆盖自然表达吃力。本地小模型适合做候选生成：

- 用户偏好/反感。
- 边界和回应规则。
- goal/open loop。
- shared experience。
- emotion pattern。
- stable impression 候选。

建议实现：

- 新增 `STRUCTURED_PROVIDER=lmstudio`、`LOCAL_STRUCTURED_MODEL=google/gemma-4-12b-qat`。
- 让 `StructuredLLMMemoryExtractor` 可选择 DeepSeek 或 Local provider。
- 第一阶段只记录 local 候选到 `generation_logs.prompt_manifest.local_shadow_extract`，不入库。
- 对比规则抽取、DeepSeek 抽取和本地抽取的差异。
- 只有当校准集和人工评分确认收益后，再允许本地抽取进入 `review_memory_candidates()`。

核心约束：

- 小模型输出必须经过 schema normalize。
- JSON 解析失败不能影响聊天回复。
- `boundary`、高敏感记忆仍应走确认队列，不能因为模型置信度高就自动入库。

### 3. 意图分类

优先级高，适合和抽取一起 shadow。

意图分类比记忆抽取更适合小模型，因为输出 schema 固定、输入短、对主回复影响可控。它可以补强：

- 用户是否在纠错/删除记忆。
- 是否完成待办。
- 是否邀请旧事接续。
- 情绪和话题。
- 信息密度。

建议实现：

- 同 `StructuredLLMIntentClassifier` 走 local provider。
- 先仅 shadow 记录 `local_shadow_intent`。
- 对 `has_correction_intent`、`has_completion_signal` 这类高影响字段设置保守门槛：规则和本地模型一致时才自动采用；不一致时保留规则或进入审计日志。

### 4. 摘要与反思

优先级中。

当前摘要是规则生成，优点是稳定，缺点是机械。本地小模型可以用于：

- 生成更自然的 session summary。
- 从多条记忆中归纳 stable impression。
- 给 follow-up 生成更贴近语境的候选问题。

但这类任务更容易“编造”，因此不能直接替换现有逻辑。

建议实现：

- 本地模型只生成 `draft_summary` 或 `draft_reflection`。
- 规则系统继续决定摘要边界、覆盖消息数量和是否归档。
- draft 必须记录来源 message ids / memory ids。
- 没有来源证据的句子丢弃。

### 5. 审计辅助和回复重写

优先级中低，不建议第一批做。

`audit_memory_use()` 已经能发现 silent/obey 记忆被表露的问题。让本地小模型做审计可以补充语义判断，但如果让它自动重写回复，会直接影响用户看到的文本。

建议顺序：

1. 本地模型只做二级审计，不改回复。
2. 只对 `fail` 级 boundary/silent_obey 做保守兜底。
3. 真要重写，仍建议用更强的主聊天模型，或至少使用严格模板重写。

## 不适合第一阶段交给本地小模型的部分

- 主聊天回复：对中文自然度、情绪稳定、人格一致性要求高。
- 用户敏感边界的最终决策：小模型可辅助，但不能单独决定。
- 自动调参：当前人工样例还不够，应先扩大 calibration/manual eval。
- 多轮 agent 规划：项目不是通用 agent，过早引入会增加不可控性。

## 推荐架构

新增一个通用但很薄的 provider 层：

```text
ChatService
  ├─ DeepSeekGateway.chat()              主聊天回复
  ├─ StructuredProvider.structured()      抽取/意图/摘要/审计
  │    ├─ DeepSeekStructuredProvider
  │    └─ OpenAICompatibleStructuredProvider
  └─ EmbeddingProvider.embed()
       ├─ LocalHashEmbeddingProvider
       └─ OpenAICompatibleEmbeddingProvider
```

配置建议：

```text
LLM_PROVIDER=deepseek
STRUCTURED_PROVIDER=rule|deepseek|lmstudio
LOCAL_LM_BASE_URL=http://127.0.0.1:7985/v1
LOCAL_STRUCTURED_MODEL=google/gemma-4-12b-qat
LOCAL_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
MEMORY_EXTRACTOR=rule|llm|shadow_local
MEMORY_INTENT_CLASSIFIER=rule|llm|shadow_local
EMBEDDING_PROVIDER=local_hash|lmstudio
```

注意：`LOCAL_LM_BASE_URL` 这里带 `/v1`，因为 LM Studio 的 OpenAI-compatible endpoint 是 `/v1/chat/completions` 和 `/v1/embeddings`。实现时可以复用一套 OpenAI-compatible provider，后续如果换 Ollama 或 llama.cpp，只改 base URL 和模型名。

## 性能与硬件判断

用户给定资源为 16G 内存和 8G 显存，本机 LM Studio 已加载 12B 量化模型。判断如下：

| 工作流 | 可行性 | 建议 |
| --- | --- | --- |
| embedding | 高 | 使用 `text-embedding-nomic-embed-text-v1.5`，可进入第一阶段实施 |
| 意图分类 | 高 | `google/gemma-4-12b-qat` + JSON schema，先 shadow，短 timeout |
| 记忆抽取 | 中高 | 可生成候选，但必须经过 `review_memory_candidates()` 和确认队列 |
| 摘要/反思 | 中 | 作为草稿异步或回复后执行，不能阻塞主回复太久 |
| 主聊天回复 | 中 | 可做本地降级，不建议替代 DeepSeek 主链路 |
| 并行多请求 | 低到中 | 8G 显存下要限制并发，避免聊天、抽取、摘要同时争抢模型 |

后台任务应设置：

- 短 timeout，例如 3-8 秒。
- 小 max tokens，例如结构化 300-700。
- 并发限制，避免多轮聊天同时压本地模型。
- 失败自动降级，不影响用户收到回复。
- 在 LM Studio 侧保持模型已加载，或在应用启动时做一次轻量 `/v1/models`/短 prompt 健康检查。

## 风险

### R1：结构化输出不稳定

即使 API 支持 JSON mode，小模型仍可能输出字段类型错误、漏字段或语义误判。必须保留 schema normalize、parse fallback 和校准集。

### R2：延迟影响聊天节奏

如果把本地抽取、意图、摘要都串在主链路前后，用户会感觉回复变慢。第一阶段应该把 embedding 增量计算、摘要、反思放到回复后或后台；主链路只允许极短的意图/抽取调用，且可超时回退。

### R3：小模型会把“像记忆的话”过度抽取

虚拟好友项目最怕过度记忆和过度表露。本地抽取必须经过现有质量审核、确认队列、表露计划和审计，而不是直接入库。

### R4：中文 embedding 模型选择错误

本机当前可用的 `text-embedding-nomic-embed-text-v1.5` 已能作为真实 embedding 试点，但它是否优于当前中文 `local-hash-v1`，要用中文校准样例验证。若“睡不好/失眠”“搞定/完成”“别提/雷区”等中文召回改善不明显，再考虑换中文/多语 embedding 模型。

### R5：部署安全

LM Studio 本地服务应绑定 localhost 或可信内网。不要把 `7985` 暴露到公网，也不要让前端直接调用 LM Studio API；应由 Python 后端代为调用并记录日志。

## 建议实施计划

### Phase 1：Embedding 试点

目标：不改主行为，验证真实 embedding 是否明显提升召回。

任务：

1. 新增 `EmbeddingProvider`。
2. 接入 LM Studio OpenAI-compatible `/v1/embeddings`。
3. 保留 `local-hash-v1` fallback。
4. 在 SQLite `memory_embeddings` 中记录 provider/model/dimensions。
5. 扩展 `evaluate_memory_calibration.py` 或新增 embedding eval，用“睡不好/失眠”“搞定/完成”等样例对比召回。

验收：

- 无 LM Studio 时测试仍绿。
- 有 LM Studio 时能写入 `text-embedding-nomic-embed-text-v1.5` 的 768 维向量。
- 召回结果和耗时进入 generation/debug log。

### Phase 2：本地结构化 shadow

目标：比较本地小模型与规则系统差异，不直接改变体验。

任务：

1. 新增 `OpenAICompatibleStructuredProvider`，默认指向 LM Studio。
2. 支持 `response_format.type=json_schema`。
3. `memory_extract` 和 `memory_intent` 增加 shadow 调用。
4. generation logs 记录本地模型输出、解析错误、耗时。
5. 增加 20-50 条校准样例覆盖纠错、删除、边界、待办、旧事接续。

验收：

- 本地模型失败不影响聊天。
- 能生成差异报告：规则命中、本地命中、冲突字段、人工期望。

### Phase 3：有限接管

目标：只让本地模型接管低风险字段。

可接管：

- `topics`
- `primary_emotion`
- `information_density`
- 低敏 preference/dislike 候选

暂不接管：

- `boundary` 自动入库。
- 删除/纠错最终执行。
- 主聊天回复。
- 自动参数调节。

验收：

- `python -m pytest -q --basetemp .tmp\pytest -p no:cacheprovider`
- `python scripts\evaluate_memory_calibration.py`
- 手工抽样 generation logs，确认 fallback 生效。

### Phase 4：摘要/反思试点

目标：提升长期聊天的历史压缩质量。

任务：

1. 本地模型生成 draft summary。
2. 规则系统验证覆盖边界和来源证据。
3. 和现有规则摘要并行存日志。
4. 人工评分摘要是否更准确、更少编造。

## 最小实现切口

最小可落地版本只需要：

1. `app/local_model.py`
   - `OpenAICompatibleLocalClient`
   - `structured_json()`
   - `embed()`
2. `app/config.py`
   - `LOCAL_LM_BASE_URL`
   - `LOCAL_STRUCTURED_MODEL`
   - `LOCAL_EMBEDDING_MODEL`
   - `EMBEDDING_PROVIDER`
3. `app/storage.py`
   - embedding model mismatch 时重算。
4. `app/memory/semantic.py`
   - 保留 hash fallback。
5. `tests/test_core.py`
   - fake local provider 测试、fallback 测试、embedding model 迁移测试。

第一版不要改前端，不要改主聊天回复，不要引入后台队列。先用同步 timeout + fallback 证明质量和稳定性。

## 最终建议

引入本地小模型是值得做的，但定位要克制：它不是“替代 DeepSeek 的本地女友模型”，而是“本地隐私友好的后台记忆/语义/分类工人”。

推荐近期只做两件事：

1. 用 `text-embedding-nomic-embed-text-v1.5` 做真实 embedding 试点。
2. 用 `google/gemma-4-12b-qat` 做结构化抽取/意图 shadow logging。

这两步和项目现有记忆路线最匹配，收益可测，失败可回退，且不会破坏虚拟好友的前台体验。
