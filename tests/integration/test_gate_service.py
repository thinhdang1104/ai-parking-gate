"""Integration & regression tests for Phase 3B GateService & gate_pipeline."""

from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from typing import Any
from unittest import mock

import cv2
import numpy as np
import pytest

from src.backend.ai.plate_detector import PlateDetectionResult
from src.backend.config import Settings
from src.backend.domain.models import FaceDetection, SecurityAlert
from src.backend.observability.metrics import MetricsRegistry
from src.backend.services.gate_service import GateService
from src.backend.services.management_service import ManagementService
from src.backend.storage.exceptions import DatabaseOperationError
from src.backend.storage.warm_mirror import WarmDatabaseMirror

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "gate_payloads.schema.json"


def _make_sharp_frame(seed: int = 0) -> np.ndarray:
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[::2, ::2] = 255
    if seed:
        frame[0, 0, 0] = seed % 255
    return frame


def _make_blurry_frame() -> np.ndarray:
    return np.full((120, 160, 3), 128, dtype=np.uint8)


def _encode_b64_jpeg(frame: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class _StubPlateDetector:
    def __init__(self, per_frame_fn: Any = None) -> None:
        self.is_ready = True
        self.calls: list[tuple[str, int]] = []
        self._fn = per_frame_fn

    def load(self) -> None:
        self.is_ready = True

    def detect(self, frame: Any) -> PlateDetectionResult:
        self.calls.append(("single", 1))
        return self._fn("single", frame) if self._fn else PlateDetectionResult()

    def detect_batch(self, frames: list[Any]) -> list[PlateDetectionResult]:
        self.calls.append(("batch", len(frames)))
        if self._fn:
            return [self._fn("batch", f, idx) for idx, f in enumerate(frames)]
        return [PlateDetectionResult() for _ in frames]


class _StubFaceService:
    def __init__(self, detect_fn: Any = None, embedding: list[float] | None = None, can_embed: bool = True) -> None:
        self.can_embed = can_embed
        self._detect_fn = detect_fn
        self._embedding = embedding if embedding is not None else ([1.0] + [0.0] * 511)
        self.detect_calls = 0

    def detect_from_bgr(self, frame: np.ndarray) -> list[FaceDetection]:
        self.detect_calls += 1
        if self._detect_fn is not None:
            return self._detect_fn(frame)
        return [FaceDetection(box=(20, 15, 110, 105), confidence=0.92)]

    def embed_face(self, frame: np.ndarray, box: tuple[int, int, int, int]) -> list[float] | None:
        del frame, box
        return list(self._embedding)


def _build_services(
    *,
    plate_detector: Any = None,
    face_service: Any = None,
    settings: Settings | None = None,
    clock: dict[str, Any] | None = None,
    db_ready: bool = True,
) -> tuple[GateService, ManagementService, mock.MagicMock, dict[str, Any]]:
    clk = clock if clock is not None else {"mono": 100.0, "now": datetime(2026, 11, 26, 15, 0, 0)}
    cfg = settings or Settings(force_cpu=True)
    fake_repo = mock.MagicMock()
    fake_repo.settings = cfg
    fake_repo.find_active_parking_session.return_value = None
    fake_repo.insert_plate_record.return_value = (1, None)

    mirror = WarmDatabaseMirror(now_fn=lambda: clk["now"])
    metrics = MetricsRegistry()
    mgmt = ManagementService(
        repository=fake_repo,
        warm_mirror=mirror,
        settings=cfg,
        metrics=metrics,
        now_fn=lambda: clk["now"],
        monotonic_fn=lambda: clk["mono"],
    )
    mgmt.set_db_status(db_ready, None if db_ready else "DB offline")

    gate = GateService(
        management_service=mgmt,
        settings=cfg,
        plate_detector=plate_detector or _StubPlateDetector(),
        face_service=face_service or _StubFaceService(),
        metrics=metrics,
        monotonic_fn=lambda: clk["mono"],
        now_fn=lambda: clk["now"],
    )
    return gate, mgmt, fake_repo, clk


def test_dual_cam_batched_yolo_skip_ocr_and_two_frame_instant_commit() -> None:
    """Batch YOLO [frame1, frame2] on Frame 1, odd-frame opposite MTCNN, Cam 2 OCR skip + Fast-Confirm on Frame 2."""
    sharp_f1 = _make_sharp_frame(1)
    sharp_f2 = _make_sharp_frame(2)

    def plate_fn(mode: str, frame: Any, idx: int = 0) -> PlateDetectionResult:
        if (mode == "batch" and idx == 0) or mode == "single":
            return PlateDetectionResult(
                plate_present=True,
                readings={"59V179379": "59V1-79379"},
                plate_boxes=[{"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.4, "label": "59V1-79379", "valid": True}],
                plate_crops={"59V179379": (42.0, "data:image/jpeg;base64,AA==")},
                reading_confs={"59V179379": 0.88},
            )
        return PlateDetectionResult()

    detector = _StubPlateDetector(per_frame_fn=plate_fn)
    face_svc = _StubFaceService()
    gate, _, fake_repo, clk = _build_services(plate_detector=detector, face_service=face_svc)
    insert_done = threading.Event()
    fake_repo.insert_plate_record.side_effect = lambda rec: (insert_done.set(), (777, None))[1]

    gate.start_camera(1)
    gate.start_camera(2)
    sid = gate.sessions.session_id

    # Frame 1 (idx=0): batched predict([frame1, frame2]), Cam 1 obs #1, Cam 2 saves sharp face
    gate.process_dual_frames(sid, sharp_f1, sharp_f2)
    assert detector.calls == [("batch", 2)]
    assert len(gate.sessions.cams[1].observations) == 1
    assert len(gate.sessions.cams[2].recent_faces) == 1

    # Frame 2 (idx=1, +0.12s): Cam 2 OCR skipped -> single predict(frame1), Fast-Confirm 2/2 + instant face commit
    clk["mono"] = 100.12
    gate.process_dual_frames(sid, sharp_f1, sharp_f2)
    assert detector.calls[1] == ("single", 1)
    assert gate.latch.latched is None
    assert insert_done.wait(timeout=2.0)
    gate.commit_executor.shutdown(wait=True)

    status = gate.get_status_payload()
    assert status["committing"] is False
    assert status["records_version"] == 1
    assert status["gate_feedback"] is not None
    assert "VÀO BÃI THÀNH CÔNG" in status["gate_feedback"]["message"]
    assert "59V179379" in gate.plates_must_leave
    gate.shutdown(timeout=2.0)


def test_odd_frame_extra_opposite_cam_mtcnn_pass() -> None:
    """When Cam 1 detects a plate on an odd frame (idle MTCNN skipped), Cam 2 gets immediate extra MTCNN pass."""
    f1, f2 = _make_sharp_frame(1), _make_sharp_frame(2)
    detector = _StubPlateDetector(
        per_frame_fn=lambda mode, frame, idx=0: PlateDetectionResult(
            plate_present=(idx == 0),
            readings={"59V179379": "59V1-79379"} if idx == 0 else {},
            plate_boxes=[{"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.4, "label": "59V1-79379", "valid": True}] if idx == 0 else [],
            reading_confs={"59V179379": 0.85} if idx == 0 else {},
        )
    )
    face_svc = _StubFaceService()
    gate, _, _, _ = _build_services(plate_detector=detector, face_service=face_svc)
    gate.start_camera(1)
    gate.start_camera(2)
    gate.sessions.frame_count = 1  # odd frame -> run_face_idle is False

    gate.process_dual_frames(gate.sessions.session_id, f1, f2)
    # Cam 1 ran MTCNN because plate_present=True; Cam 2 got extra pass because Cam 1 spotted a plate!
    assert face_svc.detect_calls == 2
    assert len(gate.sessions.cams[2].recent_faces) == 1
    gate.shutdown(timeout=2.0)


def test_async_db_commit_committing_lock_cooldown_and_db_failure() -> None:
    """committing_plates stays locked during slow DB write; cooldown/success only after DB succeeds; failure rolls back."""
    gate, _, fake_repo, clk = _build_services()
    gate.start_camera(1)
    sid = gate.sessions.session_id
    sharp = _make_sharp_frame()
    best_face = (0.95, 0.96, sharp, (10, 10, 70, 70), 26.0)

    entered_db = threading.Event()
    release_db = threading.Event()

    def slow_insert(rec: dict[str, Any]) -> tuple[int, float | None]:
        entered_db.set()
        release_db.wait(timeout=3.0)
        return (123, None)

    fake_repo.insert_plate_record.side_effect = slow_insert
    rec = {
        "_session_id": sid, "_plate_key": "59V179379", "_active_session": None,
        "plate_number": "59V1-79379", "direction": "IN", "parking_status": "IN_PARKING",
        "fee_amount": 2000, "recognized_at": clk["now"], "vote_count": 3,
        "sample_count": 3, "consensus_rate": 1.0, "face_detected": True,
        "face_confidence": 0.96, "camera_index": 0,
    }
    gate.commit_latched_pair(dict(rec), best_face, async_db=True)
    assert entered_db.wait(timeout=2.0)
    assert "59V179379" in gate.committing_plates
    assert gate.get_status_payload()["committing"] is True
    assert gate.gate_feedback is None

    release_db.set()
    gate.commit_executor.shutdown(wait=True)

    assert "59V179379" not in gate.committing_plates
    assert gate.gate_feedback is not None
    assert gate.gate_feedback["type"] == "success"
    assert "VÀO BÃI THÀNH CÔNG" in gate.gate_feedback["message"]
    assert gate.recent_confirms["59V179379:IN"] == pytest.approx(clk["mono"] + 20.0)
    assert gate.recent_confirms["59V179379:OUT"] == pytest.approx(clk["mono"] + 6.0)
    assert "59V179379" in gate.plates_must_leave
    gate.shutdown(timeout=3.0)

    # Failure path: DatabaseOperationError must clear committing_plates, skip cooldown, and emit error feedback
    gate2, _, fake_repo2, _ = _build_services()
    gate2.start_camera(1)
    fake_repo2.insert_plate_record.side_effect = DatabaseOperationError("MySQL down")
    rec2 = dict(rec, _session_id=gate2.sessions.session_id)
    gate2.commit_latched_pair(rec2, best_face, async_db=False)
    assert "59V179379" not in gate2.committing_plates
    assert "59V179379:IN" not in gate2.recent_confirms
    assert gate2.gate_feedback is not None and gate2.gate_feedback["type"] == "error"
    assert "Chưa lưu được lượt xe" in gate2.gate_feedback["message"]
    gate2.shutdown(timeout=2.0)


def test_stop_cameras_and_shutdown_never_drop_inflight_commit() -> None:
    """Stopping cameras / shutting down while commit is queued must still persist the record to MySQL."""
    gate, _, fake_repo, clk = _build_services()
    gate.start_camera(1)
    sid = gate.sessions.session_id
    sharp = _make_sharp_frame()
    best_face = (0.95, 0.96, sharp, (10, 10, 70, 70), 26.0)

    blocker_started = threading.Event()
    release_blocker = threading.Event()
    inserted_plates: list[str] = []

    def hold_worker() -> None:
        blocker_started.set()
        release_blocker.wait(timeout=3.0)

    fake_repo.insert_plate_record.side_effect = lambda rec: (inserted_plates.append(rec["plate_number"]), (555, None))[1]

    gate.commit_executor.submit(hold_worker)
    assert blocker_started.wait(timeout=2.0)

    rec = {
        "_session_id": sid, "_plate_key": "30T41975", "_active_session": None,
        "plate_number": "30T4-1975", "direction": "IN", "parking_status": "IN_PARKING",
        "fee_amount": 2000, "recognized_at": clk["now"], "vote_count": 3,
        "sample_count": 3, "consensus_rate": 1.0, "face_detected": True,
        "face_confidence": 0.96, "camera_index": 0,
    }
    gate.commit_latched_pair(rec, best_face, async_db=True)
    assert "30T41975" in gate.committing_plates

    # stop_cameras bumps session_id; release blocker and shutdown waits for commit_executor
    gate.stop_cameras()
    assert gate.sessions.session_id == sid + 1
    release_blocker.set()
    gate.shutdown(timeout=3.0)

    assert inserted_plates == ["30T4-1975"]
    assert "30T41975" not in gate.committing_plates


def test_security_alert_out_mismatch_missing_embedding_approve_retry_and_reject(tmp_path: Path) -> None:
    """OUT mismatch (<0.65) or missing entry embedding raises SecurityAlert; approve preserves on DB error; reject clears."""
    exit_emb = [0.0, 1.0] + [0.0] * 510
    entry_emb = [1.0, 0.0] + [0.0] * 510
    cfg = Settings(force_cpu=True, save_disk_snapshots=True, snapshot_dir=tmp_path / "snaps")
    gate, _, fake_repo, clk = _build_services(face_service=_StubFaceService(embedding=exit_emb), settings=cfg)
    gate.start_camera(1)
    sid = gate.sessions.session_id
    sharp = _make_sharp_frame()
    best_face = (0.95, 0.95, sharp, (10, 10, 80, 80), 30.0)

    # Mismatch OUT (< 0.65)
    out_rec = {
        "_session_id": sid, "_plate_key": "30T41975",
        "_active_session": {"id": 10, "recognized_at": "2026-11-26 08:00:00", "embedding": entry_emb},
        "plate_number": "30T4-1975", "plate_image": "data:image/jpeg;base64,AA==",
        "direction": "OUT", "parking_status": "EXITED", "fee_amount": 0,
        "recognized_at": clk["now"], "vote_count": 3, "sample_count": 3,
        "consensus_rate": 1.0, "face_detected": True, "face_confidence": 0.95, "camera_index": 0,
    }
    gate.commit_latched_pair(dict(out_rec), best_face, async_db=False)
    assert gate.security_alert is not None
    assert gate.security_alert.match_score_pct == "0%"
    assert gate.metrics is not None and gate.metrics.get_counter("security_alerts_triggered") == 1

    # Approve fails on DB error -> alert preserved, no cooldown
    fake_repo.insert_plate_record.side_effect = DatabaseOperationError("lost mysql")
    err_res = gate.resolve_security_alert(approve=True)
    assert err_res["status"] == "db_error"
    assert gate.security_alert is not None
    assert gate.alert_resolving is False
    assert "30T41975:OUT" not in gate.recent_confirms

    # Retry approve succeeds -> alert cleared, cooldown 20s/6s, snapshots saved
    fake_repo.insert_plate_record.side_effect = None
    fake_repo.insert_plate_record.return_value = (99, 0.0)
    ok_res = gate.resolve_security_alert(approve=True)
    assert ok_res["status"] == "approved"
    assert gate.security_alert is None
    assert ok_res["camera_status"]["security_alert"] is None
    assert gate.recent_confirms["30T41975:OUT"] == pytest.approx(clk["mono"] + 20.0)
    assert gate.recent_confirms["30T41975:IN"] == pytest.approx(clk["mono"] + 6.0)
    assert len(list((tmp_path / "snaps").glob("*.jpg"))) == 2

    # Missing entry embedding -> triggers SecurityAlert, reject clears with no DB insert
    fake_repo.insert_plate_record.reset_mock()
    out_missing_emb = dict(out_rec, _plate_key="59A112345", plate_number="59A1-12345", _active_session={"id": 11, "recognized_at": "2026-11-26 09:00:00", "embedding": None})
    gate.commit_latched_pair(out_missing_emb, best_face, async_db=False)
    assert gate.security_alert is not None
    assert gate.security_alert.match_score_pct == "0%"
    rej_res = gate.resolve_security_alert(approve=False)
    assert rej_res["status"] == "rejected"
    assert gate.security_alert is None
    assert fake_repo.insert_plate_record.call_count == 0
    gate.shutdown(timeout=2.0)


def test_swapped_plate_timeout_reasons_and_manual_cancel_latch() -> None:
    """Swapped plate cancels latch; 4.0s timeout distinguishes blurry vs missing face; manual cancel_latch works."""
    current_plate = {"key": "59V179379", "disp": "59V1-79379"}
    faces_to_return: list[FaceDetection] = []

    detector = _StubPlateDetector(
        per_frame_fn=lambda mode, frame: PlateDetectionResult(
            plate_present=True,
            readings={current_plate["key"]: current_plate["disp"]},
            reading_confs={current_plate["key"]: 0.90},
        )
    )
    gate, _, _, clk = _build_services(plate_detector=detector, face_service=_StubFaceService(detect_fn=lambda _: list(faces_to_return)))
    gate.start_camera(1)
    sid = gate.sessions.session_id
    blurry = _make_blurry_frame()

    # Latch 59V1-79379 in 2 frames, no face
    gate.process_dual_frames(sid, blurry, None)
    clk["mono"] += 0.12
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is not None

    # Swapped plate -> cancels latch immediately
    current_plate.update(key="60A111111", disp="60A1-11111")
    clk["mono"] += 0.10
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is None
    assert gate.gate_feedback is not None
    assert "HỦY LƯU HỜ (ĐÃ ĐỔI XE MỚI)" in gate.gate_feedback["message"]

    # Latch 60A1-11111, feed blurry face -> timeout > 4.0s -> KHUÔN MẶT BỊ MỜ
    clk["mono"] += 0.12
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is not None
    faces_to_return.append(FaceDetection(box=(10, 10, 60, 60), confidence=0.90))
    clk["mono"] += 0.2
    gate.process_dual_frames(sid, blurry, None)
    clk["mono"] += 4.2
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is None
    assert gate.gate_feedback is not None and "KHUÔN MẶT BỊ MỜ, VUI LÒNG QUÉT LẠI" in gate.gate_feedback["message"]

    # Latch again with no faces (advance > 1.8s past last blurry face) -> timeout -> THIẾU KHUÔN MẶT
    faces_to_return.clear()
    clk["mono"] += 2.5
    gate.process_dual_frames(sid, blurry, None)
    clk["mono"] += 0.12
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is not None
    clk["mono"] += 4.5
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is None
    assert gate.gate_feedback is not None and "THIẾU KHUÔN MẶT" in gate.gate_feedback["message"]

    # Manual cancel_latch
    clk["mono"] += 0.12
    gate.process_dual_frames(sid, blurry, None)
    clk["mono"] += 0.12
    gate.process_dual_frames(sid, blurry, None)
    assert gate.latch.latched is not None
    cancelled = gate.cancel_latch()
    assert cancelled["status"] == "cancelled"
    assert cancelled["camera_status"]["latched"] is None
    gate.shutdown(timeout=2.0)


def test_db_offline_delays_confirmation_with_error_banner() -> None:
    """When database_ready is False, confirmed vote clears observations and sets DB error feedback."""
    detector = _StubPlateDetector(
        per_frame_fn=lambda mode, frame: PlateDetectionResult(
            plate_present=True, readings={"59V179379": "59V1-79379"}, reading_confs={"59V179379": 0.90}
        )
    )
    gate, _, _, clk = _build_services(plate_detector=detector, db_ready=False)
    gate.start_camera(1)
    sid = gate.sessions.session_id
    frame = _make_sharp_frame()

    gate.process_dual_frames(sid, frame, None)
    clk["mono"] += 0.12
    gate.process_dual_frames(sid, frame, None)

    assert gate.latch.latched is None
    assert len(gate.sessions.cams[1].observations) == 0
    assert gate.gate_feedback is not None
    assert gate.gate_feedback["type"] == "error"
    assert "LỖI KẾT NỐI CSDL — TẠM HOÃN XÁC THỰC XE 59V1-79379" in gate.gate_feedback["message"]
    gate.shutdown(timeout=2.0)


def test_ingest_dedup_busy_infer_lock_and_independent_cam_control() -> None:
    """Identical cam1/cam2 base64 deduplicates frame2; busy infer_lock returns processed=False; Cam1/Cam2 toggle independently."""
    detector = _StubPlateDetector()
    gate, _, _, _ = _build_services(plate_detector=detector)

    assert gate.ingest_browser_frames(None, None) == {"active": False}

    assert gate.start_camera(1) == "browser"
    assert gate.start_camera(2) == "browser"
    b64 = _encode_b64_jpeg(_make_sharp_frame())

    # Identical cam1_b64 == cam2_b64 -> only frame1 processed (single detect, not batch)
    res_dedup = gate.ingest_browser_frames(b64, b64)
    assert res_dedup["active"] is True and res_dedup["processed"] is True
    assert detector.calls == [("single", 1)]
    assert gate.metrics is not None and gate.metrics.get_counter("frames_deduplicated") == 1

    # Busy infer_lock -> returns processed=False with cached boxes
    assert gate.infer_lock.acquire(blocking=False)
    try:
        res_busy = gate.ingest_browser_frames(b64, b64)
        assert res_busy["active"] is True
        assert res_busy["processed"] is False
        assert res_busy["cam1_boxes"] == res_dedup["cam1_boxes"]
        assert res_busy["cam2_boxes"] == res_dedup["cam2_boxes"]
        assert gate.metrics.get_counter("frames_skipped_busy") == 1
    finally:
        gate.infer_lock.release()

    # Stopping Cam 1 leaves Cam 2 active
    gate.stop_camera(1)
    st = gate.get_status_payload()
    assert st["running"] is True
    assert st["cam1"]["active"] is False
    assert st["cam2"]["active"] is True
    gate.shutdown(timeout=2.0)


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "null":
        return value is None
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    raise AssertionError(f"Unsupported schema type: {expected_type}")


def _validate_against_schema(
    instance: Any,
    node: dict[str, Any],
    defs: dict[str, Any],
    path: str = "$",
) -> None:
    if "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/$defs/"), f"Unsupported $ref {ref} at {path}"
        target_name = ref.removeprefix("#/$defs/")
        _validate_against_schema(instance, defs[target_name], defs, path)
        return

    if "oneOf" in node:
        matches = 0
        errors: list[str] = []
        for idx, branch in enumerate(node["oneOf"]):
            try:
                _validate_against_schema(instance, branch, defs, f"{path}.oneOf[{idx}]")
                matches += 1
            except AssertionError as err:
                errors.append(str(err))
        assert matches == 1, f"{path} failed oneOf (matches={matches}): {errors}"
        return

    if "type" in node:
        allowed = node["type"] if isinstance(node["type"], list) else [node["type"]]
        assert any(_matches_json_type(instance, t) for t in allowed), (
            f"{path} expected type {allowed}, got {type(instance).__name__}: {instance!r}"
        )

    if "enum" in node:
        assert instance in node["enum"], f"{path} value {instance!r} not in {node['enum']}"

    if isinstance(instance, str):
        if "minLength" in node:
            assert len(instance) >= node["minLength"], f"{path} shorter than {node['minLength']}"
        if "pattern" in node:
            assert re.search(node["pattern"], instance), f"{path} {instance!r} mismatch {node['pattern']}"

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in node:
            assert instance >= node["minimum"], f"{path} {instance} < {node['minimum']}"
        if "maximum" in node:
            assert instance <= node["maximum"], f"{path} {instance} > {node['maximum']}"

    if isinstance(instance, list) and "items" in node:
        for idx, item in enumerate(instance):
            _validate_against_schema(item, node["items"], defs, f"{path}[{idx}]")

    if isinstance(instance, dict):
        props = node.get("properties", {})
        required = set(node.get("required", []))
        assert required.issubset(instance.keys()), (
            f"{path} missing required keys: {sorted(required - set(instance.keys()))}"
        )
        if node.get("additionalProperties") is False:
            extra = set(instance.keys()) - set(props.keys())
            assert not extra, f"{path} unexpected keys: {sorted(extra)}"
        for key, prop_schema in props.items():
            if key in instance:
                _validate_against_schema(instance[key], prop_schema, defs, f"{path}.{key}")


def test_get_status_payload_matches_gate_payloads_schema() -> None:
    """Validate get_status_payload() keys & sub-schemas directly against schemas/gate_payloads.schema.json."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    gate_schema = defs["GateStatusResponse"]
    required_keys = set(gate_schema["required"])
    property_keys = set(gate_schema["properties"].keys())
    assert required_keys == property_keys

    gate, _, _, clk = _build_services()
    gate.start_camera(1)
    gate.start_camera(2)
    gate.sessions.cams[1].current_plates = ["59V1-79379"]
    gate.latch.start_latch(
        direction="IN",
        vote=SimpleNamespace(plate_key="59V179379", plate_display="59V1-79379", vote_count=3, vote_share=1.0, sample_count=3),  # type: ignore[arg-type]
        plate_image=None, plate_cam=1, required_face_cam=2, now=clk["mono"],
        active_session=None, opp_cam_recent_faces=gate.sessions.cams[2].recent_faces,
    )
    gate.security_alert = SecurityAlert("59V179379", "59V1-79379", "2026-11-26 08:00:00", "45%")
    with gate.state_lock:
        gate._set_feedback_locked("warn", "Cảnh báo thử nghiệm")

    payload = gate.get_status_payload()
    assert set(payload.keys()) == property_keys
    _validate_against_schema(payload, gate_schema, defs, "GateStatusResponse")

    for key, def_name in (("latched", "LatchState"), ("security_alert", "SecurityAlert"), ("gate_feedback", "GateFeedback")):
        sub_schema = defs[def_name]
        assert set(payload[key].keys()) == set(sub_schema["required"]) == set(sub_schema["properties"].keys())
        _validate_against_schema(payload[key], sub_schema, defs, def_name)

    cam_schema = defs["CameraUnitStatus"]
    for cam_key in ("cam1", "cam2"):
        assert set(payload[cam_key].keys()) == set(cam_schema["required"]) == set(cam_schema["properties"].keys())
        _validate_against_schema(payload[cam_key], cam_schema, defs, cam_key)
    gate.shutdown(timeout=2.0)
