"""Unit tests for structured logging and thread-safe metrics registry."""

from __future__ import annotations

import io
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from src.backend.observability.logging_config import (
    JsonFormatter,
    VN_TZ,
    bind_request_id,
    configure_logging,
    get_request_id,
    request_id_context,
    reset_request_id,
)
from src.backend.observability.metrics import MetricsRegistry


def test_json_formatter_outputs_required_fields_and_utc7_timestamp() -> None:
    stream = io.StringIO()
    logger = configure_logging(
        level="INFO",
        stream=stream,
        logger_name="test.observability.json",
    )

    token = bind_request_id("req-abc-123")
    try:
        logger.info(
            "Gate frame processed",
            extra={"extra_fields": {"camera": "A", "plate": "59A-12345"}, "latency_ms": 12.5},
        )
    finally:
        reset_request_id(token)

    payload = json.loads(stream.getvalue().strip())
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.observability.json"
    assert payload["message"] == "Gate frame processed"
    assert payload["request_id"] == "req-abc-123"
    assert payload["extra_fields"] == {
        "camera": "A",
        "plate": "59A-12345",
        "latency_ms": 12.5,
    }

    parsed_ts = datetime.fromisoformat(payload["timestamp"])
    assert parsed_ts.utcoffset() == VN_TZ.utcoffset(parsed_ts)


def test_json_formatter_includes_exception_when_exc_info_present() -> None:
    formatter = JsonFormatter()
    try:
        raise RuntimeError("db timeout")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="test.exc",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Commit failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "ERROR"
    assert payload["message"] == "Commit failed"
    assert "RuntimeError: db timeout" in payload["exception"]


def test_request_id_contextvar_propagation_and_reset() -> None:
    assert get_request_id() is None

    outer_token = bind_request_id("req-outer")
    try:
        assert get_request_id() == "req-outer"
        with request_id_context("req-inner") as active:
            assert active == "req-inner"
            assert get_request_id() == "req-inner"
        assert get_request_id() == "req-outer"
    finally:
        reset_request_id(outer_token)

    assert get_request_id() is None


def test_configure_logging_replaces_prior_datn2_handler_without_duplicates() -> None:
    stream_one = io.StringIO()
    stream_two = io.StringIO()
    logger_name = "test.observability.reconfigure"

    logger = configure_logging("WARNING", stream=stream_one, logger_name=logger_name)
    configure_logging("DEBUG", stream=stream_two, logger_name=logger_name)

    assert len(logger.handlers) == 1
    logger.debug("hello debug")
    assert stream_one.getvalue() == ""
    assert "hello debug" in stream_two.getvalue()


def test_metrics_registry_counters_errors_and_latencies() -> None:
    registry = MetricsRegistry()

    assert registry.inc("http_requests") == 1
    assert registry.inc("http_requests", 4) == 5
    assert registry.inc_error("db_commit") == 1

    registry.record_latency("yolo_infer", 10.0)
    registry.record_latency("yolo_infer", 20.0)
    registry.record_latency("yolo_infer", 30.0)

    snap = registry.snapshot()
    assert snap["counters"] == {"http_requests": 5}
    assert snap["errors"] == {"db_commit": 1}
    assert snap["latencies"]["yolo_infer"] == {
        "count": 3,
        "avg_ms": 20.0,
        "max_ms": 30.0,
        "last_ms": 30.0,
    }
    assert snap["uptime_seconds"] >= 0.0

    health = registry.health_summary()
    assert health["status"] == "ok"
    assert health["total_errors"] == 1
    assert health["counters"] == {"http_requests": 5}


def test_metrics_registry_track_latency_measures_and_counts_exceptions() -> None:
    registry = MetricsRegistry()

    with registry.track_latency("db_query"):
        time.sleep(0.005)

    with pytest.raises(ValueError, match="boom"):
        with registry.track_latency("db_query"):
            raise ValueError("boom")

    snap = registry.snapshot()
    assert snap["latencies"]["db_query"]["count"] == 2
    assert snap["latencies"]["db_query"]["max_ms"] >= 0.0
    assert snap["errors"]["db_query"] == 1


def test_metrics_registry_rolling_window_bounds_samples() -> None:
    registry = MetricsRegistry(latency_window=2)
    registry.record_latency("op", 100.0)
    registry.record_latency("op", 10.0)
    registry.record_latency("op", 20.0)

    stats = registry.snapshot()["latencies"]["op"]
    assert stats["count"] == 3
    assert stats["avg_ms"] == 15.0
    assert stats["max_ms"] == 20.0
    assert stats["last_ms"] == 20.0


def test_metrics_registry_thread_safety() -> None:
    registry = MetricsRegistry(latency_window=500)
    workers = 8
    iterations = 250

    def worker(worker_id: int) -> None:
        for idx in range(iterations):
            registry.inc("requests")
            if idx % 5 == 0:
                registry.inc_error("transient")
            with registry.track_latency("infer"):
                _ = worker_id * idx
            if idx % 25 == 0:
                _ = registry.snapshot()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, wid) for wid in range(workers)]
        for fut in futures:
            fut.result()

    snap = registry.snapshot()
    assert snap["counters"]["requests"] == workers * iterations
    assert snap["errors"]["transient"] == workers * (iterations // 5)
    assert snap["latencies"]["infer"]["count"] == workers * iterations
