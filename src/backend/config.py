"""Centralized configuration, thresholds, and environment settings for DATN2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional fallback when python-dotenv absent
    load_dotenv = None

# Paths
BASE_DIR: Path = Path(__file__).resolve().parents[2]
FRONTEND_DIR: Path = BASE_DIR / "src" / "frontend"
WEIGHTS_DIR: Path = BASE_DIR / "weights"
PLATE_MODEL_PATH: Path = WEIGHTS_DIR / "plate_best.pt"
CHAR_MODEL_PATH: Path = WEIGHTS_DIR / "chars_best.pt"
DATA_DIR: Path = BASE_DIR / "data"
SNAPSHOT_DIR: Path = DATA_DIR / "snapshots"

# YOLO inference thresholds
CONF_PLATE: float = 0.40
CONF_CHAR: float = 0.35
PLATE_IMGSZ: int = 512
CHAR_IMGSZ: int = 320
CHAR_IOU_DEDUP_THRESHOLD: float = 0.55

# Plate consensus voting
VOTE_WINDOW_SECONDS: float = 3.0
VOTE_SAMPLE_INTERVAL_SECONDS: float = 0.08
VOTE_MIN_SAMPLES: int = 3
VOTE_MIN_SHARE: float = 0.70
FAST_VOTE_MIN_SAMPLES: int = 2
FAST_VOTE_MIN_CHAR_CONF: float = 0.75

# Face verification & Two-Phase Latch
FACE_MATCH_THRESHOLD: float = 0.65
EMBEDDING_SIZE: int = 512
FACE_MIN_CONFIDENCE: float = 0.85
FACE_INSTANT_CONFIDENCE: float = 0.88
FACE_FLOOR_SHARPNESS: float = 15.0
FACE_MIN_SHARPNESS: float = 22.0
FACE_INSTANT_SHARPNESS: float = 22.0
FACE_SAMPLE_WINDOW_SECONDS: float = 0.15
FACE_MAX_SHARPNESS_WAIT_SECONDS: float = 0.40
FACE_PRE_LATCH_LOOKBACK_SECONDS: float = 1.80
FACE_RECENT_BUFFER_SECONDS: float = 2.00
LATCH_TIMEOUT_SECONDS: float = 4.0

# Limits, cooldowns, caches, and fee
MAX_BROWSER_FRAME_B64_CHARS: int = 2_500_000
PLATE_LOST_RESET_SECONDS: float = 1.5
PLATE_COOLDOWN_SECONDS: float = 20.0
CROSS_DIRECTION_COOLDOWN_SECONDS: float = 6.0
FACE_IDLE_EVERY_N_FRAMES: int = 2
DB_RETRY_SECONDS: float = 15.0
OVERVIEW_CACHE_MAX_SIZE: int = 20
SESSION_CASE_CACHE_MAX_SIZE: int = 64
MAX_PLATE_CROPS_PER_CAM: int = 8
WARM_MIRROR_MAX_IMAGE_RECORDS: int = 600
PARKING_FEE_VND: int = 2000

# MySQL connection timeouts (seconds)
MYSQL_CONNECT_TIMEOUT: int = 8
MYSQL_READ_TIMEOUT: int = 10
MYSQL_WRITE_TIMEOUT: int = 10


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_port(raw: str | None, default: int = 3306) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        port = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"MYSQL_PORT must be an integer, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"MYSQL_PORT must be in 1..65535, got {port}")
    return port


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime settings resolved from environment and defaults."""

    # Environment / runtime
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "defaultdb"
    force_cpu: bool = False
    save_disk_snapshots: bool = False
    seed_demo_data: bool = False
    log_level: str = "INFO"

    # Paths
    base_dir: Path = BASE_DIR
    frontend_dir: Path = FRONTEND_DIR
    weights_dir: Path = WEIGHTS_DIR
    plate_model_path: Path = PLATE_MODEL_PATH
    char_model_path: Path = CHAR_MODEL_PATH
    data_dir: Path = DATA_DIR
    snapshot_dir: Path = SNAPSHOT_DIR

    # YOLO
    conf_plate: float = CONF_PLATE
    conf_char: float = CONF_CHAR
    plate_imgsz: int = PLATE_IMGSZ
    char_imgsz: int = CHAR_IMGSZ
    char_iou_dedup_threshold: float = CHAR_IOU_DEDUP_THRESHOLD

    # Voting
    vote_window_seconds: float = VOTE_WINDOW_SECONDS
    vote_sample_interval_seconds: float = VOTE_SAMPLE_INTERVAL_SECONDS
    vote_min_samples: int = VOTE_MIN_SAMPLES
    vote_min_share: float = VOTE_MIN_SHARE
    fast_vote_min_samples: int = FAST_VOTE_MIN_SAMPLES
    fast_vote_min_char_conf: float = FAST_VOTE_MIN_CHAR_CONF

    # Face & Latch
    face_match_threshold: float = FACE_MATCH_THRESHOLD
    embedding_size: int = EMBEDDING_SIZE
    face_min_confidence: float = FACE_MIN_CONFIDENCE
    face_instant_confidence: float = FACE_INSTANT_CONFIDENCE
    face_floor_sharpness: float = FACE_FLOOR_SHARPNESS
    face_min_sharpness: float = FACE_MIN_SHARPNESS
    face_instant_sharpness: float = FACE_INSTANT_SHARPNESS
    face_sample_window_seconds: float = FACE_SAMPLE_WINDOW_SECONDS
    face_max_sharpness_wait_seconds: float = FACE_MAX_SHARPNESS_WAIT_SECONDS
    face_pre_latch_lookback_seconds: float = FACE_PRE_LATCH_LOOKBACK_SECONDS
    face_recent_buffer_seconds: float = FACE_RECENT_BUFFER_SECONDS
    latch_timeout_seconds: float = LATCH_TIMEOUT_SECONDS

    # Limits, cooldowns, caches, fee
    max_browser_frame_b64_chars: int = MAX_BROWSER_FRAME_B64_CHARS
    plate_lost_reset_seconds: float = PLATE_LOST_RESET_SECONDS
    plate_cooldown_seconds: float = PLATE_COOLDOWN_SECONDS
    cross_direction_cooldown_seconds: float = CROSS_DIRECTION_COOLDOWN_SECONDS
    face_idle_every_n_frames: int = FACE_IDLE_EVERY_N_FRAMES
    db_retry_seconds: float = DB_RETRY_SECONDS
    overview_cache_max_size: int = OVERVIEW_CACHE_MAX_SIZE
    session_case_cache_max_size: int = SESSION_CASE_CACHE_MAX_SIZE
    max_plate_crops_per_cam: int = MAX_PLATE_CROPS_PER_CAM
    warm_mirror_max_image_records: int = WARM_MIRROR_MAX_IMAGE_RECORDS
    parking_fee_vnd: int = PARKING_FEE_VND

    # MySQL timeouts
    mysql_connect_timeout: int = MYSQL_CONNECT_TIMEOUT
    mysql_read_timeout: int = MYSQL_READ_TIMEOUT
    mysql_write_timeout: int = MYSQL_WRITE_TIMEOUT


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    env_file: Path | None = None,
    load_env_file: bool = True,
) -> Settings:
    """Load Settings from environment mapping (and optional .env file)."""
    if env is None:
        if load_env_file and load_dotenv is not None:
            load_dotenv(env_file or (BASE_DIR / ".env"), override=False)
        source: Mapping[str, str] = os.environ
    else:
        source = env

    raw_level = source.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"

    return Settings(
        mysql_host=source.get("MYSQL_HOST", "127.0.0.1").strip() or "127.0.0.1",
        mysql_port=_parse_port(source.get("MYSQL_PORT"), default=3306),
        mysql_user=source.get("MYSQL_USER", "root").strip() or "root",
        mysql_password=source.get("MYSQL_PASSWORD", ""),
        mysql_database=source.get("MYSQL_DATABASE", "defaultdb").strip() or "defaultdb",
        force_cpu=_parse_bool(source.get("FORCE_CPU"), default=False),
        save_disk_snapshots=_parse_bool(source.get("SAVE_DISK_SNAPSHOTS"), default=False),
        seed_demo_data=_parse_bool(source.get("SEED_DEMO_DATA"), default=False),
        log_level=raw_level,
    )
