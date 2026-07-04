# 分支报告：人格导入学习与多实体隔离

**源分支**: `codex/persona-import-learning`
**目标分支**: `master`
**报告日期**: 2026-07-04
**评估方法**: 基于当前工作区 diff、功能走查、自动化测试、记忆校准脚本、与未合并分支文件交集检查
**变更规模**: 10 files（9 个既有文件 + 1 个新增测试文件）| 既有文件约 +858 / -51 行 | 新增测试文件 97 行

---

## 一、总体裁决

### 建议合并，但按 MVP 能力看待

本分支具备明确合并价值：它把原本单一 `active_persona_id` 的背景导入，扩展为可管理的多个人格实体，并让聊天记录/背景故事导入后能够形成可扮演的人格画像、口癖、习惯和互动规则。更重要的是，聊天消息、长期记忆、待确认记忆、调试视图和 SQLite/JSON 存储投影都按当前人格实体隔离，避免不同人格之间串记忆。

该能力符合当前项目把“记忆/人格”作为核心产品能力的方向，不是纯 UI 或辅助功能。建议合并到 `master`，但不应把它视为最终生产级人格管理系统；它仍是可验证的 MVP 级实现。

### 验证数据

| 检查项 | 结果 |
|--------|------|
| 全量测试 | `135 passed` |
| 新增人格实体测试 | `2 passed` |
| 记忆校准 | `24/24`, score `1.0` |
| Python 编译检查 | `python -m compileall -q app scripts tests` 通过 |
| dev server 编译 | `python -m py_compile dev_server.py` 通过 |
| 与 `codex/local-model-lmstudio-experiment` 文件交集 | `NO_OVERLAP` |

---

## 二、做了什么

### 1. 人格学习能力

新增 `app/persona.py` 中的人格学习流程：

- `persona_learning_prompt()`：构造结构化人格学习提示，要求模型输出 JSON。
- `parse_persona_learning_json()`：解析模型输出。
- `learn_persona_profile()`：合并 LLM 学习结果与本地规则兜底。
- `persona_from_learned_profile()`：把学习结果转成可参与系统 prompt 的 persona version。

导入材料支持三类来源：

| 类型 | 用途 |
------|------|
| `background_story` | 背景故事、设定文档 |
| `chat_log` | 历史聊天记录 |
| `mixed` | 背景 + 聊天混合材料 |

模型可用时，走结构化总结；模型不可用、无 key、返回异常或 JSON 无效时，回落到本地规则学习器。这样本地验证和无网络环境不会阻塞功能。

### 2. 多人格实体隔离

存储状态新增 `persona_entities` 和 `active_persona_entity_id`。每个人格实体拥有：

- 独立 active session
- 独立 active persona version
- 独立长期记忆集合
- 独立待确认记忆范围
- 独立 generation log 关联字段

旧数据兼容策略：

- 旧 `default` 会话自动归入 `entity_default`
- 旧 persona、memory、generation log 自动视为默认实体数据
- 空会话 `{}` 保持原状，避免破坏既有测试语义

### 3. 聊天流程实体化

`ChatService.chat()` 改为以快照时的当前实体为边界：

- 召回记忆只取当前实体
- 记忆修正只改当前实体
- 新增记忆自动打上 `persona_entity_id`
- 反思记忆和待确认项自动继承当前实体
- 写入消息时在 message meta 中记录实体 ID
- prompt manifest 记录 `snapshot_persona_entity_id` 和 `write_persona_entity_id`

这避免了切换人格后历史上下文、偏好和待跟进事项互相污染。

### 4. API 和前端管理

新增 API：

| API | 作用 |
|-----|------|
| `GET /api/persona-entities` | 列出人格实体 |
| `POST /api/persona-entities` | 新建人格实体 |
| `POST /api/persona-entities/{entity_id}/activate` | 切换当前人格实体 |
| `POST /api/persona/import-materials` | 导入背景故事、聊天记录或混合材料并学习人格 |

保留兼容 API：

- `POST /api/persona/import` 仍可用，现在内部走 `background_story` 学习路径。

前端新增：

- 人格实体列表
- 新建人格输入框
- 背景故事 / 聊天记录 / 混合材料导入类型选择
- 当前人格的消息、记忆层级和开发窗口联动刷新

### 5. dev server 路由补齐

`dev_server.py` 补齐了新实体 API 和新导入 API。FastAPI 和轻量 dev server 现在都有同一套核心入口。

### 6. 测试覆盖

新增 `tests/test_persona_entities.py`：

| 测试 | 覆盖 |
|------|------|
| `test_import_persona_materials_uses_structured_learning` | 结构化 LLM 学习能生成姓名、性格、口癖、人格记忆 |
| `test_persona_entities_isolate_messages_and_memories` | 切换实体后消息和记忆隔离，切回后原实体数据仍存在 |

---

## 三、实际效果

### 用户可见效果

用户现在可以创建多个不同人格实体，例如“林夏”“周白”。每个实体可以导入自己的背景故事或聊天记录，系统会学习：

- 人格名称和关系定位
- 稳定性格
- 说话风格
- 口癖
- 互动习惯
- 情绪回应方式
- 禁用表达

切换实体后，聊天窗口会进入该实体自己的会话和记忆上下文。导入“林夏”的口癖不会出现在“周白”的记忆里。

### 系统效果

人格学习结果同时进入两层：

- `persona_versions`：用于构造稳定人格 prompt
- `memories`：用于长期记忆系统召回、调试和后续维护

这让人格不只是静态系统 prompt，也能被现有记忆管线观察、整理和审计。

### 合并风险降低效果

与当前未合并的 `codex/local-model-lmstudio-experiment` 分支相比，本分支没有修改这些文件：

- `.env.example`
- `.gitignore`
- `README.md`
- `app/config.py`
- `app/llm_gateway.py`
- `app/local_model.py`
- `app/memory/extractors.py`
- `app/memory/intent.py`
- `scripts/run_lmstudio_backend_pilot.py`
- `tests/test_core.py`

文件级交集检查结果为 `NO_OVERLAP`。因此这两个分支后续合并时，直接文本冲突概率较低。

---

## 四、局限和风险

### 1. 本地规则学习器仍然偏浅

无模型时的规则学习能抓到显式字段、关键词、口癖标签和引用短语，但不能真正理解复杂聊天关系。它适合兜底，不适合替代 LLM 学习。

### 2. 结构化学习依赖模型输出质量

LLM 路径要求返回 JSON。代码已经做了失败兜底，但没有做多轮修复、schema 严格校验或字段置信度评分。复杂聊天记录可能总结过度或遗漏。

### 3. 还没有实体删除、重命名和归档

当前实现支持新建、切换和导入，但没有提供：

- 删除人格实体
- 重命名人格实体
- 归档实体
- 复制实体
- 导入预览后人工确认

这些适合后续独立迭代。

### 4. 隐私和原文处理仍是 MVP 级

系统 prompt 明确要求不要复述原始聊天记录，但存储层仍保存导入材料摘要和证据片段。若后续要处理真实敏感聊天记录，需要增加：

- 导入前脱敏
- 原文保留策略
- 删除导入源
- 敏感字段分级
- 用户可审计的学习结果确认

### 5. SQLite 仍以 JSON snapshot 为权威状态

实体字段已经投影到 SQLite 表，但系统架构仍是 JSON-compatible snapshot 为权威。对于大量人格和海量聊天记录，后续可能需要更彻底的实体级索引和分页 API。

### 6. dev server 后台启动在当前环境不稳定

`dev_server.py` 编译通过，前台 `python dev_server.py` 可启动；但本次桌面沙箱中后台 `Start-Process` 没有稳定保活。这个更像运行环境问题，不影响核心代码测试结果，但如果要做前端手动验收，应以前台方式启动。

---

## 五、合并价值判断

### 具有合并价值

合并价值高，原因有三点：

1. **产品方向正确**：多个人格实体隔离是“虚拟好友”产品从单一 demo 走向可管理系统的核心能力。
2. **技术边界明确**：没有强行修改 LLM backend、memory extractor、intent classifier 等当前未合并分支正在动的文件。
3. **验证充分**：全量测试、校准脚本和编译检查均通过，并新增了实体隔离测试。

### 建议合并条件

建议在以下条件满足后合并：

- 接受这是 MVP 级人格导入和实体管理，不是最终生产级人格工作台。
- 合并前人工快速试一次前端：新建两个实体，分别导入不同口癖，确认切换后消息/记忆隔离。
- 后续另开分支补实体重命名、删除/归档、导入预览确认和隐私策略。

### 不建议阻塞合并的问题

以下问题不应阻塞本分支合并：

- 本地规则学习浅：已有 LLM 学习路径和兜底，不影响主流程可用性。
- 未做实体删除/重命名：属于下一阶段管理能力。
- 后台 dev server 启动不稳定：核心测试通过，前台启动可用。

---

## 六、最终结论

### 建议合并至 `master`

本分支完成了“导入聊天记录和背景故事，由 AI 学习总结人格特征、口癖、习惯等设定，并支持多开不同人格实体隔离管理”的核心目标。功能具有明确产品价值，代码改动虽然覆盖服务、存储、API 和前端，但测试结果稳定，且与当前未合并 LM Studio 分支没有文件级冲突。

综合评分：**4.3 / 5**

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | 4.3 | 核心导入学习和隔离完成，缺实体生命周期管理 |
| 架构一致性 | 4.2 | 延续现有 snapshot + projection 架构，兼容旧数据 |
| 测试覆盖 | 4.4 | 覆盖关键学习和隔离路径，全量回归通过 |
| 合并风险 | 4.5 | 与当前未合并分支无文件交集 |
| 产品价值 | 4.6 | 直接提升虚拟好友人格管理能力 |

最终建议：**合并，有后续迭代空间。**
