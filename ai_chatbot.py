"""Gemini-powered teaching coach and quiz helper.

Only the explicit topic/question and bounded recent chat turns are sent to
Gemini. Callers should remind users not to include identifiable student data.
The API key is read from the server environment and is never returned/logged.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_INPUT_CHARS = 6000
MAX_HISTORY_TURNS = 8
MAX_OUTPUT_TOKENS = 1400

_SYSTEM_INSTRUCTIONS = {
    "teach": (
        "You are ClassPulse's teaching coach. Help educators plan inclusive, practical lessons. "
        "Give concrete steps, checks for understanding, and adaptations when useful. Keep advice "
        "non-punitive and age-appropriate. Do not infer anything about individual students."
    ),
    "quiz": (
        "You are ClassPulse's quiz creator. Create a clear student-facing quiz from the requested "
        "topic and grade/level. Include a reasonable mix of question types, then provide a separate "
        "answer key with brief explanations. Avoid personal data and stigmatizing content."
    ),
}


class ChatbotError(RuntimeError):
    """A safe, user-facing chatbot configuration or request error."""


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ChatbotError("Gemini is not configured. Add GEMINI_API_KEY in Streamlit Cloud Secrets or your private local environment.")
    return key


def _history_contents(history: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    if not isinstance(history, list):
        return contents
    for item in history[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text")
        if role not in {"user", "model"} or not isinstance(text, str):
            continue
        text = text.strip()[:MAX_INPUT_CHARS]
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    return contents


def respond(mode: str, prompt: str, history: list[dict[str, Any]] | None = None) -> str:
    """Generate a teaching tip or quiz through Gemini, returning plain text only."""
    if mode not in _SYSTEM_INSTRUCTIONS:
        raise ChatbotError("Choose teaching advice or quiz generation.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ChatbotError("Enter a topic or question first.")
    user_text = prompt.strip()[:MAX_INPUT_CHARS]
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if not model.startswith("gemini-") or any(ch in model for ch in "?/\\#"):
        model = DEFAULT_MODEL

    contents = _history_contents(history)
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTIONS[mode]}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.45 if mode == "teach" else 0.25,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }
    request = urllib.request.Request(
        f"{API_BASE}/{model}:generateContent",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": _api_key(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read(512_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not return raw provider body (it can echo request details).
        if exc.code in {401, 403}:
            raise ChatbotError("Gemini rejected the configured key or API access. Check GEMINI_API_KEY and model availability.") from None
        if exc.code == 429:
            raise ChatbotError("Gemini rate limit reached. Wait a little and try again.") from None
        raise ChatbotError(f"Gemini could not complete the request (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise ChatbotError("Gemini could not be reached. Check the connection and try again.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ChatbotError("Gemini returned an unreadable response. Try again.") from None

    try:
        candidates = result.get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        answer = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str)).strip()
    except (AttributeError, IndexError, KeyError, TypeError):
        answer = ""
    if not answer:
        raise ChatbotError("Gemini did not return a text answer. Try rephrasing the request.")
    return answer[:12_000]
