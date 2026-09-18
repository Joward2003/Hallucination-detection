"""Thin API adapter boundary.

The application service is usable without a web framework. ``create_fastapi_app``
is deliberately lazy so importing the package does not force an optional HTTP
dependency into the deterministic test/runtime environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from credit_review.knowledge_base import BuildManager

from .service import ReviewManager


class ReviewAPI:
    def __init__(self, manager: ReviewManager | None = None, build_manager: BuildManager | None = None) -> None:
        self.manager = manager or ReviewManager()
        self.build_manager = build_manager

    def create_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.manager.create(payload)

    def get_review(self, review_id: str) -> dict[str, Any]:
        return self.manager.get(review_id)

    def cancel_review(self, review_id: str) -> dict[str, Any]:
        return self.manager.cancel(review_id)

    def human_tasks(self) -> list[dict[str, Any]]:
        return self.manager.human_tasks()

    def submit_human_decision(self, review_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        return self.manager.submit_human_decision(review_id, decision)

    def create_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.build_manager is None:
            raise RuntimeError("knowledge-base build service is not configured")
        return self.build_manager.create(payload)

    def get_build(self, build_id: str) -> dict[str, Any]:
        if self.build_manager is None:
            raise RuntimeError("knowledge-base build service is not configured")
        return self.build_manager.get(build_id)

    def cancel_build(self, build_id: str) -> dict[str, Any]:
        if self.build_manager is None:
            raise RuntimeError("knowledge-base build service is not configured")
        return self.build_manager.cancel(build_id)

    def list_kb_versions(self, kb_id: str) -> list[str]:
        if self.build_manager is None:
            raise RuntimeError("knowledge-base build service is not configured")
        return self.build_manager.list_versions(kb_id)

    def search_kb(self, kb_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.build_manager is None:
            raise RuntimeError("knowledge-base build service is not configured")
        version = payload.get("kb_version")
        scope = payload.get("source_scope")
        query = payload.get("query") if isinstance(payload.get("query"), dict) else payload
        hits = self.build_manager.search(kb_id, query, version=version, scope=scope)
        return {"kb_id": kb_id, "kb_version": version or self.build_manager.repository.active_version(kb_id), "hits": hits}


def create_fastapi_app(manager: ReviewManager | None = None, build_manager: BuildManager | None = None):
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ModuleNotFoundError as exc:  # optional dependency, with actionable error
        raise RuntimeError("FastAPI adapter requires the optional 'fastapi' dependency") from exc
    api = ReviewAPI(manager, build_manager)
    app = FastAPI(title="Credit Review")
    frontend_dir = Path(__file__).resolve().parents[3] / "frontend"

    @app.post("/v1/reviews")
    def create_review(payload: dict[str, Any]):
        return api.create_review(payload)

    @app.get("/v1/reviews/{review_id}")
    def get_review(review_id: str):
        return api.get_review(review_id)

    @app.post("/v1/reviews/{review_id}/cancel")
    def cancel_review(review_id: str):
        return api.cancel_review(review_id)

    @app.get("/v1/human-tasks")
    def human_tasks():
        return api.human_tasks()

    @app.post("/v1/human-tasks/{review_id}/decision")
    def submit_human_decision(review_id: str, payload: dict[str, Any]):
        return api.submit_human_decision(review_id, payload)

    @app.post("/v1/knowledge-bases/builds")
    def create_build(payload: dict[str, Any]):
        return api.create_build(payload)

    @app.get("/v1/knowledge-bases/builds/{build_id}")
    def get_build(build_id: str):
        return api.get_build(build_id)

    @app.post("/v1/knowledge-bases/builds/{build_id}/cancel")
    def cancel_build(build_id: str):
        return api.cancel_build(build_id)

    @app.get("/v1/knowledge-bases/{kb_id}/versions")
    def list_kb_versions(kb_id: str):
        return {"kb_id": kb_id, "versions": api.list_kb_versions(kb_id)}

    @app.post("/v1/knowledge-bases/{kb_id}/search")
    def search_kb(kb_id: str, payload: dict[str, Any]):
        return api.search_kb(kb_id, payload)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    # Serve the browser client from the same origin so local use does not need
    # a separate CORS configuration. API routes are registered before this
    # fallback, so they keep their existing contracts.
    if frontend_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dir), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def frontend_index():
            return FileResponse(frontend_dir / "index.html")

        @app.get("/{frontend_path:path}", include_in_schema=False)
        def frontend_route(frontend_path: str):
            candidate = (frontend_dir / frontend_path).resolve()
            if candidate.is_file() and frontend_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(frontend_dir / "index.html")

    return app
