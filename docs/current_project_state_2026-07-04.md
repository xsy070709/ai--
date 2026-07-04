# 当前项目实现边界与后续方向报告

日期：2026-07-04  
仓库：`C:\Users\32988\Documents\ai聊天`  
当前基线：`master`，最新提交 `96d6e06 Merge branch 'codex/memory-post-merge-iteration'`  
代码规模快照：`app`、`tests`、`scripts`、`docs`、`data` 下共 52 个文件；`app/tests/scripts/docs` 中主要代码与文档约 8049 行。

## 一、总判断

这个项目当前已经不是“只有聊天页面的 MVP”，而是一个围绕“虚拟好友长期相处”构建的本地单用户聊天系统。它的核心资产是 `app/memory/`：记忆抽取、质量审核、用户确认、纠错、召回、表露控制、事后审计、维护衰减、反馈分析、校准测试都已经拆成独立模块，并接入 `ChatService.chat()` 的主链路。

当前更准确的定位是：

- 已成型：单用户、本地持久化、可离线降级运行的长期聊天 MVP。
- 核心优势：记忆生命周期完整，可观察性强，测试和校准基线扎实。
- 主要边界：规则与启发式仍是默认智能层；LLM 结构化能力是可选增强；语义搜索是本地哈希向量 fallback；还不是多用户、生产级并发或自动学习调参系统。
- 后续方向：优先扩大真实样例和人工评分闭环，再决定是否引入真实 embedding、sqlite-vec、LLM 常态化意图/抽取和更强前端产品体验。

## 二、项目形态

### 2.1 运行入口

项目有两套入口：

- `dev_server.py`：零依赖开发服务器，使用 Python 标准库 `ThreadingHTTPServer`，适合快速本地运行。
- `app/main.py`：FastAPI 入口，提供同一套 API，适合用 `uvicorn app.main:app --reload` 启动。

两套入口都通过：

- `load_settings()` 读取配置。
- `create_store(settings)` 创建 JSON 或 SQLite 后端。
- `ChatService(store, DeepSeekGateway(settings))` 组装业务服务。

这说明服务层已经基本抽象出来，入口层只是协议适配。

### 2.2 依赖与部署边界

`pyproject.toml` 只有三个运行依赖：

- `fastapi`
- `uvicorn[standard]`
- `httpx`

开发服务器甚至不依赖 FastAPI。这个设计适合本地 MVP、快速迭代和离线验证，但也意味着当前没有：

- 用户认证。
- 多账号隔离。
- 后台任务队列。
- 正式数据库迁移框架。
- 前端构建链路。
- CI 配置文件。

### 2.3 前端形态

前端位于 `app/static/`，是原生 HTML/CSS/JS：

- 聊天窗口。
- 背景人格导入。
- 模型状态展示。
- 分层记忆统计。
- 开发窗口：记忆、generation logs、API 请求、原始流。
- 记忆整理按钮。

这已经足够做本地调试和产品验证，但还不是面向普通用户的成熟体验。比如确认队列、记忆编辑、人工评分、参数调节还主要是开发/调试导向。

## 三、主链路：一次聊天真正发生了什么

核心编排在 `app/chat_service.py` 的 `ChatService.chat()`。

当前一轮聊天主链路如下：

1. 创建用户消息，读取存储快照。
2. 记录快照会话 ID 和 `state_revision`，用于跨 await 写入一致性审计。
3. 构造逻辑话轮：短时间内连续短用户消息会合并为记忆/意图判断输入。
4. 从存储后端搜索召回候选，再加入 open、boundary、response_rule、用户确认记忆等优先记忆。
5. 先构建一次 memory context，再执行意图分类。
6. 用意图结果重建 memory context。
7. 根据摘要边界构建工作记忆，避免把已摘要历史重复塞回 prompt。
8. 拼接四段 system prompt：稳定人格、会话摘要、记忆上下文、运行时间。
9. 调用 DeepSeek 网关；无 key 或失败时降级为本地回复。
10. 对模型回复做记忆表露审计。
11. 从用户消息和回复中抽取新记忆；抽取失败不丢回复。
12. 对记忆候选做质量审核：接受、确认、拒绝。
13. 在同一次 `mutate()` 中写入用户/助手消息、摘要、纠错、闭环、召回标记、新记忆、确认队列、反思、维护结果、generation log。
14. 返回回复、使用的记忆、新记忆、确认队列、跟进计划、表露计划、审计结果、意图、逻辑话轮和层级统计。

这个链路的关键点是：记忆不是“回复后顺手保存一下”，而是在回复前参与召回和 prompt，在回复后参与抽取、审计、维护和反馈。

## 四、核心模块边界

### 4.1 服务层

`app/chat_service.py`

职责：

- 把人格、时间、摘要、记忆、意图、LLM、存储串起来。
- 保证 LLM/记忆抽取/意图分类失败时有降级路径。
- 记录足够详细的 `prompt_manifest` 和 `generation_logs`。
- 提供 API 所需的状态、消息、记忆、确认队列、调试快照、删除/整理/确认操作。

边界：

- 仍是单服务实例内的本地状态编排。
- 通过 `state_revision` 和 pinned session 避免活跃会话切换造成写错会话，但不会让已经发出的 prompt 自动重算。
- 多用户隔离、请求级事务、乐观锁冲突重试还未实现。

### 4.2 LLM 网关

`app/llm_gateway.py`

职责：

- DeepSeek chat 调用。
- DeepSeek structured JSON 调用。
- 结构化调用客户端缓存。
- prompt 统计。
- 请求日志。
- 无 API key 或 provider 错误时降级。

边界：

- 只接 DeepSeek 兼容接口。
- chat fallback 是固定规则回复，不是本地模型。
- structured fallback 返回 `{}` 或走规则抽取/规则意图。
- 没有流式输出。
- 没有 provider 抽象层；未来接多模型需要再拆接口。

### 4.3 存储层

`app/storage.py`

当前有统一协议 `StorageBackend`，实现了：

- `JsonStore`
- `SqliteStore`

JSON 后端：

- 默认使用。
- 数据集中在 `data/store.json`。
- 便于调试、迁移和人工查看。

SQLite 后端：

- 通过 `STORAGE_BACKEND=sqlite` 启用。
- 保留 JSON-compatible `app_state` 作为完整状态。
- 同步派生表：sessions、messages、memories、persona_versions、generation_logs。
- 维护 `memory_fts` 和 `memory_embeddings`。
- 搜索顺序是 FTS/LIKE，再用本地语义搜索补足。
- 投影同步已从早期全量重建升级为按缺失 ID 删除、按变化内容更新，未变化记忆保留已有 FTS 和 embedding。

边界：

- SQLite 仍是“状态快照 + 投影表”模型，不是完全关系化源模型。
- embedding 是 `local-hash-v1` 的确定性本地向量，不是真实语义模型。
- 无 sqlite-vec、无外部向量索引。
- 单机单文件适合 MVP，不适合多用户高并发。

### 4.4 人格与时间

`app/persona.py`

- 从背景文本中提取身份、关系定位、性格、说话风格、边界。
- 支持人格版本与 active persona。
- 当前是规则解析，不是 LLM 背景理解。

`app/time_context.py`

- 为 prompt 注入当前日期、星期、时区、时间。
- 支持相对时间理解的提示层。

`app/memory/time_reasoning.py`

- 推断明天、后天、今天、今晚、昨天、数字日期等 deadline。
- 标注 goal 的 `time_state`：elapsed、soon、upcoming、unknown。
- 已处理 invalid numeric date 和 naive/aware datetime。

边界：

- 不完整支持“下周三”“下个月”“每周五”等复杂周期表达。
- deadline 是规则推断，不是自然语言时间解析器。

## 五、记忆系统现状

### 5.1 已经实现的记忆生命周期

当前记忆生命周期是：

抽取 -> 审核 -> 确认/入库 -> 合并/冲突处理 -> 召回 -> 表露决策 -> prompt 使用 -> 回复审计 -> 用户纠错 -> 维护衰减/归档 -> 反馈分析 -> 校准回归。

对应模块：

- 抽取：`extraction.py`、`extractors.py`
- 意图：`intent.py`
- 质量：`quality.py`
- 生命周期：`lifecycle.py`
- 纠错：`correction.py`
- 召回：`recall.py`
- 上下文：`context.py`
- 跟进：`followup.py`
- 表露：`initiative.py`
- 审计：`audit.py`
- 维护：`maintenance.py`
- 反思：`reflection.py`
- 画像：`profile.py`
- 摘要：`summary.py`
- 逻辑话轮：`turns.py`
- 信号：`signals.py`
- 语义：`semantic.py`
- 反馈：`feedback.py`
- 校准：`calibration.py`
- 参数：`params.py`
- 视图：`views.py`

### 5.2 记忆类型

系统支持的长期记忆类型包括：

- `fact`
- `preference`
- `dislike`
- `boundary`
- `response_rule`
- `goal`
- `emotion_pattern`
- `relationship_signal`
- `stable_impression`
- `shared_experience`
- `episodic`

实际产品价值最高的不是“记住 fact”，而是这几类：

- `boundary`：必须默默遵守，避免冒犯。
- `response_rule`：塑造说话方式。
- `goal`：形成待跟进事项。
- `emotion_pattern`：影响语气，不应贴标签复述。
- `shared_experience`：让长期相处有连续性。
- `stable_impression`：从碎片中形成高层理解。

### 5.3 抽取能力

默认抽取器是规则版：

- 显式记忆：“记住”“帮我记住”。
- 偏好/反感：“我喜欢”“我希望”“我讨厌”“受不了”。
- 回应规则：“以后”“下次”“别”“不要”。
- 边界：“雷区”“不要提”“别提”“不想聊”。
- 目标/待办：时间信号 + 任务信号。
- 情绪模式：情绪词和原因推断。
- 关系信号：“你真懂我”“你不像朋友”等。
- 共同经历：“我们约定”“下次继续”等。
- 情景记忆：高密度短事件或近期事件。

可选抽取器是 `StructuredLLMMemoryExtractor`：

- 通过 DeepSeek structured JSON 模式抽取。
- provider 不可用、返回 degraded 或 JSON 解析失败时回退规则版。

边界：

- 默认规则抽取覆盖有限，容易漏掉自然表达、反讽、复杂上下文。
- LLM 抽取虽然已接入，但不是默认主路径。
- 目前没有把人工标注样例持续反哺成抽取器训练数据。

### 5.4 意图分类

默认规则意图分类器会输出：

- 是否完成某事项。
- 是否纠错/删除记忆。
- 纠错目标和新值。
- 主/次情绪。
- 情感极性。
- 是否寒暄。
- 是否邀请接续旧事。
- 话题。
- 未完成事项。
- 信息密度。

可选 `StructuredLLMIntentClassifier` 也已实现，同样有规则 fallback。

边界：

- 规则分类器对新表达依赖词表扩展。
- LLM 分类器未作为默认路径，成本、延迟、稳定性还未经过长期验证。
- `_normalize_intent()` 的复杂异常输入仍值得继续加测试。

### 5.5 召回与语义

召回由两层组成：

1. 存储后端先给候选：JSON 子串/语义，SQLite FTS/LIKE/语义。
2. `relevant_memories()` 再统一打分排序。

打分考虑：

- token overlap。
- 用户确认加分。
- open item 加分。
- elapsed deadline 加分。
- 情绪相关加分。
- 旧事接续加分。
- boundary 加分。
- tone guidance 加分。
- local semantic similarity。
- cooldown penalty。
- importance、salience、confidence。

边界：

- 召回不是纯向量语义检索。
- 中文分词和 topic 仍是轻量规则。
- local hash semantic 能覆盖一部分“睡不好/失眠”类同义，但不是生产语义模型。
- 当前更适合“可解释 MVP”，不是大规模语义记忆库。

### 5.6 表露控制

这是当前系统最重要的体验设计之一：记忆被召回不等于可以说出来。

`initiative.py` 会把每条召回记忆标成：

- `obey`：只遵守，不能复述。典型是 boundary。
- `silent`：相关但不主动提。
- `hint`：只影响语气，不说“我记得你……”。
- `mention`：可自然提起。

整体模式包括：

- `quiet`
- `tone_only`
- `silent_obey`
- `can_mention`

边界：

- 这套判断仍是规则阈值系统。
- 表露自然度最终取决于模型是否遵守 prompt。
- 审计能发现一部分违规，但不会自动重写回复。

### 5.7 跟进与闭环

`followup.py` 负责：

- 根据完成信号关闭 open memory。
- 针对 elapsed/upcoming/open 目标生成跟进计划。
- 在低密度寒暄时保持安静。
- 用户主动说“上次/继续/还记得”时允许接续。

边界：

- 跟进策略已经比普通任务提醒克制，但仍需要真实聊天样本验证“贴心”和“催促”的边界。
- 多个 open item 的排序和提问方式仍偏启发式。

### 5.8 审计与反馈

`audit.py` 检查：

- silent/obey 记忆是否被表露。
- hint 记忆是否被贴标签式复述。
- mention 场景是否错过应有跟进。

`feedback.py` 从日志推断：

- 跟进是否有效。
- 用户是否转移话题。
- 用户是否修正/删除记忆。
- 是否产生确认队列。
- 用户是否接受/拒绝确认。
- open loop 是否关闭。
- 用户是否邀请旧事。
- 表露是否出问题或是否被接续。

边界：

- 反馈分析会给参数建议，但不会自动改参数。
- 反馈依赖 generation logs 的质量和后续用户行为。
- 没有在线 A/B、没有自动优化器。

### 5.9 摘要与工作记忆

当前已经不是固定“每 16 条消息摘要”的简单设计。

`summary.py` 实现：

- `work_memory(..., after_message_count=...)`：工作记忆从最新摘要边界后开始。
- 动态工作记忆窗口：寒暄更短，深度/高密度/接续更长。
- topic shift 检测：用 topic + local semantic similarity 判断换题。
- topic shift 摘要只覆盖前一个话题，避免把新话题错误标为已摘要。
- 长间隔 backstop：避免长期不摘要。

边界：

- 话题边界仍是规则 + local semantic，不是 embedding model 或 LLM summarizer。
- 摘要文本是本地规则生成，不是模型总结。
- 摘要压缩适合 MVP，但后续长期使用可能需要更强摘要质量。

## 六、数据与可观测性

### 6.1 generation logs

每轮聊天都会记录：

- API messages。
- provider/model/degraded/error/usage。
- prompt manifest。
- used/new/corrected/deleted/queued/rejected/closed/decayed/archived/reflection memory IDs。
- followup/disclosure/audit 状态。
- extractor/classifier 名称和错误。
- intent。
- logical turn。
- time context。
- feedback signals。

这让项目具备很强的可追溯性。未来调试“为什么它提了这件事”时，应该先看 `/api/debug` 和 generation logs，而不是只看最终回复。

### 6.2 开发窗口

前端开发窗口已经能展示：

- 按类型分组的记忆。
- generation logs。
- 实际发给聊天 API 的 messages。
- 同进程 DeepSeek 请求日志。
- prompt stats。

边界：

- 开发窗口是调试工具，不是最终用户记忆管理 UI。
- 记忆确认队列虽然 API 支持，但用户体验还可以继续产品化。

## 七、配置能力

`.env` 和环境变量支持：

- `APP_DATA_DIR`
- `DEEPSEEK_API_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_CHAT_MODEL`
- `DEEPSEEK_STRUCTURED_MODEL`
- `DEEPSEEK_THINKING`
- `DEEPSEEK_CHAT_MAX_TOKENS`
- `DEEPSEEK_STRUCTURED_MAX_TOKENS`
- `LLM_TIMEOUT_SECONDS`
- `LLM_MAX_RETRIES`
- `LLM_FORCE_LOCAL`
- `MEMORY_EXTRACTOR`
- `MEMORY_INTENT_CLASSIFIER`
- `STORAGE_BACKEND`
- `MEMORY_PARAM_PROFILE`
- `MEMORY_PARAMS_FILE`

记忆参数集中在 `MemoryParams`：

- `balanced`
- `cautious`
- `proactive`
- `nostalgic`

并支持 JSON 覆盖文件。未知参数会抛错，坏文件会回退并暴露 warning。

边界：

- 参数仍是人工设定值。
- 参数元数据只覆盖高影响参数，不是所有字段都有完整解释。
- 还没有 UI 调参面板。

## 八、测试与验证状态

本次审计实测：

- `python -m compileall -q app scripts tests`：通过。
- `python scripts\evaluate_memory_calibration.py`：24/24，通过，score 1.0，reference_time `2026-07-03T09:00:00+08:00`。
- `python -m pytest -q`：默认 Windows temp 目录权限拒绝，94 passed、39 errors，error 都卡在 pytest `tmp_path` fixture 创建阶段。
- `python -m pytest -q --basetemp .tmp\pytest -p no:cacheprovider`：133 passed。

结论：

- 当前代码逻辑基线是绿的。
- 默认 pytest 环境存在 Windows 临时目录和 `.pytest_cache` 权限问题，和代码逻辑无关。
- 后续在这台机器跑全量测试，建议固定使用：

```powershell
python -m pytest -q --basetemp .tmp\pytest -p no:cacheprovider
```

## 九、当前实现边界清单

### 9.1 产品边界

当前是本地单窗口长期聊天 MVP，不是完整产品：

- 没有登录、账号、用户隔离。
- 没有多会话切换 UI，虽然存储结构支持 sessions。
- 没有移动端专门体验。
- 没有正式设置页。
- 没有记忆人工评分工作台。
- 没有真实发布/安装包流程。

### 9.2 智能边界

当前智能主要来自：

- DeepSeek 聊天回复。
- 可选 DeepSeek structured 记忆抽取/意图分类。
- 大量规则、词表、启发式。
- 本地 hash semantic fallback。

尚未具备：

- 常态化真实 embedding。
- 学习型召回排序。
- 训练过的本地分类器。
- 自动参数优化。
- LLM 自反思总结的稳定工作流。
- 回复失败后的自动重写审计闭环。

### 9.3 数据边界

当前适合：

- 单人本地长期使用。
- 几百到数千条消息/记忆的 MVP 规模。
- JSON 调试与 SQLite 投影检索。

不适合直接扩展到：

- 多用户并发写入。
- 多设备同步。
- 大规模长期记忆库。
- 需要强事务隔离的生产场景。
- 隐私合规要求严格的云服务。

### 9.4 并发边界

当前已经修复“LLM await 期间 active session 改变导致写错会话”的问题：写入会锚定 snapshot session，并记录 revision 变化。

但仍然不是完整事务系统：

- prompt 基于旧快照发出后，期间其他 mutation 可能已经改变状态。
- 系统记录了这个差异，但不会自动重放本轮 prompt。
- 单用户本地使用可接受；多用户或高并发需要重新设计事务边界。

### 9.5 隐私与安全边界

已有：

- boundary 记忆。
- obey/silent/hint/mention 表露策略。
- 表露审计。
- 删除/纠错。

未完成：

- 敏感数据分级策略仍简化。
- 没有加密存储。
- 没有导出/清除个人数据的完整产品流程。
- 没有权限系统。
- 没有针对 prompt injection 的完整安全层。

## 十、主要风险

### R1：规则覆盖和真实语言之间仍有距离

虽然已经扩展了口语完成、删除、混合语言焦虑、俚语倦怠等词表，但语言变化很快。真实用户会持续产生新表达，单靠手工词表会逐步吃力。

建议：用 calibration cases 和 manual eval 记录真实失败，再定期扩展词表或切到 LLM/embedding 判断。

### R2：记忆“会不会说出来”仍取决于模型遵守提示词

表露计划已经很清晰，但它只是 prompt 约束。审计能发现问题，但当前不会自动修复回复。

建议：下一阶段可做“审计 fail -> 二次改写/重试”的安全闭环，尤其是 boundary 和 sensitive memory。

### R3：摘要质量仍偏规则化

摘要现在解决了边界问题，但内容生成还是规则拼接。长期聊天里，规则摘要可能过于机械，不能准确保留微妙上下文。

建议：保留规则 fallback，同时尝试可控 LLM summary，并把摘要质量纳入测试。

### R4：反馈闭环还停在“分析建议”

反馈信号已记录，分析脚本能提出调参方向，但没有自动化实验、没有足够人工样例，也没有参数变更评估历史。

建议：先建设 50-100 条人工标注样例，再谈自动调参。

### R5：SQLite 还是投影，不是完整数据模型

SQLite 已经可用，投影也更高效，但源模型仍是 JSON-compatible snapshot。它保持了灵活性，也保留了全状态 mutation 的架构边界。

建议：只有当数据量或并发真实触顶时，再考虑将消息、记忆、日志拆成真正的关系源模型。

## 十一、后续方向

### Phase 1：补强评估闭环

优先级最高。当前系统最需要的不是再加一堆规则，而是建立判断“变好还是变坏”的证据。

建议任务：

1. 扩充 `data/memory_calibration_cases.json` 到 50 条。
2. 建立 `data/manual_memory_eval.local.jsonl` 的真实人工评分流程。
3. 对以下场景每类至少 10 条样例：
   - 旧事接续。
   - 过度表露。
   - 边界遵守。
   - 跟进像催促。
   - 短高密度事件。
   - 用户纠错/删除。
   - 混合语言和口语。
4. 固定回归命令：
   - `python -m pytest -q --basetemp .tmp\pytest -p no:cacheprovider`
   - `python -m compileall -q app scripts tests`
   - `python scripts\evaluate_memory_calibration.py`
   - `python scripts\summarize_manual_memory_eval.py data/manual_memory_eval.local.jsonl`

产出标准：

- 能回答“这个参数为什么调”。
- 能避免凭单条聊天体感改系统。
- 每次记忆策略变更都有正反例保护。

### Phase 2：真实语义能力决策

当前 local hash semantic 是很实用的 MVP fallback，但不是最终语义能力。

两条路线：

- 保守路线：继续保留 local hash，扩充 topic aliases 和词表，只解决明显漏召回。
- 进阶路线：引入真实 embedding + sqlite-vec，做 FTS + vector 混合检索。

建议判断标准：

- 如果 calibration/manual eval 中 `missed_recall` 主要来自同义表达，优先上真实 embedding。
- 如果失败主要来自表露策略和跟进语气，先不要上 embedding，先调 disclosure/followup。

### Phase 3：LLM structured 能力产品化

当前 LLM 抽取和 LLM 意图分类已经有接口，但默认不用。

下一步可以做：

- 设置页/环境档切换 rule vs llm。
- structured 输出解析更健壮，支持 markdown code fence 清洗。
- 对 LLM 抽取和规则抽取做并行对比日志。
- 在人工评估中标记 LLM 是否明显优于规则。

目标不是“一步换成 LLM”，而是用证据决定哪些判断值得花 token。

### Phase 4：表露审计闭环

当前审计只记录问题。下一阶段应让审计影响最终回复。

建议顺序：

1. 对 `fail` 级别先做本地安全兜底：如果 boundary 被表露，重试或返回更保守回复。
2. 对 `warn` 级别只记录，不立即重试，避免过度消耗。
3. 在 generation log 中记录 retry reason 和二次 prompt。
4. 把审计 fail/warn 案例沉淀到校准集。

这是“像朋友”之外的安全底线，优先级高于花哨功能。

### Phase 5：记忆管理 UI

当前 API 已支持查看、删除、确认、整理，但前端仍偏开发窗口。

建议做一个用户可理解的记忆管理面板：

- 待确认记忆：接受/拒绝。
- 长期记忆：按类型筛选。
- 记忆详情：来源证据、置信度、最近使用。
- 删除/归档。
- “这条不该提”的反馈入口。
- “你记错了”的自然语言纠错入口。

这会显著提升产品可控感，也能给反馈闭环提供更干净的数据。

### Phase 6：会话与人格升级

当前是单窗口长期聊天。后续可以扩展：

- 多 session UI。
- 人格版本对比和回滚。
- 背景设定导入后的 LLM 结构化解析。
- 关系状态真正影响回复策略，而不只是画像展示。
- “共同经历”专题视图。

这类方向更偏产品体验，建议排在记忆安全和评估闭环之后。

### Phase 7：生产化边界

只有当准备从本地 MVP 走向多人/云端时，才需要进入这一阶段：

- 用户认证。
- 数据加密。
- 数据导出/删除。
- 多用户隔离。
- 请求限流。
- 后台任务。
- 正式数据库迁移。
- CI。
- 部署配置。
- 安全审计。

当前没有必要过早做这些，否则会分散记忆核心的迭代注意力。

## 十二、建议的近期任务排序

1. 把全量测试命令改成固定 `--basetemp .tmp\pytest -p no:cacheprovider`，避免 Windows temp 权限误报。
2. 扩展校准集到 50 条，优先覆盖 over-disclosure、follow-up fatigue、correction/deletion、slang/mixed-language。
3. 建立人工评分 JSONL 的真实样例流程，并跑 `summarize_manual_memory_eval.py`。
4. 做审计 fail 的回复重试/安全兜底，只先覆盖 boundary/silent_obey。
5. 做记忆确认队列的前端产品化。
6. 对真实 embedding 做小实验，不直接替换当前 fallback。
7. 对 LLM structured extractor/intent 做并行 shadow logging，比较 rule 与 LLM 的差异。
8. 再考虑多 session、设置页和人格版本 UI。

## 十三、代码阅读入口

如果要继续开发，建议按这个顺序读：

1. `README.md`：运行方式和配置。
2. `app/chat_service.py`：主链路。
3. `app/memory/context.py`、`recall.py`、`initiative.py`、`followup.py`、`audit.py`：记忆如何影响回复。
4. `app/memory/extraction.py`、`extractors.py`、`intent.py`、`quality.py`、`lifecycle.py`、`correction.py`：记忆如何产生和被修正。
5. `app/storage.py`：JSON/SQLite 边界。
6. `tests/test_core.py`：当前行为契约。
7. `data/memory_calibration_cases.json`：记忆行为样例。
8. `docs/memory_manual_tuning.md`：人工调参流程。
9. `app/memory/audit_status.md`：路线图完成状态。

## 十四、结论

当前项目最有价值的部分，是已经把“记忆像真人”拆成了可执行的工程问题：哪些信息该记、哪些要确认、记错如何改、旧事什么时候接、什么时候保持沉默、模型说错后怎么审计。这比普通聊天机器人高一个层次。

后续不应急着堆功能。正确方向是先把评估闭环做厚：更多校准样例、人工评分、失败案例沉淀、审计 fail 安全闭环。等能稳定判断“更自然”以后，再引入真实 embedding、LLM structured 常态化、多会话和产品化 UI。否则系统会变复杂，但无法证明体验真的更像长期朋友。
