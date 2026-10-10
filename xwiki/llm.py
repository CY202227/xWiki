"""Unified LLM client wrapper used by service modules."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional
import json
import re
from types import SimpleNamespace

from pydantic import BaseModel

from .config import XWikiConfig


class _NoCredentialsError(RuntimeError):
    pass


class XWikiLLM:
    """Thin wrapper with retry and deterministic structured parsing output."""

    def __init__(self, config: XWikiConfig) -> None:
        self._config = config
        self._client = None

    @property
    def has_credentials(self) -> bool:
        return bool(self._config.llm_api_key.strip())

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.has_credentials:
            raise _NoCredentialsError("No LLM credentials configured.")
        from openai import OpenAI

        self._client = OpenAI(
            api_key=self._config.llm_api_key,
            base_url=self._config.llm_base_url or None,
            timeout=self._config.llm_timeout,
            max_retries=0,
        )
        return self._client

    def _call_with_retries(self, fn: Callable[[], Any]) -> Any:
        attempts = max(1, self._config.llm_max_retries)
        last_error: Exception | None = None
        delay = 0.5
        for attempt in range(attempts):
            try:
                return fn()
            except (
                Exception
            ) as error:  # pragma: no cover - passthrough for transport errors
                last_error = error
                status = getattr(error, "status_code", None)
                if isinstance(error, (ValueError, TypeError)) or (status is not None and status < 500 and status not in (408, 409, 429)):
                    raise
                if attempt == attempts - 1:
                    break
                import time

                time.sleep(delay)
                delay = min(delay * 2, 8)
        if last_error is None:
            raise RuntimeError("LLM request failed.")
        raise last_error

    def structured(
        self,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
    ):
        if not self.has_credentials:
            raise _NoCredentialsError("No LLM credentials configured.")
        client = self._ensure_client()
        if self._config.llm_structured_mode == "json":
            return self._structured_text(client, messages, response_model)
        try:
            return self._call_with_retries(
                lambda: client.beta.chat.completions.parse(
                    model=self._config.llm_model,
                    messages=messages,
                    response_format=response_model,
                    max_tokens=self._config.llm_max_output_tokens,
                )
            )
        except Exception as error:
            if getattr(error, "status_code", None) not in (400, 422) or not any(term in str(error).lower() for term in ("response_format", "json_schema", "structured")):
                raise
        # Some compatible endpoints support text generation but not JSON Schema.
        # Validate locally rather than trusting the model's JSON formatting.
        return self._structured_text(client, messages, response_model)

    def _structured_text(self, client, messages, response_model):
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        instruction = "Return only one JSON object matching this schema: " + schema
        fallback = [dict(message) for message in messages]
        if fallback and fallback[0]["role"] == "system":
            fallback[0]["content"] = fallback[0]["content"] + "\n" + instruction
        else:
            fallback.insert(0, {"role": "system", "content": instruction})
        response = self._call_with_retries(lambda: client.chat.completions.create(model=self._config.llm_model, messages=fallback, max_tokens=self._config.llm_max_output_tokens))
        text = response.choices[0].message.content or ""
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        parsed = response_model.model_validate_json(text)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))], usage=getattr(response, "usage", None))

    def complete(self, messages: list[dict[str, Any]]) -> str:
        if not self.has_credentials:
            raise _NoCredentialsError("No LLM credentials configured.")
        client = self._ensure_client()
        response = self._call_with_retries(
            lambda: client.chat.completions.create(
                model=self._config.llm_model,
                messages=messages,
                max_tokens=self._config.llm_max_output_tokens,
            )
        )
        return response.choices[0].message.content or ""

    @classmethod
    def format_messages(
        cls,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Iterable[str]] = None,
    ) -> list[dict[str, str]]:
        parts = [system_prompt, user_prompt]
        if context:
            parts.extend(context)
        return [
            {"role": "system", "content": parts[0]},
            {"role": "user", "content": "\n\n".join(parts[1:])},
        ]
