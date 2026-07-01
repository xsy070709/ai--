from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    degraded: bool
    elapsed_ms: int
    error: str | None = None
    usage: dict[str, Any] | None = None


class DeepSeekGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def chat(self, messages: list[dict[str, str]], purpose: str = "chat") -> LLMResult:
        started = time.perf_counter()
        if not self.settings.has_deepseek_key:
            return self._fallback(messages, started, "missing DEEPSEEK_API_KEY")

        url = f"{self.settings.deepseek_api_base_url}/chat/completions"
        payload = {
            "model": self.settings.deepseek_chat_model,
            "messages": messages,
            "temperature": 0.8,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.settings.deepseek_api_key}"}

        last_error: str | None = None
        for _ in range(max(1, self.settings.max_retries + 1)):
            try:
                async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"].strip()
                return LLMResult(
                    text=text,
                    provider="deepseek",
                    model=self.settings.deepseek_chat_model,
                    degraded=False,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    usage=data.get("usage"),
                )
            except Exception as exc:  # noqa: BLE001 - preserve provider error for log
                last_error = str(exc)

        return self._fallback(messages, started, last_error or "provider call failed")

    async def structured(self, messages: list[dict[str, str]], purpose: str = "structured") -> LLMResult:
        started = time.perf_counter()
        if not self.settings.has_deepseek_key:
            return LLMResult(
                text="{}",
                provider="local",
                model="fallback",
                degraded=True,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error="missing DEEPSEEK_API_KEY",
                usage={"estimated_prompt_chars": sum(len(m.get("content", "")) for m in messages)},
            )

        url = f"{self.settings.deepseek_api_base_url}/chat/completions"
        payload = {
            "model": self.settings.deepseek_chat_model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.deepseek_api_key}"}

        last_error: str | None = None
        for _ in range(max(1, self.settings.max_retries + 1)):
            try:
                async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"].strip()
                json.loads(text)
                return LLMResult(
                    text=text,
                    provider="deepseek",
                    model=self.settings.deepseek_chat_model,
                    degraded=False,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    usage=data.get("usage"),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

        return LLMResult(
            text="{}",
            provider="local",
            model="fallback",
            degraded=True,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=last_error or "provider structured call failed",
            usage={"estimated_prompt_chars": sum(len(m.get("content", "")) for m in messages)},
        )

    def _fallback(self, messages: list[dict[str, str]], started: float, error: str) -> LLMResult:
        user_text = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        reply = "我先记下你说的。"
        if "记住" in user_text:
            reply = "好，我会把这件事记进长期记忆里。"
        elif any(word in user_text for word in ("难受", "焦虑", "烦", "累")):
            reply = "听起来你现在挺累的。我先陪你把这件事慢慢捋清楚。"
        elif user_text.endswith("?") or user_text.endswith("？"):
            reply = "我理解你的问题了。现在 DeepSeek-V4 还没配置好，我先按本地模式陪你聊。"
        return LLMResult(
            text=reply,
            provider="local",
            model="fallback",
            degraded=True,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=error,
            usage={"estimated_prompt_chars": sum(len(m.get("content", "")) for m in messages)},
        )
