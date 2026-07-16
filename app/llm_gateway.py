from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .local_model import OpenAICompatibleLocalClient, structured_response_format


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
        self._structured_cache: dict[str, LLMResult] = {}
        self._request_log: list[dict[str, Any]] = []
        self._local_client: OpenAICompatibleLocalClient | None = None

    async def chat(self, messages: list[dict[str, str]], purpose: str = "chat") -> LLMResult:
        started = time.perf_counter()
        if not self.settings.has_deepseek_key:
            return self._fallback(messages, started, "missing DEEPSEEK_API_KEY")

        url = f"{self.settings.deepseek_api_base_url}/chat/completions"
        payload = self._payload(messages, purpose=purpose, structured=False)
        headers = {"Authorization": f"Bearer {self.settings.deepseek_api_key}"}

        last_error: str | None = None
        for _ in range(max(1, self.settings.max_retries + 1)):
            try:
                async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"].strip()
                result = LLMResult(
                    text=text,
                    provider="deepseek",
                    model=payload["model"],
                    degraded=False,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    usage=self._usage(data),
                )
                self._record_request(purpose, payload, result)
                return result
            except Exception as exc:  # noqa: BLE001 - preserve provider error for log
                last_error = str(exc)

        result = self._fallback(messages, started, last_error or "provider call failed")
        self._record_request(purpose, payload, result)
        return result

    async def structured(self, messages: list[dict[str, str]], purpose: str = "structured") -> LLMResult:
        if self._uses_local_structured(purpose):
            return await self._local_structured(messages, purpose=purpose)

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
        payload = self._payload(messages, purpose=purpose, structured=True)
        cache_key = self._structured_cache_key(payload)
        if cache_key in self._structured_cache:
            cached = deepcopy(self._structured_cache[cache_key])
            cached.elapsed_ms = int((time.perf_counter() - started) * 1000)
            cached.usage = dict(cached.usage or {})
            cached.usage["client_cache_hit"] = True
            self._record_request(purpose, payload, cached, client_cache_hit=True)
            return cached
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
                result = LLMResult(
                    text=text,
                    provider="deepseek",
                    model=payload["model"],
                    degraded=False,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    usage=self._usage(data),
                )
                self._structured_cache[cache_key] = deepcopy(result)
                self._record_request(purpose, payload, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

        result = LLMResult(
            text="{}",
            provider="local",
            model="fallback",
            degraded=True,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=last_error or "provider structured call failed",
            usage={"estimated_prompt_chars": sum(len(m.get("content", "")) for m in messages)},
        )
        self._record_request(purpose, payload, result)
        return result

    async def _local_structured(self, messages: list[dict[str, str]], purpose: str) -> LLMResult:
        started = time.perf_counter()
        payload = self._local_payload(messages, purpose=purpose)
        cache_key = self._structured_cache_key(payload)
        if cache_key in self._structured_cache:
            cached = deepcopy(self._structured_cache[cache_key])
            cached.elapsed_ms = int((time.perf_counter() - started) * 1000)
            cached.usage = dict(cached.usage or {})
            cached.usage["client_cache_hit"] = True
            self._record_request(purpose, payload, cached, client_cache_hit=True)
            return cached

        last_error: str | None = None
        for _ in range(max(1, self.settings.local_structured_max_retries + 1)):
            try:
                data = await self._local().chat_completion(
                    messages=payload["messages"],
                    model=payload["model"],
                    response_format=payload.get("response_format"),
                    max_tokens=int(payload["max_tokens"]),
                    temperature=float(payload["temperature"]),
                    timeout_seconds=max(0.1, self.settings.local_structured_timeout_seconds),
                )
                text = data["choices"][0]["message"]["content"].strip()
                json.loads(text)
                result = LLMResult(
                    text=text,
                    provider="lmstudio",
                    model=payload["model"],
                    degraded=False,
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    usage=self._usage(data),
                )
                self._structured_cache[cache_key] = deepcopy(result)
                self._record_request(purpose, payload, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

        result = LLMResult(
            text="{}",
            provider="lmstudio",
            model=payload["model"],
            degraded=True,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=last_error or "local structured call failed",
            usage={"estimated_prompt_chars": sum(len(m.get("content", "")) for m in messages)},
        )
        self._record_request(purpose, payload, result)
        return result

    def _local(self) -> OpenAICompatibleLocalClient:
        if self._local_client is None:
            self._local_client = OpenAICompatibleLocalClient(
                self.settings.local_lm_base_url,
                api_key=self.settings.local_lm_api_key,
            )
        return self._local_client

    def _uses_local_structured(self, purpose: str) -> bool:
        if self.settings.structured_provider in {"lmstudio", "local"}:
            return True
        if purpose == "memory_extract" and self.settings.memory_extractor in {"lmstudio", "local"}:
            return True
        if purpose == "memory_intent" and self.settings.memory_intent_classifier in {"lmstudio", "local"}:
            return True
        return False

    def _payload(self, messages: list[dict[str, str]], *, purpose: str, structured: bool) -> dict[str, Any]:
        thinking = self.settings.deepseek_thinking
        payload: dict[str, Any] = {
            "model": self.settings.deepseek_structured_model if structured else self.settings.deepseek_chat_model,
            "messages": self._format_messages(messages, structured=structured),
            "stream": False,
            "max_tokens": self.settings.deepseek_structured_max_tokens if structured else self.settings.deepseek_chat_max_tokens,
        }
        if thinking in {"enabled", "disabled"}:
            payload["thinking"] = {"type": thinking}
        if thinking == "enabled":
            payload["reasoning_effort"] = "high"
        else:
            payload["temperature"] = 0.1 if structured else 0.7
        if structured:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _local_payload(self, messages: list[dict[str, str]], *, purpose: str) -> dict[str, Any]:
        return {
            "provider": "lmstudio",
            "model": self.settings.local_structured_model,
            "messages": self._format_messages(messages, structured=True),
            "stream": False,
            "max_tokens": self.settings.deepseek_structured_max_tokens,
            "temperature": 0.1,
            "response_format": structured_response_format(purpose),
        }

    def _format_messages(self, messages: list[dict[str, str]], *, structured: bool) -> list[dict[str, str]]:
        if not structured:
            return messages
        formatted = [dict(message) for message in messages]
        if formatted and "json" not in formatted[0].get("content", "").lower():
            formatted[0]["content"] = f"{formatted[0].get('content', '')}\n必须输出 valid json object。"
        return formatted

    def _usage(self, data: dict[str, Any]) -> dict[str, Any] | None:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return usage
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        total = hit + miss
        usage = dict(usage)
        usage["prompt_cache_hit_ratio"] = round(hit / total, 4) if total else 0.0
        usage["client_cache_hit"] = False
        return usage

    def _structured_cache_key(self, payload: dict[str, Any]) -> str:
        return json.dumps(
            {
                "model": payload.get("model"),
                "messages": payload.get("messages"),
                "response_format": payload.get("response_format"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _record_request(self, purpose: str, payload: dict[str, Any], result: LLMResult, *, client_cache_hit: bool = False) -> None:
        self._request_log.append(
            {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "purpose": purpose,
                "model": payload.get("model"),
                "local_base_url": self.settings.local_lm_base_url if result.provider == "lmstudio" else None,
                "thinking": payload.get("thinking"),
                "response_format": payload.get("response_format"),
                "max_tokens": payload.get("max_tokens"),
                "messages": payload.get("messages", []),
                "prompt_stats": self._prompt_stats(payload.get("messages", [])),
                "provider": result.provider,
                "degraded": result.degraded,
                "elapsed_ms": result.elapsed_ms,
                "error": result.error,
                "usage": result.usage,
                "response_text": result.text,
                "client_cache_hit": client_cache_hit,
            }
        )
        self._request_log = self._request_log[-80:]

    def debug_requests(self) -> list[dict[str, Any]]:
        return deepcopy(self._request_log)

    def _prompt_stats(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        system_messages = [message for message in messages if message.get("role") == "system"]
        system_segments = [
            {
                "index": index,
                "chars": len(message.get("content", "")),
                "first_line": message.get("content", "").splitlines()[0] if message.get("content") else "",
            }
            for index, message in enumerate(system_messages)
        ]
        return {
            "message_count": len(messages),
            "total_chars": sum(len(message.get("content", "")) for message in messages),
            "stable_system_chars": len(system_messages[0].get("content", "")) if system_messages else 0,
            "summary_system_chars": len(system_messages[1].get("content", "")) if len(system_messages) > 1 else 0,
            "memory_system_chars": len(system_messages[2].get("content", "")) if len(system_messages) > 2 else 0,
            "time_system_chars": len(system_messages[3].get("content", "")) if len(system_messages) > 3 else 0,
            "system_segments": system_segments,
        }

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
