"""Integration tests for WarmDatabaseMirror (RAM sync, eviction, parity)."""

from __future__ import annotations

from datetime import datetime, timedelta
import threading
from unittest import mock

import pytest

from src.backend.domain.face_math import embedding_to_bytes
from src.backend.storage import WarmDatabaseMirror


def _cursor_row(
    rid: int,
    plate: str,
    direction: str,
    status: str,
    rec_at: datetime,
    *,
    entry_record_id: int | None = None,
    fee_amount: int | None = None,
    match_score: float | None = None,
    plate_image: str | None = "data:image/jpeg;base64,P",
    face_image: str | None = "data:image/jpeg;base64,F",
) -> dict:
    return {
        "id": rid,
        "plate_number": plate,
        "plate_key": plate.replace("-", ""),
        "direction": direction,
        "parking_status": status,
        "entry_record_id": entry_record_id,
        "fee_amount": (0 if direction == "OUT" else 2000) if fee_amount is None else fee_amount,
        "recognized_at": rec_at,
        "vote_count": 3,
        "sample_count": 3,
        "consensus_rate": 1.0,
        "face_detected": 1,
        "face_confidence": 0.96,
        "face_embedding": 1,
        "face_match_score": match_score,
        "plate_image": plate_image,
        "face_image": face_image,
        "camera_index": 2 if direction == "IN" else 1,
    }


def test_warm_mirror_not_ready_and_min_image_limit() -> None:
    mirror = WarmDatabaseMirror(image_rows_limit=10)
    assert mirror.image_rows_limit == 50
    assert mirror.ready is False
    assert mirror.find_active_session("59V1-79379") == (False, None)
    assert mirror.query_overview() is None
    assert mirror.get_session_case(1) == (False, None)


def test_warm_mirror_load_live_sync_revenue_sort_and_session_case() -> None:
    fixed_now = datetime(2026, 11, 26, 14, 0, 0)
    mirror = WarmDatabaseMirror(now_fn=lambda: fixed_now)

    fake_cursor = mock.MagicMock()
    fake_cursor.fetchall.side_effect = [[], []]  # empty meta_rows, empty active_rows
    mirror.load_from_cursor(fake_cursor)
    assert mirror.ready is True

    emb = [0.2] * 512
    mirror.apply_inserted_record(
        101,
        {
            "plate_number": "72C1-60266",
            "direction": "IN",
            "fee_amount": 2000,
            "recognized_at": fixed_now,
            "vote_count": 3,
            "sample_count": 3,
            "consensus_rate": 1.0,
            "face_detected": True,
            "face_confidence": 0.96,
            "face_embedding": emb,
            "plate_image": "data:image/jpeg;base64,INPLATE",
            "face_image": "data:image/jpeg;base64,INFACE",
            "camera_index": 2,
        },
    )
    ready, active = mirror.find_active_session("72C160266")
    assert ready is True
    assert active is not None
    assert active["id"] == 101
    assert active["recognized_at"] == "2026-11-26 14:00:00"
    assert active["embedding"] == emb

    ov_in = mirror.query_overview(status_filter="in_parking", include_revenue=True)
    assert ov_in is not None
    assert ov_in["stats"]["in_parking"] == 1
    assert ov_in["revenue"]["today"] == {"tickets": 1, "revenue": 2000}
    assert ov_in["matched"] == 1
    assert ov_in["records"][0]["id"] == 101
    # ADR-02: raw dict only
    assert "Biển số" not in ov_in["records"][0]
    assert "images_loaded" not in ov_in["records"][0]

    # OUT closes active session and marks IN record COMPLETED
    mirror.apply_inserted_record(
        102,
        {
            "plate_number": "72C1-60266",
            "direction": "OUT",
            "entry_record_id": 101,
            "fee_amount": 0,
            "recognized_at": fixed_now + timedelta(minutes=10),
            "vote_count": 2,
            "sample_count": 2,
            "consensus_rate": 1.0,
            "face_detected": True,
            "face_confidence": 0.95,
            "face_embedding": emb,
            "face_match_score": 0.89,
            "plate_image": "data:image/jpeg;base64,OUTPLATE",
            "face_image": "data:image/jpeg;base64,OUTFACE",
            "camera_index": 1,
        },
    )
    assert mirror.find_active_session("72C1-60266") == (True, None)

    found_in, case_in = mirror.get_session_case(101)
    found_out, case_out = mirror.get_session_case(102)
    assert found_in is True and found_out is True
    assert case_in is not None and case_out is not None
    assert case_in["checkin_record"]["id"] == 101
    assert case_in["checkin_record"]["parking_status"] == "COMPLETED"
    assert case_in["checkout_record"]["id"] == 102
    assert case_out["checkin_record"]["id"] == 101
    assert case_out["checkout_record"]["id"] == 102
    assert "checkin_row" not in case_in

    # Missing ID returns (True, None)
    assert mirror.get_session_case(9999) == (True, None)

    # Sort mismatch_first vs matched_first
    mirror.apply_inserted_record(
        103,
        {
            "plate_number": "59A1-99999",
            "direction": "OUT",
            "entry_record_id": None,
            "fee_amount": 0,
            "recognized_at": fixed_now + timedelta(minutes=5),  # out-of-order timestamp
            "vote_count": 2,
            "sample_count": 2,
            "consensus_rate": 1.0,
            "face_detected": True,
            "face_confidence": 0.94,
            "face_embedding": emb,
            "face_match_score": 0.41,
            "plate_image": "P",
            "face_image": "F",
            "camera_index": 1,
        },
    )
    ov_mis = mirror.query_overview(status_filter="direction_out", sort_by="mismatch_first")
    ov_mat = mirror.query_overview(status_filter="direction_out", sort_by="matched_first")
    assert [r["id"] for r in ov_mis["records"]] == [103, 102]
    assert [r["id"] for r in ov_mat["records"]] == [102, 103]


def test_warm_mirror_eviction_triggers_mysql_fallback_and_legacy_session_pairing() -> None:
    base_dt = datetime(2026, 11, 26, 8, 0, 0)
    mirror = WarmDatabaseMirror(image_rows_limit=50, now_fn=lambda: base_dt)

    # Create 51 rows: row 1..50 in image limit, row 51 (oldest) evicted
    meta_rows = []
    # Newest: ID 51 (OUT without entry_record_id for 59B1-11111) and ID 50 (IN COMPLETED)
    # Oldest: ID 1 (IN COMPLETED) & ID 2 (OUT) - ID 1 will be evicted when 51 rows exist
    for idx in range(51, 0, -1):
        rec_at = base_dt + timedelta(minutes=idx)
        if idx == 1:
            meta_rows.append(_cursor_row(1, "59H1-00001", "IN", "COMPLETED", rec_at))
        elif idx == 2:
            meta_rows.append(
                _cursor_row(2, "59H1-00001", "OUT", "EXITED", rec_at, entry_record_id=1, match_score=0.9)
            )
        elif idx == 50:
            meta_rows.append(_cursor_row(50, "59B1-11111", "IN", "COMPLETED", rec_at))
        elif idx == 51:
            meta_rows.append(
                _cursor_row(51, "59B1-11111", "OUT", "EXITED", rec_at, entry_record_id=None, match_score=0.88)
            )
        else:
            meta_rows.append(_cursor_row(idx, f"60C1-{10000 + idx}", "IN", "IN_PARKING", rec_at))

    img_rows = [
        {"id": r["id"], "plate_image": r["plate_image"], "face_image": r["face_image"]}
        for r in meta_rows[:50]
    ]
    active_rows = [
        {
            "id": r["id"],
            "plate_number": r["plate_number"],
            "plate_key": r["plate_key"],
            "recognized_at": r["recognized_at"],
            "face_embedding": embedding_to_bytes([0.1] * 512),
        }
        for r in reversed(meta_rows)
        if r["parking_status"] == "IN_PARKING"
    ]

    fake_cursor = mock.MagicMock()
    fake_cursor.fetchall.side_effect = [meta_rows, img_rows, active_rows]
    mirror.load_from_cursor(fake_cursor)

    # Page 1 (top 10) is in RAM
    p1 = mirror.query_overview(page=1, page_size=10)
    assert p1 is not None
    assert p1["matched"] == 51

    # Page 6 contains row id=1 (images_loaded=False) -> signals fallback (returns None)
    assert mirror.query_overview(page=6, page_size=10) is None

    # Legacy session pairing without entry_record_id works in RAM
    ok_legacy, case_legacy = mirror.get_session_case(50)
    assert ok_legacy is True and case_legacy is not None
    assert case_legacy["checkout_record"]["id"] == 51

    # Session case referencing evicted record id=1 signals fallback (False, None)
    assert mirror.get_session_case(2) == (False, None)

    # Inserting a new record at top evicts row id=2 (50th -> 51st)
    mirror.apply_inserted_record(
        52,
        {
            "plate_number": "72D1-99999",
            "direction": "IN",
            "recognized_at": base_dt + timedelta(minutes=60),
            "vote_count": 3,
            "sample_count": 3,
            "consensus_rate": 1.0,
            "plate_image": "NEW_P",
            "face_image": "NEW_F",
            "camera_index": 2,
        },
    )
    assert mirror._by_id[2]["images_loaded"] is False
    assert mirror._by_id[2]["plate_image"] is None


def test_warm_mirror_thread_safety_under_concurrent_writes_and_reads() -> None:
    now = datetime(2026, 11, 26, 10, 0, 0)
    mirror = WarmDatabaseMirror(now_fn=lambda: now)
    fake_cursor = mock.MagicMock()
    fake_cursor.fetchall.side_effect = [[], []]
    mirror.load_from_cursor(fake_cursor)

    errors: list[Exception] = []

    def writer() -> None:
        try:
            for i in range(1, 31):
                mirror.apply_inserted_record(
                    i,
                    {
                        "plate_number": f"59A1-{10000 + i}",
                        "direction": "IN",
                        "recognized_at": now + timedelta(seconds=i),
                        "vote_count": 3,
                        "sample_count": 3,
                        "consensus_rate": 1.0,
                        "camera_index": 2,
                    },
                )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(30):
                res = mirror.query_overview(include_revenue=True)
                assert res is not None
                mirror.find_active_session("59A1-10001")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    final = mirror.query_overview()
    assert final is not None and final["matched"] == 30


def test_warm_mirror_midnight_record_counted_when_now_has_microseconds() -> None:
    now_with_micros = datetime(2026, 11, 26, 12, 0, 0, 500000)
    midnight = datetime(2026, 11, 26, 0, 0, 0)
    mirror = WarmDatabaseMirror(now_fn=lambda: now_with_micros)

    fake_cursor = mock.MagicMock()
    fake_cursor.fetchall.side_effect = [
        [_cursor_row(1, "59V1-79379", "IN", "IN_PARKING", midnight)],
        [{"id": 1, "plate_image": "P", "face_image": "F"}],
        [],
    ]
    mirror.load_from_cursor(fake_cursor)

    overview = mirror.query_overview(include_stats=True, include_revenue=True)
    assert overview is not None
    assert overview["stats"]["today_records"] == 1
    assert overview["revenue"]["today"] == {"tickets": 1, "revenue": 2000}
