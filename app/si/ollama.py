"""The local SI runtime (Ollama on 127.0.0.1). Only this backend talks to it.

Every call asks for JSON that fits a schema, at temperature 0 with a fixed seed,
so the same input gives the same output and every answer can be checked by code.
"""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger(__name__)
OPTIONS = {"temperature": 0, "seed": 7, "num_ctx": 8192}


class SIError(Exception):
    pass


async def installed_models(http: httpx.AsyncClient, url: str) -> list[str] | None:
    """Model names Ollama has pulled, or None if Ollama is unreachable."""
    try:
        resp = await http.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def is_installed(model: str, installed: list[str]) -> bool:
    return model in installed or f"{model}:latest" in installed


async def warm_up(http: httpx.AsyncClient, url: str, model: str, keep_alive: str, timeout: float = 300) -> float:
    """Load the model into memory (and keep it there) with a tiny call. Returns the seconds it took."""
    import time
    start = time.time()
    try:
        resp = await http.post(f"{url}/api/chat", timeout=httpx.Timeout(timeout, connect=5), json={
            "model": model, "stream": False, "keep_alive": keep_alive, "options": {"num_predict": 1, "num_ctx": 8192},
            "messages": [{"role": "user", "content": "Hi"}]})
    except httpx.HTTPError as e:
        raise SIError(f"could not reach Ollama: {e or type(e).__name__}") from None
    if resp.status_code != 200:
        raise SIError(f"Ollama error {resp.status_code}: {resp.text[:200]}")
    return round(time.time() - start, 1)


async def chat_json_stream(http: httpx.AsyncClient, url: str, model: str, system: str, user: str, schema: dict,
                           timeout: float, options: dict | None = None, keep_alive: str | None = None):
    """Like chat_json, but yields ("chunk", text so far) as the model writes, then ("done", parsed JSON).

    If the streamed text isn't valid JSON, it falls back to one ordinary chat_json call.
    """
    payload = {"model": model, "stream": True, "format": schema, "options": {**OPTIONS, **(options or {})},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if keep_alive:
        payload["keep_alive"] = keep_alive
    text = ""
    try:
        async with http.stream("POST", f"{url}/api/chat", json=payload, timeout=httpx.Timeout(timeout, connect=5)) as resp:
            if resp.status_code != 200:
                raise SIError(f"Ollama error {resp.status_code}: {(await resp.aread())[:200].decode(errors='replace')}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("error"):
                    raise SIError(f"Ollama error: {str(msg['error'])[:200]}")
                piece = (msg.get("message") or {}).get("content") or ""
                if piece:
                    text += piece
                    yield "chunk", text
    except httpx.HTTPError as e:
        raise SIError(f"could not reach Ollama: {e or type(e).__name__}") from None
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except ValueError:
        log.warning("%s streamed invalid JSON; asking once more without streaming", model)
        data = await chat_json(http, url, model, system, user, schema, timeout, options, keep_alive)
    yield "done", data


async def chat_json(http: httpx.AsyncClient, url: str, model: str, system: str, user: str, schema: dict,
                    timeout: float, options: dict | None = None, keep_alive: str | None = None) -> dict:
    """One structured-output call. Retries once if the model returns invalid JSON."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(2):
        payload = {"model": model, "stream": False, "format": schema,
                   "options": {**OPTIONS, **(options or {})}, "messages": messages}
        if keep_alive:
            payload["keep_alive"] = keep_alive
        try:
            resp = await http.post(f"{url}/api/chat", json=payload, timeout=httpx.Timeout(timeout, connect=5))
        except httpx.HTTPError as e:
            raise SIError(f"could not reach Ollama: {e or type(e).__name__}") from None
        if resp.status_code != 200:
            raise SIError(f"Ollama error {resp.status_code}: {resp.text[:200]}")
        content = resp.json().get("message", {}).get("content", "")
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            raise ValueError("not a JSON object")
        except ValueError as e:
            log.warning("%s returned invalid JSON (attempt %d): %s", model, attempt + 1, e)
            messages = messages + [{"role": "assistant", "content": content[:2000]},
                                   {"role": "user", "content": "Return valid JSON only."}]
    raise SIError("the model returned invalid JSON twice")
