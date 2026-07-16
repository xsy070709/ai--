from __future__ import annotations

import asyncio
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.chat_service import ChatService
from app.config import load_settings
from app.llm_gateway import DeepSeekGateway
from app.storage import create_store


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "app" / "static"
settings = load_settings()
service = ChatService(create_store(settings), DeepSeekGateway(settings))


class Handler(BaseHTTPRequestHandler):
    server_version = "VirtualFriendDev/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        path = urlparse(self.path).path
        if path == "/":
            return self._send_file(STATIC / "index.html")
        if path.startswith("/static/"):
            return self._send_file(STATIC / path.removeprefix("/static/"))
        if path == "/api/status":
            return self._send_json(service.status())
        if path == "/api/messages":
            return self._send_json(service.messages())
        if path == "/api/memories":
            return self._send_json(service.memories())
        if path == "/api/persona-entities":
            return self._send_json(service.persona_entities())
        if path == "/api/memory-confirmations":
            return self._send_json(service.memory_confirmations())
        if path == "/api/debug":
            return self._send_json(service.debug_snapshot())
        if path == "/api/llm/health":
            return self._send_json(
                {
                    "chat_provider": "deepseek",
                    "chat_model": settings.deepseek_chat_model,
                    "chat_available": settings.has_deepseek_key,
                    "fallback_available": True,
                }
            )
        self._send_json({"detail": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/api/chat":
            result = asyncio.run(service.chat(str(payload.get("message", ""))))
            return self._send_json(result)
        if path == "/api/messages/clear":
            return self._send_json(service.clear_current_chat())
        if path == "/api/persona-entities":
            result = service.create_persona_entity(payload.get("name"), activate=bool(payload.get("activate", True)))
            return self._send_json(result)
        if path.startswith("/api/persona-entities/") and path.endswith("/rename"):
            entity_id = path.split("/")[-2]
            result = service.rename_persona_entity(entity_id, str(payload.get("name", "")))
            return self._send_json(result or {"detail": "persona entity not found"}, 200 if result else 404)
        if path.startswith("/api/persona-entities/") and path.endswith("/activate"):
            entity_id = path.split("/")[-2]
            result = service.switch_persona_entity(entity_id)
            return self._send_json(result or {"detail": "persona entity not found"}, 200 if result else 404)
        if path == "/api/persona/import":
            result = asyncio.run(
                service.import_persona_materials(
                    str(payload.get("text", "")),
                    source_type="background_story",
                    confirm=bool(payload.get("confirm", True)),
                )
            )
            return self._send_json(result)
        if path == "/api/persona/import-materials":
            result = asyncio.run(
                service.import_persona_materials(
                    str(payload.get("text", "")),
                    source_type=str(payload.get("source_type", "mixed")),
                    persona_entity_id=payload.get("persona_entity_id"),
                    confirm=bool(payload.get("confirm", True)),
                )
            )
            return self._send_json(result)
        if path.startswith("/api/persona/") and path.endswith("/confirm"):
            persona_id = path.split("/")[-2]
            result = service.confirm_persona(persona_id)
            return self._send_json(result or {"detail": "persona not found"}, 200 if result else 404)
        if path.startswith("/api/memory-confirmations/") and path.endswith("/accept"):
            confirmation_id = path.split("/")[-2]
            result = service.confirm_memory_candidate(confirmation_id, True)
            return self._send_json(result or {"detail": "confirmation not found"}, 200 if result else 404)
        if path.startswith("/api/memory-confirmations/") and path.endswith("/reject"):
            confirmation_id = path.split("/")[-2]
            result = service.confirm_memory_candidate(confirmation_id, False)
            return self._send_json(result or {"detail": "confirmation not found"}, 200 if result else 404)
        if path == "/api/memories/tidy":
            return self._send_json(service.tidy_memory_store())
        self._send_json({"detail": "not found"}, 404)

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib hook
        path = urlparse(self.path).path
        payload = self._read_json()
        if path.startswith("/api/persona-entities/"):
            entity_id = path.rsplit("/", 1)[-1]
            result = service.rename_persona_entity(entity_id, str(payload.get("name", "")))
            return self._send_json(result or {"detail": "persona entity not found"}, 200 if result else 404)
        self._send_json({"detail": "not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib hook
        path = urlparse(self.path).path
        if path.startswith("/api/persona-entities/"):
            entity_id = path.rsplit("/", 1)[-1]
            deleted = service.delete_persona_entity(entity_id)
            return self._send_json({"deleted": deleted}, 200 if deleted else 404)
        if path.startswith("/api/memories/"):
            return self._send_json({"deleted": service.delete_memory(path.rsplit("/", 1)[-1])})
        self._send_json({"detail": "not found"}, 404)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            return self._send_json({"detail": "not found"}, 404)
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    print(f"Serving AI virtual friend MVP at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
