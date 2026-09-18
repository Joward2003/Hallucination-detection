from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class LLMGateway(Protocol):
    def complete(self, messages: Sequence[Mapping[str, str]], **kwargs: Any) -> str: ...

    def complete_json(self, messages: Sequence[Mapping[str, str]], **kwargs: Any) -> dict[str, Any]: ...
