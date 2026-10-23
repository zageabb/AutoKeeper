"""Ollama adapter for AutoKeeper's authenticated, text-only chat panel.

Only the AutoKeeper server contacts Ollama. This module intentionally has no
access to the vehicle database, DVLA tools or arbitrary user-selected URLs.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

import requests


class OllamaError(Exception):
    """Safe error suitable for showing to a logged-in operator."""


def base_url() -> str:
    url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise OllamaError("Invalid OLLAMA_BASE_URL server configuration")
    return url


def request_timeout() -> int:
    """Long read timeout helps locally hosted, CPU-offloaded large models."""
    try:
        seconds = int(os.getenv("OLLAMA_READ_TIMEOUT", "300"))
    except ValueError:
        seconds = 300
    return min(max(seconds, 30), 900)


def list_models(session=None) -> list[dict]:
    """Query the live list each time; never advertise invented model choices."""
    client = session or requests
    try:
        response = client.get(
            base_url() + "/api/tags",
            timeout=(5, 12), allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        if not isinstance(models, list):
            raise ValueError("Models array is not a list")
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise OllamaError("Cannot reach Ollama or read its model list. Check OLLAMA_BASE_URL and the Ollama service.") from exc
    cleaned = []
    seen = set()
    for item in models[:256]:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if not isinstance(name, str) or not name or len(name) > 160 or name in seen:
            continue
        seen.add(name)
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        size = item.get("size")
        cleaned.append({
            "name": name,
            "parameter_size": str(details.get("parameter_size") or "")[:40],
            "size_bytes": size if isinstance(size, int) and size >= 0 else None,
        })
    return sorted(cleaned, key=lambda m: m["name"].casefold())


def open_chat(model: str, messages: list[dict], system_context: str = "", session=None):
    """Start upstream NDJSON streaming; called from a synchronous FastAPI route.

    Model selection is checked against Ollama's *current* installed model list.
    We do not forward arbitrary roles, tools, files or model server addresses.
    """
    names = {m["name"] for m in list_models(session)}
    if model not in names:
        raise ValueError("Select a model currently installed on the Ollama server.")
    client = session or requests
    outgoing = [{
        "role": "system",
        "content": (
            "You are a general chat assistant inside AutoKeeper. "
            "You have no direct access to vehicle records, DVLA, local files, "
            "other tools or live information. Do not claim to have performed actions."
        ),
    }]
    if system_context:
        outgoing.append({"role": "system", "content": system_context})
    outgoing.extend({"role": msg["role"], "content": msg["content"]} for msg in messages)
    try:
        response = client.post(
            base_url() + "/api/chat",
            json={
                "model": model,
                "messages": outgoing,
                "stream": True,
                "options": {"num_predict": 2048},
            },
            stream=True, timeout=(5, request_timeout()), allow_redirects=False,
        )
        response.raise_for_status()
        return response
    except (requests.RequestException, ValueError) as exc:
        raise OllamaError("Ollama could not start this chat. Check the selected model and server logs.") from exc


def stream_deltas(response):
    """Forward only text deltas as line-delimited JSON, never hidden thinking.

    An explicit done/error event lets the client handle EOF and retry safely.
    """
    limit = 100_000
    emitted = 0
    done = False
    try:
        for line in response.iter_lines():
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            packet = json.loads(line)
            if not isinstance(packet, dict):
                continue
            if packet.get("error"):
                yield json.dumps({"error": "Ollama returned a generation error."}) + "\n"
                return
            msg = packet.get("message") or {}
            delta = msg.get("content", "") if isinstance(msg, dict) else ""
            if isinstance(delta, str) and delta:
                available = max(0, limit - emitted)
                if available == 0:
                    yield json.dumps({"error": "Answer exceeded the display limit."}) + "\n"
                    return
                piece = delta[:available]
                emitted += len(piece)
                yield json.dumps({"delta": piece}, ensure_ascii=False) + "\n"
            if packet.get("done"):
                done = True
                yield '{"done":true}\n'
                return
        if not done:
            yield '{"error":"Ollama ended the response before completion."}\n'
    except (requests.RequestException, ValueError, UnicodeError, TypeError):
        yield '{"error":"Ollama streaming connection was interrupted."}\n'
    finally:
        response.close()


def structured_completion(model: str, system: str, user: str, schema: dict,
                          session=None) -> dict:
    """Request a single schema-constrained JSON response for edit proposals."""
    if model not in {m["name"] for m in list_models(session)}:
        raise ValueError("Select a model installed on Ollama.")
    client = session or requests
    try:
        result = client.post(
            base_url() + "/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 1024},
            },
            timeout=(5, request_timeout()),
            allow_redirects=False,
        )
        result.raise_for_status()
        payload = result.json()
        content = payload["message"]["content"]
        decoded = json.loads(content)
        if not isinstance(decoded, dict):
            raise ValueError("Non-object response")
        return decoded
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise OllamaError(
            "The model could not prepare a structured change. "
            "Try another Ollama model with JSON-schema support."
        ) from exc
