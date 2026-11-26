"""FastAPI HTTP routes, schemas, and response presenters."""

from __future__ import annotations

from src.backend.api.camera_routes import create_camera_router
from src.backend.api.management_routes import create_management_router
from src.backend.api.presenters import (
    format_direction_label,
    format_face_label,
    format_match_label,
    format_parking_status_label,
    format_recognition_time,
    format_record_row,
    format_vnd,
    present_overview,
    present_session_case,
)
from src.backend.api.schemas import BrowserDualFrameRequest, ResolveAlertRequest
from src.backend.api.static_routes import (
    NO_CACHE_HEADERS,
    create_static_router,
    mount_frontend_assets,
)

__all__ = [
    "BrowserDualFrameRequest",
    "NO_CACHE_HEADERS",
    "ResolveAlertRequest",
    "create_camera_router",
    "create_management_router",
    "create_static_router",
    "format_direction_label",
    "format_face_label",
    "format_match_label",
    "format_parking_status_label",
    "format_recognition_time",
    "format_record_row",
    "format_vnd",
    "mount_frontend_assets",
    "present_overview",
    "present_session_case",
]
