"""Shared raw-record normalization, filtering, pagination, and session-case helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import math
from typing import Any

from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.storage.mysql_client import now_vn

SELECT_RECORD_COLS = """
    SELECT id, plate_number, plate_key, direction, parking_status, entry_record_id,
           fee_amount, recognized_at, vote_count, sample_count,
           consensus_rate, face_detected, face_confidence,
           face_embedding IS NOT NULL AS face_embedding, face_match_score,
           plate_image, face_image, camera_index
    FROM plate_recognition_history
"""

RAW_RECORD_KEYS = (
    "id",
    "plate_number",
    "plate_key",
    "direction",
    "parking_status",
    "entry_record_id",
    "fee_amount",
    "recognized_at",
    "vote_count",
    "sample_count",
    "consensus_rate",
    "face_detected",
    "face_confidence",
    "face_embedding",
    "face_match_score",
    "plate_image",
    "face_image",
    "camera_index",
)


def coerce_dt(val: Any, now_fn: Callable[[], datetime] = now_vn) -> datetime:
    """Coerce datetime or timestamp string into a naive datetime."""
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    try:
        return datetime.strptime(str(val)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return now_fn()


def format_timestamp_str(val: Any, now_fn: Callable[[], datetime] = now_vn) -> str:
    """Format a timestamp value into canonical `YYYY-MM-DD HH:MM:SS` string."""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    if val is None:
        return now_fn().strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


def normalize_raw_record(
    row: dict[str, Any],
    *,
    images_loaded: bool = True,
    now_fn: Callable[[], datetime] = now_vn,
) -> dict[str, Any]:
    """Normalize a database row or input dict into the 18-field raw domain dict."""
    plate_number = str(row.get("plate_number") or "")
    plate_key = str(row.get("plate_key") or "") or clean_plate_key(plate_number)
    raw_entry = row.get("entry_record_id")
    raw_conf = row.get("face_confidence")
    raw_match = row.get("face_match_score")

    return {
        "id": int(row["id"]),
        "plate_number": plate_number,
        "plate_key": plate_key,
        "direction": str(row.get("direction") or "IN").upper(),
        "parking_status": str(row.get("parking_status") or "IN_PARKING").upper(),
        "entry_record_id": int(raw_entry) if raw_entry is not None else None,
        "fee_amount": int(row.get("fee_amount") or 0),
        "recognized_at": coerce_dt(row.get("recognized_at"), now_fn=now_fn),
        "vote_count": int(row.get("vote_count") or 0),
        "sample_count": int(row.get("sample_count") or 0),
        "consensus_rate": float(row.get("consensus_rate") or 0.0),
        "face_detected": bool(row.get("face_detected")),
        "face_confidence": float(raw_conf) if raw_conf is not None else None,
        "face_embedding": bool(row.get("face_embedding")),
        "face_match_score": float(raw_match) if raw_match is not None else None,
        "plate_image": row.get("plate_image") if images_loaded else None,
        "face_image": row.get("face_image") if images_loaded else None,
        "camera_index": int(row.get("camera_index") or 0),
    }


def strip_internal_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Return a clean raw record dict containing only the 18 public storage fields."""
    return {key: item[key] for key in RAW_RECORD_KEYS}


def matched_from_stats(stats: dict[str, Any], status_filter: str) -> int:
    """Compute matched count for unfiltered overview tabs from precomputed stats."""
    if status_filter == "in_parking":
        return int(stats.get("in_parking") or 0)
    if status_filter == "direction_in":
        return int(stats.get("total_in") or 0)
    if status_filter == "direction_out":
        return int(stats.get("total_out") or 0)
    return int(stats.get("total_records") or 0)


def is_face_mismatch_score(score: Any, match_threshold: float) -> bool:
    """Return True when a numeric face match score falls below threshold."""
    return score is not None and float(score) < match_threshold


def compute_pagination(
    matched: int,
    limit: int | None,
    page: int,
    page_size: int,
) -> tuple[int, int, int]:
    """Return `(effective_limit, safe_page, effective_offset)` with bounds clamping."""
    if limit is not None:
        return max(1, int(limit)), 1, 0
    effective_limit = max(1, int(page_size))
    total_pages = max(1, math.ceil(matched / effective_limit)) if matched > 0 else 1
    safe_page = min(max(1, int(page)), total_pages)
    effective_offset = (safe_page - 1) * effective_limit
    return effective_limit, safe_page, effective_offset


def build_session_case_payload(
    target: dict[str, Any],
    checkin_raw: dict[str, Any] | None,
    checkout_raw: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble a raw lost-vehicle session-case dict (without UI formatting)."""
    in_status = (
        str(checkin_raw.get("parking_status") or "").upper() if checkin_raw else ""
    )
    session_closed_missing_exit = bool(
        checkin_raw is not None
        and checkout_raw is None
        and in_status != "IN_PARKING"
    )
    plate_number = (
        (checkin_raw and checkin_raw.get("plate_number"))
        or (checkout_raw and checkout_raw.get("plate_number"))
        or target.get("plate_number")
        or "-"
    )
    return {
        "target_id": int(target["id"]),
        "plate_number": plate_number,
        "checkin_record": checkin_raw,
        "checkout_record": checkout_raw,
        "in_parking_status": in_status,
        "session_closed_missing_exit": session_closed_missing_exit,
    }
