"""MySQL persistence repository returning raw domain dicts (ADR-02)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.backend.config import Settings
from src.backend.domain.face_math import (
    cosine_similarity,
    embedding_from_bytes,
    embedding_to_bytes,
)
from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.storage.exceptions import DatabaseOperationError
from src.backend.storage.migrations import ensure_mysql_table
from src.backend.storage.mysql_client import MySQLClient, now_vn
from src.backend.storage.query_helpers import (
    SELECT_RECORD_COLS,
    build_session_case_payload,
    compute_pagination,
    format_timestamp_str,
    matched_from_stats,
    normalize_raw_record,
)
from src.backend.storage.sql_queries import (
    build_overview_order_sql,
    build_overview_where,
    fetch_revenue_report_sql,
    fetch_session_pair_sql,
    fetch_stats_sql,
)


class ParkingRepository:
    """Direct MySQL repository for parking recognition history and analytics."""

    def __init__(
        self,
        client: MySQLClient,
        settings: Settings | None = None,
        now_fn: Callable[[], datetime] = now_vn,
    ) -> None:
        self.client = client
        self.settings: Settings = settings if settings is not None else client.settings
        self._now_fn = now_fn

    def initialize(
        self,
        warm_mirror: Any = None,
        seeder: Callable[[ParkingRepository], Any] | None = None,
    ) -> None:
        """Ensure table/indexes exist, optionally run seeder, and warm RAM mirror."""
        connection = self.client.connect()
        cursor = connection.cursor(dictionary=True)
        try:
            ensure_mysql_table(cursor, fee_vnd=self.settings.parking_fee_vnd)
            connection.commit()
            if seeder is not None:
                seeder(self)
                connection.commit()
            if warm_mirror is not None:
                warm_mirror.load_from_cursor(cursor)
        except self.client._error_types() as error:
            raise DatabaseOperationError(str(error)) from error
        finally:
            try:
                cursor.close()
            finally:
                connection.close()

    def find_active_parking_session(
        self,
        plate_number: str,
        cursor: Any = None,
    ) -> dict[str, Any] | None:
        """Find the latest IN_PARKING session for `plate_number`."""
        norm_plate = clean_plate_key(plate_number)

        def _query(cur: Any) -> dict[str, Any] | None:
            cur.execute(
                """
                SELECT id, plate_number, recognized_at, face_embedding
                FROM plate_recognition_history
                WHERE plate_key = %s
                  AND direction = 'IN'
                  AND parking_status = 'IN_PARKING'
                ORDER BY recognized_at DESC, id DESC
                LIMIT 1
                """,
                (norm_plate,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if not isinstance(row, dict):
                row = {
                    "id": row[0],
                    "plate_number": row[1],
                    "recognized_at": row[2],
                    "face_embedding": row[3],
                }
            raw_emb = row.get("face_embedding")
            return {
                "id": int(row["id"]),
                "plate_number": row["plate_number"],
                "recognized_at": format_timestamp_str(
                    row["recognized_at"], now_fn=self._now_fn
                ),
                "embedding": embedding_from_bytes(
                    bytes(raw_emb) if raw_emb is not None else None,
                    embedding_size=self.settings.embedding_size,
                ),
            }

        if cursor is not None:
            try:
                return _query(cursor)
            except self.client._error_types() as error:
                raise DatabaseOperationError(str(error)) from error
        return self.client.run_read_query(_query)

    def insert_plate_record(
        self,
        record: dict[str, Any],
        connection: Any = None,
    ) -> tuple[int, float | None]:
        """Insert an IN or OUT record atomically, closing prior IN_PARKING sessions."""
        own_connection = connection is None
        if own_connection:
            connection = self.client.connect()
        cursor = connection.cursor()
        try:
            direction = str(record.get("direction") or "IN").upper()
            embedding = record.get("face_embedding")
            has_embedding = embedding is not None and len(embedding) > 0
            match_score = record.get("face_match_score")
            entry_id = record.get("entry_record_id")
            plate_key = clean_plate_key(record["plate_number"])

            if direction == "OUT":
                parking_status = "EXITED"
                fee_amount = 0
                if has_embedding and match_score is None:
                    active = self.find_active_parking_session(
                        record["plate_number"], cursor=cursor
                    )
                    if active is not None:
                        if entry_id is None:
                            entry_id = active["id"]
                        previous_emb = active.get("embedding")
                        if previous_emb is not None:
                            match_score = max(
                                -1.0,
                                min(1.0, cosine_similarity(embedding, previous_emb)),
                            )
                record["entry_record_id"] = entry_id
            else:
                direction = "IN"
                parking_status = "IN_PARKING"
                fee_amount = int(
                    record.get("fee_amount", self.settings.parking_fee_vnd)
                )

            cursor.execute(
                """
                UPDATE plate_recognition_history
                SET parking_status = 'COMPLETED'
                WHERE plate_key = %s
                  AND direction = 'IN'
                  AND parking_status = 'IN_PARKING'
                """,
                (plate_key,),
            )
            cursor.execute(
                """
                INSERT INTO plate_recognition_history (
                    plate_number, plate_key, direction, parking_status, entry_record_id,
                    fee_amount, recognized_at, vote_count, sample_count,
                    consensus_rate, face_detected, face_confidence,
                    face_embedding, face_match_score, plate_image, face_image, camera_index
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record["plate_number"],
                    plate_key,
                    direction,
                    parking_status,
                    entry_id,
                    fee_amount,
                    record["recognized_at"],
                    record["vote_count"],
                    record["sample_count"],
                    record["consensus_rate"],
                    1 if record.get("face_detected") else 0,
                    record.get("face_confidence"),
                    embedding_to_bytes(embedding) if has_embedding else None,
                    match_score,
                    record.get("plate_image"),
                    record.get("face_image"),
                    record["camera_index"],
                ),
            )
            connection.commit()
            return int(cursor.lastrowid), (
                float(match_score) if match_score is not None else None
            )
        except self.client._error_types() as error:
            try:
                connection.rollback()
            except Exception:
                pass
            raise DatabaseOperationError(str(error)) from error
        finally:
            try:
                cursor.close()
            finally:
                if own_connection:
                    connection.close()

    def fetch_revenue_report(self, cursor: Any) -> dict[str, Any]:
        """Compute parking revenue (IN tickets only) for today, month, year, total."""
        return fetch_revenue_report_sql(
            cursor,
            vn_now=self._now_fn(),
            unit_price=int(self.settings.parking_fee_vnd),
        )

    def fetch_overview(
        self,
        query: str = "",
        status_filter: str = "all",
        limit: int | None = None,
        page: int = 1,
        page_size: int = 10,
        include_records: bool = True,
        include_stats: bool = True,
        include_revenue: bool = False,
        known_stats: dict[str, Any] | None = None,
        sort_by: str = "",
        include_stats_and_revenue: bool | None = None,
    ) -> dict[str, Any]:
        """Query KPI stats, optional revenue report, and paginated raw records."""
        if include_stats_and_revenue is not None:
            include_stats = bool(include_stats_and_revenue)
            include_revenue = bool(include_stats_and_revenue)

        threshold = float(self.settings.face_match_threshold)

        def _query(cursor: Any) -> dict[str, Any]:
            today_start = self._now_fn().replace(hour=0, minute=0, second=0)
            stats_payload = (
                fetch_stats_sql(cursor, today_start) if include_stats else None
            )
            revenue_report = (
                self.fetch_revenue_report(cursor) if include_revenue else None
            )

            if not include_records:
                return {
                    "stats": stats_payload,
                    "revenue": revenue_report,
                    "matched": 0,
                    "page": 1,
                    "records": [],
                }

            where_sql, params, normalized_query = build_overview_where(
                query, status_filter
            )
            effective_stats = stats_payload or known_stats
            if not normalized_query and effective_stats is not None:
                matched = matched_from_stats(effective_stats, status_filter)
            else:
                cursor.execute(
                    f"SELECT COUNT(*) AS matched FROM plate_recognition_history {where_sql}",
                    params,
                )
                matched = int((cursor.fetchone() or {}).get("matched") or 0)

            effective_limit, safe_page, effective_offset = compute_pagination(
                matched, limit, page, page_size
            )
            if matched == 0:
                records: list[dict[str, Any]] = []
            else:
                order_sql = build_overview_order_sql(sort_by, threshold)
                cursor.execute(
                    f"{SELECT_RECORD_COLS} {where_sql} {order_sql} LIMIT %s OFFSET %s",
                    [*params, effective_limit, effective_offset],
                )
                records = [
                    normalize_raw_record(row, images_loaded=True, now_fn=self._now_fn)
                    for row in (cursor.fetchall() or [])
                ]

            return {
                "stats": stats_payload,
                "revenue": revenue_report,
                "matched": matched,
                "page": safe_page,
                "records": records,
            }

        return self.client.run_read_query(_query)

    def fetch_parking_session_case(self, record_id: int) -> dict[str, Any] | None:
        """Fetch paired raw Check-in and Check-out records by record_id."""

        def _query(cursor: Any) -> dict[str, Any] | None:
            cursor.execute(
                f"{SELECT_RECORD_COLS} WHERE id = %s LIMIT 1", (int(record_id),)
            )
            target = cursor.fetchone()
            if not target:
                return None

            checkin_raw, checkout_raw = fetch_session_pair_sql(cursor, target)
            norm_target = normalize_raw_record(target, now_fn=self._now_fn)
            norm_in = (
                normalize_raw_record(checkin_raw, now_fn=self._now_fn)
                if checkin_raw
                else None
            )
            norm_out = (
                normalize_raw_record(checkout_raw, now_fn=self._now_fn)
                if checkout_raw
                else None
            )
            return build_session_case_payload(norm_target, norm_in, norm_out)

        return self.client.run_read_query(_query)
