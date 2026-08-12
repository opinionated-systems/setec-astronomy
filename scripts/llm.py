#!/usr/bin/env python3
"""Minimal provider-agnostic OpenAI-compatible chat client.

Standard library only (urllib) so the scrubber has no hard third-party
dependency. Works against any endpoint that speaks the OpenAI Chat Completions
shape: Fireworks, OpenAI, OpenRouter, Together, a local Ollama, etc.

Config comes from the environment (bring your own backend + key):
    SETEC_BASE_URL   e.g. https://api.fireworks.ai/inference/v1
                            (a full .../chat/completions URL is also accepted)
    SETEC_API_KEY    your key (use "ollama" or anything for keyless local)
    SETEC_MODEL      model id, e.g. accounts/fireworks/models/deepseek-v4-flash
                            or gpt-4o-mini, or llama3.1 (Ollama)
"""

import json
import os
import urllib.error
import urllib.request


def _endpoint(base_url: str) -> str:
    """Accept either a base ('.../v1') or a full chat-completions URL.

    Endpoint env vars get configured inconsistently in practice, so derive the
    right URL from whichever shape was given.
    """
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return trimmed + "/chat/completions"


def chat(
    messages: list[dict[str, str]],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: int = 120,
) -> str:
    """Send a chat completion and return the assistant message content.

    Raises RuntimeError with the response body on a non-2xx, which surfaces
    enough detail to diagnose the failure without repeating the call.
    """
    base_url = base_url or os.environ.get("SETEC_BASE_URL")
    api_key = api_key if api_key is not None else os.environ.get("SETEC_API_KEY", "")
    model = model or os.environ.get("SETEC_MODEL")
    if not base_url or not model:
        raise RuntimeError(
            "Set SETEC_BASE_URL and SETEC_MODEL (and usually "
            "SETEC_API_KEY). See .env.example."
        )

    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        _endpoint(base_url), data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"LLM endpoint {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM endpoint unreachable: {exc.reason}") from exc

    data = json.loads(body)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected response shape: {body[:500]}") from exc
