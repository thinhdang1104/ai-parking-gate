"""Per-camera tracking state and dual-camera WebRTC session lifecycle."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from src.backend.domain.voting import get_vote_result


class CameraUnitState:
    """Display state, plate vote buffer, and recent face buffer for one camera."""

    def __init__(self, cam_id: int, default_port: int) -> None:
        self.cam_id = cam_id
        self.default_port = default_port
        self.device_index = default_port
        self.active = False
        self.mode: str | None = None
        self.latest_boxes: dict[str, list[dict[str, Any]]] = {"plates": [], "faces": []}
        self.current_plates: list[str] = []
        self.plate_in_view = False
        self.current_faces: list[float] = []
        self.ambiguous_frame = False
        self.observations: deque[Any] = deque()
        self.plate_crops: dict[str, tuple[float, str]] = {}
        self.last_sample_time = 0.0
        self.last_plate_seen: float | None = None
        self.recent_faces: deque[Any] = deque()

    def clear_display(self) -> None:
        """Reset transient frame overlay and badge display state."""
        self.latest_boxes = {"plates": [], "faces": []}
        self.current_plates = []
        self.plate_in_view = False
        self.current_faces = []
        self.ambiguous_frame = False

    def reset_tracking(self) -> None:
        """Reset plate voting history, sharp crops, and recent face candidates."""
        self.observations = deque()
        self.plate_crops = {}
        self.last_sample_time = 0.0
        self.last_plate_seen = None
        self.recent_faces = deque()

    def serialize_status(self) -> dict[str, Any]:
        """Serialize this camera's live status into `CameraUnitStatus` payload shape."""
        vote_info: dict[str, Any] | None = None
        vote_res = get_vote_result(self.observations)
        if vote_res is not None:
            vote_info = {
                "candidate": vote_res.plate_display,
                "vote_count": vote_res.vote_count,
                "sample_count": vote_res.sample_count,
                "vote_share": vote_res.vote_share,
            }
        return {
            "active": self.active,
            "mode": self.mode,
            "device_index": self.device_index,
            "current_plates": list(self.current_plates),
            "current_faces": list(self.current_faces),
            "ambiguous_frame": self.ambiguous_frame,
            "vote": vote_info,
        }


class CameraSessionManager:
    """Manages Cam 1 & Cam 2 independent activation and session lifecycle."""

    def __init__(self) -> None:
        self.cams: dict[int, CameraUnitState] = {
            1: CameraUnitState(1, 0),
            2: CameraUnitState(2, 1),
        }
        self.running: bool = False
        self.session_id: int = 0
        self.frame_count: int = 0
        self.camera_error: str | None = None

    def get_cam(self, cam_id: int) -> CameraUnitState:
        """Return CameraUnitState for `cam_id` (1 or 2) or raise ValueError."""
        if cam_id not in self.cams:
            raise ValueError("Camera ID phải là 1 hoặc 2.")
        return self.cams[cam_id]

    def is_dual_cam_mode_locked(self) -> bool:
        """Return True when both Cam 1 and Cam 2 are active."""
        return bool(self.cams[1].active and self.cams[2].active)

    def refresh_running_locked(self) -> bool:
        """Recompute `running` from individual camera active flags."""
        self.running = any(cam.active for cam in self.cams.values())
        return self.running

    def start_camera_locked(
        self,
        cam_id: int,
        on_first_start: Callable[[], None] | None = None,
        on_reconfigure: Callable[[], None] | None = None,
    ) -> str:
        """Activate a browser camera unit; caller must hold state lock."""
        cam = self.get_cam(cam_id)
        was_running = self.running
        if not was_running:
            self.session_id += 1
            self.frame_count = 0
            if on_first_start is not None:
                on_first_start()
        else:
            if on_reconfigure is not None:
                on_reconfigure()
            self.clear_all_observations_locked()

        cam.device_index = cam_id - 1
        cam.mode = "browser"
        cam.active = True
        cam.clear_display()
        cam.reset_tracking()
        self.camera_error = None
        self.refresh_running_locked()
        return cam.mode

    def deactivate_camera_locked(
        self,
        cam_id: int,
        error: str | None = None,
        on_all_stopped: Callable[[], None] | None = None,
    ) -> bool:
        """Deactivate a camera unit; caller must hold state lock."""
        if cam_id not in self.cams:
            return False
        cam = self.cams[cam_id]
        if not cam.active:
            return False

        cam.active = False
        cam.mode = None
        cam.clear_display()
        cam.reset_tracking()
        if error:
            self.camera_error = error
        self.refresh_running_locked()
        if not self.running:
            self.session_id += 1
            if on_all_stopped is not None:
                on_all_stopped()
        return True

    def clear_all_observations_locked(self) -> None:
        """Clear plate voting queues across all cameras."""
        for cam in self.cams.values():
            cam.observations.clear()
