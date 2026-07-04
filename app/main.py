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


class PersonaEntityRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PersonaImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    source_type: str = Field(default="mixed", pattern="^(background_story|chat_log|mixed)$")
    persona_entity_id: str | None = None
    confirm: bool = True


class ImportSessionStartRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    source_type: str = Field(default="mixed", pattern="^(background_story|chat_log|mixed)$")
    persona_entity_id: str | None = None


class ImportSessionChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ImportSessionConfirmRequest(BaseModel):
    profile: dict[str, Any]


class CreateEventRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    event_type: str = Field(default="neutral", pattern="^(positive|negative|neutral|traumatic)$")
    impact_scope: str = Field(default="temporary", pattern="^(temporary|permanent|fading)$")
    expires_at: str | None = None
    trait_effects: list[dict[str, Any]] = []
    becomes_topic: bool = True
    topic_trigger_words: list[str] = []
    becomes_taboo: bool = False
    taboo_keywords: list[str] = []


class UpdateEventRequest(BaseModel):
    content: str | None = Field(default=None, max_length=2000)
    event_type: str | None = Field(default=None, pattern="^(positive|negative|neutral|traumatic)$")
    impact_scope: str | None = Field(default=None, pattern="^(temporary|permanent|fading)$")
    expires_at: str | None = None
    trait_effects: list[dict[str, Any]] | None = None
    becomes_topic: bool | None = None
    topic_trigger_words: list[str] | None = None
    becomes_taboo: bool | None = None
    taboo_keywords: list[str] | None = None
    resolution_note: str | None = Field(default=None, max_length=500)


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


@app.post("/api/messages/clear")
def api_clear_messages() -> dict[str, Any]:
    return service.clear_current_chat()


@app.post("/api/chat")
async def api_chat(request: ChatRequest) -> dict[str, Any]:
    return await service.chat(request.message)


@app.get("/api/persona-entities")
def api_persona_entities() -> list[dict[str, Any]]:
    return service.persona_entities()


@app.post("/api/persona-entities")
def api_create_persona_entity(request: PersonaEntityRequest) -> dict[str, Any]:
    return service.create_persona_entity(request.name, activate=request.activate)


@app.patch("/api/persona-entities/{entity_id}")
def api_rename_persona_entity(entity_id: str, request: PersonaEntityRenameRequest) -> dict[str, Any]:
    entity = service.rename_persona_entity(entity_id, request.name)
    if not entity:
        raise HTTPException(status_code=404, detail="persona entity not found")
    return entity


@app.post("/api/persona-entities/{entity_id}/activate")
def api_activate_persona_entity(entity_id: str) -> dict[str, Any]:
    entity = service.switch_persona_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="persona entity not found")
    return entity


@app.delete("/api/persona-entities/{entity_id}")
def api_delete_persona_entity(entity_id: str) -> dict[str, bool]:
    deleted = service.delete_persona_entity(entity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="persona entity not found")
    return {"deleted": True}


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


# ── import wizard session routes ────────────────────────────────────


@app.post("/api/persona/import-session")
async def api_start_import_session(request: ImportSessionStartRequest) -> dict[str, Any]:
    """Start a new import wizard session — paste text, get initial analysis."""
    return await service.start_import_session(
        request.text,
        source_type=request.source_type,
        persona_entity_id=request.persona_entity_id,
    )


@app.post("/api/persona/import-session/{session_id}/chat")
async def api_import_session_chat(session_id: str, request: ImportSessionChatRequest) -> dict[str, Any]:
    """Send a refinement message in the import learning dialogue."""
    try:
        return await service.import_session_chat(session_id, request.message)
    except KeyError:
        raise HTTPException(status_code=404, detail="import session not found")


@app.get("/api/persona/import-session/{session_id}")
def api_get_import_session(session_id: str) -> dict[str, Any]:
    """Get current state of an import session."""
    result = service.get_import_session_state(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="import session not found")
    return result


@app.patch("/api/persona/import-session/{session_id}/profile")
def api_update_import_session_profile(session_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Manually edit the profile in an import session."""
    result = service.update_import_session_profile(session_id, request)
    if result is None:
        raise HTTPException(status_code=404, detail="import session not found")
    return {"session_id": session_id, "current_profile": result}


@app.post("/api/persona/import-session/{session_id}/confirm")
async def api_confirm_import_session(session_id: str, request: ImportSessionConfirmRequest) -> dict[str, Any]:
    """Confirm and persist the profile from an import session."""
    try:
        return await service.confirm_import_session(session_id, request.profile)
    except KeyError:
        raise HTTPException(status_code=404, detail="import session not found")


@app.delete("/api/persona/import-session/{session_id}")
def api_delete_import_session(session_id: str) -> dict[str, bool]:
    """Discard an import session."""
    deleted = service.delete_import_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="import session not found")
    return {"deleted": True}


# ── persona event routes ────────────────────────────────────────────


@app.get("/api/persona-events")
def api_get_persona_events() -> list[dict[str, Any]]:
    """List events for the active persona entity."""
    return service.get_persona_events()


@app.post("/api/persona-events")
def api_create_persona_event(request: CreateEventRequest) -> dict[str, Any]:
    """Create a new persona event + linked memory."""
    return service.create_persona_event(
        content=request.content,
        event_type=request.event_type,
        impact_scope=request.impact_scope,
        expires_at=request.expires_at,
        trait_effects=request.trait_effects,
        becomes_topic=request.becomes_topic,
        topic_trigger_words=request.topic_trigger_words,
        becomes_taboo=request.becomes_taboo,
        taboo_keywords=request.taboo_keywords,
    )


@app.patch("/api/persona-events/{event_id}")
def api_update_persona_event(event_id: str, request: UpdateEventRequest) -> dict[str, Any]:
    """Update an event's fields."""
    patch = {k: v for k, v in request.model_dump().items() if v is not None}
    result = service.update_persona_event(event_id, patch)
    if result is None:
        raise HTTPException(status_code=404, detail="event not found")
    return result


@app.delete("/api/persona-events/{event_id}")
def api_delete_persona_event(event_id: str) -> dict[str, bool]:
    """Delete an event."""
    deleted = service.delete_persona_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="event not found")
    return {"deleted": True}


class ResolveEventRequest(BaseModel):
    note: str = ""


@app.post("/api/persona-events/{event_id}/resolve")
def api_resolve_persona_event(event_id: str, request: ResolveEventRequest = ResolveEventRequest()) -> dict[str, Any]:  # noqa: B008
    """Mark an event as resolved — converts to shared_experience memory."""
    result = service.resolve_persona_event(event_id, request.note)
    if result is None:
        raise HTTPException(status_code=404, detail="event not found")
    return result


@app.post("/api/persona-events/{event_id}/acknowledge")
def api_acknowledge_persona_event(event_id: str) -> dict[str, Any]:
    """Mark an event as acknowledged (discussed in chat)."""
    result = service.acknowledge_persona_event(event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="event not found")
    return result


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
