"""FastAPI routes for dual-camera control, frame ingestion, latch, and alerts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.backend.api.schemas import BrowserDualFrameRequest, ResolveAlertRequest
from src.backend.services.gate_service import GateService


def create_camera_router(gate_service: GateService) -> APIRouter:
    """Build APIRouter for `/api/camera/*` endpoints using injected GateService."""
    router = APIRouter(tags=["Camera & Gate"])

    @router.get("/api/camera/status")
    def get_camera_status() -> dict[str, Any]:
        return gate_service.get_status_payload()

    @router.post("/api/camera/{cam_id}/start")
    def api_start_single_camera(cam_id: int) -> dict[str, Any]:
        if cam_id not in (1, 2):
            raise HTTPException(
                status_code=404,
                detail="Camera ID phải là 1 hoặc 2.",
            )
        try:
            mode = gate_service.start_camera(cam_id)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        return {
            "status": "started",
            "cam_id": cam_id,
            "mode": mode,
            "device_index": gate_service.sessions.cams[cam_id].device_index,
        }

    @router.post("/api/camera/{cam_id}/stop")
    def api_stop_single_camera(cam_id: int) -> dict[str, Any]:
        if cam_id not in (1, 2):
            raise HTTPException(
                status_code=404,
                detail="Camera ID phải là 1 hoặc 2.",
            )
        gate_service.stop_camera(cam_id)
        return {"status": "stopped", "cam_id": cam_id}

    @router.post("/api/camera/stop")
    def api_stop_cameras() -> dict[str, Any]:
        gate_service.stop_cameras()
        return {"status": "stopped"}

    @router.post("/api/camera/browser-frame")
    def api_browser_frame(req: BrowserDualFrameRequest) -> dict[str, Any]:
        return gate_service.ingest_browser_frames(req.cam1_image, req.cam2_image)

    @router.post("/api/camera/cancel-latch")
    def api_cancel_latch() -> dict[str, Any]:
        return gate_service.cancel_latch()

    @router.post("/api/camera/resolve-alert")
    def api_resolve_alert(req: ResolveAlertRequest) -> dict[str, Any]:
        return gate_service.resolve_security_alert(req.action == "approve")

    return router
