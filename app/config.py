from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    deepseek_api_base_url: str
    deepseek_api_key: str
    deepseek_chat_model: str
    timeout_seconds: float
    max_retries: int
    force_local_llm: bool = False
    memory_extractor: str = "rule"
    memory_intent_classifier: str = "rule"
    storage_backend: str = "json"
    deepseek_structured_model: str = "deepseek-v4-flash"
    deepseek_thinking: str = "disabled"
    deepseek_chat_max_tokens: int = 700
    deepseek_structured_max_tokens: int = 900
    structured_provider: str = "deepseek"
    local_lm_base_url: str = "http://127.0.0.1:7985/v1"
    local_lm_api_key: str = "lm-studio"
    local_structured_model: str = "google/gemma-4-12b-qat"
    local_embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    local_structured_timeout_seconds: float = 12.0
    local_structured_max_retries: int = 0

    @property
    def has_deepseek_key(self) -> bool:
        return bool(self.deepseek_api_key) and not self.force_local_llm


def load_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    _load_dotenv(root / ".env")
    data_dir = Path(os.getenv("APP_DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return Settings(
        data_dir=data_dir,
        deepseek_api_base_url=os.getenv("DEEPSEEK_API_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_chat_model=os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash"),
        deepseek_structured_model=os.getenv("DEEPSEEK_STRUCTURED_MODEL", os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash")),
        deepseek_thinking=os.getenv("DEEPSEEK_THINKING", "disabled").lower(),
        deepseek_chat_max_tokens=int(os.getenv("DEEPSEEK_CHAT_MAX_TOKENS", "700")),
        deepseek_structured_max_tokens=int(os.getenv("DEEPSEEK_STRUCTURED_MAX_TOKENS", "900")),
        structured_provider=os.getenv("STRUCTURED_PROVIDER", "deepseek").lower(),
        local_lm_base_url=os.getenv("LOCAL_LM_BASE_URL", "http://127.0.0.1:7985/v1").rstrip("/"),
        local_lm_api_key=os.getenv("LOCAL_LM_API_KEY", "lm-studio"),
        local_structured_model=os.getenv("LOCAL_STRUCTURED_MODEL", "google/gemma-4-12b-qat"),
        local_embedding_model=os.getenv("LOCAL_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5"),
        local_structured_timeout_seconds=float(os.getenv("LOCAL_STRUCTURED_TIMEOUT_SECONDS", "12")),
        local_structured_max_retries=int(os.getenv("LOCAL_STRUCTURED_MAX_RETRIES", "0")),
        timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        force_local_llm=os.getenv("LLM_FORCE_LOCAL", "").lower() in {"1", "true", "yes"},
        memory_extractor=os.getenv("MEMORY_EXTRACTOR", "rule").lower(),
        memory_intent_classifier=os.getenv("MEMORY_INTENT_CLASSIFIER", "rule").lower(),
        storage_backend=os.getenv("STORAGE_BACKEND", "json").lower(),
    )
