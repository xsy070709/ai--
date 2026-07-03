# 🔍 合并审计报告

**源分支**: `codex/memory-post-merge-iteration`
**目标分支**: `master`
**审计日期**: 2026-07-03
**评估方法**: 人工全面审查 + 当前工作树验证 + 回归门禁复核
**变更规模**: 7 commits | 7 files | +426 / -49 lines

> **本轮更新**：审查 `master..HEAD` 的 7 个提交（`27d674b..74c20a1`），
> 针对上一轮审计后继续暴露的反馈闭环、异步写入、SQLite 投影/搜索和参数覆盖问题进行迭代验证。
> **结论：建议合并。当前分支工作区干净，测试门禁通过，原审计报告保持原始版本。**

---

## 一、总体裁决

### 🟢 后续迭代分支评估：建议合并

本分支不再扩展记忆系统的大框架，而是对上一分支合并后的可靠性缺口做定向收敛。核心收益集中在四类：

1. 反馈信号从“能记录”推进到“能形成可用参数证据”。
2. 聊天异步等待后的写入位置固定到 prompt snapshot session，避免 active session 切换导致回复写错会话。
3. SQLite projection 从全量重建推进到增量同步，并对搜索查询做转义和候选窗口限制。
4. 参数覆盖文件从静默失败/导入崩溃推进到可诊断、可回退。

### 验证数据

| 检查项 | 结果 | 详情 |
|--------|------|------|
| 当前分支 | ✅ `codex/memory-post-merge-iteration` | HEAD `74c20a1` |
| 工作区状态 | ✅ 干净 | 仅 `.pytest_cache/` 权限扫描警告 |
| 单元测试 | ✅ `133 passed` | `python -m pytest -q` |
| 核心测试 | ✅ `133 passed` | `python -m pytest tests\test_core.py -q` |
| 编译检查 | ✅ 通过 | `python -m compileall -q app scripts tests` |
| 校准案例 | ✅ `24/24` | `python scripts\evaluate_memory_calibration.py`，score 1.0 |
| 反馈分析 | ✅ 通过 | `python scripts\analyze_memory_feedback.py`，无建议 |
| 空白检查 | ✅ 通过 | `git diff --check` 仅 CRLF 提示 |
| 密钥扫描 | ✅ 无真实密钥 | 仅既有配置字段、测试占位值、token 计数字段 |
| 原审计报告 | ✅ 未再修改 | `docs/audit_codex-audit-memory-idea_2026-07-03.md` 与 `4ed5efa` 一致 |

---

## 二、变更概览

### 四个阶段

| 阶段 | 提交 | 主题 |
|------|------|------|
| 一 | `27d674b`, `a1f7bee` | 反馈闭环补强：confirmation 信号、tone-only 正反馈、去重保留证据 |
| 二 | `2bf7909` | 异步写入一致性：固定 snapshot session，记录 revision/session 漂移 |
| 三 | `9775d58`, `74c20a1` | SQLite 存储优化：projection 增量同步，搜索转义和候选窗口限制 |
| 四 | `ba6d145` | 参数覆盖健壮性：未知键报错，环境文件失败回退并暴露 warning |

### 提交清单

| 提交 | 类型 | 主题 | 说明 |
|------|------|------|------|
| `27d674b` | fix | Centralize confirmation feedback | confirmation accept/reject 复用统一反馈推断路径 |
| `2bf7909` | fix | Pin chat writes across awaits | 异步等待后写入 snapshot session，记录 state revision 变化 |
| `9775d58` | perf | Increment projection sync | SQLite projection 按实体 id 增量同步，避免全量重建 |
| `d2f81ab` | docs | Restore original audit report | 按用户要求恢复上一份审计报告为原始版本 |
| `ba6d145` | fix | Harden parameter overrides | 参数文件未知键报错，环境加载失败回退 |
| `a1f7bee` | fix | Preserve feedback evidence | tone-only 正反馈，反馈信号按 type/reason/parameters 去重 |
| `74c20a1` | fix | Harden SQLite memory search | LIKE/FTS 查询加固，语义候选窗口限制 |

### 影响文件

| 文件 | 变更重点 |
|------|----------|
| `app/chat_service.py` | 写入 session 固定、revision/session 变化记录、参数 warning 状态暴露 |
| `app/memory/__init__.py` | 导出参数加载 warning |
| `app/memory/audit_status.md` | 记录本轮已实现的 storage/feedback 状态 |
| `app/memory/feedback.py` | confirmation 与 tone-only 信号、证据去重策略 |
| `app/memory/params.py` | 参数文件读取错误、未知键、环境回退逻辑 |
| `app/storage.py` | SQLite projection 增量同步、搜索转义、语义候选 LIMIT |
| `tests/test_core.py` | 新增 20+ 条覆盖异步写入、projection、参数、feedback、SQLite 搜索的回归测试 |

---

## 三、问题清单

### HIGH / 关键可靠性问题

| # | 问题 | 状态 | 证据 |
|---|------|------|------|
| H1 | confirmation accept/reject 没有进入统一反馈证据 | ✅ 已修复 | `27d674b`，新增确认结果测试 |
| H2 | 异步 await 后 active session 变化可能导致回复写错会话 | ✅ 已修复 | `2bf7909`，新增 active-session race 测试 |
| H3 | SQLite projection 每次 mutation 全量删除重建 | ✅ 已修复 | `9775d58`，embedding/FTS 行保留测试 |
| H4 | 参数覆盖文件未知键静默跳过 | ✅ 已修复 | `ba6d145`，未知 dotted key 报错测试 |
| H5 | `MEMORY_PARAMS_FILE` 无效导致模块导入崩溃 | ✅ 已修复 | `ba6d145`，环境回退 warning 测试 |
| H6 | 同类 feedback 去重丢失不同证据 | ✅ 已修复 | `a1f7bee`，type/reason/parameters 去重测试 |
| H7 | `tone_only` 只有负向审计，没有正向反馈 | ✅ 已修复 | `a1f7bee`，`tone_guidance_engaged` 测试 |
| H8 | SQLite LIKE/FTS 查询未加固，特殊字符可能误匹配或触发语法风险 | ✅ 已修复 | `74c20a1`，`%` 字面查询和 operator-only 查询测试 |

### MEDIUM / 剩余设计风险

| # | 问题 | 状态 | 说明 |
|---|------|------|------|
| M1 | 真实向量检索未接入 | ⚠️ 保留 | 当前仍是 deterministic local semantic vector，不是 `sqlite-vec` |
| M2 | 语义搜索候选窗口是折中方案 | ⚠️ 保留 | 已从全量扫描改为 `max(limit * 16, 256)`，但不是向量索引 |
| M3 | prompt 已发出后仍可能基于旧 snapshot | ⚠️ 保留 | 已避免写错 session 并记录 revision，尚未做乐观重试 |
| M4 | `.pytest_cache` 权限警告 | ⚠️ 环境问题 | Git 扫描提示，不影响提交内容 |

---

## 四、模块风险评级

| 模块 | 合并前风险 | 本分支后风险 | 变化原因 |
|------|------------|--------------|----------|
| `chat_service.py` | 🟡 中 | 🟢 低 | 异步写入固定到 snapshot session，参数 warning 可观测 |
| `storage.py` | 🟡 中 | 🟢 低 | projection 增量同步；LIKE/FTS 转义；语义候选有上限 |
| `feedback.py` | 🟡 中 | 🟢 低 | confirmation/tone-only 信号补齐，去重不再丢证据 |
| `params.py` | 🟡 中 | 🟢 低 | 未知覆盖键报错，环境参数文件失败可回退 |
| `tests/test_core.py` | 🟢 低 | 🟢 低 | 覆盖面继续扩大，当前 133 passed |
| `audit_status.md` | 🟢 低 | 🟢 低 | 仅状态说明更新 |

---

## 五、测试覆盖评估

### 覆盖充分 ✅

- confirmation accept/reject 反馈信号
- active session 切换期间的聊天写入固定
- SQLite projection 增量同步、删除清理、embedding 行保留
- 参数文件覆盖、未知键、环境加载失败回退
- tone-only 正反馈和反馈信号去重
- SQLite LIKE wildcard 字面匹配
- FTS operator-only 查询安全降级
- 既有 24 条校准案例全部保持通过

### 仍需后续覆盖 ⚠️

- 大数据量下真实向量索引或 `sqlite-vec` 的性能/召回对比
- 多用户/多 worker 并发下的乐观重试策略
- 更多真实聊天失败样本驱动的校准案例扩容

---

## 六、合并前检查清单

### 已完成

```
✅ 当前分支：codex/memory-post-merge-iteration
✅ HEAD：74c20a1
✅ 工作区干净
✅ 原审计报告保持原始版本
✅ pytest 全量通过：133 passed
✅ compileall 通过
✅ memory calibration：24/24，score 1.0
✅ feedback analysis：通过，无建议
✅ diff 范围只涉及 7 个预期文件
✅ 无真实密钥进入 diff
```

### 合并建议

```
✅ 建议合并到 master
⚠️ 合并后建议保留本报告，作为后续真实向量检索和并发策略迭代的基线
⚠️ 不建议继续修改上一份审计报告；它已按要求固定为原始版本
```

---

## 七、最终评分

| 维度 | 评分 | 评语 |
|------|------|------|
| 功能完整性 | ⭐⭐⭐⭐ | 没有新增大模块，但补齐了多个可靠性缺口 |
| 代码架构 | ⭐⭐⭐⭐ | 维持现有架构边界，未引入不必要抽象 |
| 代码质量 | ⭐⭐⭐⭐⭐ | 变更聚焦，错误路径更明确，状态更可观测 |
| 测试覆盖 | ⭐⭐⭐⭐⭐ | 回归覆盖与风险点匹配，133 passed |
| 向后兼容 | ⭐⭐⭐⭐⭐ | 参数和 storage 行为保持兼容，失败路径更安全 |
| 可观测性 | ⭐⭐⭐⭐ | revision/session、参数 warning、feedback 证据更完整 |
| 长期可扩展性 | ⭐⭐⭐⭐ | projection/search 已收敛，真实向量索引仍待单独设计 |

**综合评分: 4.7 / 5.0**

**建议合并至 `master`。** 本分支主要完成上一分支后的可靠性收敛，未发现阻塞合并的问题。剩余风险均为中长期设计项，不影响当前 MVP 合并。
