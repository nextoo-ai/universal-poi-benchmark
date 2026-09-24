from __future__ import annotations

from typing import Any, Protocol


class ReviewProvider(Protocol):
    """Future adapter boundary for LLM or human-assisted content review."""

    provider_name: str
    model_name: str | None

    def review(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return an object valid against contracts/llm-review-result.schema.json."""
        ...
