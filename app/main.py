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


class PersonaEntityRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    activate: bool = True


class PersonaImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    source_type: str = Field(default="mixed", pattern="^(background_story|chat_log|mixed)$")
    persona_entity_id: str | None = None
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


@app.get("/api/persona-entities")
def api_persona_entities() -> list[dict[str, Any]]:
    return service.persona_entities()


@app.post("/api/persona-entities")
def api_create_persona_entity(request: PersonaEntityRequest) -> dict[str, Any]:
    return service.create_persona_entity(request.name, activate=request.activate)


@app.post("/api/persona-entities/{entity_id}/activate")
def api_activate_persona_entity(entity_id: str) -> dict[str, Any]:
    entity = service.switch_persona_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="persona entity not found")
    return entity


@app.post("/api/persona/import")
async def api_import_persona(request: BackgroundRequest) -> dict[str, Any]:
    return await service.import_persona_materials(request.text, source_type="background_story", confirm=request.confirm)


@app.post("/api/persona/import-materials")
async def api_import_persona_materials(request: PersonaImportRequest) -> dict[str, Any]:
    return await service.import_persona_materials(
        request.text,
        source_type=request.source_type,
        persona_entity_id=request.persona_entity_id,
        confirm=request.confirm,
    )


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


@app.get("/api/debug")
def api_debug() -> dict[str, Any]:
    return service.debug_snapshot()


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


@app.post("/api/memories/tidy")
def api_tidy_memories() -> dict[str, Any]:
    return service.tidy_memory_store()


@app.get("/api/llm/health")
def api_llm_health() -> dict[str, Any]:
    return {
        "chat_provider": "deepseek",
        "chat_model": settings.deepseek_chat_model,
        "chat_available": settings.has_deepseek_key,
        "fallback_available": True,
    }
