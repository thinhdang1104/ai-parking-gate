"""In-memory WarmDatabaseMirror synced 1-to-1 with MySQL returning raw domain dicts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import threading
from typing import Any

from src.backend.config import (
    EMBEDDING_SIZE,
    FACE_MATCH_THRESHOLD,
    PARKING_FEE_VND,
    WARM_MIRROR_MAX_IMAGE_RECORDS,
)
from src.backend.domain.face_math import embedding_from_bytes
from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.storage.mirror_helpers import (
    compute_mirror_revenue,
    compute_mirror_stats,
    filter_and_sort_mirror_items,
    resolve_mirror_session_pair,
)
from src.backend.storage.mysql_client import now_vn
from src.backend.storage.query_helpers import (
    build_session_case_payload,
    compute_pagination,
    format_timestamp_str,
    normalize_raw_record,
    strip_internal_fields,
)


class WarmDatabaseMirror:
    """Thread-safe RAM mirror for zero-SQL reads and MySQL eviction fallback."""

    def __init__(
        self,
        image_rows_limit: int = WARM_MIRROR_MAX_IMAGE_RECORDS,
        fee_vnd: int = PARKING_FEE_VND,
        match_threshold: float = FACE_MATCH_THRESHOLD,
        now_fn: Callable[[], datetime] = now_vn,
        embedding_size: int = EMBEDDING_SIZE,
    ) -> None:
        self._lock = threading.Lock()
        self.image_rows_limit = max(50, int(image_rows_limit))
        self.fee_vnd = int(fee_vnd)
        self.match_threshold = float(match_threshold)
        self._now_fn = now_fn
        self._embedding_size = int(embedding_size)
        self.ready = False
        self._items: list[dict[str, Any]] = []
        self._by_id: dict[int, dict[str, Any]] = {}
        self._active_sessions: dict[str, dict[str, Any]] = {}

    def _build_item(self, row: dict[str, Any], images_loaded: bool) -> dict[str, Any]:
        item = normalize_raw_record(
            row, images_loaded=images_loaded, now_fn=self._now_fn
        )
        item["images_loaded"] = bool(images_loaded)
        return item

    def load_from_cursor(self, cursor: Any) -> None:
        """Load full metadata, recent image rows, and active IN_PARKING sessions."""
        cursor.execute(
            """
            SELECT id, plate_number, plate_key, direction, parking_status, entry_record_id,
                   fee_amount, recognized_at, vote_count, sample_count,
                   consensus_rate, face_detected, face_confidence,
                   face_embedding IS NOT NULL AS face_embedding, face_match_score, camera_index
            FROM plate_recognition_history
            ORDER BY recognized_at DESC, id DESC
            """
        )
        meta_rows = cursor.fetchall() or []

        img_map: dict[int, tuple[str | None, str | None]] = {}
        if meta_rows:
            cursor.execute(
                """
                SELECT id, plate_image, face_image
                FROM plate_recognition_history
                ORDER BY recognized_at DESC, id DESC
                LIMIT %s
                """,
                (self.image_rows_limit,),
            )
            for img_row in cursor.fetchall() or []:
                img_map[int(img_row["id"])] = (
                    img_row.get("plate_image"),
                    img_row.get("face_image"),
                )

        cursor.execute(
            """
            SELECT id, plate_number, plate_key, recognized_at, face_embedding
            FROM plate_recognition_history
            WHERE direction = 'IN' AND parking_status = 'IN_PARKING'
            ORDER BY recognized_at ASC, id ASC
            """
        )
        active_sessions: dict[str, dict[str, Any]] = {}
        for act in cursor.fetchall() or []:
            pk = str(act.get("plate_key") or "") or clean_plate_key(
                act.get("plate_number") or ""
            )
            raw_emb = act.get("face_embedding")
            active_sessions[pk] = {
                "id": int(act["id"]),
                "plate_number": act["plate_number"],
                "recognized_at": format_timestamp_str(
                    act["recognized_at"], now_fn=self._now_fn
                ),
                "embedding": embedding_from_bytes(
                    bytes(raw_emb) if raw_emb is not None else None,
                    embedding_size=self._embedding_size,
                ),
            }

        items: list[dict[str, Any]] = []
        by_id: dict[int, dict[str, Any]] = {}
        for idx, meta in enumerate(meta_rows):
            rid = int(meta["id"])
            has_img = rid in img_map or idx < self.image_rows_limit
            merged = dict(meta)
            if rid in img_map:
                merged["plate_image"], merged["face_image"] = img_map[rid]
            built = self._build_item(merged, images_loaded=has_img)
            items.append(built)
            by_id[rid] = built

        with self._lock:
            self._items = items
            self._by_id = by_id
            self._active_sessions = active_sessions
            self.ready = True

    def find_active_session(self, plate_number: str) -> tuple[bool, dict[str, Any] | None]:
        """Return `(mirror_ready, active_session_or_none)` from RAM."""
        norm_plate = clean_plate_key(plate_number)
        with self._lock:
            if not self.ready:
                return False, None
            found = self._active_sessions.get(norm_plate)
            return True, (dict(found) if found is not None else None)

    def apply_inserted_record(self, new_id: int, record: dict[str, Any]) -> None:
        """Apply a newly committed MySQL record to the mirror and evict excess images."""
        plate_number = str(record.get("plate_number") or "")
        plate_key = clean_plate_key(plate_number)
        direction = str(record.get("direction") or "IN").upper()
        parking_status = "EXITED" if direction == "OUT" else "IN_PARKING"
        fee_amount = (
            0 if direction == "OUT" else int(record.get("fee_amount", self.fee_vnd))
        )
        emb = record.get("face_embedding")
        has_emb = emb is not None and len(emb) > 0

        with self._lock:
            if not self.ready:
                return

            for existing in self._items:
                if (
                    existing["plate_key"] == plate_key
                    and existing["direction"] == "IN"
                    and existing["parking_status"] == "IN_PARKING"
                ):
                    existing["parking_status"] = "COMPLETED"

            if direction == "IN":
                self._active_sessions[plate_key] = {
                    "id": int(new_id),
                    "plate_number": plate_number,
                    "recognized_at": format_timestamp_str(
                        record.get("recognized_at"), now_fn=self._now_fn
                    ),
                    "embedding": list(emb) if has_emb else None,
                }
            else:
                self._active_sessions.pop(plate_key, None)

            raw_row = {
                "id": int(new_id),
                "plate_number": plate_number,
                "plate_key": plate_key,
                "direction": direction,
                "parking_status": parking_status,
                "entry_record_id": record.get("entry_record_id"),
                "fee_amount": fee_amount,
                "recognized_at": record.get("recognized_at"),
                "vote_count": record.get("vote_count", 0),
                "sample_count": record.get("sample_count", 0),
                "consensus_rate": record.get("consensus_rate", 0.0),
                "face_detected": record.get("face_detected", False),
                "face_confidence": record.get("face_confidence"),
                "face_embedding": has_emb,
                "face_match_score": record.get("face_match_score"),
                "plate_image": record.get("plate_image"),
                "face_image": record.get("face_image"),
                "camera_index": record.get("camera_index", 0),
            }
            new_item = self._build_item(raw_row, images_loaded=True)
            self._items.insert(0, new_item)
            self._by_id[int(new_id)] = new_item
            if len(self._items) >= 2 and (
                self._items[0]["recognized_at"],
                self._items[0]["id"],
            ) < (
                self._items[1]["recognized_at"],
                self._items[1]["id"],
            ):
                self._items.sort(
                    key=lambda it: (it["recognized_at"], it["id"]), reverse=True
                )

            for evicted in self._items[self.image_rows_limit :]:
                if evicted["images_loaded"]:
                    evicted["plate_image"] = None
                    evicted["face_image"] = None
                    evicted["images_loaded"] = False

    def query_overview(
        self,
        query: str = "",
        status_filter: str = "all",
        limit: int | None = None,
        page: int = 1,
        page_size: int = 10,
        include_records: bool = True,
        include_stats: bool = True,
        include_revenue: bool = False,
        sort_by: str = "",
        known_stats: dict[str, Any] | None = None,
        include_stats_and_revenue: bool | None = None,
    ) -> dict[str, Any] | None:
        """Query overview stats, revenue, and raw records from RAM or signal fallback."""
        del known_stats
        if include_stats_and_revenue is not None:
            include_stats = bool(include_stats_and_revenue)
            include_revenue = bool(include_stats_and_revenue)

        with self._lock:
            if not self.ready:
                return None
            items = list(self._items)

        vn_now = self._now_fn()
        today_start = vn_now.replace(hour=0, minute=0, second=0)
        stats_payload = (
            compute_mirror_stats(items, today_start) if include_stats else None
        )
        revenue_report = (
            compute_mirror_revenue(items, vn_now, self.fee_vnd)
            if include_revenue
            else None
        )

        if not include_records:
            return {
                "stats": stats_payload,
                "revenue": revenue_report,
                "matched": 0,
                "page": 1,
                "records": [],
            }

        filtered = filter_and_sort_mirror_items(
            items, query, status_filter, sort_by, self.match_threshold
        )
        matched = len(filtered)
        effective_limit, safe_page, effective_offset = compute_pagination(
            matched, limit, page, page_size
        )
        page_slice = filtered[effective_offset : effective_offset + effective_limit]
        if any(not it["images_loaded"] for it in page_slice):
            return None

        return {
            "stats": stats_payload,
            "revenue": revenue_report,
            "matched": matched,
            "page": safe_page,
            "records": [strip_internal_fields(it) for it in page_slice],
        }

    def get_session_case(self, record_id: int) -> tuple[bool, dict[str, Any] | None]:
        """Resolve paired raw Check-in/Check-out records from RAM or signal fallback."""
        rec_id = int(record_id)
        with self._lock:
            if not self.ready:
                return False, None
            target = self._by_id.get(rec_id)
            if target is None:
                return True, None
            items = list(self._items)
            by_id = dict(self._by_id)

        checkin_item, checkout_item = resolve_mirror_session_pair(target, items, by_id)
        if (checkin_item is not None and not checkin_item["images_loaded"]) or (
            checkout_item is not None and not checkout_item["images_loaded"]
        ):
            return False, None

        return True, build_session_case_payload(
            strip_internal_fields(target),
            strip_internal_fields(checkin_item) if checkin_item else None,
            strip_internal_fields(checkout_item) if checkout_item else None,
        )
