from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import Settings


class ServiceUnavailable(RuntimeError):
    pass


def query_service(prompt: str, settings: Settings, timeout: float = 600.0) -> str:
    headers = {"Content-Type": "application/json"}
    if settings.server_token:
        headers["X-AI-Helper-Token"] = settings.server_token
    request = urllib.request.Request(
        f"http://{settings.host}:{settings.port}/v1/query",
        data=json.dumps({"prompt": prompt}).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise ServiceUnavailable(
            f"ai-helper service is not running at {settings.host}:{settings.port}"
        ) from error

    if "error" in payload:
        raise RuntimeError(payload["error"])
    return str(payload.get("response", ""))


def healthcheck(settings: Settings, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(f"http://{settings.host}:{settings.port}/health")
    if settings.server_token:
        request.add_header("X-AI-Helper-Token", settings.server_token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except urllib.error.URLError:
        return False
