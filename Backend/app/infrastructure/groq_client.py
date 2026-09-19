"""Groq API client wrapper with model fallback and caching."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("curator.groq")

_groq_model_cache: dict[str, tuple[str, float]] = {}


def _get_model_cache() -> dict[str, tuple[str, float]]:
    try:
        import app.engine as eng
        if hasattr(eng, "_groq_model_cache") and isinstance(eng._groq_model_cache, dict):
            return eng._groq_model_cache
    except (ImportError, AttributeError):
        pass
    return _groq_model_cache


def _api_key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()


def _requested_model() -> str:
    return os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")


def _fallback_model() -> str:
    return os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")


def groq_available() -> bool:
    """Return True if a Groq API key is configured."""
    return bool(_api_key())


def resolve_model() -> str:
    """Return the best available model (cached fallback aware)."""
    requested = _requested_model()
    cached = _get_model_cache().get(requested)
    if cached and cached[1] > time.time():
        return cached[0]
    return requested


async def chat_completion(
    *,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int = 2300,
    json_mode: bool = True,
    timeout_seconds: float = 9.0,
) -> dict[str, Any]:
    """Send a chat completion request to Groq with automatic model fallback.

    Returns the parsed JSON content from the first choice.
    Raises on network/parsing errors.
    """
    key = _api_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    requested = _requested_model()
    fallback = _fallback_model()
    model = resolve_model()

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=3.0)) as client:
        for attempt in range(2):
            payload: dict[str, Any] = {
                "model": model,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            if model.startswith("openai/gpt-oss-"):
                payload["reasoning_effort"] = "low"

            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )

            if response.status_code in {400, 404} and attempt == 0 and fallback and model != fallback:
                error_code = response.json().get("error", {}).get("code")
                if error_code in {"model_not_found", "model_decommissioned"}:
                    model = fallback
                    continue

            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content) if json_mode else {"text": content}

            if model != requested:
                _get_model_cache()[requested] = (model, time.time() + 600)

            return {
                "data": parsed,
                "model_used": model,
                "model_fallback": model != requested,
            }

    # Should not be reached, but satisfy type checker
    raise RuntimeError("Groq completion loop exited without result")
