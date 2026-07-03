from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_service import ChatService
from app.config import Settings, load_settings
from app.llm_gateway import DeepSeekGateway
from app.storage import create_store


async def main() -> None:
    base = load_settings()
    if not base.deepseek_api_key:
        raise SystemExit("DEEPSEEK_API_KEY is missing; set it in .env before running the live flash test.")

    with tempfile.TemporaryDirectory(prefix="deepseek-flash-user-test-") as tmp:
        settings = Settings(
            data_dir=Path(tmp),
            deepseek_api_base_url=base.deepseek_api_base_url,
            deepseek_api_key=base.deepseek_api_key,
            deepseek_chat_model=os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash"),
            deepseek_structured_model=os.getenv("DEEPSEEK_STRUCTURED_MODEL", "deepseek-v4-flash"),
            deepseek_thinking=os.getenv("DEEPSEEK_THINKING", "disabled"),
            deepseek_chat_max_tokens=base.deepseek_chat_max_tokens,
            deepseek_structured_max_tokens=base.deepseek_structured_max_tokens,
            timeout_seconds=base.timeout_seconds,
            max_retries=base.max_retries,
            force_local_llm=False,
            memory_extractor="llm",
            memory_intent_classifier="llm",
            storage_backend="json",
        )
        service = ChatService(create_store(settings), DeepSeekGateway(settings))
        service.import_background("名字：林夏。关系定位：长期陪伴型虚拟好友。性格：温柔、理性、少说教。")

        turns = [
            "明天下午我要交材料，现在有点焦虑。",
            "我刚刚又想到，别上来就讲大道理，先陪我缓一下。",
            "材料搞定了，收工。你还记得我刚才最怕什么吗？",
        ]
        results = []
        for text in turns:
            result = await service.chat(text)
            results.append(
                {
                    "user": text,
                    "reply": result["reply"],
                    "model": result["llm"]["model"],
                    "elapsed_ms": result["llm"]["elapsed_ms"],
                    "degraded": result["degraded"],
                    "error": result["llm"].get("error"),
                    "usage": result["llm"].get("usage"),
                    "intent": result["intent"].get("classifier"),
                    "followup_mode": result["followup_plan"]["mode"],
                    "disclosure_mode": result["disclosure_plan"]["mode"],
                    "audit": result["memory_audit"]["status"],
                }
            )

        state = service.store.snapshot()
        usage = [log.get("usage") for log in state.get("generation_logs", []) if log.get("provider") == "deepseek"]
        print(
            json.dumps(
                {
                    "model": settings.deepseek_chat_model,
                    "structured_model": settings.deepseek_structured_model,
                    "turns": results,
                    "deepseek_usage": usage,
                    "memories": [
                        {"type": item.get("type"), "content": item.get("content"), "open": item.get("open"), "status": item.get("status")}
                        for item in state.get("memories", [])
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if any(item["degraded"] for item in results):
            raise SystemExit("Live DeepSeek flash test degraded; see error fields above.")


if __name__ == "__main__":
    asyncio.run(main())
