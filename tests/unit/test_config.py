"""Unit tests for Settings defaults, env loading, and domain model helpers."""

from __future__ import annotations

from dataclasses import fields

import pytest

from src.backend import config
from src.backend.domain.models import (
    FaceDetection,
    LatchState,
    ParkingRecord,
    PlateBox,
    SecurityAlert,
)


def test_settings_defaults_match_module_constants() -> None:
    settings = config.load_settings(env={}, load_env_file=False)

    assert settings.mysql_host == "127.0.0.1"
    assert settings.mysql_port == 3306
    assert settings.mysql_user == "root"
    assert settings.mysql_password == ""
    assert settings.mysql_database == "defaultdb"
    assert settings.force_cpu is False
    assert settings.save_disk_snapshots is False
    assert settings.seed_demo_data is False
    assert settings.log_level == "INFO"

    assert settings.base_dir == config.BASE_DIR
    assert settings.frontend_dir == config.BASE_DIR / "src" / "frontend"
    assert settings.plate_model_path == config.BASE_DIR / "weights" / "plate_best.pt"
    assert settings.char_model_path == config.BASE_DIR / "weights" / "chars_best.pt"
    assert settings.snapshot_dir == config.BASE_DIR / "data" / "snapshots"

    assert settings.conf_plate == 0.40
    assert settings.conf_char == 0.35
    assert settings.plate_imgsz == 512
    assert settings.char_imgsz == 320
    assert settings.char_iou_dedup_threshold == 0.55

    assert settings.vote_window_seconds == 3.0
    assert settings.vote_sample_interval_seconds == 0.08
    assert settings.vote_min_samples == 3
    assert settings.vote_min_share == 0.70
    assert settings.fast_vote_min_samples == 2
    assert settings.fast_vote_min_char_conf == 0.75

    assert settings.face_match_threshold == 0.65
    assert settings.embedding_size == 512
    assert settings.face_min_confidence == 0.85
    assert settings.face_instant_confidence == 0.88
    assert settings.face_floor_sharpness == 15.0
    assert settings.face_min_sharpness == 22.0
    assert settings.face_instant_sharpness == 22.0
    assert settings.face_sample_window_seconds == 0.15
    assert settings.face_max_sharpness_wait_seconds == 0.40
    assert settings.face_pre_latch_lookback_seconds == 1.80
    assert settings.face_recent_buffer_seconds == 2.00
    assert settings.latch_timeout_seconds == 4.0

    assert settings.max_browser_frame_b64_chars == 2_500_000
    assert settings.plate_lost_reset_seconds == 1.5
    assert settings.plate_cooldown_seconds == 20.0
    assert settings.cross_direction_cooldown_seconds == 6.0
    assert settings.face_idle_every_n_frames == 2
    assert settings.db_retry_seconds == 15.0
    assert settings.overview_cache_max_size == 20
    assert settings.session_case_cache_max_size == 64
    assert settings.max_plate_crops_per_cam == 8
    assert settings.warm_mirror_max_image_records == 600
    assert settings.parking_fee_vnd == 2000
    assert settings.mysql_connect_timeout == 8
    assert settings.mysql_read_timeout == 10
    assert settings.mysql_write_timeout == 10


def test_load_settings_parses_env_flags_and_validates_port() -> None:
    settings = config.load_settings(
        env={
            "MYSQL_HOST": "localhost",
            "MYSQL_PORT": "3307",
            "MYSQL_USER": "parking",
            "MYSQL_PASSWORD": "secret",
            "MYSQL_DATABASE": "parking_db",
            "FORCE_CPU": "1",
            "SAVE_DISK_SNAPSHOTS": "true",
            "SEED_DEMO_DATA": "yes",
            "LOG_LEVEL": "debug",
        },
        load_env_file=False,
    )
    assert settings.mysql_host == "localhost"
    assert settings.mysql_port == 3307
    assert settings.mysql_user == "parking"
    assert settings.mysql_password == "secret"
    assert settings.mysql_database == "parking_db"
    assert settings.force_cpu is True
    assert settings.save_disk_snapshots is True
    assert settings.seed_demo_data is True
    assert settings.log_level == "DEBUG"

    with pytest.raises(ValueError, match="MYSQL_PORT"):
        config.load_settings(env={"MYSQL_PORT": "abc"}, load_env_file=False)
    with pytest.raises(ValueError, match="MYSQL_PORT"):
        config.load_settings(env={"MYSQL_PORT": "70000"}, load_env_file=False)


def test_domain_models_contracts_and_helpers() -> None:
    assert len(fields(ParkingRecord)) == 19
    rec = ParkingRecord(plate_number="59V1-79379", plate_key="59V179379", camera_index=2)
    rec_dict = rec.to_dict()
    assert len(rec_dict) == 19
    assert rec_dict["plate_number"] == "59V1-79379"
    assert rec_dict["fee_amount"] == 2000

    face = FaceDetection(box=(10, 20, 60, 80), confidence=0.95)
    assert face.area == 50 * 60
    assert FaceDetection(box=(50, 50, 10, 10), confidence=0.9).area == 0

    box = PlateBox(x1=0.1, y1=0.2, x2=0.5, y2=0.6, label="59V1-79379", valid=True)
    assert box.to_dict() == {
        "x1": 0.1,
        "y1": 0.2,
        "x2": 0.5,
        "y2": 0.6,
        "label": "59V1-79379",
        "valid": True,
    }

    latch = LatchState(
        direction="OUT",
        plate_key="59V179379",
        plate_number="59V1-79379",
        plate_image=None,
        vote_count=3,
        sample_count=3,
        consensus_rate=1.0,
        plate_cam=1,
        required_face_cam=2,
        latched_at=100.0,
    )
    assert latch.to_status_dict(remaining_seconds=3, sampling_face=True) == {
        "direction": "OUT",
        "plate_number": "59V1-79379",
        "plate_cam": 1,
        "required_face_cam": 2,
        "remaining_seconds": 3,
        "sampling_face": True,
    }

    alert = SecurityAlert(
        plate_key="59V179379",
        plate_number="59V1-79379",
        entry_time="2026-01-01 08:00:00",
        match_score_pct="42%",
    )
    assert alert.to_status_dict() == {
        "plate_number": "59V1-79379",
        "entry_time": "2026-01-01 08:00:00",
        "match_score_pct": "42%",
    }
