"""Thread-safe in-process metrics registry for requests, AI inference, and DB."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class LatencyStats:
    """Rolling latency accumulator for a single named operation."""

    window_size: int = 200
    count: int = 0
    _samples: deque[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError("window_size must be >= 1")
        self._samples = deque(maxlen=self.window_size)

    def record(self, duration_ms: float) -> None:
        safe_ms = max(0.0, float(duration_ms))
        self.count += 1
        self._samples.append(safe_ms)

    def to_dict(self) -> dict[str, Any]:
        if not self._samples:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "max_ms": 0.0,
                "last_ms": 0.0,
            }
        avg_ms = sum(self._samples) / len(self._samples)
        max_ms = max(self._samples)
        last_ms = self._samples[-1]
        return {
            "count": self.count,
            "avg_ms": round(avg_ms, 3),
            "max_ms": round(max_ms, 3),
            "last_ms": round(last_ms, 3),
        }


class MetricsRegistry:
    """DI-friendly, thread-safe registry for counters, errors, and rolling latencies."""

    def __init__(self, latency_window: int = 200) -> None:
        if latency_window < 1:
            raise ValueError("latency_window must be >= 1")
        self._latency_window = latency_window
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._counters: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._latencies: dict[str, LatencyStats] = {}

    def inc(self, name: str, value: int = 1) -> int:
        """Increment a named counter by value and return its updated total."""
        if value < 0:
            raise ValueError("counter increment value must be >= 0")
        with self._lock:
            updated = self._counters.get(name, 0) + value
            self._counters[name] = updated
            return updated

    def inc_error(self, name: str, value: int = 1) -> int:
        """Increment an error counter by value and return its updated total."""
        if value < 0:
            raise ValueError("error increment value must be >= 0")
        with self._lock:
            updated = self._errors.get(name, 0) + value
            self._errors[name] = updated
            return updated

    def record_latency(self, name: str, duration_ms: float) -> None:
        """Record a duration sample in milliseconds for a named operation."""
        with self._lock:
            bucket = self._latencies.get(name)
            if bucket is None:
                bucket = LatencyStats(window_size=self._latency_window)
                self._latencies[name] = bucket
            bucket.record(duration_ms)

    @contextmanager
    def track_latency(
        self, name: str, *, count_error: bool = True
    ) -> Iterator[None]:
        """Measure elapsed wall time of a block and optionally count exceptions."""
        start = time.perf_counter()
        try:
            yield
        except Exception:
            if count_error:
                self.inc_error(name)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.record_latency(name, elapsed_ms)

    def get_counter(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def get_error(self, name: str) -> int:
        with self._lock:
            return self._errors.get(name, 0)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot suitable for /api/metrics."""
        with self._lock:
            return {
                "uptime_seconds": round(time.monotonic() - self._started_at, 3),
                "counters": dict(sorted(self._counters.items())),
                "errors": dict(sorted(self._errors.items())),
                "latencies": {
                    name: stats.to_dict()
                    for name, stats in sorted(self._latencies.items())
                },
            }

    def health_summary(self) -> dict[str, Any]:
        """Return a compact health summary suitable for /api/health."""
        snap = self.snapshot()
        return {
            "status": "ok",
            "uptime_seconds": snap["uptime_seconds"],
            "total_errors": sum(snap["errors"].values()),
            "counters": snap["counters"],
        }

    def reset(self) -> None:
        """Clear all recorded counters, errors, and latency buckets."""
        with self._lock:
            self._counters.clear()
            self._errors.clear()
            self._latencies.clear()
            self._started_at = time.monotonic()
