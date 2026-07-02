from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .chat_service import ChatService
from .config import load_settings
from .llm_gateway import DeepSeekGateway
from .storage import create_store


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class BackgroundRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    confirm: bool = True


settings = load_settings()
store = create_store(settings)
service = ChatService(store, DeepSeekGateway(settings))
app = FastAPI(title="AI 虚拟好友聊天 MVP")

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return service.status()


@app.get("/api/messages")
def api_messages() -> list[dict[str, Any]]:
    return service.messages()


@app.post("/api/chat")
async def api_chat(request: ChatRequest) -> dict[str, Any]:
    return await service.chat(request.message)


@app.post("/api/persona/import")
def api_import_persona(request: BackgroundRequest) -> dict[str, Any]:
    return service.import_background(request.text, request.confirm)


@app.post("/api/persona/{persona_id}/confirm")
def api_confirm_persona(persona_id: str) -> dict[str, Any]:
    persona = service.confirm_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="persona not found")
    return persona


@app.get("/api/memories")
def api_memories() -> list[dict[str, Any]]:
    return service.memories()


@app.get("/api/memory-confirmations")
def api_memory_confirmations() -> list[dict[str, Any]]:
    return service.memory_confirmations()


@app.post("/api/memory-confirmations/{confirmation_id}/accept")
def api_accept_memory_confirmation(confirmation_id: str) -> dict[str, Any]:
    item = service.confirm_memory_candidate(confirmation_id, True)
    if not item:
        raise HTTPException(status_code=404, detail="confirmation not found")
    return item


@app.post("/api/memory-confirmations/{confirmation_id}/reject")
def api_reject_memory_confirmation(confirmation_id: str) -> dict[str, Any]:
    item = service.confirm_memory_candidate(confirmation_id, False)
    if not item:
        raise HTTPException(status_code=404, detail="confirmation not found")
    return item


@app.delete("/api/memories/{memory_id}")
def api_delete_memory(memory_id: str) -> dict[str, bool]:
    return {"deleted": service.delete_memory(memory_id)}


@app.get("/api/llm/health")
def api_llm_health() -> dict[str, Any]:
    return {
        "chat_provider": "deepseek",
        "chat_model": settings.deepseek_chat_model,
        "chat_available": settings.has_deepseek_key,
        "fallback_available": True,
    }
