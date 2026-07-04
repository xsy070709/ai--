from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_service import ChatService
from app.config import Settings, load_settings
from app.llm_gateway import DeepSeekGateway
from app.local_model import OpenAICompatibleLocalClient
from app.memory.extractors import RuleBasedMemoryExtractor, StructuredLLMMemoryExtractor
from app.memory.intent import RuleBasedIntentClassifier, StructuredLLMIntentClassifier
from app.memory.semantic import semantic_similarity
from app.storage import JsonStore


INTENT_CASES = [
    {
        "name": "completion_materials",
        "text": "材料已经交完了，终于松口气。",
        "expected": {"has_completion_signal": True, "has_correction_intent": False},
    },
    {
        "name": "memory_correction",
        "text": "不是周三，是周五下午面试。",
        "expected": {"has_correction_intent": True, "correction_action": "correct"},
    },
    {
        "name": "followup_invitation",
        "text": "上次说的那个面试准备，我们继续吧。",
        "expected": {"has_followup_invitation": True},
    },
]


EXTRACTION_CASES = [
    {
        "name": "response_rule",
        "user": "以后别上来就讲大道理，我更希望你先安慰我。",
        "assistant": "好，我会先陪你缓一下，再一起分析。",
        "expected_types": ["response_rule"],
    },
    {
        "name": "sensitive_boundary",
        "user": "这是我的雷区，不要提我家里的事。",
        "assistant": "知道了，我会避开这个话题。",
        "expected_types": ["boundary"],
    },
    {
        "name": "open_goal",
        "user": "明天下午我要交材料，现在因为项目有点焦虑。",
        "assistant": "我先陪你把材料拆成小步。",
        "expected_types": ["goal", "emotion_pattern"],
    },
]


EMBEDDING_PAIRS = [
    {"name": "sleep_synonym", "left": "我最近睡不好", "right": "用户最近失眠严重"},
    {"name": "completion_synonym", "left": "材料搞定了", "right": "用户已经完成材料提交"},
    {"name": "topic_mismatch", "left": "我最近睡不好", "right": "明天要准备面试简历"},
]


def _settings(base: Settings) -> Settings:
    return Settings(
        data_dir=base.data_dir,
        deepseek_api_base_url=base.deepseek_api_base_url,
        deepseek_api_key=base.deepseek_api_key,
        deepseek_chat_model=base.deepseek_chat_model,
        deepseek_structured_model=base.deepseek_structured_model,
        deepseek_thinking=base.deepseek_thinking,
        deepseek_chat_max_tokens=base.deepseek_chat_max_tokens,
        deepseek_structured_max_tokens=base.deepseek_structured_max_tokens,
        structured_provider="lmstudio",
        local_lm_base_url=base.local_lm_base_url,
        local_lm_api_key=base.local_lm_api_key,
        local_structured_model=base.local_structured_model,
        local_embedding_model=base.local_embedding_model,
        timeout_seconds=base.timeout_seconds,
        max_retries=base.max_retries,
        force_local_llm=True,
        memory_extractor="lmstudio",
        memory_intent_classifier="lmstudio",
        storage_backend="json",
    )


async def _model_health(settings: Settings) -> dict[str, Any]:
    started = time.perf_counter()
    client = OpenAICompatibleLocalClient(settings.local_lm_base_url, settings.local_lm_api_key)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=settings.timeout_seconds) as http:
            response = await http.get(f"{settings.local_lm_base_url}/models")
            response.raise_for_status()
            data = response.json()
        model_ids = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
        return {
            "ok": True,
            "elapsed_ms": _elapsed_ms(started),
            "base_url": settings.local_lm_base_url,
            "structured_model": settings.local_structured_model,
            "embedding_model": settings.local_embedding_model,
            "models": model_ids,
            "structured_model_available": settings.local_structured_model in model_ids,
            "embedding_model_available": settings.local_embedding_model in model_ids,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(started),
            "base_url": settings.local_lm_base_url,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        _ = client


async def _run_intent_cases(settings: Settings) -> list[dict[str, Any]]:
    gateway = DeepSeekGateway(settings)
    local_classifier = StructuredLLMIntentClassifier(gateway, name="structured_lmstudio_intent")
    rule_classifier = RuleBasedIntentClassifier()
    results = []
    for case in INTENT_CASES:
        rule_intent = rule_classifier.classify(case["text"])
        started = time.perf_counter()
        local_intent = await local_classifier.classify_async(case["text"])
        elapsed_ms = _elapsed_ms(started)
        checks = {
            key: local_intent.get(key) == expected
            for key, expected in case["expected"].items()
        }
        results.append(
            {
                "name": case["name"],
                "text": case["text"],
                "elapsed_ms": elapsed_ms,
                "passed": all(checks.values()),
                "checks": checks,
                "rule": _intent_view(rule_intent),
                "lmstudio": _intent_view(local_intent),
            }
        )
    return results


async def _run_extraction_cases(settings: Settings) -> list[dict[str, Any]]:
    gateway = DeepSeekGateway(settings)
    local_extractor = StructuredLLMMemoryExtractor(gateway, name="structured_lmstudio")
    rule_extractor = RuleBasedMemoryExtractor()
    results = []
    for case in EXTRACTION_CASES:
        rule_memories = rule_extractor.extract(case["user"], case["assistant"])
        started = time.perf_counter()
        local_memories = await local_extractor.extract_async(case["user"], case["assistant"])
        elapsed_ms = _elapsed_ms(started)
        local_types = sorted({memory.get("type") for memory in local_memories})
        checks = {
            memory_type: memory_type in local_types
            for memory_type in case["expected_types"]
        }
        results.append(
            {
                "name": case["name"],
                "user": case["user"],
                "elapsed_ms": elapsed_ms,
                "passed": all(checks.values()),
                "checks": checks,
                "rule_types": sorted({memory.get("type") for memory in rule_memories}),
                "lmstudio_types": local_types,
                "lmstudio_memories": [
                    {
                        "type": memory.get("type"),
                        "content": memory.get("content"),
                        "confidence": memory.get("confidence"),
                        "open": memory.get("open"),
                        "extractor": memory.get("extractor"),
                    }
                    for memory in local_memories
                ],
            }
        )
    return results


async def _run_embedding_pairs(settings: Settings) -> list[dict[str, Any]]:
    client = OpenAICompatibleLocalClient(settings.local_lm_base_url, settings.local_lm_api_key)
    results = []
    for pair in EMBEDDING_PAIRS:
        started = time.perf_counter()
        try:
            data = await client.embeddings(
                texts=[pair["left"], pair["right"]],
                model=settings.local_embedding_model,
                timeout_seconds=settings.timeout_seconds,
            )
            vectors = [item["embedding"] for item in data.get("data", [])]
            similarity = _cosine(vectors[0], vectors[1]) if len(vectors) == 2 else 0.0
            results.append(
                {
                    "name": pair["name"],
                    "left": pair["left"],
                    "right": pair["right"],
                    "elapsed_ms": _elapsed_ms(started),
                    "ok": len(vectors) == 2,
                    "dimension": len(vectors[0]) if vectors else 0,
                    "lmstudio_similarity": round(similarity, 4),
                    "local_hash_similarity": round(semantic_similarity(pair["left"], pair["right"]), 4),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "name": pair["name"],
                    "left": pair["left"],
                    "right": pair["right"],
                    "elapsed_ms": _elapsed_ms(started),
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "local_hash_similarity": round(semantic_similarity(pair["left"], pair["right"]), 4),
                }
            )
    return results


async def _run_frontend_guard(base: Settings) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lmstudio-frontend-guard-") as tmp:
        settings = Settings(
            data_dir=Path(tmp),
            deepseek_api_base_url=base.deepseek_api_base_url,
            deepseek_api_key="",
            deepseek_chat_model=base.deepseek_chat_model,
            deepseek_structured_model=base.deepseek_structured_model,
            deepseek_thinking=base.deepseek_thinking,
            deepseek_chat_max_tokens=base.deepseek_chat_max_tokens,
            deepseek_structured_max_tokens=base.deepseek_structured_max_tokens,
            structured_provider="deepseek",
            local_lm_base_url=base.local_lm_base_url,
            local_lm_api_key=base.local_lm_api_key,
            local_structured_model=base.local_structured_model,
            local_embedding_model=base.local_embedding_model,
            timeout_seconds=base.timeout_seconds,
            max_retries=0,
            force_local_llm=True,
            memory_extractor="rule",
            memory_intent_classifier="rule",
            storage_backend="json",
        )
        service = ChatService(JsonStore(settings), DeepSeekGateway(settings))
        started = time.perf_counter()
        result = await service.chat("明天下午我要交材料，现在有点焦虑。")
        elapsed_ms = _elapsed_ms(started)
        requests = service.gateway.debug_requests()
        return {
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "reply_provider": result["llm"]["provider"],
            "reply_model": result["llm"]["model"],
            "reply_degraded": result["degraded"],
            "lmstudio_request_count": sum(1 for request in requests if request.get("provider") == "lmstudio"),
            "memory_extractor": service.store.snapshot()["generation_logs"][-1]["prompt_manifest"]["memory_extractor"],
            "intent_classifier": service.store.snapshot()["generation_logs"][-1]["prompt_manifest"]["intent_classifier"],
            "evidence": "Default foreground chat used rule memory workflow and did not call LM Studio.",
        }


def _intent_view(intent: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "classifier",
        "has_completion_signal",
        "completion_target",
        "has_correction_intent",
        "correction_action",
        "has_followup_invitation",
        "primary_emotion",
        "valence",
        "is_casual_chat",
        "topics",
        "information_density",
    ]
    return {key: intent.get(key) for key in keys}


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    intent = report["intent_cases"]
    extraction = report["extraction_cases"]
    embeddings = report["embedding_pairs"]
    return {
        "health_ok": report["health"].get("ok") is True,
        "intent_passed": sum(1 for item in intent if item.get("passed")),
        "intent_total": len(intent),
        "extraction_passed": sum(1 for item in extraction if item.get("passed")),
        "extraction_total": len(extraction),
        "embedding_ok": sum(1 for item in embeddings if item.get("ok")),
        "embedding_total": len(embeddings),
        "frontend_lmstudio_request_count": report["frontend_guard"].get("lmstudio_request_count"),
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def run_pilot() -> dict[str, Any]:
    base = load_settings()
    settings = _settings(base)
    report: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": "lmstudio_backend_workflow_pilot",
        "config": {
            "base_url": settings.local_lm_base_url,
            "structured_model": settings.local_structured_model,
            "embedding_model": settings.local_embedding_model,
            "timeout_seconds": settings.timeout_seconds,
            "max_retries": settings.max_retries,
        },
        "health": await _model_health(settings),
    }
    if not report["health"].get("ok"):
        report["summary"] = _summary({**report, "intent_cases": [], "extraction_cases": [], "embedding_pairs": [], "frontend_guard": {}})
        return report
    report["intent_cases"] = await _run_intent_cases(settings)
    report["extraction_cases"] = await _run_extraction_cases(settings)
    report["embedding_pairs"] = await _run_embedding_pairs(settings)
    report["frontend_guard"] = await _run_frontend_guard(base)
    report["summary"] = _summary(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an LM Studio backend-workflow pilot without touching user data.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()

    report = asyncio.run(run_pilot())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if not report.get("health", {}).get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
