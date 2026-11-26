"""FastAPI application factory, DI container, middleware, and uvicorn entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import os
import sys
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

from src.backend.ai.face_service import FaceService
from src.backend.ai.plate_detector import PlateDetector
from src.backend.api import (
    NO_CACHE_HEADERS,
    create_camera_router,
    create_management_router,
    create_static_router,
    mount_frontend_assets,
)
from src.backend.config import Settings, load_settings
from src.backend.observability.logging_config import configure_logging, request_id_context
from src.backend.observability.metrics import MetricsRegistry
from src.backend.services.gate_service import GateService
from src.backend.services.management_service import ManagementService
from src.backend.storage.mysql_client import MySQLClient
from src.backend.storage.repository import ParkingRepository
from src.backend.storage.warm_mirror import WarmDatabaseMirror

APP_VERSION = "2.0.0"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContainer:
    """Explicit dependency container for DATN2 backend services and adapters."""

    settings: Settings
    metrics: MetricsRegistry
    mysql_client: MySQLClient
    repository: ParkingRepository
    warm_mirror: WarmDatabaseMirror
    management_service: ManagementService
    plate_detector: PlateDetector
    gate_service: GateService


def build_container(
    *,
    settings: Settings | None = None,
    mysql_client: MySQLClient | None = None,
    repository: ParkingRepository | None = None,
    warm_mirror: WarmDatabaseMirror | None = None,
    management_service: ManagementService | None = None,
    plate_detector: PlateDetector | None = None,
    face_service: FaceService | None = None,
    gate_service: GateService | None = None,
    metrics: MetricsRegistry | None = None,
) -> AppContainer:
    """Assemble the dependency graph cleanly without performing I/O at import time."""
    cfg = settings if settings is not None else load_settings()
    resolved_metrics = metrics if metrics is not None else MetricsRegistry()
    resolved_client = (
        mysql_client if mysql_client is not None else MySQLClient(settings=cfg)
    )
    resolved_repo = (
        repository
        if repository is not None
        else ParkingRepository(client=resolved_client, settings=cfg)
    )
    resolved_mirror = (
        warm_mirror
        if warm_mirror is not None
        else WarmDatabaseMirror(
            image_rows_limit=cfg.warm_mirror_max_image_records,
            fee_vnd=cfg.parking_fee_vnd,
            match_threshold=cfg.face_match_threshold,
            embedding_size=cfg.embedding_size,
        )
    )
    if management_service is not None:
        resolved_mgmt = management_service
    elif gate_service is not None:
        resolved_mgmt = gate_service.management_service
    else:
        resolved_mgmt = ManagementService(
            repository=resolved_repo,
            warm_mirror=resolved_mirror,
            settings=cfg,
            metrics=resolved_metrics,
        )

    if gate_service is not None:
        resolved_gate = gate_service
        resolved_detector = gate_service.plate_detector
    else:
        resolved_detector = (
            plate_detector
            if plate_detector is not None
            else PlateDetector(settings=cfg)
        )
        resolved_gate = GateService(
            management_service=resolved_mgmt,
            settings=cfg,
            plate_detector=resolved_detector,
            face_service=face_service,
            metrics=resolved_metrics,
        )

    return AppContainer(
        settings=cfg,
        metrics=resolved_metrics,
        mysql_client=resolved_client,
        repository=resolved_repo,
        warm_mirror=resolved_mgmt.warm_mirror,
        management_service=resolved_mgmt,
        plate_detector=resolved_detector,
        gate_service=resolved_gate,
    )


def create_app(
    *,
    settings: Settings | None = None,
    mysql_client: MySQLClient | None = None,
    repository: ParkingRepository | None = None,
    warm_mirror: WarmDatabaseMirror | None = None,
    management_service: ManagementService | None = None,
    plate_detector: PlateDetector | None = None,
    face_service: FaceService | None = None,
    gate_service: GateService | None = None,
    metrics: MetricsRegistry | None = None,
    enable_lifespan_startup: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application with DI and observability middleware."""
    container = build_container(
        settings=settings,
        mysql_client=mysql_client,
        repository=repository,
        warm_mirror=warm_mirror,
        management_service=management_service,
        plate_detector=plate_detector,
        face_service=face_service,
        gate_service=gate_service,
        metrics=metrics,
    )
    configure_logging(level=container.settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if enable_lifespan_startup:
            container.gate_service.startup()
        try:
            yield
        finally:
            container.gate_service.shutdown()

    application = FastAPI(
        title="DATN2 School Parking Gate AI API",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    application.add_middleware(GZipMiddleware, minimum_size=1024)

    @application.middleware("http")
    async def request_observability_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        container.metrics.inc("http_requests")
        with request_id_context(req_id):
            try:
                response = await call_next(request)
            except Exception:
                container.metrics.inc_error("http_request")
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                container.metrics.record_latency("http_request", elapsed_ms)
                raise

            elapsed_ms = (time.perf_counter() - start) * 1000.0
            container.metrics.record_latency("http_request", elapsed_ms)
            logger.debug(
                "http_request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round(elapsed_ms, 2),
                    }
                },
            )

        response.headers["X-Request-ID"] = req_id
        if request.url.path.startswith(("/css/", "/js/")):
            for key, value in NO_CACHE_HEADERS.items():
                response.headers.setdefault(key, value)
        return response

    application.include_router(create_camera_router(container.gate_service))
    application.include_router(
        create_management_router(
            container.management_service,
            container.gate_service,
            container.metrics,
            app_version=APP_VERSION,
        )
    )
    application.include_router(create_static_router(container.settings.frontend_dir))
    mount_frontend_assets(application, container.settings.frontend_dir)

    application.state.container = container
    return application


app = create_app()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    logger.info("Starting DATN2 server at http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port)
