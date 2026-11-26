"""Optional demo dataset seeder (38 records) gated by SEED_DEMO_DATA."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any

from src.backend.config import EMBEDDING_SIZE, PARKING_FEE_VND
from src.backend.storage.mysql_client import now_vn

if TYPE_CHECKING:
    from src.backend.storage.repository import ParkingRepository

logger = logging.getLogger(__name__)

DEMO_MARKER_PLATE_KEY = "59S248219"


def make_demo_embedding(seed_idx: int, shift: float = 0.0) -> list[float]:
    """Generate a deterministic L2-normalized 512-D face vector for demo data."""
    raw = [
        math.sin((i + 1) * (seed_idx + 1) * 0.17 + shift)
        for i in range(EMBEDDING_SIZE)
    ]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def _make_demo_row(
    plate: str,
    direction: str,
    rec_time: datetime,
    vc: int,
    sc: int,
    rate: float,
    f_conf: float,
    seed_idx: int,
    shift: float = 0.0,
    m_score: float | None = None,
    fee_vnd: int = PARKING_FEE_VND,
) -> dict[str, Any]:
    is_in = direction == "IN"
    return {
        "plate_number": plate,
        "direction": direction,
        "parking_status": "IN_PARKING" if is_in else "EXITED",
        "fee_amount": int(fee_vnd) if is_in else 0,
        "recognized_at": rec_time,
        "vote_count": vc,
        "sample_count": sc,
        "consensus_rate": rate,
        "face_detected": True,
        "face_confidence": f_conf,
        "face_embedding": make_demo_embedding(seed_idx, shift),
        "face_match_score": m_score,
        "camera_index": 2 if is_in else 1,
    }


def build_demo_records(
    now: datetime | None = None,
    fee_vnd: int = PARKING_FEE_VND,
) -> list[dict[str, Any]]:
    """Build the 38 deterministic demo records (20 historical + 12 today + 6 active)."""
    ref_now = now if now is not None else now_vn()
    records: list[dict[str, Any]] = []

    historical_completed = [
        ("59H1-30488", 42, 180, 5, 5, 1.00, 0.98, 0.94, 1),
        ("60F2-71925", 38, 210, 4, 5, 0.80, 0.97, 0.92, 2),
        ("59N2-84160", 32, 145, 5, 6, 0.83, 0.99, 0.96, 3),
        ("71B3-20914", 18, 195, 5, 5, 1.00, 0.96, 0.91, 4),
        ("59T1-66239", 12, 160, 4, 5, 0.80, 0.98, 0.95, 5),
        ("61G1-53072", 7, 240, 5, 5, 1.00, 0.97, 0.93, 6),
        ("59K2-19455", 4, 175, 5, 6, 0.83, 0.99, 0.97, 7),
        ("62L1-88307", 2, 150, 5, 5, 1.00, 0.96, 0.92, 8),
        ("59U1-41790", 1, 200, 4, 5, 0.80, 0.98, 0.94, 9),
        ("59D2-75631", 1, 130, 5, 5, 1.00, 0.97, 0.95, 10),
    ]
    for plate, days_ago, dur_min, vc, sc, rate, f_conf, m_score, s_idx in historical_completed:
        in_time = (ref_now - timedelta(days=days_ago, hours=4, minutes=dur_min)).replace(
            hour=7, minute=(s_idx * 7) % 55, second=12
        )
        out_time = in_time + timedelta(minutes=dur_min)
        records.append(
            _make_demo_row(plate, "IN", in_time, vc, sc, rate, f_conf, s_idx, 0.0, fee_vnd=fee_vnd)
        )
        records.append(
            _make_demo_row(
                plate,
                "OUT",
                out_time,
                vc,
                sc,
                rate,
                round(max(0.92, f_conf - 0.01), 2),
                s_idx,
                0.06,
                m_score,
                fee_vnd=fee_vnd,
            )
        )

    today_completed = [
        ("59A3-12845", 240, 55, 5, 5, 1.00, 0.99, 0.96, 21),
        ("59G2-60412", 215, 50, 4, 5, 0.80, 0.97, 0.93, 22),
        ("60B1-88930", 185, 45, 5, 6, 0.83, 0.98, 0.95, 23),
        ("61C1-44278", 155, 40, 5, 5, 1.00, 0.96, 0.91, 24),
        ("72D1-31956", 125, 35, 5, 5, 1.00, 0.99, 0.97, 25),
        ("59P2-91023", 95, 30, 4, 5, 0.80, 0.98, 0.94, 26),
    ]
    for plate, in_mins_ago, out_mins_ago, vc, sc, rate, f_conf, m_score, s_idx in today_completed:
        in_time = ref_now - timedelta(minutes=in_mins_ago)
        if in_time.date() != ref_now.date():
            in_time = ref_now.replace(hour=max(0, ref_now.hour - 2), minute=10, second=0)
        out_time = ref_now - timedelta(minutes=out_mins_ago)
        if out_time <= in_time:
            out_time = in_time + timedelta(minutes=25)
        records.append(
            _make_demo_row(plate, "IN", in_time, vc, sc, rate, f_conf, s_idx, 0.0, fee_vnd=fee_vnd)
        )
        records.append(
            _make_demo_row(
                plate,
                "OUT",
                out_time,
                vc,
                sc,
                rate,
                round(max(0.93, f_conf - 0.01), 2),
                s_idx,
                0.05,
                m_score,
                fee_vnd=fee_vnd,
            )
        )

    active_in_parking = [
        ("59S2-48219", 72, 5, 5, 1.00, 0.99, 31),
        ("59X3-71504", 58, 5, 6, 0.83, 0.97, 32),
        ("60B8-33962", 44, 4, 5, 0.80, 0.98, 33),
        ("61D1-90427", 31, 5, 5, 1.00, 0.96, 34),
        ("72C1-55811", 19, 5, 5, 1.00, 0.99, 35),
        ("49E1-26785", 8, 4, 5, 0.80, 0.98, 36),
    ]
    for plate, mins_ago, vc, sc, rate, f_conf, s_idx in active_in_parking:
        in_time = ref_now - timedelta(minutes=mins_ago)
        if in_time.date() != ref_now.date():
            in_time = ref_now.replace(hour=max(0, ref_now.hour - 1), minute=35, second=0)
        records.append(
            _make_demo_row(plate, "IN", in_time, vc, sc, rate, f_conf, s_idx, 0.0, fee_vnd=fee_vnd)
        )

    return records


def seed_demo_records_if_empty(
    repository: ParkingRepository,
    enabled: bool = False,
) -> int:
    """Seed 38 demo records on a single connection if enabled and not yet present."""
    if not enabled:
        return 0

    connection = None
    cursor = None
    try:
        connection = repository.client.connect()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM plate_recognition_history WHERE plate_key = %s",
            (DEMO_MARKER_PLATE_KEY,),
        )
        row = cursor.fetchone()
        existing_count = 0
        if isinstance(row, dict):
            existing_count = int(next(iter(row.values()), 0) or 0)
        elif row:
            existing_count = int(row[0] or 0)
        if existing_count > 0:
            return 0

        demo_list = build_demo_records(fee_vnd=repository.settings.parking_fee_vnd)
        for rec in demo_list:
            repository.insert_plate_record(rec, connection=connection)
        logger.info("Seeded %s demo parking records into MySQL", len(demo_list))
        return len(demo_list)
    except Exception as error:  # noqa: BLE001
        logger.warning("Failed to seed demo records: %s", error)
        return 0
    finally:
        if cursor is not None:
            try:
                cursor.close()
            finally:
                if connection is not None:
                    connection.close()
        elif connection is not None:
            connection.close()
