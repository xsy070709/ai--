# AI 虚拟好友聊天工程项目书

版本：0.3  
日期：2026-07-01  
范围：本项目使用 AI 开发。第一阶段不接入 QQ，而是先实现独立聊天入口，用单窗口长期多轮聊天模拟 QQ 聊天体验；优先完成 DeepSeek-V4 接入、分层记忆功能、系统提示词初版、虚拟好友身份定义，以及“用户导入背景设定后 AI 自行学习设定并完成人格初始化”的闭环。AI 后端通过外部模型 API 实现，本项目后端负责记忆、检索、编排、风格控制和安全边界。

## 1. 项目目标

本项目目标是开发一个具有稳定虚拟好友身份、自然聊天能力、分层记忆、背景设定学习能力和渐进式成长感的 AI 聊天智能体。

初始资源包括：

- 用户导入的背景设定文档：用于锚定 AI 的身份、人格、关系定位、价值观、禁区和长期行为准则，并作为人格初始化的主要输入。
- 独立聊天入口中的长期多轮对话：用于模拟 QQ 私聊体验，持续形成共同经历、更新短期记忆和长期记忆。
- 后续可选的 QQ 聊天记录：用于分析用户画像、聊天风格、兴趣偏好、重要关系和历史上下文，但不进入第一阶段强依赖。
- 后续实时聊天记录：用于持续形成共同经历、更新短期记忆和长期记忆。

当前阶段不做 QQ 接入，先完成本地或 Web 端独立聊天系统闭环。模型能力不内置在本项目内，而是通过统一 LLM API 适配层调用外部模型服务；第一阶段主对话模型优先接入 DeepSeek-V4。

## 2. 核心产品要求

### 2.1 自然聊天

AI 回复需要接近日常聊天，而不是客服式问答：

- 能接住情绪，而不是只回答事实。
- 能使用符合人设的语气、口癖和表达节奏。
- 能根据上下文短回复、追问、打趣、安慰或认真讨论。
- 不频繁暴露系统机制，例如避免说“根据历史聊天记录显示”。
- 避免长篇说教，除非用户明确要求分析。

### 2.2 长期印象

AI 应逐渐形成对用户的稳定印象：

- 用户喜欢什么、讨厌什么。
- 用户常见情绪模式。
- 用户重要的人、事、目标和习惯。
- 用户希望 AI 如何回应自己。
- 哪些话题是雷区，哪些话题可以主动跟进。

### 2.3 短期记忆

AI 应记住当前和近期对话：

- 当前会话最近若干轮原文。
- 当天或近期聊过的话题摘要。
- 未完成事项，例如“明天下午面试”“晚上要交材料”。
- 当前情绪状态和对话氛围。

### 2.4 历史聊天接续

当用户提到旧人旧事时，AI 能必要时检索历史聊天记录：

- 通过人名、时间、关键词、语义相似度召回旧片段。
- 用旧片段帮助理解上下文。
- 必要时追问确认，不强行编造。
- 避免泄露第三方隐私。

### 2.5 学习成长感

成长感应通过行为体现：

- 初期多确认用户偏好。
- 中期能记住用户表达习惯和重要事项。
- 后期能主动接续共同经历。
- 风格逐渐贴合用户，但核心人设保持稳定。

### 2.6 背景设定学习与人格初始化

用户可以导入背景设定，AI 需要从设定中学习并生成可执行的人格配置，而不是只把设定原文塞进 Prompt。

初始化结果应包含：

- 虚拟好友身份：名字、关系定位、说话方式、互动边界。
- 核心性格：稳定特征、情绪表达方式、价值倾向。
- 行为规则：该主动什么、回避什么、如何安慰、如何开玩笑。
- 禁区与安全边界：隐私、依赖、角色扮演边界、不可承诺事项。
- 初始系统提示词：供第一版聊天闭环直接使用。

人格初始化完成后，后续聊天可以学习用户偏好和共同经历，但不得随意改写核心性格。性格变化必须有明确版本记录、来源和用户确认。

## 3. 技术路径调研

### 3.1 不建议第一阶段直接微调

第一阶段不建议把 QQ 聊天记录直接用于 SFT/LoRA 微调，原因：

- 历史记录包含大量第三方隐私，清洗成本高。
- 微调后的行为不易解释，也不易删除某条记忆。
- 用户偏好和关系状态会变化，微调模型更新成本高。
- 微调更容易学到错误语气、脏数据和临时情绪。

更合适的第一阶段路线是：

```text
背景设定学习 + 人格初始化 + 独立聊天入口 + DeepSeek-V4 接入 + 分层记忆 + Prompt 编排 + 评估集
```

当独立聊天闭环、记忆边界、隐私边界、评估体系成熟后，再考虑接入 QQ 记录、做历史检索或用少量高质量样本做风格微调。

### 3.2 RAG 路线

RAG 适合本项目的历史聊天检索需求。LlamaIndex 官方 RAG 文档将 RAG 系统拆为加载、索引、存储、查询和评估等阶段，适合用于聊天记录知识库和检索系统的工程化设计。参考：[LlamaIndex RAG 文档](https://developers.llamaindex.ai/python/framework/understanding/rag/)。

本项目中 RAG 的职责不是回答百科知识，而是帮助 AI 在必要时找回相关历史上下文。

适用场景：

- 用户提到“上次那个事情”。
- 用户提到某个朋友、地点、游戏、课程、项目。
- 用户询问“你还记得我之前说过什么吗”。
- 当前消息语义和某些历史片段高度相似。

不适用场景：

- 普通寒暄。
- 情绪强烈时的第一响应。
- 用户明确不希望翻旧账。
- 涉及第三方隐私且没有必要引用原文。

### 3.3 Agent 记忆路线

LangGraph/LangChain 的记忆文档将记忆区分为短期记忆和长期记忆，并进一步讨论语义、情节和程序性记忆。这个分类适合本项目：短期记忆用于当前对话连续性，长期记忆用于用户画像和关系成长。参考：[LangGraph Memory 概念文档](https://docs.langchain.com/oss/python/concepts/memory)。

本项目建议采用四层记忆：

- 工作记忆：当前会话窗口。
- 会话摘要记忆：近期对话摘要。
- 长期语义记忆：用户稳定事实、偏好和关系状态。
- 历史聊天检索库：可按需查询的历史原文片段。

### 3.4 向量数据库路线

候选方案：

| 方案 | 优点 | 缺点 | 推荐阶段 |
| --- | --- | --- | --- |
| PostgreSQL + pgvector | 架构简单，结构化数据和向量共库，部署成本低 | 大规模检索和复杂过滤性能不如专用向量库 | MVP / V1 |
| Qdrant | 向量检索能力强，payload 过滤成熟，适合按人物、时间、敏感等级过滤 | 需要额外服务，部署复杂度更高 | V1 / V2 |
| Milvus | 面向大规模向量检索 | 对个人项目偏重 | 大规模后续版本 |
| Chroma | 上手简单 | 生产化能力和复杂过滤相对弱 | 原型验证 |

pgvector 是 PostgreSQL 的向量相似度搜索扩展，适合小到中等规模数据直接落在 PostgreSQL 中。参考：[pgvector README](https://github.com/pgvector/pgvector)。

Qdrant 支持基于 payload 的过滤，适合按聊天对象、时间范围、敏感级别、话题标签组合过滤。参考：[Qdrant Filtering 文档](https://qdrant.tech/documentation/search/filtering/)。

推荐：

- MVP：PostgreSQL + pgvector。
- 聊天记录规模较大或过滤复杂后：迁移或并行引入 Qdrant。

### 3.5 编排框架路线

候选方案：

| 方案 | 优点 | 缺点 | 推荐 |
| --- | --- | --- | --- |
| 手写流程编排 | 可控、透明、易调试 | 后续复杂状态机需要自己维护 | MVP 推荐 |
| LangGraph | 适合有状态 Agent、记忆、分支决策、工具调用 | 学习成本和抽象成本较高 | V1/V2 推荐 |
| LangChain Agent | 生态成熟 | 对复杂长期状态控制需要谨慎设计 | 可局部使用 |
| LlamaIndex Workflow | 数据索引和检索结合较好 | Agent 状态管理不是唯一重点 | 可用于 RAG 层 |

推荐：

- MVP 不急着上复杂 Agent 框架。
- 先手写明确链路：理解消息 -> 判断检索 -> 取记忆 -> 生成回复 -> 写记忆。
- 当状态分支和工具调用变多后，再引入 LangGraph。

### 3.6 外部模型 API 路线

由于 AI 后端通过 API 实现，本项目不直接训练或托管主对话模型。第一阶段优先接入 DeepSeek-V4 作为主对话模型，同时系统应将模型能力抽象为统一的 `LLM Gateway`，业务层只依赖内部接口，不直接依赖具体供应商 SDK。

需要通过 API 调用的能力：

- 对话生成：生成最终聊天回复。
- 消息理解：判断情绪、意图、是否需要检索。
- 摘要生成：生成会话摘要、历史片段摘要。
- 记忆抽取：从对话中抽取长期记忆候选。
- Embedding：为聊天片段、记忆、查询生成向量。
- 可选重排序：对召回片段做 rerank。
- 可选安全检查：对输出做二次审核或敏感信息裁剪。

统一 API 适配的好处：

- 后续可以切换模型供应商。
- 可以区分高质量模型和低成本模型。
- 可以针对不同任务选择不同模型。
- 可以统一做限流、重试、超时、日志、成本统计。
- 可以隔离 API 密钥，避免业务模块散落密钥和模型参数。

推荐模型分层：

| 任务 | 推荐模型策略 |
| --- | --- |
| 最终回复生成 | 第一阶段使用 DeepSeek-V4，要求中文表达自然、角色稳定、可流式输出 |
| 意图/情绪分类 | 使用低成本快速模型，或规则 + 小模型 |
| 会话摘要 | 使用中低成本模型，允许异步执行 |
| 记忆抽取 | 使用中等模型，要求结构化输出稳定 |
| Embedding | 使用专用 embedding API |
| 安全检查 | 规则优先，必要时使用低成本模型复核 |

DeepSeek-V4 第一阶段接入要求：

- `LLM Gateway` 必须支持 DeepSeek-V4 的 chat、stream、structured 三类调用。
- 所有模型名、API base、key、超时、重试次数从配置读取。
- 最终回复使用 DeepSeek-V4；记忆抽取和人格初始化可以先复用 DeepSeek-V4，后续再拆分低成本模型。
- Prompt Builder 必须能输出完整调试视图，但普通日志默认只记录 `prompt_manifest`，不保存完整敏感上下文。
- 如果 DeepSeek-V4 调用失败，应能用简短降级回复保持单窗口聊天不中断。

API 路线下的关键取舍：

- 每轮不要把完整历史发送给模型，只发送裁剪后的必要上下文。
- 长期记忆和历史聊天原文保存在本地数据库，不交给模型长期托管。
- 需要记录每次模型调用的 token、耗时、模型名和用途。
- API 超时或失败时，应能降级回复，而不是整轮对话崩溃。

## 4. 总体架构设计

```text
┌──────────────────────────┐
│  独立 Chat UI/API         │
│  单窗口长期多轮聊天       │
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐
│     Conversation API      │
│  FastAPI / WebSocket/SSE  │
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐
│     Dialogue Orchestrator │
│  路由、策略、Prompt 编排   │
└──────┬───────────┬───────┘
       │           │
┌──────▼─────┐ ┌───▼────────────┐
│ Memory Svc │ │ Retrieval Svc   │
│ 短/中/长期 │ │ 历史聊天检索     │
└──────┬─────┘ └───┬────────────┘
       │           │
┌──────▼───────────▼───────┐
│ PostgreSQL / pgvector     │
│ messages, memories, index │
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐
│      LLM Gateway          │
│  API适配、重试、限流、审计 │
└─────────────┬────────────┘
              │
┌─────────────▼────────────┐
│ External Model Providers  │
│ chat / embedding / rerank │
└──────────────────────────┘
```

API 后端模式下，本项目的职责边界如下：

| 层 | 本项目负责 | 外部模型 API 负责 |
| --- | --- | --- |
| 对话状态 | 会话、短期记忆、长期记忆、历史检索 | 不负责保存业务状态 |
| Prompt | 动态拼装、裁剪、优先级控制 | 按输入生成结果 |
| 安全 | 隐私过滤、第三方数据裁剪、输出检查 | 可作为辅助审核 |
| 成长 | 记忆写入、偏好更新、关系状态变化 | 不直接保存成长状态 |
| 成本 | 调用路由、缓存、限流、统计 | 按调用计费 |

## 5. 模块设计

### 5.1 独立聊天入口模块

第一阶段用独立聊天入口模拟 QQ 私聊体验，不接入 QQ 客户端、不监听 QQ 消息、不依赖 QQ 协议。

职责：

- 提供单窗口长期多轮聊天界面。
- 支持用户连续输入、AI 流式回复、历史消息滚动查看。
- 支持会话长期保存，用户下次打开后能接续旧聊天。
- 支持展示基础状态，例如当前人格版本、记忆写入状态、模型连接状态。
- 支持调试模式查看本轮使用的记忆、策略和降级原因。

第一阶段设计原则：

- 页面像聊天窗口，而不是管理后台。
- 默认只有一个主要聊天入口，避免多会话带来的状态复杂度。
- 允许后台按天或长度生成会话摘要，但前端体验保持“长期连续聊天”。
- QQ 只作为体验参照，不作为技术依赖。

### 5.2 背景设定导入与人格初始化模块

职责：

- 接收用户导入的背景设定文本、Markdown 或 JSON。
- 调用 DeepSeek-V4 对背景设定进行结构化理解。
- 生成虚拟好友身份、人设边界、说话风格、关系定位和初始系统提示词。
- 将人格初始化结果保存为版本化配置。
- 支持用户查看、确认、重生成或手动修正初始化结果。

初始化流程：

```text
导入背景设定
-> 设定解析与冲突检查
-> 人格结构化抽取
-> 初始系统提示词生成
-> 用户确认
-> 保存 persona_version
-> 进入聊天闭环
```

结构化输出建议：

```yaml
identity:
  name: ""
  role: "virtual_friend"
  relationship_to_user: ""
  self_description: ""
personality:
  stable_traits: []
  emotional_style: []
  humor_style: []
  conflict_style: []
speaking_style:
  tone: []
  sentence_length: ""
  emoji_policy: ""
  taboo_phrases: []
behavior_rules:
  comfort_user: []
  ask_follow_up: []
  proactive_topics: []
  forbidden_behaviors: []
boundaries:
  privacy_rules: []
  dependency_boundaries: []
  safety_rules: []
system_prompt:
  version: ""
  content: ""
```

人格稳定性要求：

- `stable_traits`、`relationship_to_user`、`boundaries` 属于高稳定字段，默认不能被普通聊天自动改写。
- 聊天中学到的用户偏好只能影响回复策略和互动细节，不能直接覆盖核心人格。
- 任何人格版本变化都必须记录来源、修改原因、时间和确认状态。
- 当背景设定冲突时，优先提示用户确认，不让模型自行合并成不透明结果。

### 5.3 历史数据导入模块

QQ 聊天记录导入不属于第一阶段必做能力，后续作为历史学习和检索增强模块接入。

职责：

- 导入 QQ 聊天导出文件或其他历史聊天文件。
- 解析文本、HTML、JSON 或数据库导出格式。
- 统一为内部消息格式。
- 标注发言人、时间、会话、群聊/私聊。
- 清理无效消息，如撤回提示、系统通知、空消息。

输入示例：

```json
{
  "source": "qq_export",
  "conversation_name": "friend_a",
  "sender": "user",
  "timestamp": "2024-03-01T20:10:00+08:00",
  "content": "今天真的有点烦",
  "message_type": "text"
}
```

输出表：

- `raw_import_files`
- `raw_messages`
- `normalized_messages`
- `conversation_participants`

### 5.4 数据清洗与脱敏模块

职责：

- 去除重复消息。
- 修复时间格式。
- 标记第三方个人信息。
- 识别手机号、地址、身份证、邮箱、账号、学校、公司等敏感信息。
- 将第三方真实姓名映射为稳定 ID。

脱敏策略：

| 数据类型 | 处理方式 |
| --- | --- |
| 用户本人信息 | 可保留，但需要可删除 |
| 朋友姓名 | 映射为 `person_xxx` |
| 手机号/身份证/地址 | 默认移除或加密保存 |
| 第三方私密经历 | 不进入长期记忆，只保留必要抽象摘要 |
| 群聊原文 | 默认更高敏感等级 |

### 5.5 用户画像模块

职责：

- 从用户本人发言中抽取稳定表达特征。
- 从历史对话中总结兴趣、偏好和重要事件。
- 形成可更新的画像，而不是一次性静态报告。

画像维度：

- 语言风格：短句/长句、玩梗、语气词、表情、标点习惯。
- 情绪模式：焦虑点、兴奋点、压力来源。
- 兴趣主题：游戏、学习、工作、创作、关系等。
- 互动偏好：喜欢安慰、分析、吐槽、陪伴还是建议。
- 雷区：不喜欢被说教、不喜欢某些称呼等。

画像不直接等于 Prompt 长文本，应拆成结构化字段。

### 5.6 背景设定模块

职责：

- 管理 AI 的核心人设。
- 将背景设定拆成结构化配置。
- 保持版本化，支持回滚。

建议结构：

```yaml
identity:
  name: ""
  apparent_age: ""
  relationship_to_user: "AI girlfriend"
  core_personality: []
  speaking_style: []
boundaries:
  privacy_rules: []
  emotional_boundaries: []
  forbidden_behaviors: []
relationship:
  initial_stage: "not_overly_intimate"
  growth_rules: []
worldview:
  values: []
  preferences: []
```

优先级规则：

```text
安全与隐私规则 > 背景设定 > 用户明确偏好 > 长期记忆 > 历史聊天片段 > 当前模型自由发挥
```

### 5.7 分层记忆模块

第一阶段重点攻克分层记忆功能。记忆系统不能只是把聊天历史无限塞进上下文，而要区分不同生命周期、不同可信度、不同写入规则的记忆。

推荐采用五层记忆：

| 层级 | 内容 | 生命周期 | 写入方式 | 使用方式 |
| --- | --- | --- | --- | --- |
| 工作记忆 | 当前窗口最近 N 轮原文 | 当前上下文 | 自动 | 每轮必带，按 token 裁剪 |
| 会话摘要记忆 | 一段时间内聊过的话题、情绪、未完成事项 | 天/周级 | 自动摘要，用户可查看 | 上下文过长时替代旧原文 |
| 长期语义记忆 | 用户稳定事实、偏好、雷区、关系状态 | 长期 | 抽取候选 + 置信度 + 可确认 | 按相关性召回 |
| 人格记忆 | 虚拟好友身份、核心性格、说话风格、边界 | 版本化长期 | 背景设定初始化 + 用户确认 | 高优先级进入 Prompt |
| 共同经历记忆 | 用户和 AI 在聊天中形成的事件与约定 | 长期 | 摘要抽取 + 来源记录 | 用于制造熟悉感和接续感 |

记忆写入原则：

- 事实和偏好不能仅凭一次模糊表达就高置信写入。
- 用户明确说“记住”“以后都这样”时，可提高置信度。
- 与人格冲突的记忆不能自动覆盖人格，只能作为待确认候选。
- 记忆必须可查看、可删除、可修正、可追溯来源。
- 每轮回复前要先选择必要记忆，而不是全量注入。

#### 工作记忆

保存当前会话最近 N 轮原文，通常 10-30 轮。

作用：

- 保证当前上下文连续。
- 避免每轮都查数据库。

#### 会话摘要记忆

当对话过长或会话结束时生成摘要。

字段：

- `summary`
- `topics`
- `user_emotion`
- `unfinished_items`
- `follow_up_at`
- `importance`

#### 长期语义记忆

保存稳定事实和偏好。

字段建议：

```sql
id
user_id
memory_type
content
confidence
source_type
source_id
created_at
updated_at
last_confirmed_at
expires_at
sensitivity_level
is_user_confirmed
status
```

记忆类型：

- `preference`
- `dislike`
- `fact`
- `relationship`
- `event`
- `goal`
- `boundary`
- `response_rule`

#### 历史聊天检索库

聊天记录切分为片段后入库。

片段字段：

- `chunk_id`
- `conversation_id`
- `start_time`
- `end_time`
- `participants`
- `speaker_ratio`
- `text`
- `summary`
- `topics`
- `entities`
- `emotion_tags`
- `sensitivity_level`
- `embedding`

切分策略：

- 按时间间隔切分，例如间隔超过 20-30 分钟开新片段。
- 按话题切分，例如语义突变时开新片段。
- 每个 chunk 控制在 300-1000 中文字左右。
- 保留前后相邻 chunk 的引用关系。

### 5.8 检索模块

采用混合检索：

```text
关键词检索 + 向量检索 + 元数据过滤 + 时间衰减 + 重排序
```

检索触发条件：

- 用户提到人名、旧事、时间。
- 用户问“你还记得吗”。
- 当前话题和长期记忆相关。
- 对话决策器判断短期上下文不足。

检索过滤条件：

- 只查和用户相关的会话。
- 默认排除高敏感第三方原文。
- 可按时间范围过滤。
- 可按聊天对象过滤。
- 可按话题标签过滤。

检索输出不直接给生成模型，应先压缩成“可用上下文”：

```json
{
  "memory_context": [
    {
      "type": "history_chunk",
      "summary": "用户曾在 2024 年和朋友聊过考研压力，情绪偏低。",
      "evidence": "低敏摘要，不直接暴露第三方隐私",
      "confidence": 0.78
    }
  ]
}
```

### 5.9 对话决策模块

职责：

- 判断当前消息类型。
- 判断是否检索。
- 判断回复策略。
- 判断是否写入记忆。

消息类型：

- `casual_chat`
- `emotional_support`
- `old_topic_reference`
- `direct_question`
- `preference_update`
- `memory_request`
- `relationship_interaction`
- `sensitive_topic`

回复策略：

- 轻松闲聊
- 情绪安抚
- 撒娇/亲密表达
- 认真分析
- 追问确认
- 引用共同记忆
- 避免回答并转移

### 5.10 回复生成模块

Prompt 建议分层：

1. 系统规则：安全、隐私、不伪装真人、不泄露第三方隐私。
2. 虚拟好友身份：名字、关系定位、自我认知、互动边界。
3. 核心人格：稳定性格、价值倾向、语气边界。
4. 当前关系状态：亲密度、互动阶段。
5. 用户画像：稳定偏好、雷区、表达习惯。
6. 当前上下文：最近几轮对话。
7. 检索上下文：相关长期记忆、共同经历和历史摘要。
8. 本轮策略：安慰/打趣/追问/分析。
9. 用户最新消息。

生成原则：

- 默认短回复。
- 先回应情绪，再回应事实。
- 需要查证时不编造。
- 引用记忆要自然。
- 不要频繁解释自己是 AI 系统。

### 5.11 LLM API 网关模块

由于模型通过 API 提供，必须单独建设 `LLM Gateway`，不要让业务模块直接调用模型供应商。

职责：

- 统一封装不同模型供应商。
- 管理 API key 和模型配置。
- 提供 chat、json、embedding、rerank 等内部方法。
- 统一处理超时、重试、限流和熔断。
- 记录 token 用量、耗时、错误、调用用途。
- 支持不同任务使用不同模型。
- 支持流式输出给前端。
- 支持模型降级和 fallback。

内部接口建议：

```python
class LLMGateway:
    async def chat(self, request: ChatRequest) -> ChatResult:
        ...

    async def structured(self, request: StructuredRequest) -> dict:
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    async def rerank(self, query: str, documents: list[str]) -> list[RankedDocument]:
        ...
```

配置示例：

```yaml
llm:
  default_provider: "deepseek"
  chat_model: "deepseek-v4"
  cheap_model: "deepseek-v4"
  embedding_model: "embedding_model"
  timeout_seconds: 30
  max_retries: 2
  stream: true
  max_prompt_tokens: 12000
  max_completion_tokens: 800
```

任务路由示例：

| 调用场景 | API 方法 | 是否同步 | 失败降级 |
| --- | --- | --- | --- |
| 最终回复 | `chat` | 同步 | 使用较短上下文重试，失败后返回温和降级回复 |
| 情绪/意图识别 | `structured` | 同步 | 使用规则分类 |
| 历史片段摘要 | `structured` | 异步 | 标记待处理 |
| 长期记忆抽取 | `structured` | 异步 | 下次任务重试 |
| Embedding | `embed` | 异步/批量 | 延迟入索引 |
| Rerank | `rerank` | 同步可选 | 使用原始相似度排序 |

上下文发送原则：

- 只发送本轮必要材料。
- 发送给模型的历史片段优先使用摘要，而不是第三方原文。
- 高敏感片段默认不发送。
- 每次发送前记录 `prompt_manifest`，说明包含了哪些上下文类型，但不在日志里保存完整敏感原文。
- API 日志中默认脱敏，不记录完整聊天记录。

### 5.12 后处理与安全模块

检查项：

- 是否泄露第三方隐私。
- 是否编造历史聊天。
- 是否过度承诺。
- 是否使用不符合人设的语气。
- 是否过度冗长。
- 是否错误地把朋友信息当成用户信息。

高风险回复处理：

- 重新生成。
- 降级为追问。
- 删除敏感细节。
- 只保留抽象表达。

### 5.13 学习与成长模块

成长变量：

- `familiarity_score`：熟悉度。
- `intimacy_level`：亲密阶段。
- `trust_score`：用户信任度。
- `style_preferences`：回复风格偏好。
- `topic_affinity`：话题亲近度。

成长来源：

- 用户显式反馈：“别这么正式”“以后这样叫我”。
- 长期互动频率。
- 用户主动分享的深度。
- 用户对某类回复的正负反馈。
- 共同经历沉淀。

成长约束：

- 亲密度影响语气，不突破隐私和安全边界。
- 背景设定的核心人格不随意变化。
- 记忆可审计、可删除、可修正。

## 6. 数据库设计草案

### 6.1 核心表

```text
users
personas
persona_versions
conversations
participants
raw_import_files
raw_messages
normalized_messages
message_chunks
conversation_sessions
session_summaries
long_term_memories
memory_events
retrieval_logs
generation_logs
feedback_events
```

### 6.2 表职责

| 表 | 职责 |
| --- | --- |
| `users` | 用户主表 |
| `personas` | AI 人设主表 |
| `persona_versions` | 人设版本 |
| `conversations` | QQ 会话或应用内会话 |
| `participants` | 会话参与者，含脱敏映射 |
| `raw_messages` | 原始消息 |
| `normalized_messages` | 标准化消息 |
| `message_chunks` | 检索片段和向量 |
| `conversation_sessions` | AI 实时聊天会话 |
| `session_summaries` | 会话摘要 |
| `long_term_memories` | 长期记忆 |
| `memory_events` | 记忆创建、确认、修改、删除记录 |
| `retrieval_logs` | 检索日志 |
| `generation_logs` | 生成日志 |
| `feedback_events` | 用户反馈 |

## 7. 项目结构规划

推荐 Python 后端项目结构：

```text
qq-ai-girlfriend/
  README.md
  pyproject.toml
  .env.example
  docker-compose.yml
  alembic.ini

  app/
    main.py
    config.py
    logging.py

    api/
      routes_chat.py
      routes_memory.py
      routes_import.py
      routes_persona.py
      routes_admin.py

    core/
      orchestrator.py
      dialogue_state.py
      prompt_builder.py
      policy.py
      safety.py

    llm/
      base.py
      gateway.py
      provider_base.py
      provider_openai_compatible.py
      provider_custom_http.py
      local_client.py
      embeddings.py
      reranker.py
      rate_limit.py
      usage_tracker.py
      fallback.py

    memory/
      working_memory.py
      session_summary.py
      long_term_memory.py
      memory_extractor.py
      memory_conflict.py
      memory_decay.py

    retrieval/
      chunking.py
      keyword_search.py
      vector_search.py
      hybrid_search.py
      retrieval_router.py
      context_compressor.py

    ingestion/
      qq_parser.py
      normalizer.py
      deduplicator.py
      pii_detector.py
      anonymizer.py
      importer.py

    persona/
      schema.py
      loader.py
      versioning.py
      consistency_checker.py

    style/
      user_profile.py
      style_analyzer.py
      response_style.py

    db/
      session.py
      models.py
      repositories/
        messages.py
        memories.py
        personas.py
        retrieval.py

    schemas/
      chat.py
      memory.py
      import_job.py
      persona.py

    jobs/
      summarize_session.py
      extract_memories.py
      build_embeddings.py
      rebuild_index.py
      retry_failed_llm_calls.py

    evals/
      datasets/
      evaluators.py
      run_eval.py
      metrics.py

  migrations/
  scripts/
    import_qq_export.py
    build_index.py
    run_chat_cli.py
    inspect_memory.py

  tests/
    test_ingestion.py
    test_memory.py
    test_retrieval.py
    test_prompt_builder.py
    test_safety.py

  docs/
    architecture.md
    memory_design.md
    data_privacy.md
    prompt_design.md
    evaluation_plan.md
```

## 8. 开发进程规划

### 阶段 0：需求冻结与样本确认

周期：2-3 天

目标：

- 确认第一阶段不接入 QQ，只做独立聊天入口。
- 确认单窗口长期多轮聊天的产品形态。
- 确认背景设定导入格式。
- 确认虚拟好友身份边界和关系定位。
- 确认隐私边界。
- 选定 DeepSeek-V4 作为第一版主对话模型，并确认部署方式。

交付物：

- 需求说明。
- 背景设定样本说明。
- 虚拟好友身份约束说明。
- 风险清单。
- MVP 范围冻结。

### 阶段 1：独立聊天入口与 DeepSeek-V4 接入

周期：1 周

任务：

- 实现单窗口 Web/CLI 聊天入口。
- 实现 FastAPI 聊天接口。
- 实现 `LLM Gateway` 的 DeepSeek-V4 provider。
- 支持普通回复和流式回复。
- 支持长期会话保存和历史消息加载。
- 支持模型调用日志、超时、重试和降级回复。
- 建立当前会话工作记忆。

验收：

- 能在独立入口连续对话 20 轮不断片。
- DeepSeek-V4 能稳定返回中文聊天回复。
- API 超时或失败时不会导致聊天窗口崩溃。
- 每次模型调用记录用途、模型名、耗时和 token 估算。
- 中文内容无乱码。

### 阶段 2：背景设定学习与人格初始化

周期：1 周

任务：

- 背景设定导入接口。
- 背景设定解析与冲突检查。
- 使用 DeepSeek-V4 抽取虚拟好友身份、核心人格、说话风格和边界规则。
- 生成系统提示词初版。
- 保存 `persona_versions`。
- 提供人格初始化结果查看、确认、重生成和手动修正能力。

验收：

- 用户导入背景设定后，系统能生成结构化人格配置。
- 生成的系统提示词能直接驱动聊天。
- 虚拟好友身份明确，不摇摆、不自相矛盾。
- 核心性格字段被标记为高稳定，不被普通聊天自动覆盖。
- 用户能确认或修正初始化结果。

### 阶段 3：分层记忆 MVP

周期：1-2 周

任务：

- 工作记忆裁剪。
- 会话摘要生成。
- 长期语义记忆表。
- 人格记忆版本读取。
- 共同经历记忆初版。
- 显式记忆写入。
- 记忆抽取任务。
- 记忆置信度、来源和敏感等级记录。
- 记忆查看、修改、删除接口。

验收：

- 用户说“记住我喜欢 X”后，后续能自然使用。
- 聊天过长后能自动摘要并继续接上。
- 人格记忆、用户偏好、共同经历不会混在同一层不可区分。
- 记忆能查看、修改、删除。
- 错误记忆不会不可控地扩散。
- 记忆抽取通过结构化 API 输出，字段不完整时不直接入库。

### 阶段 4：对话决策与风格控制

周期：1-2 周

任务：

- 消息分类。
- 记忆召回路由。
- 回复策略选择。
- 用户画像初版。
- 风格偏好学习。
- 后处理安全检查。
- 系统提示词模板细化。

验收：

- 普通闲聊不会过度检索记忆。
- 情绪倾诉优先回应情绪。
- 回复长度和语气更接近熟人聊天。
- 角色语气符合背景设定和系统提示词。
- 核心性格保持稳定，用户偏好只影响互动细节。

### 阶段 5：历史聊天检索与 QQ 数据预备

周期：1-2 周

任务：

- QQ 聊天记录导入格式调研。
- 聊天记录 chunking。
- embedding 生成。
- pgvector 检索。
- 关键词检索。
- 混合检索和重排序。
- 检索上下文压缩。
- 第三方隐私过滤。

验收：

- 能导入至少 3 个历史聊天样本。
- 输入人名/关键词能召回对应历史片段。
- 输入语义相似问题能召回相关片段。
- 检索结果带来源和置信度。
- 高敏感内容默认不直接进入 Prompt。
- QQ 实时接入仍不进入本阶段。

### 阶段 6：成长机制与评估

周期：1-2 周

任务：

- 熟悉度、亲密度、信任度等状态变量。
- 共同经历沉淀。
- 未完成事项跟进。
- 评估集建设。
- 自动化评估和人工评分。

验收：

- AI 能跟进近期事项。
- AI 的语气随熟悉度轻微变化。
- 人设不漂移。
- 对 50-100 个测试场景有评分记录。

## 9. MVP 范围

MVP 必须包含：

- 独立聊天入口。
- 单窗口长期多轮聊天。
- DeepSeek-V4 接入。
- 外部模型 API 网关。
- 背景设定导入。
- AI 自行学习背景设定并完成人格初始化。
- 虚拟好友身份、核心人格和系统提示词初版。
- 当前会话工作记忆。
- 会话摘要。
- 显式长期记忆。
- 共同经历记忆初版。
- 基础隐私过滤。
- 最小评估集。
- 模型调用失败降级。
- API 调用成本和日志统计。

MVP 不包含：

- QQ 实时接入。
- QQ 聊天记录强制导入。
- 复刻真实 QQ 客户端。
- 多窗口复杂会话管理。
- 主动定时发消息。
- 大规模微调。
- 复杂多智能体系统。
- 完整移动端。
- 多用户商业化权限系统。

## 10. 评估体系

### 10.1 对话质量指标

| 指标 | 说明 |
| --- | --- |
| 自然度 | 是否像日常聊天 |
| 连续性 | 是否接得住当前上下文 |
| 记忆准确性 | 是否正确使用记忆 |
| 不乱编 | 不凭空制造历史 |
| 人设一致性 | 是否符合背景设定 |
| 情绪响应 | 是否先接住情绪 |
| 隐私安全 | 是否避免泄露第三方隐私 |
| 长度控制 | 是否避免过度长篇 |

### 10.2 测试场景

至少准备以下场景：

- 普通寒暄。
- 用户倾诉压力。
- 用户导入背景设定并要求初始化人格。
- 用户询问虚拟好友的身份。
- 用户连续 20 轮聊天后切换话题。
- 用户要求 AI 记住偏好。
- 用户提到旧朋友。
- 用户问“你还记得吗”。
- 用户纠正记忆。
- 用户要求删除记忆。
- 用户试探第三方隐私。
- 用户要求改变称呼。
- 用户连续多轮换话题。
- 用户情绪强烈但信息不足。

### 10.3 人工评分

每条测试对话按 1-5 分评分：

- 1：明显错误或不自然。
- 2：能回答但像客服。
- 3：基本可用。
- 4：自然且记忆较准。
- 5：像熟悉的人，情绪和记忆都接得住。

## 11. 安全与隐私设计

### 11.1 原则

- 默认不把完整聊天库发送给模型。
- 每轮只发送必要上下文。
- 第三方隐私不进入长期记忆，除非高度抽象且必要。
- 原始聊天记录加密保存。
- 用户可以查看和删除 AI 记住的内容。
- 不复刻真实朋友人格。
- API 调用前做上下文裁剪和敏感信息过滤。
- API 调用日志默认不保存完整 prompt 和完整回复原文，或至少加密保存。

### 11.2 风险控制

| 风险 | 控制 |
| --- | --- |
| 泄露朋友隐私 | 脱敏、敏感等级、后处理检查 |
| 记忆错误 | 来源、置信度、用户确认、删除机制 |
| 人设漂移 | 背景设定高优先级、版本化 |
| 人格初始化错误 | 结构化抽取、冲突检查、用户确认、版本回滚 |
| 聊天像客服 | 风格样例、短回复策略、评估集 |
| 过度依赖 | 主动性克制、边界规则 |
| 成本过高 | 检索路由、摘要压缩、缓存 |
| API 供应商故障 | 超时、重试、fallback、降级回复 |
| API 数据外发过多 | 最小上下文、脱敏、摘要替代原文 |
| 模型切换成本高 | LLM Gateway 抽象 Provider |

## 12. Prompt 设计原则

不要把所有内容塞进一个巨大 Prompt。应动态拼装：

```text
[系统底线]
[虚拟好友身份]
[核心人格]
[当前关系阶段]
[用户画像关键项]
[最近对话]
[相关记忆]
[本轮回复策略]
[用户消息]
```

API 后端模式下，Prompt Builder 必须输出两类内容：

- `model_messages`：真正发送给模型的上下文。
- `prompt_manifest`：内部审计用的上下文清单，例如使用了哪些记忆、哪些历史片段、敏感等级是多少。

不要在普通日志里直接保存完整 `model_messages`。调试环境可以开启加密日志，但生产默认关闭。

不同场景使用不同 Prompt 模板：

- 人格初始化模板。
- 日常闲聊模板。
- 情绪支持模板。
- 旧话题接续模板。
- 记忆确认模板。
- 敏感话题模板。

## 13. API 草案

### 13.1 聊天

```http
POST /api/chat
```

请求：

```json
{
  "user_id": "user_001",
  "session_id": "session_001",
  "message": "你还记得我之前说那个面试吗？"
}
```

响应：

```json
{
  "reply": "记得，你之前说下午那场让你有点紧张。今天是想再准备一下，还是已经面完了？",
  "used_memories": ["mem_123"],
  "used_history_chunks": ["chunk_456"],
  "strategy": "old_topic_reference"
}
```

如果前端需要打字机效果，聊天接口应支持 SSE 或 WebSocket：

```http
GET /api/chat/stream?session_id=session_001
```

流式事件建议：

```text
event: token
data: {"delta":"记得"}

event: meta
data: {"strategy":"old_topic_reference","used_memories":["mem_123"]}

event: done
data: {}
```

### 13.6 模型调用健康检查

```http
GET /api/llm/health
```

返回：

```json
{
  "chat_provider": "provider_a",
  "embedding_provider": "provider_a",
  "chat_available": true,
  "embedding_available": true,
  "last_error": null
}
```

### 13.7 模型调用统计

```http
GET /api/admin/llm-usage?from=2026-06-01&to=2026-06-30
```

返回：

```json
{
  "total_calls": 1200,
  "chat_calls": 640,
  "embedding_calls": 420,
  "summary_calls": 140,
  "estimated_cost": 12.35
}
```

### 13.2 导入聊天记录

```http
POST /api/import/qq
```

### 13.3 查看记忆

```http
GET /api/memories?user_id=user_001
```

### 13.4 删除记忆

```http
DELETE /api/memories/{memory_id}
```

### 13.5 更新人设

```http
POST /api/persona/versions
```

## 14. 部署建议

### 本地开发

```text
FastAPI
PostgreSQL + pgvector
Redis 可选
本地文件加密归档
Web/CLI 测试入口
外部 LLM API
```

### 后续生产化

```text
API 服务
异步任务 Worker
PostgreSQL
Qdrant
对象存储
日志与评估系统
管理后台
LLM API 网关
密钥管理
调用限流和成本监控
```

### API 密钥与配置

`.env.example` 应包含：

```text
LLM_PROVIDER=
LLM_API_BASE_URL=
LLM_API_KEY=
LLM_CHAT_MODEL=deepseek-v4
LLM_CHEAP_MODEL=deepseek-v4
LLM_EMBEDDING_MODEL=
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
LLM_STREAM=true
```

密钥管理要求：

- 不提交真实 API key。
- 本地开发使用 `.env`。
- 部署环境使用平台密钥管理或环境变量。
- 日志中不得打印 Authorization header。
- 错误日志中不得包含完整敏感 prompt。

## 15. 关键里程碑

| 里程碑 | 目标 | 预计周期 |
| --- | --- | --- |
| M0 | 独立聊天范围、背景设定样本、DeepSeek-V4 配置确认 | 2-3 天 |
| M1 | 独立聊天入口和 DeepSeek-V4 聊天闭环 | 1 周 |
| M2 | 背景设定学习、人格初始化、系统提示词初版 | 1 周 |
| M3 | 分层记忆 MVP 可用 | 1-2 周 |
| M4 | 对话策略、风格控制和人格稳定性验证 | 1-2 周 |
| M5 | 历史聊天检索与 QQ 数据预备 | 1-2 周 |
| M6 | 评估、修正、MVP 封版 | 1 周 |

MVP 总周期预计：6-9 周。

在 API 后端模式下，M1 必须完成 `LLM Gateway`、DeepSeek-V4 配置、调用日志、失败降级和流式输出，否则后续人格初始化、记忆和检索模块无法稳定接入生成链路。

## 16. 最终建议

第一版的正确目标不是“训练出一个完美 AI 女友”，而是先做出一个可控、可记忆、可检索、可评估、可持续变熟的智能体。

优先级排序：

1. 独立聊天入口。
2. DeepSeek-V4 接入和模型调用治理。
3. 背景设定结构化学习。
4. 虚拟好友身份、人格初始化和系统提示词初版。
5. 单窗口长期多轮聊天体验。
6. 分层记忆：工作记忆、会话摘要、长期语义记忆、人格记忆、共同经历记忆。
7. 对话策略和风格控制。
8. 成长机制与人格稳定性验证。
9. 后续再考虑历史聊天检索、QQ 数据导入、微调和 QQ 实时接入。

最重要的工程原则：

```text
模型负责自然表达。
记忆系统负责想起相关内容。
检索系统负责查证历史。
规则系统负责守住边界。
评估系统负责证明它真的变好。
```
