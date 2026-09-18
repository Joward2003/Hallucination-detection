"""Optional ASGI entry point for the API and bundled browser workspace."""

from __future__ import annotations

import os

from .app import create_fastapi_app
from .service import ReviewManager


def _manager() -> ReviewManager:
    backend = os.getenv("CREDIT_REVIEW_AGENT_BACKEND", "deterministic").strip().lower()
    if backend == "deepseek":
        from credit_review.graph.builder import run_review_with_deepseek

        return ReviewManager(runner=run_review_with_deepseek)
    if backend != "deterministic":
        raise ValueError("CREDIT_REVIEW_AGENT_BACKEND must be 'deterministic' or 'deepseek'")
    return ReviewManager()


app = create_fastapi_app(manager=_manager())


def run() -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - optional runtime
        raise RuntimeError("Install the API extra with: python -m pip install -e '.[api]'") from exc
    uvicorn.run("credit_review.api.server:app", host="127.0.0.1", port=8000, reload=False)
