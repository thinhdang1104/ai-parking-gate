"""API presenters converting raw storage dicts into Vietnamese UI payloads (ADR-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.backend.config import FACE_MATCH_THRESHOLD


def format_recognition_time(value: Any) -> str:
    """Format a recognition timestamp into `YYYY-MM-DD HH:MM:SS`."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if value is None:
        return ""
    return str(value)


def format_vnd(amount: int | float | None) -> str:
    """Format VND amount as dot-separated currency string or `'-'` when <= 0."""
    val = int(round(float(amount or 0)))
    if val <= 0:
        return "-"
    return f"{val:,}".replace(",", ".") + " đ"


def format_direction_label(direction: str | None) -> str:
    """Format gate direction code (`IN`/`OUT`) into Vietnamese display label."""
    if str(direction or "IN").upper() == "OUT":
        return "Ra bãi"
    return "Vào bãi"


def format_parking_status_label(
    direction: str | None,
    parking_status: str | None,
) -> str:
    """Format parking status code into Vietnamese display label."""
    status = str(parking_status or "").upper()
    if status == "IN_PARKING":
        return "Đang gửi"
    if str(direction or "IN").upper() == "OUT" or status == "EXITED":
        return "Đã ra bãi"
    return "Đã lấy xe"


def format_face_label(face_detected: Any, face_confidence: Any) -> str:
    """Format face detection presence and optional percentage confidence."""
    if face_detected and face_confidence is not None:
        return f"Có ({float(face_confidence):.0%})"
    if face_detected:
        return "Có"
    return "Không rõ"


def format_match_label(
    direction: str | None,
    face_match_score: Any,
    has_embedding: bool,
    match_threshold: float = FACE_MATCH_THRESHOLD,
) -> str:
    """Format FaceNet similarity score or enrollment state in Vietnamese."""
    dir_code = str(direction or "IN").upper()
    if face_match_score is not None:
        score = float(face_match_score)
        verdict = "Khớp" if score >= match_threshold else "Lệch"
        return f"{verdict} ({max(score, 0.0):.0%})"
    if dir_code == "IN":
        return "Đã lưu mẫu mặt" if has_embedding else "-"
    return "Chưa đối chiếu" if has_embedding else "-"


def format_record_row(
    record_id: int | Any,
    record: dict[str, Any],
    match_threshold: float = FACE_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Convert a raw storage record dict into `ParkingRecordRow` API payload."""
    direction = str(record.get("direction") or "IN").upper()
    parking_status = str(record.get("parking_status") or "IN_PARKING").upper()
    has_emb = bool(record.get("face_embedding"))
    raw_entry_id = record.get("entry_record_id")
    entry_record_id = int(raw_entry_id) if raw_entry_id is not None else None
    raw_match = record.get("face_match_score")
    face_match_score = float(raw_match) if raw_match is not None else None

    return {
        "ID": int(record_id),
        "Biển số": str(record["plate_number"]),
        "direction_code": direction,
        "parking_status_code": parking_status,
        "entry_record_id": entry_record_id,
        "face_match_score": face_match_score,
        "Luồng": format_direction_label(direction),
        "Trạng thái bãi": format_parking_status_label(direction, parking_status),
        "Thời gian nhận diện": format_recognition_time(record["recognized_at"]),
        "Khuôn mặt": format_face_label(
            record.get("face_detected"), record.get("face_confidence")
        ),
        "Đối chiếu": format_match_label(
            direction,
            record.get("face_match_score"),
            has_emb,
            match_threshold=match_threshold,
        ),
        "plate_image": record.get("plate_image"),
        "face_image": record.get("face_image"),
    }


def present_overview(
    raw_overview: dict[str, Any],
    match_threshold: float = FACE_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Present a raw overview response by formatting all `records` rows."""
    raw_records = raw_overview.get("records") or []
    return {
        "stats": raw_overview.get("stats"),
        "revenue": raw_overview.get("revenue"),
        "matched": int(raw_overview.get("matched") or 0),
        "page": int(raw_overview.get("page") or 1),
        "records": [
            format_record_row(rec["id"], rec, match_threshold=match_threshold)
            for rec in raw_records
        ],
    }


def present_session_case(
    raw_case: dict[str, Any],
    match_threshold: float = FACE_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """Present a raw session-case payload into `SessionCaseResponse` shape."""
    checkin_rec = raw_case.get("checkin_record")
    checkout_rec = raw_case.get("checkout_record")
    return {
        "target_id": int(raw_case["target_id"]),
        "plate_number": raw_case["plate_number"],
        "checkin_row": (
            format_record_row(
                checkin_rec["id"], checkin_rec, match_threshold=match_threshold
            )
            if checkin_rec is not None
            else None
        ),
        "checkout_row": (
            format_record_row(
                checkout_rec["id"], checkout_rec, match_threshold=match_threshold
            )
            if checkout_rec is not None
            else None
        ),
        "in_parking_status": raw_case["in_parking_status"],
        "session_closed_missing_exit": bool(raw_case["session_closed_missing_exit"]),
    }
