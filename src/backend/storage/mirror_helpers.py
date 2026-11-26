"""In-memory computation helpers for WarmDatabaseMirror."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.storage.query_helpers import is_face_mismatch_score


def compute_mirror_stats(
    items: list[dict[str, Any]],
    today_start: datetime,
) -> dict[str, int]:
    """Compute KPI stats from in-memory mirror items."""
    today_cnt = 0
    in_parking_cnt = 0
    in_cnt = 0
    out_cnt = 0
    for it in items:
        if it["recognized_at"] >= today_start:
            today_cnt += 1
        if it["direction"] == "IN":
            in_cnt += 1
            if it["parking_status"] == "IN_PARKING":
                in_parking_cnt += 1
        elif it["direction"] == "OUT":
            out_cnt += 1
    return {
        "total_records": len(items),
        "today_records": today_cnt,
        "in_parking": in_parking_cnt,
        "total_in": in_cnt,
        "total_out": out_cnt,
    }


def compute_mirror_revenue(
    items: list[dict[str, Any]],
    vn_now: datetime,
    unit_price: int,
) -> dict[str, Any]:
    """Compute revenue totals and daily/monthly/yearly breakdowns from RAM items."""
    today_start = vn_now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    tickets_today = revenue_today = 0
    tickets_month = revenue_month = 0
    tickets_year = revenue_year = 0
    tickets_total = revenue_total = 0

    daily_buckets: dict[str, list[Any]] = {}
    monthly_buckets: dict[str, list[Any]] = {}
    yearly_buckets: dict[int, list[Any]] = {}

    for it in items:
        dt = it["recognized_at"]
        fee = it["fee_amount"]
        revenue_total += fee
        if dt >= year_start:
            revenue_year += fee
            if dt >= month_start:
                revenue_month += fee
                if dt >= today_start:
                    revenue_today += fee

        if it["direction"] != "IN":
            continue

        tickets_total += 1
        if dt >= year_start:
            tickets_year += 1
            if dt >= month_start:
                tickets_month += 1
                if dt >= today_start:
                    tickets_today += 1

        day_key = dt.strftime("%Y-%m-%d")
        d_bucket = daily_buckets.get(day_key)
        if d_bucket is None:
            daily_buckets[day_key] = [dt.strftime("%d/%m/%Y"), 1, fee]
        else:
            d_bucket[1] += 1
            d_bucket[2] += fee

        month_key = dt.strftime("%Y-%m")
        m_bucket = monthly_buckets.get(month_key)
        if m_bucket is None:
            monthly_buckets[month_key] = [dt.strftime("%m/%Y"), 1, fee]
        else:
            m_bucket[1] += 1
            m_bucket[2] += fee

        year_key = dt.year
        y_bucket = yearly_buckets.get(year_key)
        if y_bucket is None:
            yearly_buckets[year_key] = [str(year_key), 1, fee]
        else:
            y_bucket[1] += 1
            y_bucket[2] += fee

    return {
        "unit_price": unit_price,
        "today": {"tickets": tickets_today, "revenue": revenue_today},
        "month": {"tickets": tickets_month, "revenue": revenue_month},
        "year": {"tickets": tickets_year, "revenue": revenue_year},
        "total": {"tickets": tickets_total, "revenue": revenue_total},
        "daily": [
            {
                "period": val[0],
                "tickets": val[1],
                "unit_price": unit_price,
                "revenue": val[2],
            }
            for _, val in sorted(
                daily_buckets.items(), key=lambda kv: kv[0], reverse=True
            )
        ],
        "monthly": [
            {
                "period": f"Tháng {val[0]}",
                "tickets": val[1],
                "unit_price": unit_price,
                "revenue": val[2],
            }
            for _, val in sorted(
                monthly_buckets.items(), key=lambda kv: kv[0], reverse=True
            )
        ],
        "yearly": [
            {
                "period": f"Năm {val[0]}",
                "tickets": val[1],
                "unit_price": unit_price,
                "revenue": val[2],
            }
            for _, val in sorted(
                yearly_buckets.items(), key=lambda kv: kv[0], reverse=True
            )
        ],
    }


def filter_and_sort_mirror_items(
    items: list[dict[str, Any]],
    query: str,
    status_filter: str,
    sort_by: str,
    match_threshold: float,
) -> list[dict[str, Any]]:
    """Filter and sort RAM mirror items matching MySQL query semantics."""
    normalized_query = clean_plate_key(query)
    filtered = items
    if normalized_query:
        filtered = [it for it in filtered if normalized_query in it["plate_key"]]
    if status_filter == "in_parking":
        filtered = [
            it
            for it in filtered
            if it["direction"] == "IN" and it["parking_status"] == "IN_PARKING"
        ]
    elif status_filter == "direction_in":
        filtered = [it for it in filtered if it["direction"] == "IN"]
    elif status_filter == "direction_out":
        filtered = [it for it in filtered if it["direction"] == "OUT"]

    if sort_by == "mismatch_first":
        return sorted(
            filtered,
            key=lambda it: (
                0
                if is_face_mismatch_score(
                    it.get("face_match_score"), match_threshold
                )
                else 1
            ),
        )
    if sort_by == "matched_first":
        return sorted(
            filtered,
            key=lambda it: (
                1
                if is_face_mismatch_score(
                    it.get("face_match_score"), match_threshold
                )
                else 0
            ),
        )
    return filtered


def resolve_mirror_session_pair(
    target: dict[str, Any],
    items: list[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve paired `(checkin_item, checkout_item)` from RAM mirror snapshot."""
    if target["direction"] == "OUT":
        checkout_item = target
        checkin_item = None
        entry_id = target["entry_record_id"]
        if entry_id is not None:
            checkin_item = by_id.get(entry_id)
        if checkin_item is None:
            t_key = (target["recognized_at"], target["id"])
            for it in items:
                if (
                    it["plate_key"] == target["plate_key"]
                    and it["direction"] == "IN"
                    and (it["recognized_at"], it["id"]) < t_key
                ):
                    checkin_item = it
                    break
        return checkin_item, checkout_item

    checkin_item = target
    checkout_item = None
    if target["parking_status"] != "IN_PARKING":
        for it in reversed(items):
            if it["direction"] == "OUT" and it["entry_record_id"] == target["id"]:
                checkout_item = it
                break
        if checkout_item is None:
            t_key = (target["recognized_at"], target["id"])
            next_in_key = None
            for it in reversed(items):
                if (
                    it["plate_key"] == target["plate_key"]
                    and it["direction"] == "IN"
                    and (it["recognized_at"], it["id"]) > t_key
                ):
                    next_in_key = (it["recognized_at"], it["id"])
                    break
            for it in reversed(items):
                if it["plate_key"] != target["plate_key"] or it["direction"] != "OUT":
                    continue
                it_key = (it["recognized_at"], it["id"])
                if it_key > t_key and (next_in_key is None or it_key < next_in_key):
                    checkout_item = it
                    break
    return checkin_item, checkout_item
