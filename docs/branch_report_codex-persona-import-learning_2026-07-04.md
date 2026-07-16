# 分支报告：人格导入学习、多实体隔离、导入向导与事件系统

**源分支**: `codex/persona-import-learning`
**目标分支**: `master`
**报告日期**: 2026-07-04（更新于 2026-07-05）
**评估方法**: 基于当前工作区 diff、功能走查、自动化测试、记忆校准脚本、前端语法检查、与未合并分支文件交集检查
**变更规模**: 第一阶段 11 files | 第二阶段新增 7 files | 第三阶段（导入向导）9 files | 第四阶段（事件系统）8 files | 约 +3,500 / −80 行

---

## 一、总体裁决

### 建议合并，已具备完整的好友生命周期管理闭环

本分支具备明确合并价值：它把原本单一 `active_persona_id` 的背景导入，扩展为可管理的多个人格实体，并让聊天记录/背景故事导入后能够形成可扮演的人格画像、口癖、习惯和互动规则。聊天消息、长期记忆、待确认记忆、调试视图和 SQLite/JSON 存储投影都按当前人格实体隔离。

第二阶段补齐了用户可直接操作的好友管理能力：删除好友、重命名好友、清空当前好友聊天记录。

**第三阶段**引入了人格导入向导 —— 一个独立模态窗口，支持多轮学习对话和用户修改确认后再导入。解决了背景故事中多人物的主体识别、叙事推断、隐式描述等关键问题。

**第四阶段**引入了追加事件系统 —— 用户可以为角色追加线下发生的事件，事件可以暂时或长期改变角色的性格特质，成为聊天话题或敏感禁忌，并具有完整的生命周期管理。

### 验证数据

| 检查项 | 结果 |
|--------|------|
| 全量测试 | `179 passed` |
| 新增人格实体测试 | `7 passed`（含导入会话测试） |
| 新增导入向导测试 | `8 passed` |
| 新增事件系统测试 | `31 passed` |
| 记忆校准 | `24/24`, score `1.0` |
| Python 编译检查 | `python -m compileall -q app scripts tests` 通过 |
| dev server 编译 | `python -m py_compile dev_server.py` 通过 |
| 前端语法检查 | `node --check app\static\app.js` 通过 |
| 与 `codex/local-model-lmstudio-experiment` 文件交集 | `NO_OVERLAP` |

---

## 二、做了什么

### 1. 人格学习能力（第一阶段）

新增 `app/persona.py` 中的人格学习流程：

- `persona_learning_prompt()`：构造结构化人格学习提示，要求模型输出 JSON。
- `parse_persona_learning_json()`：解析模型输出。
- `learn_persona_profile()`：合并 LLM 学习结果与本地规则兜底。
- `persona_from_learned_profile()`：把学习结果转成可参与系统 prompt 的 persona version。

导入材料支持三类来源：

| 类型 | 用途 |
|------|------|
| `background_story` | 背景故事、设定文档 |
| `chat_log` | 历史聊天记录 |
| `mixed` | 背景 + 聊天混合材料 |

### 2. 多人格实体隔离（第一阶段）

存储状态新增 `persona_entities` 和 `active_persona_entity_id`。每个人格实体拥有独立的活跃会话、人格版本、长期记忆集合、待确认记忆范围和 generation log 关联字段。旧数据自动兼容归入默认实体。

### 3. 好友管理操作（第二阶段）

新增重命名好友、清空当前好友聊天记录、删除好友及其关联数据。删除是实体级清理，覆盖 sessions、persona_versions、memories、memory_confirmations、generation_logs。

### 4. 人格导入向导（第三阶段）★ 新增

针对用户反馈"背景故事中可能有多个人，不一定是直接描述，也可能是一段经历，需要根据人格名称确定主体，从经历中推测可能的性格和阅历"等问题，引入了完整的多步骤导入向导：

**后端改进**（`app/persona.py`）：
- `persona_learning_prompt_v2()`：增强版 LLM 提示词，支持多人物主体识别、叙事推断（从"经历了战争"推断"坚韧、成熟"）、隐式描述处理、不确定项标记和澄清问题生成
- `persona_refine_prompt()`：多轮对话精炼提示词，支持增量更新
- `merge_profile_diff()`：将 LLM 的部分更新合并到当前设定档
- `_extract_subject_name()`：更智能的本地名称提取 —— 显式命名模式 → 句子主语位置 → 高频专有名词
- `_infer_traits_from_narrative()`：从经历关键词推断性格（如"独自抚养"→ 独立、坚强）
- `build_persona_learning_memories()`：从设定档生成记忆记录的共享函数

**导入会话管理**（新文件 `app/persona_import.py`）：
- `ImportSession`：内存中的临时导入会话，保存源文本、对话历史、当前设定档
- `ImportSessionManager`：管理会话的完整生命周期 —— 初始分析、多轮对话精炼、手动编辑、确认导入
- 名称优先级策略：实体名称 > 源文本中出现的 LLM 名称 > 合并结果
- 线程安全的会话存储

**导入向导 API**（`app/main.py`）：
| API | 作用 |
|-----|------|
| `POST /api/persona/import-session` | 粘贴文本，开始分析 |
| `POST /api/persona/import-session/{id}/chat` | 发送精炼消息 |
| `GET /api/persona/import-session/{id}` | 获取会话状态 |
| `PATCH /api/persona/import-session/{id}/profile` | 手动编辑设定档 |
| `POST /api/persona/import-session/{id}/confirm` | 确认并持久化 |
| `DELETE /api/persona/import-session/{id}` | 丢弃会话 |

**导入向导前端**（`index.html` + `app.js` + `styles.css`）：
- 步骤 1：粘贴文本 + 选择材料类型 → "开始分析"
- 步骤 2：分屏布局 —— 左侧精炼对话，右侧实时更新的设定档卡片（名称、关系、特质标签、风格等）
- 步骤 3：可编辑表单 —— 文本字段 + 标签编辑器（添加/删除特质、口癖、习惯等）
- 模态窗口设计，支持键盘快捷键

### 5. 追加事件系统（第四阶段）★ 新增

针对用户需求"人物关系除了聊天记录外，还包括线下发生的事情，用户可以追加事件，事件会改变人物的性格和对待他人的方式，可能是暂时的，也可能是长期的，可能成为话题，也可能变成敏感的禁忌"，引入了完整的事件系统：

**事件模型**（新文件 `app/persona_events.py`）：
- 事件可标记为正面/负面/中性/创伤四种类型
- 影响范围分为暂时/长期/逐渐消退
- 特质效果支持新增、减弱、加强、移除四种方向
- 可选择成为话题（角色自然提及）或禁忌（角色回避）

**三种影响机制**：
- **特质调节**（`apply_event_trait_effects()`）：在构建提示词时动态计算活跃特质，不修改存储的角色数据。消退中的事件效果减半
- **话题效果**（`build_event_context()`）：在系统提示词中注入"近期经历"段落，同时创建 `shared_experience` 记忆供回忆系统使用
- **禁忌效果**（`build_event_taboo_context()` + `check_taboo_triggers()`）：在系统提示词中注入"敏感话题"段落，每次聊天检测用户消息中的禁忌关键词

**事件生命周期**：
```
active → (时间流逝) → fading → (过期) → resolved
active → (在聊天中讨论) → acknowledged → (7天) → absorbed
active → (用户手动标记) → resolved
```

每次聊天轮次自动运行维护（`maintain_events()`），处理状态转换和自动确认。

**事件 API**（`app/main.py`）：
| API | 作用 |
|-----|------|
| `GET /api/persona-events` | 列出当前实体的事件 |
| `POST /api/persona-events` | 创建事件 + 关联记忆 |
| `PATCH /api/persona-events/{id}` | 更新事件字段 |
| `DELETE /api/persona-events/{id}` | 删除事件 |
| `POST /api/persona-events/{id}/resolve` | 标记已解决 |
| `POST /api/persona-events/{id}/acknowledge` | 标记已讨论 |

**事件前端**（`index.html` + `app.js` + `styles.css`）：
- 侧边栏新增"近期事件"面板，展示活跃事件列表，含类型徽章、状态指示器、特质影响、操作按钮
- "追加事件"模态框，可配置内容、类型、影响范围、持续时间、特质效果编辑器、话题/禁忌开关及关键词
- 事件随聊天自动刷新状态

### 6. 聊天流程实体化（第一阶段）

`ChatService.chat()` 改为以快照时的当前实体为边界：召回记忆、记忆修正、新增记忆、反思记忆和待确认项都自动限定在当前实体范围。

### 7. API 和前端管理

除上述导入向导和事件 API 外，已有的管理 API：

| API | 作用 |
|-----|------|
| `GET /api/persona-entities` | 列出人格实体 |
| `POST /api/persona-entities` | 新建人格实体 |
| `POST /api/persona-entities/{entity_id}/activate` | 切换当前人格实体 |
| `POST /api/persona/import-materials` | 导入背景故事/聊天记录（一键式，保留兼容） |
| `PATCH /api/persona-entities/{entity_id}` | 重命名好友 |
| `DELETE /api/persona-entities/{entity_id}` | 删除好友及其关联数据 |
| `POST /api/messages/clear` | 清空当前好友聊天记录 |

### 8. 测试覆盖

新增/更新的测试文件：

**`tests/test_persona_entities.py`（15 tests）**：
| 测试 | 覆盖 |
|------|------|
| `test_import_persona_materials_uses_structured_learning` | 结构化 LLM 学习 |
| `test_persona_entities_isolate_messages_and_memories` | 实体隔离 |
| `test_persona_entity_can_be_renamed` | 重命名好友 |
| `test_clear_current_chat_removes_messages_summaries_and_chat_logs_only` | 清空聊天 |
| `test_delete_persona_entity_removes_scoped_data_and_selects_replacement` | 删除好友 |
| `test_import_session_basic_extraction` | 导入向导基础提取 |
| `test_import_session_refinement_dialogue` | 多轮对话精炼 |
| `test_import_session_manual_edit` | 手动编辑设定档 |
| `test_import_session_confirm_creates_persona` | 确认导入端到端 |
| `test_import_session_not_found` | 404 处理 |
| `test_import_session_delete` | 会话清理 |
| `test_import_session_preserves_entity_name_when_no_name_in_text` | 名称优先级 |
| `test_import_session_handles_llm_failure_gracefully` | LLM 故障兜底 |

**`tests/test_persona_events.py`（31 tests）**：
- 事件创建（基础、禁忌、特质规范化）
- 特质调节（添加、减弱、加强、移除、消退、已解决忽略）
- 上下文构建器（话题、禁忌、特质变更描述）
- 禁忌检测（触发、不触发）
- 生命周期（过期转换、消退→已解决、永久吸收）
- 记忆桥接（活跃、已解决带备注）
- ChatService 集成（CRUD、记忆创建、更新、删除、解决、确认、实体隔离）
- 聊天流程集成（事件特质效果在聊天中应用）

---

## 三、实际效果

### 用户可见效果

**导入向导**：
用户点击"导入并学习"后，进入独立模态窗口。粘贴背景故事后，系统分析并展示初始设定档。用户可以通过多轮对话精炼设定（"她其实更内向"、"名字改成林夏"），实时查看右侧面板的设定档更新。确认前可在编辑页面直接修改名称、关系、特质、口癖、习惯等所有字段。

**事件系统**：
用户可以在侧边栏"近期事件"面板看到当前角色的活跃事件。点击"+ 追加事件"打开配置窗口，设置事件内容、类型、影响范围、对性格的影响（新增/减弱/加强/移除哪些特质）、是否成为话题或禁忌。事件自动影响角色的聊天表现 —— 角色会因事件改变性格侧重点、自然提及相关话题、回避禁忌话题。事件随时间自动消退或可手动标记解决。

**好友管理**：
用户可以创建多个不同人格实体（如"林夏""周白"），每个实体独立导入背景设定、管理事件、维护聊天记录和长期记忆。切换实体后聊天窗口无缝切换到对应上下文。支持重命名、清空聊天、删除好友。

### 系统效果

**导入向导**：
- 人格学习结果同时进入 `persona_versions`（系统 prompt）和 `memories`（长期回忆系统）
- 导入过程在内存中进行直到确认，不会污染存储
- LLM 不可用时回退到增强的本地规则学习器（含叙事推断和主体识别）

**事件系统**：
- 事件作为第 5 条系统消息注入聊天 prompt
- 动态特质调节在每次聊天轮次计算，不修改持久化的角色数据
- 事件维护自动运行：过期转换、消退、吸收
- 事件被话题触发词讨论后自动确认并转化为记忆

---

## 四、局限和风险

### 1. 本地规则学习器仍然偏浅

无模型时的规则学习能抓到显式字段、关键词、口癖标签和叙事推断模式，但不能真正理解复杂聊天关系。适合兜底，不适合替代 LLM 学习。

### 2. 导入向导是内存会话

导入会话在服务器重启后丢失。对于长时间精炼的场景，用户可能需要重新开始。适合 MVP 阶段，后续可考虑持久化暂存。

### 3. 事件系统的特质调节是文本级

动态特质通过改变 `stable_traits` 列表的顺序和内容来影响 prompt，而不是通过嵌入或向量级的特质表示。效果依赖于 LLM 对特质顺序的敏感度。

### 4. 隐私和原文处理仍是 MVP 级

系统 prompt 明确要求不要复述原始聊天记录，但存储层仍保存导入材料摘要和证据片段。

### 5. 还没有实体归档、复制和事件模板

当前实现支持 CRUD 全流程，但缺少实体归档、复制、事件模板和批量导入等高级管理功能。

---

## 五、合并价值判断

### 具有合并价值

1. **产品方向正确**：导入向导和事件系统进一步完善了"虚拟好友"产品的人格管理闭环 —— 从创建 → 导入学习 → 多轮精炼 → 事件驱动演化。
2. **技术边界明确**：没有强行修改 LLM backend、memory extractor、intent classifier 等当前未合并分支正在动的文件。
3. **验证充分**：179 项测试全量通过，包括导入会话、事件系统、实体隔离和好友管理的完整覆盖。

### 建议合并条件

- 接受这是 MVP 级人格管理工作台，不是最终生产级产品。
- 合并前人工快速验收：导入向导三步流程、事件追加和自动影响、好友管理操作。
- 后续另开分支补实体归档、复制、事件模板和隐私策略。

---

## 六、最终结论

### 建议合并至 `master`

本分支从初始的"导入学习 + 实体隔离"逐步演进为完整的虚拟好友人格管理闭环：**导入向导**解决了复杂背景故事的主体识别和叙事推断问题，支持多轮学习对话和用户审核确认；**事件系统**让角色能够随"线下经历"动态演化性格、产生话题和回避禁忌；**好友管理**提供了多实体隔离的 CRUD 全流程。

综合评分：**4.7 / 5**

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | 4.8 | 导入向导、事件系统、好友管理闭环完成 |
| 架构一致性 | 4.3 | 延续现有 snapshot + projection 架构，事件上下文无缝注入 prompt |
| 测试覆盖 | 4.7 | 179 tests，覆盖导入会话、事件生命周期、实体隔离 |
| 合并风险 | 4.5 | 与当前未合并分支无文件交集 |
| 产品价值 | 4.8 | 直接提升虚拟好友人格管理的深度和真实感 |

最终建议：**合并，有后续迭代空间。**
