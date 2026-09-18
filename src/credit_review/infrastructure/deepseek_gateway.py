"""DeepSeek OpenAI-compatible gateway.

The API key is read at construction time and is never included in responses,
State, exceptions or repr output.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from credit_review.config.models import DeepSeekConfig


class DeepSeekGateway:
    def __init__(self, config: DeepSeekConfig | None = None, *, client: Any | None = None, client_factory: Callable[..., Any] | None = None) -> None:
        self.config = config or DeepSeekConfig.from_env(require_key=True)
        self.config.validate(require_key=True)
        self._client = client
        self._client_factory = client_factory

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("DeepSeek integration requires the optional 'openai' package") from exc
            factory = self._client_factory or OpenAI
            self._client = factory(api_key=self.config.api_key, base_url=self.config.base_url, timeout=self.config.timeout_seconds)
        return self._client

    def complete(self, messages: Sequence[Mapping[str, str]], *, temperature: float | None = None, max_tokens: int | None = None, response_format: dict[str, str] | None = None, **kwargs: Any) -> str:
        if not messages:
            raise ValueError("messages must not be empty")
        params: dict[str, Any] = {"model": self.config.model, "messages": [dict(message) for message in messages], "temperature": self.config.temperature if temperature is None else temperature, "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens, "stream": False}
        if response_format is not None:
            params["response_format"] = response_format
        # The review pipeline needs a concise final/JSON answer and must not
        # persist chain-of-thought. DeepSeek enables thinking by default; use
        # its OpenAI-compatible switch to disable it for this gateway.
        params["extra_body"] = {"thinking": {"type": "disabled"}}
        params.update(kwargs)
        try:
            response = self._get_client().chat.completions.create(**params)
        except Exception as exc:
            # Do not propagate provider exception text: SDKs may include
            # request metadata. Keep the original type for diagnostics only.
            raise RuntimeError(f"DeepSeek API request failed: {type(exc).__name__}") from None
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError) as exc:
            raise ValueError("DeepSeek response did not contain a message") from exc
        if not isinstance(content, str):
            raise ValueError("DeepSeek response content must be a string")
        return content

    def complete_json(self, messages: Sequence[Mapping[str, str]], **kwargs: Any) -> dict[str, Any]:
        content = self.complete(messages, response_format={"type": "json_object"}, **kwargs)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("DeepSeek JSON response could not be parsed") from exc
        if not isinstance(data, dict):
            raise ValueError("DeepSeek JSON response must be an object")
        return data

    def healthcheck(self) -> str:
        return self.complete([{"role": "user", "content": "仅回复 OK"}], max_tokens=4, temperature=0.0)
