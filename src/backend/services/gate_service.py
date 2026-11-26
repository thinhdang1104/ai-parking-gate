"""Gate orchestration service: dual-cam ingestion, Two-Phase Latch, async commit, and security alerts."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
import logging
import threading
import time
from typing import Any

from src.backend.ai.face_service import FaceService
from src.backend.ai.plate_detector import PlateDetector
from src.backend.config import Settings
from src.backend.domain.image_utils import save_snapshot_to_disk
from src.backend.domain.voting import get_vote_result, is_vote_confirmed
from src.backend.observability.metrics import MetricsRegistry
from src.backend.services.camera_session import CameraSessionManager
from src.backend.services.gate_pipeline import (
    analyze_dual_frames,
    apply_analysis_and_collect_locked,
    build_latched_record,
    compute_cam_schedule,
    decode_browser_pair,
    evaluate_out_face_match,
    extract_face_crop_and_embedding,
)
from src.backend.services.latch_coordinator import LatchCoordinator
from src.backend.services.management_service import ManagementService
from src.backend.storage.exceptions import DatabaseConfigurationError, DatabaseOperationError
from src.backend.storage.mysql_client import now_vn

logger = logging.getLogger(__name__)


class GateService:
    """Thread-safe gate state machine coordinating AI inference, latch, and MySQL commits."""

    def __init__(
        self,
        management_service: ManagementService,
        settings: Settings | None = None,
        plate_detector: PlateDetector | None = None,
        face_service: FaceService | None = None,
        metrics: MetricsRegistry | None = None,
        monotonic_fn: Callable[[], float] = time.monotonic,
        now_fn: Callable[[], datetime] = now_vn,
    ) -> None:
        self.management_service = management_service
        self.settings: Settings = (
            settings if settings is not None else management_service.settings
        )
        self.plate_detector: PlateDetector = (
            plate_detector if plate_detector is not None else PlateDetector(settings=self.settings)
        )
        self.face_service = face_service
        self.metrics = metrics
        self._monotonic_fn = monotonic_fn
        self._now_fn = now_fn

        self.state_lock = threading.Lock()
        self.control_lock = threading.Lock()
        self.infer_lock = threading.Lock()
        self.commit_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="datn2_db_commit",
        )
        self.stopping = threading.Event()

        self.sessions = CameraSessionManager()
        self.latch = LatchCoordinator(self.settings)
        self.models_ready: bool = bool(
            self.plate_detector.is_ready and self.face_service is not None
        )
        self.recent_confirms: dict[str, float] = {}
        self.plates_must_leave: set[str] = set()
        self.plate_last_seen_global: dict[str, float] = {}
        self.committing_plates: set[str] = set()
        self.feedback_seq = 0
        self.gate_feedback: dict[str, Any] | None = None
        self.security_alert: Any = None
        self.alert_resolving = False

    def _inc(self, name: str, value: int = 1) -> None:
        if self.metrics is not None:
            self.metrics.inc(name, value)

    def _set_feedback_locked(self, fb_type: str, message: str) -> None:
        self.feedback_seq += 1
        self.gate_feedback = {
            "seq": self.feedback_seq,
            "type": fb_type,
            "message": message,
            "expires_at": self._monotonic_fn() + 3.0,
        }

    def _clear_obs_with_feedback(self, session_id: int, fb_type: str, message: str) -> None:
        with self.state_lock:
            if self.sessions.session_id == session_id:
                self.sessions.clear_all_observations_locked()
                self._set_feedback_locked(fb_type, message)

    def _reset_session_state_locked(self) -> None:
        for cam in self.sessions.cams.values():
            cam.reset_tracking()
        # Intentionally preserve self.committing_plates across stop/restart cycles;
        # each background commit worker removes its plate_key in _finalize_db_commit's finally.
        self.recent_confirms.clear()
        self.plates_must_leave.clear()
        self.plate_last_seen_global.clear()
        self.alert_resolving = False
        self.security_alert = None
        self.latch.clear()

    def _lock_plate_cooldown_locked(self, plate_key: str, direction: str, now: float) -> None:
        opp = "OUT" if direction == "IN" else "IN"
        self.recent_confirms[f"{plate_key}:{direction}"] = (
            now + self.settings.plate_cooldown_seconds
        )
        self.recent_confirms[f"{plate_key}:{opp}"] = max(
            self.recent_confirms.get(f"{plate_key}:{opp}", 0.0),
            now + self.settings.cross_direction_cooldown_seconds,
        )
        self.plates_must_leave.add(plate_key)
        self.plate_last_seen_global[plate_key] = now

    def _save_pair_snapshots(
        self,
        plate_number: str,
        plate_img: str | None,
        face_img: str | None,
    ) -> None:
        for kind, img in (("plate", plate_img), ("face", face_img)):
            save_snapshot_to_disk(
                kind,
                plate_number,
                img,
                snapshot_dir=self.settings.snapshot_dir,
                enabled=self.settings.save_disk_snapshots,
            )

    def load_ai_models(self) -> None:
        """Load YOLO plate/char models and FaceService if not already loaded."""
        if not self.plate_detector.is_ready:
            self.plate_detector.load()
        if self.face_service is None:
            self.face_service = FaceService(settings=self.settings)
        with self.state_lock:
            self.models_ready = bool(self.plate_detector.is_ready)

    def startup(self) -> None:
        """Start background MySQL connection/reconnect and AI model loading threads."""
        self.stopping.clear()

        def _bg_db() -> None:
            try:
                self.management_service.connect_database()
            except (DatabaseConfigurationError, DatabaseOperationError) as err:
                logger.warning("Chưa kết nối được MySQL: %s", err)
            if not self.stopping.is_set():
                self.management_service.start_reconnect_loop()

        def _bg_ai() -> None:
            try:
                self.load_ai_models()
            except Exception as err:  # noqa: BLE001 - degrade gracefully with error banner
                logger.warning("Không tải được mô hình AI: %s", err)
                with self.state_lock:
                    self.sessions.camera_error = f"Không tải được mô hình AI: {err}"

        for name, fn in (("datn2-init-db", _bg_db), ("datn2-init-ai", _bg_ai)):
            threading.Thread(target=fn, name=name, daemon=True).start()

    def shutdown(self, timeout: float = 15.0) -> None:
        """Stop cameras and wait for all queued DB commits before stopping reconnect loop."""
        self.stopping.set()
        self.stop_cameras()
        self.commit_executor.shutdown(wait=True, cancel_futures=False)
        self.management_service.stop_reconnect_loop(timeout=timeout)

    def start_camera(self, cam_id: int) -> str:
        """Activate Cam 1 or Cam 2 independently for browser WebRTC streaming."""
        self.sessions.get_cam(cam_id)
        with self.control_lock, self.state_lock:
            return self.sessions.start_camera_locked(
                cam_id,
                on_first_start=self._reset_session_state_locked,
                on_reconfigure=self.latch.clear,
            )

    def stop_camera(self, cam_id: int) -> None:
        """Deactivate one camera without interrupting the other or in-flight DB commits."""
        if cam_id not in self.sessions.cams:
            return
        with self.control_lock, self.state_lock:
            deactivated = self.sessions.deactivate_camera_locked(
                cam_id,
                on_all_stopped=self._reset_session_state_locked,
            )
            if deactivated and self.sessions.running:
                self.latch.clear()

    def stop_cameras(self) -> None:
        """Deactivate both cameras and wait for any active AI inference pass to complete."""
        for cam_id in (1, 2):
            self.stop_camera(cam_id)
        with self.infer_lock:
            pass

    def _boxes_snapshot(
        self,
        cam1_active: bool,
        cam2_active: bool,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with self.state_lock:
            cam1_boxes = self.sessions.cams[1].latest_boxes if cam1_active else None
            cam2_boxes = self.sessions.cams[2].latest_boxes if cam2_active else None
            return cam1_boxes, cam2_boxes

    def ingest_browser_frames(
        self,
        cam1_b64: str | None,
        cam2_b64: str | None,
    ) -> dict[str, Any]:
        """Decode browser frames, deduplicate identical streams, and run non-blocking inference."""
        if self.stopping.is_set():
            return {"active": False}

        with self.state_lock:
            cam1 = self.sessions.cams[1]
            cam2 = self.sessions.cams[2]
            b1 = cam1.active and cam1.mode == "browser"
            b2 = cam2.active and cam2.mode == "browser"
            if not (b1 or b2):
                return {"active": False}
            session_id = self.sessions.session_id

        self._inc("frames_received")
        frame1, frame2, deduped = decode_browser_pair(
            cam1_b64,
            cam2_b64,
            active1=b1,
            active2=b2,
            max_chars=self.settings.max_browser_frame_b64_chars,
        )
        if deduped:
            self._inc("frames_deduplicated")
        if frame1 is None and frame2 is None:
            return {"active": True, "processed": False}

        if not self.infer_lock.acquire(blocking=False):
            self._inc("frames_skipped_busy")
            b1_boxes, b2_boxes = self._boxes_snapshot(b1, b2)
            return {
                "active": True,
                "processed": False,
                "cam1_boxes": b1_boxes,
                "cam2_boxes": b2_boxes,
                "status": self.get_status_payload(),
            }

        try:
            latency_ctx = (
                self.metrics.track_latency("gate_infer")
                if self.metrics is not None
                else nullcontext()
            )
            with latency_ctx:
                self.process_dual_frames(session_id, frame1, frame2)
            self._inc("frames_processed")
            b1_boxes, b2_boxes = self._boxes_snapshot(b1, b2)
        except Exception as err:  # noqa: BLE001 - isolate frame processing failures
            logger.warning("Lỗi xử lý AI khung hình trình duyệt: %s", err)
            return {"active": True, "processed": False, "error": str(err)}
        finally:
            self.infer_lock.release()

        return {
            "active": True,
            "processed": True,
            "cam1_boxes": b1_boxes,
            "cam2_boxes": b2_boxes,
            "status": self.get_status_payload(),
        }

    def process_dual_frames(self, session_id: int, frame1: Any, frame2: Any) -> None:
        """Execute dual-camera AI inference and Section 2.1 Latch/Commit state machine."""
        with self.state_lock:
            if (
                self.sessions.session_id != session_id
                or self.security_alert is not None
                or self.alert_resolving
            ):
                return
            latched = self.latch.latched
            cam1 = self.sessions.cams[1]
            cam2 = self.sessions.cams[2]
            req_face_cam = latched.required_face_cam if latched else None
            active1 = cam1.active
            active2 = cam2.active
            schedule = compute_cam_schedule(
                active1=active1,
                active2=active2,
                current_frame_idx=self.sessions.frame_count,
                required_face_cam=req_face_cam,
                latched_plate_cam=latched.plate_cam if latched else None,
                cam1_has_plate=bool(cam1.plate_in_view or cam1.observations),
                cam2_has_plate=bool(cam2.plate_in_view or cam2.observations),
                face_idle_every_n_frames=self.settings.face_idle_every_n_frames,
            )

        res1, res2 = analyze_dual_frames(
            frame1=frame1,
            frame2=frame2,
            active1=active1,
            active2=active2,
            schedule=schedule,
            required_face_cam=req_face_cam,
            plate_detector=self.plate_detector,
            face_service=self.face_service,
        )

        for item in (res1, res2):
            if item is None:
                continue
            if item.plate_present:
                self._inc("plates_detected", len(item.readings) or 1)
            if item.faces:
                self._inc("faces_detected", len(item.faces))

        now = self._monotonic_fn()
        with self.state_lock:
            if self.sessions.session_id != session_id:
                return
            self.recent_confirms = {
                k: v for k, v in self.recent_confirms.items() if v > now
            }
            allow_new_latch = (
                self.security_alert is None
                and not self.alert_resolving
                and self.latch.latched is None
            )
            confirmed = apply_analysis_and_collect_locked(
                cams=self.sessions.cams,
                res1=res1,
                res2=res2,
                frame1=frame1,
                frame2=frame2,
                settings=self.settings,
                plates_must_leave=self.plates_must_leave,
                committing_plates=self.committing_plates,
                recent_confirms=self.recent_confirms,
                plate_last_seen_global=self.plate_last_seen_global,
                now=now,
                allow_new_latch=allow_new_latch,
            )

        active_session_map = {
            plate: self.management_service.get_active_parking_session(plate)
            for plate in set(confirmed.values())
        }

        commit_pair: tuple[dict[str, Any], Any] | None = None
        with self.state_lock:
            if self.sessions.session_id != session_id:
                return
            if self.security_alert is None and not self.alert_resolving:
                if self.latch.latched is None:
                    self._try_start_latch_locked(
                        now,
                        self.sessions.is_dual_cam_mode_locked(),
                        active_session_map,
                    )
                if self.latch.latched is not None:
                    commit_pair = self._evaluate_active_latch_locked(session_id, now)
            self.sessions.frame_count += 1

        if commit_pair is not None:
            self.commit_latched_pair(*commit_pair)

    def _try_start_latch_locked(
        self,
        now: float,
        dual_cam_mode: bool,
        active_session_map: dict[str, tuple[dict[str, Any] | None, bool]],
    ) -> None:
        for plate_cam_id in (cid for cid in (2, 1) if self.sessions.cams[cid].active):
            cam = self.sessions.cams[plate_cam_id]
            vote = get_vote_result(cam.observations)
            if vote is None or not is_vote_confirmed(
                vote,
                cam.observations,
                min_samples=self.settings.vote_min_samples,
                min_share=self.settings.vote_min_share,
                fast_min_samples=self.settings.fast_vote_min_samples,
                fast_min_char_conf=self.settings.fast_vote_min_char_conf,
            ):
                continue

            active_session, db_ok = active_session_map.get(vote.plate_display, (None, True))
            if not db_ok:
                cam.observations.clear()
                self._set_feedback_locked(
                    "error",
                    f"LỖI KẾT NỐI CSDL — TẠM HOÃN XÁC THỰC XE {vote.plate_display}",
                )
                continue

            direction = "OUT" if active_session is not None else "IN"
            target_face_cam_id = (3 - plate_cam_id) if dual_cam_mode else plate_cam_id
            if (
                vote.plate_key in self.plates_must_leave
                or vote.plate_key in self.committing_plates
                or f"{vote.plate_key}:{direction}" in self.recent_confirms
            ):
                cam.observations.clear()
                continue

            best_crop = cam.plate_crops.get(vote.plate_key)
            self.latch.start_latch(
                direction=direction,
                vote=vote,
                plate_image=best_crop[1] if best_crop else None,
                plate_cam=plate_cam_id,
                required_face_cam=target_face_cam_id,
                now=now,
                active_session=active_session,
                opp_cam_recent_faces=self.sessions.cams[target_face_cam_id].recent_faces,
            )
            self._inc("latches_started")
            cam.observations.clear()
            cam.plate_crops.clear()
            break

    def _evaluate_active_latch_locked(
        self,
        session_id: int,
        now: float,
    ) -> tuple[dict[str, Any], Any] | None:
        latched = self.latch.latched
        if latched is None:
            return None

        plate_cam_obj = self.sessions.cams[latched.plate_cam]
        req_cam = self.sessions.cams[latched.required_face_cam]
        outcome, payload = self.latch.evaluate(
            now=now,
            plate_cam_current_plates=plate_cam_obj.current_plates,
            req_cam_recent_faces=req_cam.recent_faces,
        )
        if outcome == "swapped":
            dir_label = "VÀO BÃI" if payload.direction == "IN" else "RA BÃI"
            self._set_feedback_locked(
                "warn",
                f"XE {payload.plate_number} {dir_label} HỦY LƯU HỜ (ĐÃ ĐỔI XE MỚI)",
            )
            self._inc("latches_cancelled")
        elif outcome == "timeout":
            info, reason = payload
            dir_label = "VÀO BÃI" if info.direction == "IN" else "RA BÃI"
            self._set_feedback_locked(
                "warn",
                f"XE {info.plate_number} {dir_label} HỦY LƯU HỜ ({reason})",
            )
            self._inc("latches_timed_out")
        elif outcome == "ready":
            info, best_face = payload
            self._inc("latches_committed")
            record = build_latched_record(
                info,
                best_face,
                session_id=session_id,
                camera_index=plate_cam_obj.device_index,
                fee_vnd=self.settings.parking_fee_vnd,
                recognized_at=self._now_fn(),
            )
            return record, best_face
        return None

    def cancel_latch(self) -> dict[str, Any]:
        """Manually cancel active Two-Phase Latch and clear camera vote queues."""
        with self.state_lock:
            if self.latch.latched is not None:
                self._inc("latches_cancelled")
            self.latch.clear()
            self.sessions.clear_all_observations_locked()
        return {"status": "cancelled", "camera_status": self.get_status_payload()}

    def _commit_success_locked(
        self,
        plate_key: str,
        direction: str,
        now: float,
        fb_type: str,
        msg: str,
    ) -> None:
        if plate_key:
            self._lock_plate_cooldown_locked(plate_key, direction, now)
        self._set_feedback_locked(fb_type, msg)

    def _resp(self, status: str, message: str, fb_type: str) -> dict[str, Any]:
        return {
            "status": status,
            "message": message,
            "type": fb_type,
            "camera_status": self.get_status_payload(),
        }

    def resolve_security_alert(self, approve: bool) -> dict[str, Any]:
        """Approve or reject an active FaceNet mismatch Security Alert."""
        if self.stopping.is_set():
            return {"status": "none", "message": ""}

        record_to_save: dict[str, Any] | None = None
        rejected_msg: str | None = None
        plate_key = ""
        plate_number = ""
        direction = "OUT"

        with self.state_lock:
            alert = self.security_alert
            if alert is None or self.alert_resolving:
                return {"status": "none", "message": ""}
            plate_key = alert.plate_key
            rec = alert.record or {}
            plate_number = str(rec.get("plate_number") or alert.plate_number)
            direction = str(rec.get("direction") or "OUT")
            if approve:
                self.alert_resolving = True
                record_to_save = dict(rec)
            else:
                self.security_alert = None
                self.alert_resolving = False
                rejected_msg = f"XE {plate_number} RA BÃI BỊ TỪ CHỐI"
                if plate_key:
                    self.recent_confirms.pop(f"{plate_key}:OUT", None)
                self.sessions.clear_all_observations_locked()
                self._set_feedback_locked("error", rejected_msg)
                self._inc("security_alerts_rejected")

        if rejected_msg is not None:
            return self._resp("rejected", rejected_msg, "error")
        if record_to_save is None:
            return {"status": "none", "message": ""}

        try:
            saved = self.management_service.store_record(record_to_save)
        finally:
            with self.state_lock:
                self.alert_resolving = False

        now = self._monotonic_fn()
        if not saved:
            err_msg = f"Chưa lưu được lượt xe {plate_number} vào CSDL, vui lòng thử lại"
            with self.state_lock:
                self._set_feedback_locked("error", err_msg)
            return self._resp("db_error", err_msg, "error")

        msg = f"XE {plate_number} RA BÃI ĐƯỢC DUYỆT"
        self._save_pair_snapshots(
            record_to_save["plate_number"],
            record_to_save.get("plate_image"),
            record_to_save.get("face_image"),
        )
        with self.state_lock:
            self.security_alert = None
            self._commit_success_locked(plate_key, direction, now, "warn", msg)
            self._inc("security_alerts_approved")
        return self._resp("approved", msg, "warn")

    def _finalize_db_commit(
        self,
        record: dict[str, Any],
        commit_session_id: int,
        plate_key: str,
        direction: str,
        plate: str,
        face_image: str | None,
        feedback_type: str,
        feedback_msg: str,
    ) -> None:
        try:
            saved = self.management_service.store_record(record)
            now = self._monotonic_fn()
            if saved:
                self._save_pair_snapshots(
                    record["plate_number"],
                    record.get("plate_image"),
                    face_image,
                )
            with self.state_lock:
                if self.sessions.session_id == commit_session_id:
                    if not saved:
                        if plate_key:
                            self.recent_confirms.pop(f"{plate_key}:{direction}", None)
                            self.plates_must_leave.discard(plate_key)
                        self.sessions.clear_all_observations_locked()
                        self._set_feedback_locked(
                            "error",
                            f"Chưa lưu được lượt xe {plate} vào CSDL, vui lòng quét lại",
                        )
                    else:
                        self._commit_success_locked(
                            plate_key,
                            direction,
                            now,
                            feedback_type,
                            feedback_msg,
                        )
        finally:
            if plate_key:
                with self.state_lock:
                    self.committing_plates.discard(plate_key)

    def commit_latched_pair(
        self,
        record: dict[str, Any],
        best_face: Any,
        async_db: bool = True,
    ) -> None:
        """Embed best face, verify OUT cosine similarity, and commit IN/OUT record to MySQL."""
        commit_session_id = record.pop("_session_id", self.sessions.session_id)
        plate_key = record.pop("_plate_key", "")
        cached_sess = record.pop("_active_session", None)
        if self.stopping.is_set():
            return

        if self.face_service is None or not self.face_service.can_embed:
            self._clear_obs_with_feedback(
                commit_session_id,
                "error",
                "Mô hình khuôn mặt chưa sẵn sàng, vui lòng đợi",
            )
            return

        face_image, embedding = extract_face_crop_and_embedding(self.face_service, best_face)
        if not embedding:
            self._clear_obs_with_feedback(
                commit_session_id,
                "warn",
                "Không lấy được đặc trưng khuôn mặt, vui lòng quét lại",
            )
            return

        record["face_embedding"] = embedding
        record["face_image"] = face_image
        direction = record["direction"]
        plate = record["plate_number"]

        if direction == "OUT":
            alert = evaluate_out_face_match(
                record,
                plate_key=plate_key,
                embedding=embedding,
                active_session=cached_sess,
                match_threshold=self.settings.face_match_threshold,
            )
            if alert is not None:
                with self.state_lock:
                    if self.sessions.session_id == commit_session_id:
                        self.security_alert = alert
                        self._inc("security_alerts_triggered")
                return

        fb_msg = f"XE {plate} {'RA' if direction == 'OUT' else 'VÀO'} BÃI THÀNH CÔNG"
        with self.state_lock:
            if self.sessions.session_id != commit_session_id:
                return
            if plate_key:
                self.committing_plates.add(plate_key)

        args = (
            record,
            commit_session_id,
            plate_key,
            direction,
            plate,
            face_image,
            "success",
            fb_msg,
        )
        if async_db and not self.stopping.is_set():
            try:
                self.commit_executor.submit(self._finalize_db_commit, *args)
                return
            except RuntimeError:
                pass
        self._finalize_db_commit(*args)

    def get_status_payload(self) -> dict[str, Any]:
        """Serialize current gate status matching `GateStatusResponse` schema keys."""
        database_ready, _, records_version = self.management_service.get_status_snapshot()
        now = self._monotonic_fn()
        with self.state_lock:
            cam1 = self.sessions.cams[1].serialize_status()
            cam2 = self.sessions.cams[2].serialize_status()
            if (
                self.gate_feedback is not None
                and now >= self.gate_feedback.get("expires_at", 0.0)
            ):
                self.gate_feedback = None
            return {
                "running": self.sessions.running,
                "committing": bool(self.committing_plates),
                "cam1": cam1,
                "cam2": cam2,
                "latched": self.latch.to_status_dict(now),
                "security_alert": (
                    self.security_alert.to_status_dict() if self.security_alert else None
                ),
                "gate_feedback": (
                    dict(self.gate_feedback) if self.gate_feedback is not None else None
                ),
                "ambiguous_frame": bool(
                    cam1["ambiguous_frame"] or cam2["ambiguous_frame"]
                ),
                "error": self.sessions.camera_error,
                "records_version": records_version,
                "database_ready": database_ready,
                "models_ready": self.models_ready,
                "face_match_threshold": self.settings.face_match_threshold,
            }
