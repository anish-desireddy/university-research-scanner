"""FastAPI application for the local web interface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__
from app.backend.scan_manager import (
    ScanBusyError,
    ScanManager,
    ScanNotFoundError,
)
from app.config import default_scan_options

logger = logging.getLogger("urd.api")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class ScanRequest(BaseModel):
    url: str
    max_depth: Optional[int] = None
    max_pages: Optional[int] = None
    max_external_domains: Optional[int] = None
    request_delay: Optional[float] = None


class RetryRequest(BaseModel):
    force_refresh: bool = False


def create_app(config: Dict[str, Any], manager: Optional[ScanManager] = None) -> FastAPI:
    app = FastAPI(
        title="University Research Discovery",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )
    scan_manager = manager or ScanManager(config)
    app.state.config = config
    app.state.manager = scan_manager

    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.exception_handler(ScanBusyError)
    async def busy_handler(request: Any, exc: ScanBusyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ScanNotFoundError)
    async def not_found_handler(request: Any, exc: ScanNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request: Any, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Any, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected server error occurred. Check logs/app.log for details."
            },
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        index_path = FRONTEND_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=500, detail="Frontend files are missing.")
        return FileResponse(
            index_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        ollama = scan_manager.health()
        return {
            "status": "ok",
            "application": "University Research Discovery",
            "version": __version__,
            "ollama": ollama,
            "defaults": default_scan_options(config),
            "outputs_dir": config["output"]["directory"],
            "active_scan": scan_manager._active_scan,
        }

    @app.post("/api/scans", status_code=202)
    async def create_scan(payload: ScanRequest) -> Dict[str, Any]:
        logger.info("Received scan request for %s", payload.url)
        status = scan_manager.start_scan(
            payload.url,
            {
                "max_depth": payload.max_depth,
                "max_pages": payload.max_pages,
                "max_external_domains": payload.max_external_domains,
                "request_delay": payload.request_delay,
            },
        )
        return status

    @app.get("/api/scans")
    async def list_scans(limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
        return {"scans": scan_manager.list_scans(limit)}

    @app.get("/api/scans/{scan_id}")
    async def get_scan(scan_id: str) -> Dict[str, Any]:
        return scan_manager.get_status(scan_id)

    @app.get("/api/scans/{scan_id}/results")
    async def get_results(scan_id: str) -> Dict[str, Any]:
        return scan_manager.get_results(scan_id)

    @app.post("/api/scans/{scan_id}/retry-ai", status_code=202)
    async def retry_ai(scan_id: str, payload: Optional[RetryRequest] = None) -> Dict[str, Any]:
        logger.info("AI retry requested for scan %s", scan_id)
        return scan_manager.retry_ai(
            scan_id, force_refresh=bool(payload.force_refresh) if payload else False
        )

    @app.get("/api/scans/{scan_id}/download/{kind}")
    async def download(scan_id: str, kind: str) -> FileResponse:
        path = scan_manager.download_path(scan_id, kind)
        if kind == "json":
            filename = f"research_results_{scan_id}.json"
            media_type = "application/json"
        else:
            filename = f"research_report_{scan_id}.pdf"
            media_type = "application/pdf"
        return FileResponse(path, media_type=media_type, filename=filename)

    return app
