"""Two-Phase Latch coordinator for symmetric dual-camera plate + face capture."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Any

from src.backend.config import Settings, load_settings
from src.backend.domain.face_math import face_candidate_rank
from src.backend.domain.models import LatchState, VoteResult
from src.backend.domain.plate_normalizer import clean_plate_key

FaceCandidate = tuple[float, float, Any, tuple[int, int, int, int], float]


class LatchCoordinator:
    """Manages Two-Phase Latch transitions, pre-latch lookback, and sharpness tiers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings: Settings = settings if settings is not None else load_settings()
        self.latched: LatchState | None = None
        self.face_window_start: float | None = None
        self.best_face: FaceCandidate | None = None

    def clear(self) -> None:
        """Clear active latch state and face sampling buffers."""
        self.latched = None
        self.face_window_start = None
        self.best_face = None

    def start_latch(
        self,
        *,
        direction: str,
        vote: VoteResult,
        plate_image: str | None,
        plate_cam: int,
        required_face_cam: int,
        now: float,
        active_session: dict[str, Any] | None,
        opp_cam_recent_faces: deque[Any],
    ) -> LatchState:
        """Enter LATCHED state and seed best_face from pre-latch lookback window."""
        self.latched = LatchState(
            direction=direction,
            plate_key=vote.plate_key,
            plate_number=vote.plate_display,
            plate_image=plate_image,
            vote_count=vote.vote_count,
            sample_count=vote.sample_count,
            consensus_rate=round(vote.vote_share, 4),
            plate_cam=plate_cam,
            required_face_cam=required_face_cam,
            latched_at=now,
            active_session=active_session,
        )
        self.face_window_start = None
        self.best_face = None

        lookback = self.settings.face_pre_latch_lookback_seconds
        while opp_cam_recent_faces and now - opp_cam_recent_faces[0][0] > lookback:
            opp_cam_recent_faces.popleft()

        if opp_cam_recent_faces:
            best_recent = max(
                opp_cam_recent_faces,
                key=lambda item: face_candidate_rank(
                    item[1],
                    item[5],
                    min_sharpness=self.settings.face_min_sharpness,
                    floor_sharpness=self.settings.face_floor_sharpness,
                ),
            )
            self.face_window_start = opp_cam_recent_faces[0][0]
            self.best_face = (
                best_recent[1],
                best_recent[2],
                best_recent[3],
                best_recent[4],
                best_recent[5],
            )
        return self.latched

    def evaluate(
        self,
        *,
        now: float,
        plate_cam_current_plates: Sequence[str],
        req_cam_recent_faces: deque[Any],
    ) -> tuple[str, Any]:
        """Evaluate active latch against swap, timeout, and face sharpness gates."""
        if self.latched is None:
            return ("none", None)

        swapped_plate = any(
            clean_plate_key(plate) != self.latched.plate_key
            for plate in plate_cam_current_plates
        )
        if swapped_plate:
            latched_info = self.latched
            self.clear()
            return ("swapped", latched_info)

        elapsed_latch = now - self.latched.latched_at
        if elapsed_latch > self.settings.latch_timeout_seconds:
            latched_info = self.latched
            if (
                self.best_face is not None
                and self.best_face[4] < self.settings.face_floor_sharpness
            ):
                reason = "KHUÔN MẶT BỊ MỜ, VUI LÒNG QUÉT LẠI"
            else:
                reason = "THIẾU KHUÔN MẶT"
            self.clear()
            return ("timeout", (latched_info, reason))

        latched_at = self.latched.latched_at
        lookback = self.settings.face_pre_latch_lookback_seconds
        if req_cam_recent_faces:
            if self.face_window_start is None:
                self.face_window_start = now
            for f_ts, f_score, f_conf, f_frame, f_box, f_sharp in req_cam_recent_faces:
                if f_ts < latched_at - lookback:
                    continue
                if self.best_face is None or face_candidate_rank(
                    f_score,
                    f_sharp,
                    min_sharpness=self.settings.face_min_sharpness,
                    floor_sharpness=self.settings.face_floor_sharpness,
                ) > face_candidate_rank(
                    self.best_face[0],
                    self.best_face[4],
                    min_sharpness=self.settings.face_min_sharpness,
                    floor_sharpness=self.settings.face_floor_sharpness,
                ):
                    self.best_face = (f_score, f_conf, f_frame, f_box, f_sharp)

        face_wait_elapsed = (
            now - self.face_window_start if self.face_window_start is not None else 0.0
        )
        is_instant_sharp = (
            self.best_face is not None
            and self.best_face[1] >= self.settings.face_instant_confidence
            and self.best_face[4] >= self.settings.face_instant_sharpness
        )
        is_sharp_enough = self.best_face is not None and (
            is_instant_sharp
            or (
                face_wait_elapsed >= self.settings.face_sample_window_seconds
                and self.best_face[4] >= self.settings.face_min_sharpness
            )
            or (
                face_wait_elapsed >= self.settings.face_max_sharpness_wait_seconds
                and self.best_face[4] >= self.settings.face_floor_sharpness
            )
        )
        if (
            self.best_face is not None
            and self.face_window_start is not None
            and is_sharp_enough
        ):
            latched_info = self.latched
            best_face = self.best_face
            self.clear()
            req_cam_recent_faces.clear()
            return ("ready", (latched_info, best_face))

        return ("waiting", None)

    def to_status_dict(self, now: float) -> dict[str, Any] | None:
        """Serialize current latch into `LatchState` API payload or None."""
        if self.latched is None:
            return None
        remaining = max(
            0,
            round(self.settings.latch_timeout_seconds - (now - self.latched.latched_at)),
        )
        return self.latched.to_status_dict(
            remaining_seconds=remaining,
            sampling_face=(self.face_window_start is not None),
        )
