"""Model access plus the verifiable development record.

Two providers are supported:

* ``minimax`` — MiniMax's Anthropic-compatible surface, ``POST {base}/anthropic/v1/messages``
  with an ``x-api-key`` header. This is the provider required by the task.
* ``deepseek`` — DeepSeek's OpenAI-compatible surface, ``POST {base}/chat/completions``
  with a bearer token.

Every call is appended to ``artifacts/records/llm-calls.jsonl`` with the request hash,
the exact prompt, the raw response and the timing, so the development record can be
checked against the code diff that the model produced.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sdd_context.config import Settings


class LlmError(RuntimeError):
    """Raised when the model call cannot be completed."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class LlmResponse:
    provider: str
    model: str
    text: str
    latency_ms: int
    prompt_sha256: str
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    recorded_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LlmClient:
    """Small, dependency-free HTTP client with an on-disk call record."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._records_dir = settings.artifacts_dir / "records"
        self._records_dir.mkdir(parents=True, exist_ok=True)
        self._calls_path = self._records_dir / "llm-calls.jsonl"

    # -- public API --------------------------------------------------------

    def complete(self, *, system: str, user: str, max_tokens: int = 8192) -> LlmResponse:
        provider = self._settings.llm_provider
        prompt_hash = _sha256(system + "\x00" + user)
        started = time.monotonic()
        try:
            if provider == "minimax":
                text, model, usage, request_id = self._call_minimax(system, user, max_tokens)
            elif provider == "deepseek":
                text, model, usage, request_id = self._call_deepseek(system, user, max_tokens)
            else:
                raise LlmError(f"unknown provider {provider!r}")
        except LlmError as error:
            self._record(
                {
                    "provider": provider,
                    "model": self._model_name(),
                    "outcome": "error",
                    "status": error.status,
                    "error": str(error),
                    "error_body": error.body[:4000],
                    "prompt_sha256": prompt_hash,
                    "prompt_chars": len(user),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            raise

        response = LlmResponse(
            provider=provider,
            model=model,
            text=text,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_sha256=prompt_hash,
            usage=usage,
            request_id=request_id,
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        self._record(
            {
                "provider": provider,
                "model": model,
                "outcome": "ok",
                "prompt_sha256": prompt_hash,
                "prompt_chars": len(user),
                "prompt": user,
                "system": system,
                "response": text,
                "usage": usage,
                "request_id": request_id,
                "latency_ms": response.latency_ms,
                "recorded_at": response.recorded_at,
            }
        )
        return response

    # -- providers ---------------------------------------------------------

    def _model_name(self) -> str:
        return (
            self._settings.minimax_model
            if self._settings.llm_provider == "minimax"
            else self._settings.deepseek_model
        )

    def _call_minimax(self, system: str, user: str, max_tokens: int) -> tuple[str, str, dict, str]:
        if not self._settings.minimax_api_key:
            raise LlmError("MINIMAX_API_KEY is not configured")
        model = self._settings.minimax_model
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        effort = self._settings.minimax_reasoning_effort
        if effort and effort != "none":
            # M3 models always think; the effort level bounds that thinking so the reply
            # still contains the answer. ``none`` is rejected by the API for these models.
            payload["reasoning"] = {"effort": effort}
        body = self._post(
            f"{self._settings.minimax_base_url.rstrip('/')}/anthropic/v1/messages",
            payload,
            headers={"x-api-key": self._settings.minimax_api_key, "anthropic-version": "2023-06-01"},
        )
        blocks = body.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
        usage = body.get("usage") or {}
        if not text.strip():
            thinking = (usage.get("output_tokens_details") or {}).get("thinking_tokens")
            raise LlmError(
                "model returned no text"
                + (f" (all {thinking} output tokens were spent thinking)" if thinking else ""),
                status=200,
                body=json.dumps({"usage": usage, "content": blocks}, ensure_ascii=False)[:2000],
            )
        return text, model, dict(usage), str(body.get("id", ""))

    def _call_deepseek(self, system: str, user: str, max_tokens: int) -> tuple[str, str, dict, str]:
        if not self._settings.deepseek_api_key:
            raise LlmError("DEEPSEEK_API_KEY is not configured")
        model = self._settings.deepseek_model
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        body = self._post(
            f"{self._settings.deepseek_base_url.rstrip('/')}/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self._settings.deepseek_api_key}"},
        )
        choices = body.get("choices") or []
        text = ""
        if choices:
            message = choices[0].get("message") or {}
            text = message.get("content") or ""
        usage = body.get("usage") or {}
        return text, model, dict(usage), str(body.get("id", ""))

    # -- transport ---------------------------------------------------------

    def _post(self, url: str, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "sdd-context/1.0", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._settings.request_timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise LlmError(f"model request failed with HTTP {error.code}", status=error.code, body=detail) from error
        except urllib.error.URLError as error:
            raise LlmError(f"model request failed: {error.reason}") from error
        try:
            return json.loads(raw)
        except ValueError as error:
            raise LlmError("model returned a non-JSON response", body=raw[:2000]) from error

    # -- record ------------------------------------------------------------

    def _record(self, entry: dict[str, Any]) -> None:
        entry.setdefault("logged_at", datetime.now(UTC).isoformat(timespec="seconds"))
        with self._calls_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def calls_path(self) -> Path:
        return self._calls_path
