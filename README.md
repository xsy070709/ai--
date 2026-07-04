# AI 虚拟好友聊天 MVP

第一阶段实现内容：

- 独立聊天入口，模拟 QQ 单窗口长期多轮聊天。
- DeepSeek-V4 网关，支持配置化 API 调用和无密钥降级回复。
- 背景设定导入与人格初始化。
- 分层记忆 MVP：动态工作记忆、话题摘要、长期记忆、人格记忆、共同经历、待跟进、表露审计。
- 可切换持久化：默认 JSON，支持 SQLite + FTS5 投影表，便于长期使用和检索。
- 短消息逻辑话轮：60 秒内连续短用户片段会合并用于记忆抽取、意图判断和反馈分析，聊天记录仍保留原始逐条消息。

## 快速运行

零依赖开发服务器：

```powershell
python dev_server.py
```

打开：

```text
http://127.0.0.1:8000
```

FastAPI 运行方式：

```powershell
python -m pip install -e .
python -m uvicorn app.main:app --reload
```

## DeepSeek-V4 配置

复制 `.env.example` 为 `.env`，填写：

```text
DEEPSEEK_API_KEY=你的 key
DEEPSEEK_CHAT_MODEL=deepseek-v4-flash
DEEPSEEK_STRUCTURED_MODEL=deepseek-v4-flash
DEEPSEEK_THINKING=disabled
```

没有 API key 时，系统会使用本地降级回复，便于验证聊天、记忆和人格初始化流程。

`deepseek-v4-flash` 是当前默认低成本模型；如需更强推理可改为 `deepseek-v4-pro`，并按需把 `DEEPSEEK_THINKING=enabled`。DeepSeek 服务端上下文缓存默认开启，返回的 `usage` 会记录 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens` 和本项目补充的 `prompt_cache_hit_ratio`。

结构化记忆抽取和意图分类可单独切换：

```text
MEMORY_EXTRACTOR=rule
MEMORY_INTENT_CLASSIFIER=rule
```

有可用 API key 时可改为：

```text
MEMORY_EXTRACTOR=llm
MEMORY_INTENT_CLASSIFIER=llm
```

本地 LM Studio 实验接入：

```text
STRUCTURED_PROVIDER=lmstudio
LOCAL_LM_BASE_URL=http://127.0.0.1:7985/v1
LOCAL_STRUCTURED_MODEL=google/gemma-4-12b-qat
MEMORY_EXTRACTOR=lmstudio
MEMORY_INTENT_CLASSIFIER=lmstudio
```

这只会把结构化记忆抽取和意图分类切到 LM Studio 的 OpenAI-compatible API；主聊天回复仍按 DeepSeek 配置运行。LM Studio 不可用、返回 degraded 或 JSON 解析失败时，记忆模块会回退到规则抽取/规则意图。注意：直接启用 `MEMORY_EXTRACTOR=lmstudio` 或 `MEMORY_INTENT_CLASSIFIER=lmstudio` 会把本地模型调用串入当前聊天请求，适合实验，不适合作为“不影响前台响应”的默认配置。

不影响前台聊天的后台试点评估：

```powershell
python scripts\run_lmstudio_backend_pilot.py --output docs\lmstudio_backend_pilot_results_2026-07-04.json
```

参数档和覆盖文件：

```text
MEMORY_PARAM_PROFILE=balanced
MEMORY_PARAMS_FILE=data/my_memory_params.json
```

覆盖文件使用 JSON，例如：

```json
{"recall":{"open_item_bonus":0.9},"quality":{"auto_accept_min_confidence":0.7}}
```

## 记忆存储

默认仍使用 JSON，便于检查和调试：

```text
STORAGE_BACKEND=json
```

切换到 SQLite：

```text
STORAGE_BACKEND=sqlite
```

从现有 `data/store.json` 迁移到 `data/store.sqlite3`：

```powershell
python scripts/migrate_json_to_sqlite.py
```

迁移脚本会保留原 JSON 文件，不会删除备份。

SQLite 后端会维护 `memory_fts` 和 `memory_embeddings` 投影表。当前 embedding 是零依赖的本地语义 fallback，用于同义表达召回；后续可以替换为真实 embedding 或 sqlite-vec。

## 记忆反馈分析

每轮聊天会在 `generation_logs` 中记录记忆使用、表露审计和隐式反馈信号。离线查看参数调优建议：

```powershell
python scripts/analyze_memory_feedback.py
```

输出包含信号计数、按参数聚合的证据和建议调整方向，例如降低待跟进加分、提高自动接受阈值或提高记忆表露阈值。

运行记忆校准样例集：

```powershell
python scripts/evaluate_memory_calibration.py
```

校准集位于 `data/memory_calibration_cases.json`，可继续补充“用户消息 -> 期望记忆/召回/表露模式”的标注案例。

人工测试调参流程见 `docs/memory_manual_tuning.md`。人工评分样例为 `data/manual_memory_eval.example.jsonl`，本地真实评分建议写到 `data/manual_memory_eval.local.jsonl`，再运行：

```powershell
python scripts/summarize_manual_memory_eval.py data/manual_memory_eval.local.jsonl
```

运行一次真实 DeepSeek flash 用户测试：

```powershell
python scripts/run_deepseek_flash_user_test.py
```

该脚本使用临时数据目录，不会写入当前 `data/store.json`。
