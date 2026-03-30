#!/usr/bin/env python3
"""
Remote inference backend for Codey-v2.

Handles any OpenAI-compatible /v1/chat/completions API — OpenRouter,
UnlimitedClaude, or any other proxy.  Drop-in replacement for
inference_hybrid.ChatCompletionBackend.

The embed model (port 8082) always runs locally regardless of backend.

Backends:
    openrouter      — openrouter.ai  (OPENROUTER_API_KEY / OPENROUTER_MODEL)
    unlimitedclaude — unlimitedclaude.com  (UNLIMITEDCLAUDE_API_KEY / UNLIMITEDCLAUDE_MODEL)

Activation:
    export CODEY_BACKEND=openrouter        # or unlimitedclaude
    export OPENROUTER_API_KEY=sk-or-...
    export OPENROUTER_MODEL=qwen/qwen-2.5-coder-7b-instruct
"""

import json
import sys
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

from utils.logger import info, warning, error
from utils.config import MODEL_CONFIG, OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL


class OpenRouterBackend:
    """
    Generic remote inference backend — OpenAI-compatible /v1/chat/completions.

    Mirrors the interface of inference_hybrid.ChatCompletionBackend.
    Accepts explicit api_key/model/base_url so it can serve any backend,
    defaulting to OpenRouter config values when called without arguments.
    """

    def __init__(self, api_key: str = None, model: str = None,
                 base_url: str = None, name: str = "openrouter"):
        self._base_url   = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        self._api_key    = api_key if api_key is not None else OPENROUTER_API_KEY
        self._model      = model   if model   is not None else OPENROUTER_MODEL
        self._name       = name
        self._calls_made = 0

    def check_health(self) -> bool:
        """OpenRouter is always reachable if we have a key."""
        return bool(self._api_key)

    def is_server_running(self) -> bool:
        """For compatibility with loader checks — always True for remote API."""
        return bool(self._api_key)

    def infer(self, messages: list, max_tokens: int = 2048,
              stop: List[str] = None, stream: bool = False) -> Optional[tuple]:
        """
        Run inference via OpenRouter /v1/chat/completions.

        Returns:
            (text, tokens, tps) tuple or None on error
        """
        if not self._api_key:
            error("OPENROUTER_API_KEY is not set — cannot use OpenRouter backend")
            return None

        try:
            start = time.time()

            # Build stop list — filter to strings OpenRouter will accept
            # (some llama.cpp-specific tokens like <|im_end|> are fine to pass;
            # OpenRouter ignores any it doesn't understand)
            stop_tokens = list(MODEL_CONFIG.get("stop", []))
            if stop:
                stop_tokens.extend(s for s in stop if s not in stop_tokens)

            payload = {
                "model": self._model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": MODEL_CONFIG["temperature"],
                "top_p": MODEL_CONFIG["top_p"],
                "stop": stop_tokens,
                "stream": stream,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://github.com/codey-v2",
                "X-Title": "Codey-v2",
            }

            req = urllib.request.Request(
                f"{self._base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            if stream:
                return self._infer_streaming(req, start)
            else:
                return self._infer_blocking(req, start)

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            error(f"{self._name} HTTP {e.code}: {body[:200]}")
            return None
        except urllib.error.URLError as e:
            error(f"{self._name} connection failed: {e}")
            return None
        except Exception as e:
            error(f"{self._name} inference failed: {e}")
            return None

    def _infer_blocking(self, req, start: float) -> Optional[tuple]:
        """Non-streaming — waits for full response."""
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

        elapsed = time.time() - start
        self._calls_made += 1

        text = result["choices"][0]["message"]["content"]

        tokens = 0
        if "usage" in result:
            tokens = result["usage"].get("completion_tokens", 0)
        if not tokens:
            tokens = len(text.split())

        tps = round(tokens / elapsed, 1) if elapsed > 0 else 0.0
        info(f"{self._name} ({self._model}): {tokens} tokens in {elapsed:.1f}s ({tps:.1f} t/s)")
        return text.strip(), tokens, tps

    def _infer_streaming(self, req, start: float) -> Optional[tuple]:
        """
        SSE streaming — prints each token to stdout as it arrives.
        OpenRouter uses the same SSE format as llama-server / OpenAI.
        """
        full_text = []
        tokens = 0

        response = urllib.request.urlopen(req, timeout=120)
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\n\r")

                if line == "data: [DONE]":
                    break
                if not line or not line.startswith("data: "):
                    continue

                try:
                    chunk = json.loads(line[6:])
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            sys.stdout.write(content)
                            sys.stdout.flush()
                            full_text.append(content)
                        if choices[0].get("finish_reason"):
                            break
                    # OpenRouter sends usage in the final chunk when stream_options enabled;
                    # fall back to word count if absent
                    if "usage" in chunk:
                        tokens = chunk["usage"].get("completion_tokens", 0)
                except (json.JSONDecodeError, KeyError):
                    pass
        finally:
            try:
                response.close()
            except Exception:
                pass

        sys.stdout.write("\n\033[0m")
        sys.stdout.flush()

        elapsed = time.time() - start
        self._calls_made += 1

        text = "".join(full_text)
        if not tokens:
            tokens = len(text.split())
        tps = round(tokens / elapsed, 1) if elapsed > 0 else 0.0

        info(f"{self._name} stream ({self._model}): {tokens} tokens in {elapsed:.1f}s ({tps:.1f} t/s)")
        return text.strip(), tokens, tps

    @property
    def backend_name(self) -> str:
        return f"{self._name}:{self._model}"

    def get_stats(self) -> Dict[str, Any]:
        return {
            "active_backend": self._name,
            "model": self._model,
            "base_url": self._base_url,
            "calls_made": self._calls_made,
        }


# Singletons — one per backend type
_backends: dict = {}


def get_openrouter_backend() -> OpenRouterBackend:
    """Return the OpenRouter backend singleton (backward-compat helper)."""
    return get_remote_backend("openrouter")


def get_remote_backend(backend_name: str = None) -> OpenRouterBackend:
    """
    Return a backend singleton configured for the given backend name.
    Defaults to the active CODEY_BACKEND setting.
    """
    from utils.config import (
        CODEY_BACKEND,
        OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL,
        UNLIMITEDCLAUDE_API_KEY, UNLIMITEDCLAUDE_MODEL, UNLIMITEDCLAUDE_BASE_URL,
    )
    name = backend_name or CODEY_BACKEND

    if name not in _backends:
        if name == "unlimitedclaude":
            b = OpenRouterBackend(
                api_key=UNLIMITEDCLAUDE_API_KEY,
                model=UNLIMITEDCLAUDE_MODEL,
                base_url=UNLIMITEDCLAUDE_BASE_URL,
                name="unlimitedclaude",
            )
        else:  # openrouter (default)
            b = OpenRouterBackend(
                api_key=OPENROUTER_API_KEY,
                model=OPENROUTER_MODEL,
                base_url=OPENROUTER_BASE_URL,
                name="openrouter",
            )
        if b.check_health():
            info(f"{name} backend: {b._model}")
        else:
            warning(f"{name} backend: API key not set")
        _backends[name] = b

    return _backends[name]
