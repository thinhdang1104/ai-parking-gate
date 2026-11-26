"""FastAPI routes for management overview, session lookup, DB reconnect, and observability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.backend.observability.metrics import MetricsRegistry
from src.backend.services.gate_service import GateService
from src.backend.services.management_service import ManagementService
from src.backend.storage.exceptions import (
    DatabaseConfigurationError,
    DatabaseOperationError,
)

_METRIC_COUNTER_KEYS: tuple[str, ...] = (
    "frames_received",
    "frames_processed",
    "frames_skipped_busy",
    "frames_deduplicated",
    "plates_detected",
    "faces_detected",
    "latches_started",
    "latches_committed",
    "latches_cancelled",
    "latches_timed_out",
    "security_alerts_triggered",
    "security_alerts_approved",
    "security_alerts_rejected",
    "db_commits_succeeded",
    "db_commits_failed",
)


def create_management_router(
    management_service: ManagementService,
    gate_service: GateService,
    metrics: MetricsRegistry,
    *,
    app_version: str = "2.0.0",
) -> APIRouter:
    """Build APIRouter for `/api/management/*`, `/api/health`, and `/api/metrics`."""
    router = APIRouter()

    @router.get("/api/management/overview", tags=["Management"])
    def get_management_overview(
        q: str = "",
        status: str = "all",
        limit: int | None = None,
        page: int = 1,
        page_size: int = 10,
        include_records: bool = True,
        include_revenue: bool | None = None,
        sort: str = "",
    ) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit), 1000)) if limit is not None else None
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 200))
        safe_sort = sort if sort in ("mismatch_first", "matched_first") else ""

        db_ready, _, _ = management_service.get_status_snapshot()
        overview: dict[str, Any] | None = None
        if db_ready:
            try:
                overview = management_service.get_cached_overview(
                    q,
                    status,
                    limit=safe_limit,
                    page=safe_page,
                    page_size=safe_page_size,
                    include_records=include_records,
                    include_revenue=include_revenue,
                    sort_by=safe_sort,
                )
            except (DatabaseConfigurationError, DatabaseOperationError) as err:
                management_service.set_db_status(False, str(err))

        db_ready, db_error, version = management_service.get_status_snapshot()
        return {
            "database_ready": db_ready,
            "database_error": db_error,
            "stats": overview["stats"] if overview else None,
            "revenue": overview["revenue"] if overview else None,
            "matched": overview["matched"] if overview else 0,
            "page": overview.get("page", safe_page) if overview else safe_page,
            "records": overview["records"] if overview else [],
            "records_version": version,
        }

    @router.get("/api/management/session-case/{record_id}", tags=["Management"])
    def get_parking_session_case(record_id: int) -> dict[str, Any]:
        try:
            case_data = management_service.get_cached_session_case(record_id)
        except (DatabaseConfigurationError, DatabaseOperationError) as err:
            management_service.set_db_status(False, str(err))
            raise HTTPException(status_code=503, detail=str(err)) from err

        if case_data is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi.")
        management_service.set_db_status(True, None)
        return case_data

    @router.post("/api/management/reconnect", tags=["Management"])
    def api_reconnect_database() -> dict[str, Any]:
        try:
            management_service.connect_database()
        except (DatabaseConfigurationError, DatabaseOperationError) as err:
            raise HTTPException(status_code=503, detail=str(err)) from err
        return {"status": "ok"}

    @router.get("/api/health", tags=["Observability"])
    def get_health() -> dict[str, Any]:
        snap = metrics.snapshot()
        db_ready, _, _ = management_service.get_status_snapshot()
        models_ready = bool(gate_service.models_ready)
        face_encoder_ready = bool(
            gate_service.face_service is not None and gate_service.face_service.can_embed
        )
        warm_mirror_ready = bool(management_service.warm_mirror.ready)
        status = "ok" if (db_ready and models_ready) else "degraded"
        return {
            "status": status,
            "database_ready": db_ready,
            "models_ready": models_ready,
            "face_encoder_ready": face_encoder_ready,
            "warm_mirror_ready": warm_mirror_ready,
            "uptime_seconds": snap["uptime_seconds"],
            "version": app_version,
        }

    @router.get("/api/metrics", tags=["Observability"])
    def get_metrics() -> dict[str, Any]:
        snap = metrics.snapshot()
        counters = snap["counters"]
        _, _, records_version = management_service.get_status_snapshot()
        payload: dict[str, Any] = {
            key: int(counters.get(key, 0)) for key in _METRIC_COUNTER_KEYS
        }
        payload["records_version"] = records_version
        payload["warm_mirror_count"] = management_service.warm_mirror.record_count
        payload["latencies"] = snap["latencies"]
        payload["errors"] = snap["errors"]
        return payload

    return router
