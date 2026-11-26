"""Shared pytest fixtures, in-process ASGI test client, and fake DB/AI adapters."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
import gzip
import json
import threading
from typing import Any
from urllib.parse import urlencode, urlsplit

import cv2
import numpy as np
import pytest

from src.backend.ai.plate_detector import PlateDetectionResult
from src.backend.config import Settings
from src.backend.domain.face_math import cosine_similarity, embedding_from_bytes, embedding_to_bytes
from src.backend.domain.models import FaceDetection
from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.main import create_app
from src.backend.observability.metrics import MetricsRegistry
from src.backend.services.gate_service import GateService
from src.backend.services.management_service import ManagementService
from src.backend.storage.exceptions import DatabaseOperationError
from src.backend.storage.mirror_helpers import (
    compute_mirror_revenue,
    compute_mirror_stats,
    filter_and_sort_mirror_items,
    resolve_mirror_session_pair,
)
from src.backend.storage.query_helpers import (
    build_session_case_payload,
    compute_pagination,
    format_timestamp_str,
    normalize_raw_record,
    strip_internal_fields,
)
from src.backend.storage.warm_mirror import WarmDatabaseMirror


class CaseInsensitiveHeaders(Mapping[str, str]):
    """Read-only case-insensitive HTTP header mapping."""

    def __init__(self, pairs: list[tuple[bytes, bytes]]) -> None:
        self._items: dict[str, str] = {}
        for k, v in pairs:
            key = k.decode("latin-1").lower()
            val = v.decode("latin-1")
            if key in self._items:
                self._items[key] = f"{self._items[key]}, {val}"
            else:
                self._items[key] = val

    def __getitem__(self, key: str) -> str:
        return self._items[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


class AsgiResponse:
    """HTTP response returned by AsgiTestClient."""

    def __init__(self, status_code: int, headers: CaseInsensitiveHeaders, content: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


class AsgiTestClient:
    """Zero-dependency ASGI 3.0 HTTP + Lifespan client (no httpx required)."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._in_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._out_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._lifespan_task: asyncio.Task[Any] | None = None

    def __enter__(self) -> AsgiTestClient:
        ready_event = threading.Event()
        startup_error: list[BaseException] = []

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            in_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            out_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._in_queue = in_q
            self._out_queue = out_q

            async def _run_lifespan() -> None:
                scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}}
                await self.app(scope, in_q.get, out_q.put)

            async def _startup() -> None:
                self._lifespan_task = asyncio.create_task(_run_lifespan())
                await in_q.put({"type": "lifespan.startup"})
                msg = await out_q.get()
                if msg["type"] == "lifespan.startup.failed":
                    raise RuntimeError(msg.get("message", "ASGI lifespan startup failed"))

            try:
                loop.run_until_complete(_startup())
            except BaseException as exc:  # noqa: BLE001
                startup_error.append(exc)
            finally:
                ready_event.set()

            if not startup_error:
                loop.run_forever()
            loop.close()

        self._thread = threading.Thread(target=_runner, name="datn2-asgi-test", daemon=True)
        self._thread.start()
        ready_event.wait(timeout=10.0)
        if startup_error:
            raise startup_error[0]
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        del exc_type, exc, tb
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _shutdown() -> None:
            if self._in_queue is not None and self._out_queue is not None:
                await self._in_queue.put({"type": "lifespan.shutdown"})
                await self._out_queue.get()
            if self._lifespan_task is not None:
                await self._lifespan_task

        fut = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        fut.result(timeout=10.0)
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        self._loop = None
        self._thread = None

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsgiResponse:
        parsed = urlsplit(url)
        query_items: list[str] = []
        if parsed.query:
            query_items.append(parsed.query)
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                query_items.append(urlencode(filtered, doseq=True))
        query_bytes = "&".join(query_items).encode("ascii")

        req_headers: dict[str, str] = {"host": "testserver"}
        if headers:
            for k, v in headers.items():
                req_headers[k.lower()] = v

        body = b""
        if json is not None:
            body = json_module_dumps(json).encode("utf-8")
            req_headers.setdefault("content-type", "application/json")
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        if body:
            req_headers.setdefault("content-length", str(len(body)))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": parsed.path or "/",
            "raw_path": (parsed.path or "/").encode("ascii"),
            "query_string": query_bytes,
            "root_path": "",
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in req_headers.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }

        async def _call() -> AsgiResponse:
            sent_request = False
            response_done = asyncio.Event()
            status_code = 500
            raw_headers: list[tuple[bytes, bytes]] = []
            chunks: list[bytes] = []

            async def _receive() -> dict[str, Any]:
                nonlocal sent_request
                if not sent_request:
                    sent_request = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await response_done.wait()
                return {"type": "http.disconnect"}

            async def _send(message: dict[str, Any]) -> None:
                nonlocal status_code, raw_headers
                if message["type"] == "http.response.start":
                    status_code = int(message["status"])
                    raw_headers = list(message.get("headers") or [])
                elif message["type"] == "http.response.body":
                    chunks.append(bytes(message.get("body") or b""))
                    if not message.get("more_body", False):
                        response_done.set()

            try:
                await self.app(scope, _receive, _send)
            finally:
                response_done.set()
            resp_headers = CaseInsensitiveHeaders(raw_headers)
            raw_body = b"".join(chunks)
            if resp_headers.get("content-encoding", "").lower() == "gzip" and raw_body:
                raw_body = gzip.decompress(raw_body)
            return AsgiResponse(status_code=status_code, headers=resp_headers, content=raw_body)

        if self._loop is not None and self._loop.is_running():
            return asyncio.run_coroutine_threadsafe(_call(), self._loop).result(timeout=15.0)
        return asyncio.run(_call())

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsgiResponse:
        return self.request("GET", url, params=params, headers=headers)

    def head(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsgiResponse:
        return self.request("HEAD", url, params=params, headers=headers)

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        data: bytes | str | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsgiResponse:
        return self.request("POST", url, params=params, json=json, data=data, headers=headers)


def json_module_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


class _InMemoryCursor:
    """Minimal dictionary cursor supporting WarmDatabaseMirror.load_from_cursor queries."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._result: list[dict[str, Any]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        ordered_desc = sorted(
            self._rows,
            key=lambda r: (r["recognized_at"], r["id"]),
            reverse=True,
        )
        if "SELECT id, plate_image, face_image" in sql:
            limit = int(params[0]) if params else len(ordered_desc)
            self._result = [
                {
                    "id": r["id"],
                    "plate_image": r.get("plate_image"),
                    "face_image": r.get("face_image"),
                }
                for r in ordered_desc[:limit]
            ]
        elif "WHERE direction = 'IN' AND parking_status = 'IN_PARKING'" in sql:
            ordered_asc = sorted(
                (
                    r
                    for r in self._rows
                    if r["direction"] == "IN" and r["parking_status"] == "IN_PARKING"
                ),
                key=lambda r: (r["recognized_at"], r["id"]),
            )
            self._result = [
                {
                    "id": r["id"],
                    "plate_number": r["plate_number"],
                    "plate_key": r["plate_key"],
                    "recognized_at": r["recognized_at"],
                    "face_embedding": r.get("face_embedding"),
                }
                for r in ordered_asc
            ]
        else:
            self._result = [
                {
                    "id": r["id"],
                    "plate_number": r["plate_number"],
                    "plate_key": r["plate_key"],
                    "direction": r["direction"],
                    "parking_status": r["parking_status"],
                    "entry_record_id": r.get("entry_record_id"),
                    "fee_amount": r["fee_amount"],
                    "recognized_at": r["recognized_at"],
                    "vote_count": r.get("vote_count", 0),
                    "sample_count": r.get("sample_count", 0),
                    "consensus_rate": r.get("consensus_rate", 0.0),
                    "face_detected": 1 if r.get("face_detected") else 0,
                    "face_confidence": r.get("face_confidence"),
                    "face_embedding": 1 if r.get("face_embedding") is not None else 0,
                    "face_match_score": r.get("face_match_score"),
                    "camera_index": r.get("camera_index", 0),
                }
                for r in ordered_desc
            ]

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._result)


class InMemoryParkingRepository:
    """Fake ParkingRepository backed by an in-memory row list."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or Settings(force_cpu=True)
        self._now_fn = now_fn or (lambda: datetime(2026, 11, 26, 15, 0, 0))
        self._lock = threading.Lock()
        self.rows: list[dict[str, Any]] = []
        self._next_id = 1
        self.fail_connect = False
        self.fail_reads = False
        self.fail_writes = False

    def initialize(
        self,
        warm_mirror: Any = None,
        seeder: Callable[[Any], Any] | None = None,
    ) -> None:
        if self.fail_connect:
            raise DatabaseOperationError("Simulated MySQL connection failure")
        if seeder is not None:
            seeder(self)
        if warm_mirror is not None:
            with self._lock:
                snapshot = [dict(r) for r in self.rows]
            warm_mirror.load_from_cursor(_InMemoryCursor(snapshot))

    def find_active_parking_session(self, plate_number: str) -> dict[str, Any] | None:
        if self.fail_reads:
            raise DatabaseOperationError("Simulated MySQL read failure")
        pk = clean_plate_key(plate_number)
        with self._lock:
            matches = [
                r
                for r in self.rows
                if r["plate_key"] == pk
                and r["direction"] == "IN"
                and r["parking_status"] == "IN_PARKING"
            ]
        if not matches:
            return None
        latest = max(matches, key=lambda r: (r["recognized_at"], r["id"]))
        raw_emb = latest.get("face_embedding")
        return {
            "id": int(latest["id"]),
            "plate_number": latest["plate_number"],
            "recognized_at": format_timestamp_str(latest["recognized_at"], now_fn=self._now_fn),
            "embedding": embedding_from_bytes(
                bytes(raw_emb) if raw_emb is not None else None,
                embedding_size=self.settings.embedding_size,
            ),
        }

    def insert_plate_record(self, record: dict[str, Any]) -> tuple[int, float | None]:
        if self.fail_writes:
            raise DatabaseOperationError("Simulated MySQL write failure")
        with self._lock:
            direction = str(record.get("direction") or "IN").upper()
            plate_number = str(record["plate_number"])
            plate_key = clean_plate_key(plate_number)
            emb = record.get("face_embedding")
            has_emb = emb is not None and len(emb) > 0
            match_score = record.get("face_match_score")
            entry_id = record.get("entry_record_id")

            if direction == "OUT":
                parking_status = "EXITED"
                fee_amount = 0
                if has_emb and match_score is None:
                    active = [
                        r
                        for r in self.rows
                        if r["plate_key"] == plate_key
                        and r["direction"] == "IN"
                        and r["parking_status"] == "IN_PARKING"
                    ]
                    if active:
                        latest = max(active, key=lambda r: (r["recognized_at"], r["id"]))
                        if entry_id is None:
                            entry_id = latest["id"]
                        prev_emb = embedding_from_bytes(
                            latest.get("face_embedding"),
                            embedding_size=self.settings.embedding_size,
                        )
                        if prev_emb is not None:
                            match_score = max(
                                -1.0,
                                min(1.0, cosine_similarity(emb, prev_emb)),
                            )
                record["entry_record_id"] = entry_id
            else:
                direction = "IN"
                parking_status = "IN_PARKING"
                fee_amount = int(record.get("fee_amount", self.settings.parking_fee_vnd))

            for r in self.rows:
                if (
                    r["plate_key"] == plate_key
                    and r["direction"] == "IN"
                    and r["parking_status"] == "IN_PARKING"
                ):
                    r["parking_status"] = "COMPLETED"

            new_id = self._next_id
            self._next_id += 1
            self.rows.append(
                {
                    "id": new_id,
                    "plate_number": plate_number,
                    "plate_key": plate_key,
                    "direction": direction,
                    "parking_status": parking_status,
                    "entry_record_id": entry_id,
                    "fee_amount": fee_amount,
                    "recognized_at": record["recognized_at"],
                    "vote_count": int(record.get("vote_count") or 0),
                    "sample_count": int(record.get("sample_count") or 0),
                    "consensus_rate": float(record.get("consensus_rate") or 0.0),
                    "face_detected": bool(record.get("face_detected")),
                    "face_confidence": record.get("face_confidence"),
                    "face_embedding": embedding_to_bytes(emb) if has_emb else None,
                    "face_match_score": match_score,
                    "plate_image": record.get("plate_image"),
                    "face_image": record.get("face_image"),
                    "camera_index": int(record.get("camera_index") or 0),
                }
            )
            return new_id, (float(match_score) if match_score is not None else None)

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
        del known_stats
        if self.fail_reads:
            raise DatabaseOperationError("Simulated MySQL read failure")
        if include_stats_and_revenue is not None:
            include_stats = bool(include_stats_and_revenue)
            include_revenue = bool(include_stats_and_revenue)

        with self._lock:
            items = [
                normalize_raw_record(
                    {**r, "face_embedding": r.get("face_embedding") is not None},
                    images_loaded=True,
                    now_fn=self._now_fn,
                )
                for r in sorted(
                    self.rows, key=lambda x: (x["recognized_at"], x["id"]), reverse=True
                )
            ]

        vn_now = self._now_fn()
        today_start = vn_now.replace(hour=0, minute=0, second=0, microsecond=0)
        stats = compute_mirror_stats(items, today_start) if include_stats else None
        revenue = (
            compute_mirror_revenue(items, vn_now, int(self.settings.parking_fee_vnd))
            if include_revenue
            else None
        )
        if not include_records:
            return {
                "stats": stats,
                "revenue": revenue,
                "matched": 0,
                "page": 1,
                "records": [],
            }

        filtered = filter_and_sort_mirror_items(
            items, query, status_filter, sort_by, float(self.settings.face_match_threshold)
        )
        matched = len(filtered)
        eff_limit, safe_page, eff_offset = compute_pagination(matched, limit, page, page_size)
        return {
            "stats": stats,
            "revenue": revenue,
            "matched": matched,
            "page": safe_page,
            "records": [
                strip_internal_fields(it) for it in filtered[eff_offset : eff_offset + eff_limit]
            ],
        }

    def fetch_parking_session_case(self, record_id: int) -> dict[str, Any] | None:
        if self.fail_reads:
            raise DatabaseOperationError("Simulated MySQL read failure")
        with self._lock:
            items = [
                normalize_raw_record(
                    {**r, "face_embedding": r.get("face_embedding") is not None},
                    images_loaded=True,
                    now_fn=self._now_fn,
                )
                for r in sorted(
                    self.rows, key=lambda x: (x["recognized_at"], x["id"]), reverse=True
                )
            ]
        by_id = {int(it["id"]): it for it in items}
        target = by_id.get(int(record_id))
        if target is None:
            return None
        checkin_item, checkout_item = resolve_mirror_session_pair(target, items, by_id)
        return build_session_case_payload(
            strip_internal_fields(target),
            strip_internal_fields(checkin_item) if checkin_item else None,
            strip_internal_fields(checkout_item) if checkout_item else None,
        )


def make_sharp_frame(seed: int = 0) -> np.ndarray:
    """Create a deterministic high-Laplacian-sharpness synthetic BGR frame (JPEG-resilient)."""
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    ys = np.arange(120)[:, None] // 6
    xs = np.arange(160)[None, :] // 6
    frame[(ys + xs) % 2 == (seed % 2)] = 255
    if seed:
        x0 = (seed * 23) % 120
        frame[10:30, x0 : x0 + 30] = (40, 180, 220)
    return frame


def encode_b64_jpeg(frame: np.ndarray) -> str:
    """Encode a BGR ndarray to JPEG Data URL suitable for /api/camera/browser-frame."""
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class StubPlateDetector:
    """Configurable PlateDetector test double."""

    def __init__(
        self,
        per_frame_fn: Callable[..., PlateDetectionResult] | None = None,
        *,
        is_ready: bool = True,
    ) -> None:
        self.is_ready = is_ready
        self.calls: list[tuple[str, int]] = []
        self._fn = per_frame_fn

    def load(self) -> None:
        self.is_ready = True

    def detect(self, frame: Any) -> PlateDetectionResult:
        self.calls.append(("single", 1))
        return self._fn("single", frame, 0) if self._fn else PlateDetectionResult()

    def detect_batch(self, frames: list[Any]) -> list[PlateDetectionResult]:
        self.calls.append(("batch", len(frames)))
        if self._fn:
            return [self._fn("batch", frame, idx) for idx, frame in enumerate(frames)]
        return [PlateDetectionResult() for _ in frames]


class StubFaceService:
    """Configurable FaceService test double."""

    def __init__(
        self,
        *,
        detect_fn: Callable[[np.ndarray], list[FaceDetection]] | None = None,
        embed_fn: Callable[[np.ndarray, tuple[int, int, int, int]], list[float] | None] | None = None,
        embedding: list[float] | None = None,
        can_embed: bool = True,
    ) -> None:
        self.can_embed = can_embed
        self._detect_fn = detect_fn
        self._embed_fn = embed_fn
        self._embedding = embedding if embedding is not None else ([1.0] + [0.0] * 511)
        self.detect_calls = 0

    def detect_from_bgr(self, frame: np.ndarray) -> list[FaceDetection]:
        self.detect_calls += 1
        if self._detect_fn is not None:
            return self._detect_fn(frame)
        return [FaceDetection(box=(20, 15, 110, 105), confidence=0.92)]

    def embed_face(self, frame: np.ndarray, box: tuple[int, int, int, int]) -> list[float] | None:
        if not self.can_embed:
            return None
        if self._embed_fn is not None:
            return self._embed_fn(frame, box)
        return list(self._embedding)


@pytest.fixture
def fake_mysql_store() -> InMemoryParkingRepository:
    return InMemoryParkingRepository()


@pytest.fixture
def stub_ai() -> tuple[StubPlateDetector, StubFaceService]:
    return StubPlateDetector(), StubFaceService()


@pytest.fixture
def test_app_factory(
    fake_mysql_store: InMemoryParkingRepository,
    stub_ai: tuple[StubPlateDetector, StubFaceService],
) -> Callable[..., Any]:
    def _factory(
        *,
        settings: Settings | None = None,
        plate_detector: Any = None,
        face_service: Any = None,
        repo: InMemoryParkingRepository | None = None,
        clock: dict[str, Any] | None = None,
        connect_db: bool = True,
        enable_lifespan_startup: bool = False,
    ) -> Any:
        clk = clock if clock is not None else {
            "mono": 100.0,
            "now": datetime(2026, 11, 26, 15, 0, 0),
        }
        cfg = settings or Settings(force_cpu=True)
        resolved_repo = repo or fake_mysql_store
        resolved_repo.settings = cfg
        resolved_repo._now_fn = lambda: clk["now"]

        metrics = MetricsRegistry()
        mirror = WarmDatabaseMirror(
            image_rows_limit=cfg.warm_mirror_max_image_records,
            fee_vnd=cfg.parking_fee_vnd,
            match_threshold=cfg.face_match_threshold,
            now_fn=lambda: clk["now"],
            embedding_size=cfg.embedding_size,
        )
        mgmt = ManagementService(
            repository=resolved_repo,  # type: ignore[arg-type]
            warm_mirror=mirror,
            settings=cfg,
            metrics=metrics,
            now_fn=lambda: clk["now"],
            monotonic_fn=lambda: clk["mono"],
        )
        if connect_db:
            mgmt.connect_database()

        det, face = stub_ai
        gate = GateService(
            management_service=mgmt,
            settings=cfg,
            plate_detector=plate_detector or det,
            face_service=face_service if face_service is not None else face,
            metrics=metrics,
            monotonic_fn=lambda: clk["mono"],
            now_fn=lambda: clk["now"],
        )
        return create_app(
            settings=cfg,
            repository=resolved_repo,  # type: ignore[arg-type]
            warm_mirror=mirror,
            management_service=mgmt,
            gate_service=gate,
            metrics=metrics,
            enable_lifespan_startup=enable_lifespan_startup,
        )

    return _factory


@pytest.fixture
def api_client(test_app_factory: Callable[..., Any]) -> Iterator[AsgiTestClient]:
    app = test_app_factory()
    with AsgiTestClient(app) as client:
        yield client
