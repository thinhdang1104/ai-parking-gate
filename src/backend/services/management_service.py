"""Management service coordinating MySQL, WarmDatabaseMirror, caches, and reconnect."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import logging
import threading
import time
from typing import Any

from src.backend.api.presenters import present_overview, present_session_case
from src.backend.config import Settings
from src.backend.observability.metrics import MetricsRegistry
from src.backend.storage.demo_seeder import seed_demo_records_if_empty
from src.backend.storage.exceptions import DatabaseConfigurationError, DatabaseOperationError
from src.backend.storage.mysql_client import now_vn
from src.backend.storage.repository import ParkingRepository
from src.backend.storage.warm_mirror import WarmDatabaseMirror

logger = logging.getLogger(__name__)


class ManagementService:
    """Facade over ParkingRepository & WarmDatabaseMirror with versioned read caches."""

    def __init__(
        self,
        repository: ParkingRepository,
        warm_mirror: WarmDatabaseMirror | None = None,
        settings: Settings | None = None,
        metrics: MetricsRegistry | None = None,
        now_fn: Callable[[], datetime] = now_vn,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repository = repository
        self.settings: Settings = settings if settings is not None else repository.settings
        self.warm_mirror: WarmDatabaseMirror = (
            warm_mirror
            if warm_mirror is not None
            else WarmDatabaseMirror(
                image_rows_limit=self.settings.warm_mirror_max_image_records,
                fee_vnd=self.settings.parking_fee_vnd,
                match_threshold=self.settings.face_match_threshold,
                now_fn=now_fn,
                embedding_size=self.settings.embedding_size,
            )
        )
        self.metrics = metrics
        self._now_fn = now_fn
        self._monotonic_fn = monotonic_fn
        self._lock = threading.Lock()
        self._db_write_lock = threading.Lock()
        self.database_ready: bool = False
        self.database_error: str | None = None
        self.records_version: int = 0
        self._overview_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._overview_summary_cache: dict[tuple[str, int], dict[str, Any]] = {}
        self._overview_cache_date: str | None = None
        self._session_case_cache: dict[tuple[int, int], dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._reconnect_thread: threading.Thread | None = None

    def set_db_status(self, ready: bool, error: str | None) -> None:
        """Update database readiness and error state thread-safely."""
        with self._lock:
            self.database_ready = ready
            self.database_error = error

    def bump_version(self) -> int:
        """Increment `records_version` and clear overview/case read caches."""
        with self._lock:
            self.records_version += 1
            self._overview_cache.clear()
            self._overview_summary_cache.clear()
            self._session_case_cache.clear()
            return self.records_version

    def get_status_snapshot(self) -> tuple[bool, str | None, int]:
        """Return `(database_ready, database_error, records_version)` consistently."""
        with self._lock:
            return self.database_ready, self.database_error, self.records_version

    def connect_database(self) -> None:
        """Initialize schema, optionally seed demo rows, warm RAM mirror, and bump version."""
        seeder = (
            (lambda repo: seed_demo_records_if_empty(repo, enabled=True))
            if self.settings.seed_demo_data
            else None
        )
        try:
            self.repository.initialize(warm_mirror=self.warm_mirror, seeder=seeder)
        except (DatabaseConfigurationError, DatabaseOperationError) as err:
            self.set_db_status(False, str(err))
            raise
        self.set_db_status(True, None)
        self.bump_version()

    def store_record(self, record: dict[str, Any]) -> bool:
        """Persist one IN/OUT record to MySQL, sync WarmDatabaseMirror, and bump version."""
        inserted_to_db = False
        with self._db_write_lock:
            try:
                new_id, match_score = self.repository.insert_plate_record(record)
                if match_score is not None:
                    record["face_match_score"] = match_score
                if new_id is not None and self.warm_mirror.ready:
                    self.warm_mirror.apply_inserted_record(int(new_id), record)
                self.set_db_status(True, None)
                inserted_to_db = True
                if self.metrics is not None:
                    self.metrics.inc("db_commits_succeeded")
            except (DatabaseConfigurationError, DatabaseOperationError) as err:
                self.set_db_status(False, str(err))
                if self.metrics is not None:
                    self.metrics.inc("db_commits_failed")
                logger.warning("Không thể ghi bản ghi vào MySQL: %s", err)

        if inserted_to_db:
            self.bump_version()
        return inserted_to_db

    def get_active_parking_session(
        self, plate_number: str
    ) -> tuple[dict[str, Any] | None, bool]:
        """Return `(active_session, db_ok)` from WarmDatabaseMirror or MySQL fallback."""
        with self._lock:
            db_ready = self.database_ready
        if not db_ready:
            return None, False

        warm_ready, warm_sess = self.warm_mirror.find_active_session(plate_number)
        if warm_ready:
            return warm_sess, True

        try:
            return self.repository.find_active_parking_session(plate_number), True
        except (DatabaseConfigurationError, DatabaseOperationError) as err:
            self.set_db_status(False, str(err))
            return None, False

    def get_cached_overview(
        self,
        q: str = "",
        status: str = "all",
        limit: int | None = None,
        page: int = 1,
        page_size: int = 10,
        include_records: bool = True,
        include_revenue: bool | None = None,
        sort_by: str = "",
    ) -> dict[str, Any]:
        """Return formatted overview stats, revenue, and paginated records with caching."""
        eff_rev = bool(include_revenue) if include_revenue is not None else (not include_records)
        safe_sort = sort_by.strip() if sort_by else ""
        today_str = self._now_fn().strftime("%Y-%m-%d")

        with self._lock:
            if self._overview_cache_date != today_str:
                self._overview_cache.clear()
                self._overview_summary_cache.clear()
                self._overview_cache_date = today_str
            ver = self.records_version
            key = (
                today_str, ver, q.strip(), status.strip(), safe_sort,
                limit, int(page), int(page_size), bool(include_records),
            )
            cached = self._overview_cache.get(key)
            summary_key = (today_str, ver)
            cached_summary = self._overview_summary_cache.get(summary_key)

        cached_stats = cached_summary.get("stats") if cached_summary else None
        cached_revenue = cached_summary.get("revenue") if cached_summary else None
        if cached is not None:
            if not eff_rev or cached.get("revenue") is not None:
                return cached
            if cached_revenue is not None:
                return {**cached, "revenue": cached_revenue}

        need_stats = cached_stats is None
        need_revenue = eff_rev and (cached_revenue is None)
        if not include_records and not need_stats and not need_revenue:
            return {"stats": cached_stats, "revenue": cached_revenue, "matched": 0, "page": 1, "records": []}

        raw_overview = self.warm_mirror.query_overview(
            q, status, limit=limit, page=page, page_size=page_size,
            include_records=include_records, include_stats=need_stats,
            include_revenue=need_revenue, sort_by=safe_sort,
        )
        if raw_overview is None:
            raw_overview = self.repository.fetch_overview(
                q, status, limit=limit, page=page, page_size=page_size,
                include_records=include_records, include_stats=need_stats,
                include_revenue=need_revenue, known_stats=cached_stats, sort_by=safe_sort,
            )

        overview = present_overview(raw_overview, match_threshold=self.settings.face_match_threshold)
        if overview.get("stats") is None and cached_stats is not None:
            overview["stats"] = cached_stats
        if overview.get("revenue") is None and cached_revenue is not None:
            overview["revenue"] = cached_revenue

        with self._lock:
            if self.records_version == ver and self._overview_cache_date == today_str:
                merged = dict(self._overview_summary_cache.get(summary_key) or {"stats": None, "revenue": None})
                if overview.get("stats") is not None:
                    merged["stats"] = overview["stats"]
                if overview.get("revenue") is not None:
                    merged["revenue"] = overview["revenue"]
                if merged["stats"] is not None or merged["revenue"] is not None:
                    self._overview_summary_cache[summary_key] = merged
                if len(self._overview_cache) >= self.settings.overview_cache_max_size:
                    self._overview_cache.pop(next(iter(self._overview_cache)), None)
                self._overview_cache[key] = overview
        return overview

    def get_cached_session_case(self, record_id: int) -> dict[str, Any] | None:
        """Return formatted paired Check-in/Check-out session case with versioned caching."""
        rec_id = int(record_id)
        with self._lock:
            ver = self.records_version
            cache_key = (ver, rec_id)
            cached_case = self._session_case_cache.get(cache_key)
        if cached_case is not None:
            return cached_case

        handled_in_ram, raw_case = self.warm_mirror.get_session_case(rec_id)
        if not handled_in_ram:
            raw_case = self.repository.fetch_parking_session_case(rec_id)
        if raw_case is None:
            return None

        case_data = present_session_case(raw_case, match_threshold=self.settings.face_match_threshold)
        with self._lock:
            if self.records_version == ver:
                if len(self._session_case_cache) >= self.settings.session_case_cache_max_size:
                    self._session_case_cache.pop(next(iter(self._session_case_cache)), None)
                self._session_case_cache[cache_key] = case_data
        return case_data

    def _db_reconnect_loop(self) -> None:
        last_retry = self._monotonic_fn()
        wait_step = min(1.0, max(0.01, float(self.settings.db_retry_seconds)))
        while not self._stop_event.wait(timeout=wait_step):
            with self._lock:
                ready = self.database_ready
            now = self._monotonic_fn()
            if not ready and now - last_retry >= self.settings.db_retry_seconds:
                last_retry = now
                try:
                    self.connect_database()
                    logger.info("Đã kết nối lại MySQL thành công.")
                except (DatabaseConfigurationError, DatabaseOperationError):
                    pass

    def start_reconnect_loop(self) -> None:
        """Start background MySQL reconnect thread if not already running."""
        if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
            return
        self._stop_event.clear()
        self._reconnect_thread = threading.Thread(
            target=self._db_reconnect_loop,
            name="datn2-db-reconnect",
            daemon=True,
        )
        self._reconnect_thread.start()

    def stop_reconnect_loop(self, timeout: float = 15.0) -> None:
        """Signal the reconnect loop to exit and join cleanly."""
        self._stop_event.set()
        thread = self._reconnect_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._reconnect_thread = None
