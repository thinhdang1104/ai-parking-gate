"""Unit and integration tests for Phase 3A AI adapters, session, latch, and management."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any
from unittest import mock

import numpy as np
import pytest
import torch

from src.backend.ai import FaceService, PlateDetectionResult, PlateDetector
from src.backend.config import Settings
from src.backend.domain.models import VoteObservation, VoteResult
from src.backend.observability.metrics import MetricsRegistry
from src.backend.services.camera_session import CameraSessionManager, CameraUnitState
from src.backend.services.latch_coordinator import LatchCoordinator
from src.backend.services.management_service import ManagementService
from src.backend.storage.exceptions import DatabaseOperationError
from src.backend.storage.warm_mirror import WarmDatabaseMirror


class _FakeBox:
    def __init__(self, xyxy: list[int], cls_idx: int = 0, conf: float = 0.9) -> None:
        self.xyxy = [xyxy]
        self.cls = [cls_idx]
        self.conf = [conf]


class _FakePlateModel:
    def __init__(self, per_frame_boxes: list[list[_FakeBox]]) -> None:
        self.per_frame_boxes = per_frame_boxes
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def predict(self, source: Any, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append((source, kwargs))
        return [SimpleNamespace(boxes=boxes) for boxes in self.per_frame_boxes]


class _FakeCharModel:
    def __init__(self, names: dict[int, str], char_boxes_seq: list[list[_FakeBox]]) -> None:
        self.names = names
        self._seq = list(char_boxes_seq)
        self.calls = 0

    def predict(self, crop: Any, **kwargs: Any) -> list[SimpleNamespace]:
        del crop, kwargs
        idx = min(self.calls, len(self._seq) - 1)
        self.calls += 1
        return [SimpleNamespace(boxes=self._seq[idx])]


def test_plate_detector_load_device_and_single_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing_settings = Settings(
        plate_model_path=tmp_path / "missing_plate.pt",
        char_model_path=tmp_path / "missing_char.pt",
    )
    detector = PlateDetector(settings=missing_settings)
    assert detector.is_ready is False
    with pytest.raises(RuntimeError, match="biển số"):
        detector.load()

    plate_pt = tmp_path / "plate_best.pt"
    plate_pt.write_bytes(b"p")
    detector_missing_char = PlateDetector(
        settings=Settings(plate_model_path=plate_pt, char_model_path=tmp_path / "no_char.pt")
    )
    with pytest.raises(RuntimeError, match="ký tự"):
        detector_missing_char.load()

    char_pt = tmp_path / "chars_best.pt"
    char_pt.write_bytes(b"c")
    fake_ultralytics = SimpleNamespace(YOLO=lambda p: f"loaded:{Path(p).name}")
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ultralytics)
    loaded_detector = PlateDetector(
        settings=Settings(plate_model_path=plate_pt, char_model_path=char_pt, force_cpu=True)
    )
    loaded_detector.load()
    assert loaded_detector.is_ready is True
    assert loaded_detector.plate_model == "loaded:plate_best.pt"
    assert loaded_detector.char_model == "loaded:chars_best.pt"
    assert loaded_detector.device_kwargs() == {"device": "cpu"}

    monkeypatch.delenv("SPACE_ID", raising=False)
    gpu_detector = PlateDetector(settings=Settings(force_cpu=False))
    assert gpu_detector.device_kwargs() == {}
    monkeypatch.setenv("SPACE_ID", "demo-space")
    assert gpu_detector.device_kwargs() == {"device": "cpu"}

    # Build 2-line plate "59V1-79379" + duplicate overlapping '5' with lower conf
    names = {0: "5", 1: "9", 2: "V", 3: "1", 4: "7", 5: "3"}
    char_boxes = [
        _FakeBox([5, 5, 19, 25], 0, 0.92),
        _FakeBox([6, 6, 18, 24], 1, 0.40),  # IoU overlap with '5' -> deduplicated
        _FakeBox([22, 5, 36, 25], 1, 0.91),
        _FakeBox([40, 5, 54, 25], 2, 0.90),
        _FakeBox([58, 5, 72, 25], 3, 0.89),
        _FakeBox([5, 35, 19, 55], 4, 0.88),
        _FakeBox([21, 35, 35, 55], 1, 0.87),
        _FakeBox([37, 35, 51, 55], 5, 0.86),
        _FakeBox([53, 35, 67, 55], 4, 0.85),
        _FakeBox([69, 35, 83, 55], 1, 0.84),
    ]
    fake_plate_model = _FakePlateModel(
        [
            [_FakeBox([10, 10, 120, 80]), _FakeBox([0, 0, 0, 0])],
            [_FakeBox([20, 20, 140, 90])],
        ]
    )
    fake_char_model = _FakeCharModel(names, [char_boxes, [_FakeBox([5, 5, 15, 25], 0, 0.5)]])
    batch_detector = PlateDetector(
        settings=Settings(force_cpu=True),
        plate_model=fake_plate_model,
        char_model=fake_char_model,
    )
    frame = np.full((180, 240, 3), 180, dtype=np.uint8)
    frame[15:75, 15:115] = 40  # texture for Laplacian sharpness

    batch_res = batch_detector.detect_batch([frame, frame])
    assert len(batch_res) == 2
    assert len(fake_plate_model.calls) == 1
    assert fake_plate_model.calls[0][1]["device"] == "cpu"

    first: PlateDetectionResult = batch_res[0]
    assert first.plate_present is True
    assert first.readings == {"59V179379": "59V1-79379"}
    assert "59V179379" in first.plate_crops
    assert first.plate_crops["59V179379"][1].startswith("data:image/jpeg;base64,")
    assert first.reading_confs["59V179379"] > 0.85
    assert first.plate_boxes[0]["valid"] is True

    second = batch_res[1]
    assert second.plate_present is True
    assert second.readings == {}
    assert second.plate_boxes[0]["valid"] is False
    assert batch_detector.detect_batch([]) == []

    # Single detect()
    single_detector = PlateDetector(
        settings=Settings(force_cpu=True),
        plate_model=_FakePlateModel([[_FakeBox([10, 10, 120, 80])]]),
        char_model=_FakeCharModel(names, [char_boxes]),
    )
    single_res = single_detector.detect(frame)
    assert single_res.readings == {"59V179379": "59V1-79379"}


def test_face_service_detect_embed_and_degraded_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeDetector:
        def __init__(self, extract_tensor: torch.Tensor | None = None) -> None:
            self._extract_tensor = extract_tensor
            self.last_image_size: tuple[int, int] | None = None

        def detect(self, image: Any) -> tuple[list[list[float]], list[float | None]]:
            self.last_image_size = image.size
            return (
                [[36.0, 20.0, 108.0, 92.0], [180.0, 40.0, 250.0, 110.0], [10.0, 10.0, 20.0, 20.0]],
                [0.8612, 0.9544, float("nan")],
            )

        def extract(self, image: Any, boxes: Any, save_path: Any = None) -> torch.Tensor | None:
            del image, boxes, save_path
            return self._extract_tensor

    class _FakeEncoder:
        def __call__(self, tensor: torch.Tensor) -> torch.Tensor:
            assert tensor.shape == (1, 3, 160, 160)
            out = torch.zeros((1, 512), dtype=torch.float32)
            out[0, 0] = 3.0
            out[0, 1] = 4.0
            return out

    # CPU downscale (> 360px -> 360px width), confidence desc sort, inverse box scaling
    det = _FakeDetector(extract_tensor=torch.ones((3, 160, 160), dtype=torch.float32))
    svc = FaceService(
        settings=Settings(force_cpu=True),
        detector=det,
        encoder=_FakeEncoder(),
        load_models=False,
    )
    assert svc.device == "cpu"
    assert svc.can_embed is True

    frame = np.zeros((360, 720, 3), dtype=np.uint8)
    faces = svc.detect_from_bgr(frame)
    assert det.last_image_size == (360, 180)
    assert len(faces) == 2
    assert faces[0].confidence == 0.954
    assert faces[0].box == (360, 80, 500, 220)
    assert faces[1].confidence == 0.861
    assert faces[1].box == (72, 40, 216, 184)

    emb_extracted = svc.embed_face(frame, faces[0].box)
    assert emb_extracted is not None
    assert len(emb_extracted) == 512
    assert pytest.approx(np.linalg.norm(emb_extracted), abs=1e-4) == 1.0
    assert pytest.approx(emb_extracted[0], abs=1e-4) == 0.6

    # Fallback direct 160x160 crop when extract() returns None
    det_none = _FakeDetector(extract_tensor=None)
    svc_fallback = FaceService(
        settings=Settings(force_cpu=True),
        detector=det_none,
        encoder=_FakeEncoder(),
        load_models=False,
    )
    emb_fallback = svc_fallback.embed_face(frame, (10, 10, 90, 90))
    assert emb_fallback is not None
    assert len(emb_fallback) == 512
    assert svc_fallback.embed_face(frame, (50, 50, 50, 90)) is None

    # Graceful degradation when InceptionResnetV1 fails to load
    class _BrokenResnet:
        def __init__(self, pretrained: str = "vggface2") -> None:
            del pretrained
            raise OSError("offline weight download error")

    monkeypatch.setattr("src.backend.ai.face_service.MTCNN", lambda **kw: _FakeDetector())
    monkeypatch.setattr("src.backend.ai.face_service.InceptionResnetV1", _BrokenResnet)
    degraded = FaceService(settings=Settings(force_cpu=True), load_models=True)
    assert degraded.can_embed is False
    assert "offline weight download error" in (degraded.encoder_error or "")
    assert degraded.embed_face(frame, (10, 10, 50, 50)) is None


def test_camera_session_and_latch_coordinator() -> None:
    mgr = CameraSessionManager()
    with pytest.raises(ValueError):
        mgr.get_cam(3)

    first_starts = 0
    reconfigures = 0
    all_stopped = 0

    def _on_first() -> None:
        nonlocal first_starts
        first_starts += 1

    def _on_reconf() -> None:
        nonlocal reconfigures
        reconfigures += 1

    def _on_stopped() -> None:
        nonlocal all_stopped
        all_stopped += 1

    assert mgr.start_camera_locked(1, on_first_start=_on_first) == "browser"
    assert first_starts == 1
    assert mgr.running is True
    assert mgr.session_id == 1
    assert mgr.is_dual_cam_mode_locked() is False

    cam1: CameraUnitState = mgr.get_cam(1)
    cam1.observations.append(VoteObservation(1.0, "59V179379", "59V1-79379", 0.9))
    cam1.current_plates = ["59V1-79379"]
    cam1.current_faces = [0.95]
    status1 = cam1.serialize_status()
    assert status1["vote"]["candidate"] == "59V1-79379"
    assert status1["vote"]["vote_count"] == 1

    assert mgr.start_camera_locked(2, on_reconfigure=_on_reconf) == "browser"
    assert reconfigures == 1
    assert mgr.is_dual_cam_mode_locked() is True
    assert len(cam1.observations) == 0

    assert mgr.deactivate_camera_locked(1, on_all_stopped=_on_stopped) is True
    assert mgr.running is True
    assert all_stopped == 0
    assert mgr.deactivate_camera_locked(1) is False
    assert mgr.deactivate_camera_locked(2, on_all_stopped=_on_stopped) is True
    assert mgr.running is False
    assert all_stopped == 1
    assert mgr.session_id == 2

    # LatchCoordinator tests
    coord = LatchCoordinator(Settings())
    vote = VoteResult("59V179379", "59V1-79379", 3, 1.0, 3)
    dummy_frame = np.zeros((40, 40, 3), dtype=np.uint8)

    # Pre-latch lookback: stale face (2.5s ago) trimmed; blurry large face beaten by sharp face
    recent_faces: deque[Any] = deque(
        [
            (7.0, 999.0, 0.99, dummy_frame, (0, 0, 20, 20), 30.0),  # stale (>1.8s before 10.0)
            (9.2, 500.0, 0.95, dummy_frame, (0, 0, 30, 30), 10.0),  # blurry tier 0
            (9.5, 120.0, 0.92, dummy_frame, (0, 0, 15, 15), 25.0),  # sharp tier 2
        ]
    )
    latch = coord.start_latch(
        direction="IN",
        vote=vote,
        plate_image="data:image/jpeg;base64,P",
        plate_cam=2,
        required_face_cam=1,
        now=10.0,
        active_session=None,
        opp_cam_recent_faces=recent_faces,
    )
    assert latch.required_face_cam == 1
    assert len(recent_faces) == 2
    assert coord.best_face is not None
    assert coord.best_face[4] == 25.0

    # Instant ready because best_face conf 0.92 >= 0.88 and sharpness 25.0 >= 22.0
    status_dict = coord.to_status_dict(10.5)
    assert status_dict is not None
    assert status_dict["remaining_seconds"] == 4
    assert status_dict["sampling_face"] is True
    outcome, payload = coord.evaluate(
        now=10.5,
        plate_cam_current_plates=["59V1-79379"],
        req_cam_recent_faces=recent_faces,
    )
    assert outcome == "ready"
    assert payload[0].plate_key == "59V179379"
    assert coord.latched is None
    assert len(recent_faces) == 0

    # Swapped plate cancellation
    coord.start_latch(
        direction="IN",
        vote=vote,
        plate_image=None,
        plate_cam=1,
        required_face_cam=1,
        now=20.0,
        active_session=None,
        opp_cam_recent_faces=deque(),
    )
    outcome, swapped = coord.evaluate(
        now=20.2,
        plate_cam_current_plates=["60A1-11111"],
        req_cam_recent_faces=deque(),
    )
    assert outcome == "swapped"
    assert swapped.plate_key == "59V179379"
    assert coord.latched is None

    # Timeout with blurry face vs missing face
    coord.start_latch(
        direction="OUT",
        vote=vote,
        plate_image=None,
        plate_cam=2,
        required_face_cam=1,
        now=30.0,
        active_session={"id": 1},
        opp_cam_recent_faces=deque([(29.8, 50.0, 0.86, dummy_frame, (0, 0, 10, 10), 11.0)]),
    )
    outcome, timeout_payload = coord.evaluate(
        now=34.5,
        plate_cam_current_plates=[],
        req_cam_recent_faces=deque(),
    )
    assert outcome == "timeout"
    assert timeout_payload[1] == "KHUÔN MẶT BỊ MỜ, VUI LÒNG QUÉT LẠI"

    # Floor sharpness after 0.40s wait
    req_faces = deque([(40.0, 100.0, 0.86, dummy_frame, (0, 0, 10, 10), 16.5)])
    coord.start_latch(
        direction="IN",
        vote=vote,
        plate_image=None,
        plate_cam=2,
        required_face_cam=1,
        now=40.0,
        active_session=None,
        opp_cam_recent_faces=deque(),
    )
    wait_res, _ = coord.evaluate(now=40.2, plate_cam_current_plates=[], req_cam_recent_faces=req_faces)
    assert wait_res == "waiting"
    ready_res, _ = coord.evaluate(now=40.65, plate_cam_current_plates=[], req_cam_recent_faces=req_faces)
    assert ready_res == "ready"


def test_management_service_cache_mirror_fallback_and_reconnect() -> None:
    base_now = datetime(2026, 11, 26, 14, 0, 0)
    clock = {"now": base_now, "mono": 0.0}

    settings = Settings(
        seed_demo_data=True,
        db_retry_seconds=0.05,
        overview_cache_max_size=2,
        session_case_cache_max_size=2,
    )
    mirror = WarmDatabaseMirror(now_fn=lambda: clock["now"])
    metrics = MetricsRegistry()

    raw_rows: dict[int, dict[str, Any]] = {
        1: {
            "id": 1,
            "plate_number": "59V1-79379",
            "plate_key": "59V179379",
            "direction": "IN",
            "parking_status": "IN_PARKING",
            "entry_record_id": None,
            "fee_amount": 2000,
            "recognized_at": base_now - timedelta(minutes=10),
            "vote_count": 3,
            "sample_count": 3,
            "consensus_rate": 1.0,
            "face_detected": True,
            "face_confidence": 0.96,
            "face_embedding": True,
            "face_match_score": None,
            "plate_image": "data:image/jpeg;base64,P1",
            "face_image": "data:image/jpeg;base64,F1",
            "camera_index": 2,
        }
    }

    fake_repo = mock.MagicMock()
    fake_repo.settings = settings

    def _init_repo(warm_mirror: WarmDatabaseMirror | None = None, seeder: Any = None) -> None:
        if seeder is not None:
            seeder(fake_repo)
        if warm_mirror is not None:
            cur = mock.MagicMock()
            cur.fetchall.side_effect = [
                [raw_rows[1]],
                [{"id": 1, "plate_image": "data:image/jpeg;base64,P1", "face_image": "data:image/jpeg;base64,F1"}],
                [{"id": 1, "plate_number": "59V1-79379", "plate_key": "59V179379", "recognized_at": base_now, "face_embedding": None}],
            ]
            warm_mirror.load_from_cursor(cur)

    fake_repo.initialize.side_effect = _init_repo
    fake_repo.insert_plate_record.return_value = (2, 0.91)
    fake_repo.fetch_overview.return_value = {
        "stats": {"total_records": 2, "today_records": 2, "in_parking": 0, "total_in": 1, "total_out": 1},
        "revenue": {"unit_price": 2000, "today": {"tickets": 1, "revenue": 2000}, "month": {"tickets": 1, "revenue": 2000}, "year": {"tickets": 1, "revenue": 2000}, "total": {"tickets": 1, "revenue": 2000}, "daily": [], "monthly": [], "yearly": []},
        "matched": 1,
        "page": 1,
        "records": [raw_rows[1]],
    }
    fake_repo.fetch_parking_session_case.return_value = {
        "target_id": 1,
        "plate_number": "59V1-79379",
        "checkin_record": raw_rows[1],
        "checkout_record": None,
        "in_parking_status": "IN_PARKING",
        "session_closed_missing_exit": False,
    }

    svc = ManagementService(
        repository=fake_repo,
        warm_mirror=mirror,
        settings=settings,
        metrics=metrics,
        now_fn=lambda: clock["now"],
        monotonic_fn=lambda: clock["mono"],
    )

    with mock.patch(
        "src.backend.services.management_service.seed_demo_records_if_empty",
        return_value=38,
    ) as seed_mock:
        svc.connect_database()
        seed_mock.assert_called_once_with(fake_repo, enabled=True)

    assert svc.database_ready is True
    assert svc.records_version == 1
    assert mirror.ready is True

    # Active session hits RAM mirror (0 repo queries)
    sess, db_ok = svc.get_active_parking_session("59V1-79379")
    assert db_ok is True
    assert sess is not None and sess["id"] == 1
    assert fake_repo.find_active_parking_session.call_count == 0

    # Store OUT record -> updates match score, mirror, version, metrics
    out_rec = {
        "plate_number": "59V1-79379",
        "direction": "OUT",
        "entry_record_id": 1,
        "recognized_at": base_now,
        "vote_count": 3,
        "sample_count": 3,
        "consensus_rate": 1.0,
        "face_detected": True,
        "face_confidence": 0.94,
        "face_embedding": [0.1] * 512,
        "plate_image": "data:image/jpeg;base64,P2",
        "face_image": "data:image/jpeg;base64,F2",
        "camera_index": 1,
    }
    assert svc.store_record(out_rec) is True
    assert out_rec["face_match_score"] == 0.91
    assert svc.records_version == 2
    assert metrics.get_counter("db_commits_succeeded") == 1

    # Overview formatted via presenter and cached
    ov = svc.get_cached_overview(include_records=True, include_revenue=True)
    assert ov["records"][0]["Biển số"] == "59V1-79379"
    assert ov["records"][0]["Đối chiếu"] == "Khớp (91%)"
    assert ov["revenue"]["today"]["revenue"] == 2000

    # Zero-DB revenue tab when summary cached
    rev_only = svc.get_cached_overview(include_records=False, include_revenue=True)
    assert rev_only["records"] == []
    assert rev_only["revenue"]["today"]["tickets"] == 1
    assert fake_repo.fetch_overview.call_count == 0

    # Session case formatted via presenter and cached
    case1 = svc.get_cached_session_case(1)
    assert case1 is not None
    assert case1["checkin_row"]["ID"] == 1
    assert case1["checkout_row"]["ID"] == 2
    assert fake_repo.fetch_parking_session_case.call_count == 0

    # When mirror returns None (e.g. not ready / evicted), falls back to repository
    mirror.ready = False
    ov_fb = svc.get_cached_overview(q="59V1", include_records=True)
    assert ov_fb["records"][0]["ID"] == 1
    assert fake_repo.fetch_overview.call_count == 1
    case_fb = svc.get_cached_session_case(99)
    assert case_fb is not None
    assert fake_repo.fetch_parking_session_case.call_count == 1

    # Store failure flips database_ready=False and increments failure metric
    fake_repo.insert_plate_record.side_effect = DatabaseOperationError("lost mysql")
    assert svc.store_record(dict(out_rec)) is False
    assert svc.database_ready is False
    assert "lost mysql" in (svc.database_error or "")
    assert metrics.get_counter("db_commits_failed") == 1

    # Active session returns (None, False) when DB not ready
    assert svc.get_active_parking_session("59V1-79379") == (None, False)

    # Background reconnect recovers DB automatically
    fake_repo.insert_plate_record.side_effect = None
    svc.start_reconnect_loop()
    try:
        for _ in range(40):
            clock["mono"] += 0.1
            if svc.database_ready:
                break
            time.sleep(0.02)
        assert svc.database_ready is True
    finally:
        svc.stop_reconnect_loop(timeout=2.0)
