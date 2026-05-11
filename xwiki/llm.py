"""Unified LLM client wrapper used by service modules."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

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
        )
        return self._client

    def _call_with_retries(self, fn: Callable[[], Any]) -> Any:
        attempts = max(1, self._config.llm_max_retries)
        last_error: Exception | None = None
        delay = 0.5
        for _ in range(attempts):
            try:
                return fn()
            except (
                Exception
            ) as error:  # pragma: no cover - passthrough for transport errors
                last_error = error
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
        return self._call_with_retries(
            lambda: client.beta.chat.completions.parse(
                model=self._config.llm_model,
                messages=messages,
                response_format=response_model,
            )
        )

    def complete(self, messages: list[dict[str, Any]]) -> str:
        if not self.has_credentials:
            raise _NoCredentialsError("No LLM credentials configured.")
        client = self._ensure_client()
        response = self._call_with_retries(
            lambda: client.chat.completions.create(
                model=self._config.llm_model,
                messages=messages,
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
