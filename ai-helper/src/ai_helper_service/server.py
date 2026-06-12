from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import Settings
from .provider import build_provider, is_loopback_host


class AiHelperServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], settings: Settings):
        super().__init__(server_address, Handler)
        self.settings = settings
        self.provider = build_provider(settings)


class Handler(BaseHTTPRequestHandler):
    server: AiHelperServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = self.server.settings.server_token
        return not token or self.headers.get("X-AI-Helper-Token") == token

    def do_GET(self) -> None:
        if self.path == "/health":
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/query":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._send_json(400, {"error": "prompt is required"})
                return
            response = self.server.provider.generate(prompt)
            self._send_json(200, {"response": response})
        except Exception:
            self._send_json(500, {"error": "generation failed"})


def serve(settings: Settings) -> None:
    if (
        settings.backend in {"http", "python"}
        and not is_loopback_host(settings.host)
        and not settings.server_token
    ):
        raise RuntimeError(
            "AI_HELPER_SERVER_TOKEN is required to serve a non-local backend on a non-loopback host"
        )

    httpd = AiHelperServer((settings.host, settings.port), settings)
    print(
        f"ai-helper: serving {settings.backend} backend on http://{settings.host}:{settings.port}",
        flush=True,
    )
    httpd.serve_forever()
