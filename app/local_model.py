from __future__ import annotations

from typing import Any

import httpx


class OpenAICompatibleLocalClient:
    def __init__(self, base_url: str, api_key: str = "lm-studio") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 700,
        temperature: float = 0.1,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    async def embeddings(
        self,
        *,
        texts: list[str],
        model: str,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        payload = {"model": model, "input": texts}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/embeddings", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()


def structured_response_format(purpose: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _schema_name(purpose),
            "strict": True,
            "schema": _schema_for_purpose(purpose),
        },
    }


def _schema_name(purpose: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in purpose.lower()).strip("_")
    return safe or "structured_response"


def _schema_for_purpose(purpose: str) -> dict[str, Any]:
    if purpose == "memory_extract":
        return {
            "type": "object",
            "properties": {
                "memories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "content": {"type": "string"},
                            "confidence": {"type": "number"},
                            "confirmed": {"type": "boolean"},
                            "open": {"type": "boolean"},
                            "stability": {"type": "string"},
                            "sensitivity_level": {"type": "string"},
                        },
                        "required": [
                            "type",
                            "content",
                            "confidence",
                            "confirmed",
                            "open",
                            "stability",
                            "sensitivity_level",
                        ],
                    },
                }
            },
            "required": ["memories"],
        }
    if purpose == "memory_intent":
        nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        return {
            "type": "object",
            "properties": {
                "has_completion_signal": {"type": "boolean"},
                "completion_target": nullable_string,
                "has_correction_intent": {"type": "boolean"},
                "correction_action": nullable_string,
                "correction_query": nullable_string,
                "correction_new_value": nullable_string,
                "primary_emotion": {"type": "string"},
                "secondary_emotion": nullable_string,
                "valence": {"type": "string"},
                "is_casual_chat": {"type": "boolean"},
                "has_followup_invitation": {"type": "boolean"},
                "topics": {"type": "array", "items": {"type": "string"}},
                "unfinished_items": {"type": "array", "items": {"type": "string"}},
                "information_density": {"type": "number"},
            },
            "required": [
                "has_completion_signal",
                "completion_target",
                "has_correction_intent",
                "correction_action",
                "correction_query",
                "correction_new_value",
                "primary_emotion",
                "secondary_emotion",
                "valence",
                "is_casual_chat",
                "has_followup_invitation",
                "topics",
                "unfinished_items",
                "information_density",
            ],
        }
    return {"type": "object", "properties": {}, "additionalProperties": True}
