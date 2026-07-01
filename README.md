# AI 虚拟好友聊天 MVP

第一阶段实现内容：

- 独立聊天入口，模拟 QQ 单窗口长期多轮聊天。
- DeepSeek-V4 网关，支持配置化 API 调用和无密钥降级回复。
- 背景设定导入与人格初始化。
- 分层记忆 MVP：工作记忆、会话摘要、长期记忆、人格记忆、共同经历。
- 本地 JSON 持久化，便于快速开发和调试。

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
DEEPSEEK_CHAT_MODEL=deepseek-v4
```

没有 API key 时，系统会使用本地降级回复，便于验证聊天、记忆和人格初始化流程。
