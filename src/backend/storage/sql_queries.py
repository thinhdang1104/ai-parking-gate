"""Pure SQL query helpers for revenue, overview filtering, and session-case lookup."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.storage.query_helpers import SELECT_RECORD_COLS


def fetch_stats_sql(cursor: Any, today_start: datetime) -> dict[str, int]:
    """Query aggregate KPI counts from plate_recognition_history."""
    cursor.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(recognized_at >= %s), 0) AS today,
            COALESCE(SUM(direction = 'IN' AND parking_status = 'IN_PARKING'), 0) AS in_parking,
            COALESCE(SUM(direction = 'IN'), 0) AS total_in,
            COALESCE(SUM(direction = 'OUT'), 0) AS total_out
        FROM plate_recognition_history
        """,
        (today_start,),
    )
    stats_row = cursor.fetchone() or {}
    return {
        "total_records": int(stats_row.get("total") or 0),
        "today_records": int(stats_row.get("today") or 0),
        "in_parking": int(stats_row.get("in_parking") or 0),
        "total_in": int(stats_row.get("total_in") or 0),
        "total_out": int(stats_row.get("total_out") or 0),
    }


def fetch_revenue_report_sql(
    cursor: Any,
    vn_now: datetime,
    unit_price: int,
) -> dict[str, Any]:
    """Compute revenue totals and daily/monthly/yearly breakdowns (IN tickets only)."""
    today_start = vn_now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN recognized_at >= %s AND direction = 'IN' THEN 1 ELSE 0 END), 0) AS tickets_today,
            COALESCE(SUM(CASE WHEN recognized_at >= %s THEN fee_amount ELSE 0 END), 0) AS revenue_today,
            COALESCE(SUM(CASE WHEN recognized_at >= %s AND direction = 'IN' THEN 1 ELSE 0 END), 0) AS tickets_month,
            COALESCE(SUM(CASE WHEN recognized_at >= %s THEN fee_amount ELSE 0 END), 0) AS revenue_month,
            COALESCE(SUM(CASE WHEN recognized_at >= %s AND direction = 'IN' THEN 1 ELSE 0 END), 0) AS tickets_year,
            COALESCE(SUM(CASE WHEN recognized_at >= %s THEN fee_amount ELSE 0 END), 0) AS revenue_year,
            COALESCE(SUM(CASE WHEN direction = 'IN' THEN 1 ELSE 0 END), 0) AS tickets_total,
            COALESCE(SUM(fee_amount), 0) AS revenue_total
        FROM plate_recognition_history
        """,
        (today_start, today_start, month_start, month_start, year_start, year_start),
    )
    summary = cursor.fetchone() or {}

    cursor.execute(
        """
        SELECT
            DATE_FORMAT(recognized_at, '%d/%m/%Y') AS period_label,
            DATE(recognized_at) AS sort_date,
            COUNT(*) AS ticket_count,
            COALESCE(SUM(fee_amount), 0) AS total_vnd
        FROM plate_recognition_history
        WHERE direction = 'IN'
        GROUP BY DATE(recognized_at), DATE_FORMAT(recognized_at, '%d/%m/%Y')
        ORDER BY sort_date DESC
        """
    )
    daily_rows = [
        {
            "period": row["period_label"],
            "tickets": int(row["ticket_count"] or 0),
            "unit_price": unit_price,
            "revenue": int(row["total_vnd"] or 0),
        }
        for row in (cursor.fetchall() or [])
    ]

    cursor.execute(
        """
        SELECT
            DATE_FORMAT(recognized_at, '%m/%Y') AS period_label,
            DATE_FORMAT(recognized_at, '%Y-%m') AS sort_month,
            COUNT(*) AS ticket_count,
            COALESCE(SUM(fee_amount), 0) AS total_vnd
        FROM plate_recognition_history
        WHERE direction = 'IN'
        GROUP BY sort_month, period_label
        ORDER BY sort_month DESC
        """
    )
    monthly_rows = [
        {
            "period": f"Tháng {row['period_label']}",
            "tickets": int(row["ticket_count"] or 0),
            "unit_price": unit_price,
            "revenue": int(row["total_vnd"] or 0),
        }
        for row in (cursor.fetchall() or [])
    ]

    cursor.execute(
        """
        SELECT
            CAST(YEAR(recognized_at) AS CHAR) AS period_label,
            YEAR(recognized_at) AS sort_year,
            COUNT(*) AS ticket_count,
            COALESCE(SUM(fee_amount), 0) AS total_vnd
        FROM plate_recognition_history
        WHERE direction = 'IN'
        GROUP BY sort_year, period_label
        ORDER BY sort_year DESC
        """
    )
    yearly_rows = [
        {
            "period": f"Năm {row['period_label']}",
            "tickets": int(row["ticket_count"] or 0),
            "unit_price": unit_price,
            "revenue": int(row["total_vnd"] or 0),
        }
        for row in (cursor.fetchall() or [])
    ]

    return {
        "unit_price": unit_price,
        "today": {
            "tickets": int(summary.get("tickets_today") or 0),
            "revenue": int(summary.get("revenue_today") or 0),
        },
        "month": {
            "tickets": int(summary.get("tickets_month") or 0),
            "revenue": int(summary.get("revenue_month") or 0),
        },
        "year": {
            "tickets": int(summary.get("tickets_year") or 0),
            "revenue": int(summary.get("revenue_year") or 0),
        },
        "total": {
            "tickets": int(summary.get("tickets_total") or 0),
            "revenue": int(summary.get("revenue_total") or 0),
        },
        "daily": daily_rows,
        "monthly": monthly_rows,
        "yearly": yearly_rows,
    }


def build_overview_where(query: str, status_filter: str) -> tuple[str, list[Any], str]:
    """Build parameterized WHERE clause and normalized search key for overview queries."""
    conditions: list[str] = []
    params: list[Any] = []
    normalized_query = clean_plate_key(query)
    if normalized_query:
        conditions.append("plate_key LIKE %s")
        params.append(f"%{normalized_query}%")

    if status_filter == "in_parking":
        conditions.append("direction = 'IN' AND parking_status = 'IN_PARKING'")
    elif status_filter == "direction_in":
        conditions.append("direction = 'IN'")
    elif status_filter == "direction_out":
        conditions.append("direction = 'OUT'")

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_sql, params, normalized_query


def build_overview_order_sql(sort_by: str, match_threshold: float) -> str:
    """Build ORDER BY clause for overview pagination."""
    if sort_by == "mismatch_first":
        return (
            f"ORDER BY (CASE WHEN face_match_score IS NOT NULL "
            f"AND face_match_score < {match_threshold:.4f} THEN 0 ELSE 1 END) ASC, "
            "recognized_at DESC, id DESC"
        )
    if sort_by == "matched_first":
        return (
            f"ORDER BY (CASE WHEN face_match_score IS NOT NULL "
            f"AND face_match_score < {match_threshold:.4f} THEN 1 ELSE 0 END) ASC, "
            "recognized_at DESC, id DESC"
        )
    return "ORDER BY recognized_at DESC, id DESC"


def fetch_session_pair_sql(
    cursor: Any,
    target: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve raw `(checkin_raw, checkout_raw)` pair for a fetched target row."""
    target_dir = str(target.get("direction") or "IN").upper()
    checkin_raw = None
    checkout_raw = None

    if target_dir == "OUT":
        checkout_raw = target
        entry_id = target.get("entry_record_id")
        if entry_id is not None:
            cursor.execute(
                f"{SELECT_RECORD_COLS} WHERE id = %s LIMIT 1", (int(entry_id),)
            )
            checkin_raw = cursor.fetchone()
        if checkin_raw is None:
            norm_plate = target.get("plate_key") or clean_plate_key(
                target.get("plate_number") or ""
            )
            cursor.execute(
                f"""
                {SELECT_RECORD_COLS}
                WHERE plate_key = %s
                  AND direction = 'IN'
                  AND (recognized_at < %s OR (recognized_at = %s AND id < %s))
                ORDER BY recognized_at DESC, id DESC
                LIMIT 1
                """,
                (
                    norm_plate,
                    target["recognized_at"],
                    target["recognized_at"],
                    int(target["id"]),
                ),
            )
            checkin_raw = cursor.fetchone()
        return checkin_raw, checkout_raw

    checkin_raw = target
    if str(target.get("parking_status") or "").upper() != "IN_PARKING":
        cursor.execute(
            f"""
            {SELECT_RECORD_COLS}
            WHERE direction = 'OUT' AND entry_record_id = %s
            ORDER BY recognized_at ASC, id ASC
            LIMIT 1
            """,
            (int(target["id"]),),
        )
        checkout_raw = cursor.fetchone()
        if checkout_raw is None:
            checkout_raw = _find_checkout_fallback_sql(cursor, target)
    return checkin_raw, checkout_raw


def _find_checkout_fallback_sql(cursor: Any, target: dict[str, Any]) -> Any:
    norm_plate = target.get("plate_key") or clean_plate_key(
        target.get("plate_number") or ""
    )
    cursor.execute(
        """
        SELECT id, recognized_at
        FROM plate_recognition_history
        WHERE plate_key = %s
          AND direction = 'IN'
          AND (recognized_at > %s OR (recognized_at = %s AND id > %s))
        ORDER BY recognized_at ASC, id ASC
        LIMIT 1
        """,
        (
            norm_plate,
            target["recognized_at"],
            target["recognized_at"],
            int(target["id"]),
        ),
    )
    next_in = cursor.fetchone()
    if next_in:
        cursor.execute(
            f"""
            {SELECT_RECORD_COLS}
            WHERE plate_key = %s
              AND direction = 'OUT'
              AND (recognized_at > %s OR (recognized_at = %s AND id > %s))
              AND (recognized_at < %s OR (recognized_at = %s AND id < %s))
            ORDER BY recognized_at ASC, id ASC
            LIMIT 1
            """,
            (
                norm_plate,
                target["recognized_at"],
                target["recognized_at"],
                int(target["id"]),
                next_in["recognized_at"],
                next_in["recognized_at"],
                int(next_in["id"]),
            ),
        )
    else:
        cursor.execute(
            f"""
            {SELECT_RECORD_COLS}
            WHERE plate_key = %s
              AND direction = 'OUT'
              AND (recognized_at > %s OR (recognized_at = %s AND id > %s))
            ORDER BY recognized_at ASC, id ASC
            LIMIT 1
            """,
            (
                norm_plate,
                target["recognized_at"],
                target["recognized_at"],
                int(target["id"]),
            ),
        )
    return cursor.fetchone()
