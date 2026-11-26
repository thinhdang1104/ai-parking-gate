"""Unit tests for API presenters (ADR-02 Vietnamese formatting layer)."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from src.backend.api.presenters import (
    format_direction_label,
    format_face_label,
    format_match_label,
    format_parking_status_label,
    format_recognition_time,
    format_record_row,
    format_vnd,
    present_overview,
    present_session_case,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "gate_payloads.schema.json"


def _sample_raw_record(**overrides) -> dict:
    base = {
        "id": 101,
        "plate_number": "59V1-79379",
        "plate_key": "59V179379",
        "direction": "IN",
        "parking_status": "IN_PARKING",
        "entry_record_id": None,
        "fee_amount": 2000,
        "recognized_at": datetime(2026, 11, 26, 8, 15, 30),
        "vote_count": 3,
        "sample_count": 3,
        "consensus_rate": 1.0,
        "face_detected": True,
        "face_confidence": 0.95,
        "face_embedding": True,
        "face_match_score": None,
        "plate_image": "data:image/jpeg;base64,PLATE",
        "face_image": "data:image/jpeg;base64,FACE",
        "camera_index": 2,
    }
    base.update(overrides)
    return base


def test_format_recognition_time_and_vnd() -> None:
    assert format_recognition_time(datetime(2026, 11, 26, 9, 5, 7)) == "2026-11-26 09:05:07"
    assert format_recognition_time("2026-11-26 09:05:07") == "2026-11-26 09:05:07"
    assert format_recognition_time(None) == ""

    assert format_vnd(None) == "-"
    assert format_vnd(0) == "-"
    assert format_vnd(-500) == "-"
    assert format_vnd(2000) == "2.000 đ"
    assert format_vnd(50000) == "50.000 đ"
    assert format_vnd(1234567) == "1.234.567 đ"


def test_format_direction_and_parking_status_labels() -> None:
    assert format_direction_label("IN") == "Vào bãi"
    assert format_direction_label("in") == "Vào bãi"
    assert format_direction_label(None) == "Vào bãi"
    assert format_direction_label("OUT") == "Ra bãi"
    assert format_direction_label("out") == "Ra bãi"

    assert format_parking_status_label("IN", "IN_PARKING") == "Đang gửi"
    assert format_parking_status_label("IN", "COMPLETED") == "Đã lấy xe"
    assert format_parking_status_label("OUT", "EXITED") == "Đã ra bãi"
    assert format_parking_status_label("IN", "EXITED") == "Đã ra bãi"


def test_format_face_and_match_labels() -> None:
    assert format_face_label(True, 0.95) == "Có (95%)"
    assert format_face_label(True, None) == "Có"
    assert format_face_label(False, 0.99) == "Không rõ"
    assert format_face_label(0, None) == "Không rõ"

    assert format_match_label("OUT", 0.92, True) == "Khớp (92%)"
    assert format_match_label("OUT", 0.65, True) == "Khớp (65%)"
    assert format_match_label("OUT", 0.45, True) == "Lệch (45%)"
    assert format_match_label("OUT", -0.15, True) == "Lệch (0%)"
    assert format_match_label("OUT", 0.70, True, match_threshold=0.75) == "Lệch (70%)"
    assert format_match_label("IN", None, True) == "Đã lưu mẫu mặt"
    assert format_match_label("IN", None, False) == "-"
    assert format_match_label("OUT", None, True) == "Chưa đối chiếu"
    assert format_match_label("OUT", None, False) == "-"


def test_format_record_row_matches_schema_contract() -> None:
    raw = _sample_raw_record(
        id=205,
        direction="OUT",
        parking_status="EXITED",
        entry_record_id=101,
        fee_amount=0,
        face_match_score=0.884,
    )
    row = format_record_row(raw["id"], raw)

    assert row == {
        "ID": 205,
        "Biển số": "59V1-79379",
        "direction_code": "OUT",
        "parking_status_code": "EXITED",
        "entry_record_id": 101,
        "face_match_score": 0.884,
        "Luồng": "Ra bãi",
        "Trạng thái bãi": "Đã ra bãi",
        "Thời gian nhận diện": "2026-11-26 08:15:30",
        "Khuôn mặt": "Có (95%)",
        "Đối chiếu": "Khớp (88%)",
        "plate_image": "data:image/jpeg;base64,PLATE",
        "face_image": "data:image/jpeg;base64,FACE",
    }

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    row_schema = schema["$defs"]["ParkingRecordRow"]
    assert set(row.keys()) == set(row_schema["required"])


def test_present_overview_and_session_case() -> None:
    rec_in = _sample_raw_record(id=10, parking_status="COMPLETED")
    rec_out = _sample_raw_record(
        id=11,
        direction="OUT",
        parking_status="EXITED",
        entry_record_id=10,
        fee_amount=0,
        face_match_score=0.42,
    )

    overview = present_overview(
        {
            "stats": {"total_records": 2, "in_parking": 0},
            "revenue": {"unit_price": 2000, "total": {"tickets": 1, "revenue": 2000}},
            "matched": 2,
            "page": 1,
            "records": [rec_out, rec_in],
        }
    )
    assert overview["matched"] == 2
    assert overview["page"] == 1
    assert [r["ID"] for r in overview["records"]] == [11, 10]
    assert overview["records"][0]["Đối chiếu"] == "Lệch (42%)"
    assert overview["records"][1]["Trạng thái bãi"] == "Đã lấy xe"

    case = present_session_case(
        {
            "target_id": 10,
            "plate_number": "59V1-79379",
            "checkin_record": rec_in,
            "checkout_record": None,
            "in_parking_status": "COMPLETED",
            "session_closed_missing_exit": True,
        }
    )
    assert case["target_id"] == 10
    assert case["plate_number"] == "59V1-79379"
    assert case["checkin_row"]["ID"] == 10
    assert case["checkout_row"] is None
    assert case["in_parking_status"] == "COMPLETED"
    assert case["session_closed_missing_exit"] is True
