"""Static UI entrypoint and asset mounting for DATN2 frontend."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

NO_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
}

_PLACEHOLDER_HTML = (
    "<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
    "<title>DATN2</title></head>"
    "<body><h1>DATN2 frontend not built yet</h1></body></html>"
)


def _serve_index_response(frontend_dir: Path) -> Response:
    index_path = frontend_dir / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path), headers=NO_CACHE_HEADERS)
    return HTMLResponse(
        content=_PLACEHOLDER_HTML,
        status_code=200,
        headers=NO_CACHE_HEADERS,
    )


def create_static_router(frontend_dir: Path) -> APIRouter:
    """Build APIRouter serving `/` and `/ui` HTML entrypoint with no-cache headers."""
    router = APIRouter(tags=["UI"])

    @router.api_route("/", methods=["GET", "HEAD"])
    async def serve_index() -> Response:
        return _serve_index_response(frontend_dir)

    @router.api_route("/ui", methods=["GET", "HEAD"])
    async def serve_ui() -> Response:
        return _serve_index_response(frontend_dir)

    return router


def mount_frontend_assets(app: FastAPI, frontend_dir: Path) -> None:
    """Mount `/css` and `/js` static directories when present on disk."""
    for folder in ("css", "js"):
        asset_dir = frontend_dir / folder
        if asset_dir.is_dir():
            app.mount(
                f"/{folder}",
                StaticFiles(directory=str(asset_dir)),
                name=f"frontend_{folder}",
            )
