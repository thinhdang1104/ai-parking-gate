"""Integration tests for FastAPI routes, status codes, validation, and middleware."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.backend.ai.plate_detector import PlateDetectionResult
from src.backend.config import MAX_BROWSER_FRAME_B64_CHARS, Settings
from tests.conftest import (
    AsgiTestClient,
    InMemoryParkingRepository,
    StubFaceService,
    StubPlateDetector,
    encode_b64_jpeg,
    make_sharp_frame,
)

EXPECTED_GATE_STATUS_KEYS = {
    "running",
    "committing",
    "cam1",
    "cam2",
    "latched",
    "security_alert",
    "gate_feedback",
    "ambiguous_frame",
    "error",
    "records_version",
    "database_ready",
    "models_ready",
    "face_match_threshold",
}

EXPECTED_HEALTH_KEYS = {
    "status",
    "database_ready",
    "models_ready",
    "face_encoder_ready",
    "warm_mirror_ready",
    "uptime_seconds",
    "version",
}

EXPECTED_METRIC_COUNTER_KEYS = {
    "frames_received",
    "frames_processed",
    "frames_skipped_busy",
    "frames_deduplicated",
    "plates_detected",
    "faces_detected",
    "latches_started",
    "latches_committed",
    "latches_cancelled",
    "latches_timed_out",
    "security_alerts_triggered",
    "security_alerts_approved",
    "security_alerts_rejected",
    "db_commits_succeeded",
    "db_commits_failed",
    "records_version",
    "warm_mirror_count",
}


def test_static_ui_placeholder_and_mounted_assets(
    test_app_factory: Callable[..., Any],
    tmp_path: Path,
) -> None:
    empty_fe = tmp_path / "empty_fe"
    empty_fe.mkdir()
    app_placeholder = test_app_factory(settings=Settings(force_cpu=True, frontend_dir=empty_fe))
    with AsgiTestClient(app_placeholder) as client:
        for path in ("/", "/ui"):
            res_get = client.get(path)
            assert res_get.status_code == 200
            assert "no-cache" in res_get.headers["cache-control"]
            assert "DATN2" in res_get.text
            res_head = client.head(path)
            assert res_head.status_code == 200

    built_fe = tmp_path / "built_fe"
    (built_fe / "css").mkdir(parents=True)
    (built_fe / "js").mkdir(parents=True)
    (built_fe / "index.html").write_text("<html><body>DATN2 UI</body></html>", encoding="utf-8")
    (built_fe / "css" / "tokens.css").write_text(":root { --bg: #000; }", encoding="utf-8")
    (built_fe / "js" / "main.js").write_text("console.log('ok');", encoding="utf-8")

    app_built = test_app_factory(settings=Settings(force_cpu=True, frontend_dir=built_fe))
    with AsgiTestClient(app_built) as client:
        idx = client.get("/")
        assert idx.status_code == 200
        assert "DATN2 UI" in idx.text
        assert "no-cache" in idx.headers["cache-control"]

        css = client.get("/css/tokens.css")
        assert css.status_code == 200
        assert "--bg" in css.text
        assert "no-cache" in css.headers["cache-control"]

        js = client.get("/js/main.js")
        assert js.status_code == 200
        assert "console.log" in js.text
        assert "no-cache" in js.headers["cache-control"]


def test_camera_lifecycle_browser_frame_latch_and_validation(
    test_app_factory: Callable[..., Any],
) -> None:
    def plate_fn(mode: str, frame: Any, idx: int = 0) -> PlateDetectionResult:
        del mode, frame
        if idx == 0:
            return PlateDetectionResult(
                plate_present=True,
                readings={"59V179379": "59V1-79379"},
                plate_boxes=[
                    {
                        "x1": 0.1,
                        "y1": 0.1,
                        "x2": 0.5,
                        "y2": 0.4,
                        "label": "59V1-79379",
                        "valid": True,
                    }
                ],
                plate_crops={"59V179379": (40.0, "data:image/jpeg;base64,AA==")},
                reading_confs={"59V179379": 0.88},
            )
        return PlateDetectionResult()

    app = test_app_factory(
        plate_detector=StubPlateDetector(per_frame_fn=plate_fn),
        face_service=StubFaceService(detect_fn=lambda _frame: []),
    )
    with AsgiTestClient(app) as client:
        status_res = client.get("/api/camera/status")
        assert status_res.status_code == 200
        assert EXPECTED_GATE_STATUS_KEYS.issubset(status_res.json().keys())
        assert status_res.json()["running"] is False

        # Stopped browser-frame -> active: False
        idle_frame = client.post("/api/camera/browser-frame", json={"cam1_image": "abc"})
        assert idle_frame.status_code == 200
        assert idle_frame.json() == {"active": False}

        # Invalid cam_id -> 404
        assert client.post("/api/camera/0/start").status_code == 404
        assert client.post("/api/camera/3/start").status_code == 404
        assert client.post("/api/camera/9/stop").status_code == 404

        # Start Cam 1 & Cam 2
        s1 = client.post("/api/camera/1/start")
        assert s1.status_code == 200
        assert s1.json() == {
            "status": "started",
            "cam_id": 1,
            "mode": "browser",
            "device_index": 0,
        }
        s2 = client.post("/api/camera/2/start")
        assert s2.status_code == 200
        assert s2.json()["device_index"] == 1

        # 422 validation errors
        bad_extra = client.post("/api/camera/browser-frame", json={"unexpected": "x"})
        assert bad_extra.status_code == 422
        oversized = client.post(
            "/api/camera/browser-frame",
            json={"cam1_image": "a" * (MAX_BROWSER_FRAME_B64_CHARS + 1)},
        )
        assert oversized.status_code == 422
        bad_alert = client.post("/api/camera/resolve-alert", json={"action": "ignore"})
        assert bad_alert.status_code == 422

        # Send 2 frames to trigger Fast-Confirm latch (no face -> stays latched)
        b64_1 = encode_b64_jpeg(make_sharp_frame(1))
        b64_2 = encode_b64_jpeg(make_sharp_frame(2))
        r1 = client.post("/api/camera/browser-frame", json={"cam1_image": b64_1, "cam2_image": b64_2})
        assert r1.status_code == 200
        assert r1.json()["processed"] is True
        app.state.container.gate_service._monotonic_fn = lambda: 100.12
        r2 = client.post("/api/camera/browser-frame", json={"cam1_image": b64_1, "cam2_image": b64_2})
        assert r2.status_code == 200
        assert r2.json()["status"]["latched"] is not None
        assert r2.json()["status"]["latched"]["plate_number"] == "59V1-79379"

        # Cancel latch
        cancelled = client.post("/api/camera/cancel-latch")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["camera_status"]["latched"] is None

        # Resolve alert when none active -> status: none
        no_alert = client.post("/api/camera/resolve-alert", json={"action": "reject"})
        assert no_alert.status_code == 200
        assert no_alert.json()["status"] == "none"

        # Stop individual and all cameras
        stop1 = client.post("/api/camera/1/stop")
        assert stop1.status_code == 200
        assert stop1.json() == {"status": "stopped", "cam_id": 1}
        stop_all = client.post("/api/camera/stop")
        assert stop_all.status_code == 200
        assert stop_all.json() == {"status": "stopped"}


def test_camera_start_value_error_maps_to_400(test_app_factory: Callable[..., Any]) -> None:
    app = test_app_factory()

    def _raise_value_error(cam_id: int) -> str:
        raise ValueError(f"Camera {cam_id} busy")

    app.state.container.gate_service.start_camera = _raise_value_error
    with AsgiTestClient(app) as client:
        res = client.post("/api/camera/1/start")
        assert res.status_code == 400
        assert "Camera 1 busy" in res.json()["detail"]


def test_management_overview_session_case_reconnect_and_db_failures(
    test_app_factory: Callable[..., Any],
    fake_mysql_store: InMemoryParkingRepository,
) -> None:
    fake_mysql_store.insert_plate_record(
        {
            "plate_number": "59V1-79379",
            "direction": "IN",
            "recognized_at": datetime(2026, 11, 26, 8, 0, 0),
            "vote_count": 3,
            "sample_count": 3,
            "consensus_rate": 1.0,
            "face_detected": True,
            "face_confidence": 0.94,
            "face_embedding": [1.0] + [0.0] * 511,
            "camera_index": 0,
        }
    )

    app = test_app_factory(repo=fake_mysql_store, connect_db=True)
    with AsgiTestClient(app) as client:
        # Overview with clamping + revenue
        ov = client.get(
            "/api/management/overview",
            params={
                "q": "59v1",
                "status": "in_parking",
                "limit": 5000,
                "page": -3,
                "page_size": 999,
                "include_revenue": True,
                "sort": "invalid_sort",
            },
        )
        assert ov.status_code == 200
        data = ov.json()
        assert data["database_ready"] is True
        assert data["database_error"] is None
        assert data["page"] == 1
        assert data["matched"] == 1
        assert data["stats"]["in_parking"] == 1
        assert data["revenue"]["unit_price"] == 2000
        assert data["revenue"]["today"]["revenue"] == 2000
        assert data["records"][0]["Biển số"] == "59V1-79379"

        # Session case found (200) & missing (404)
        case_ok = client.get("/api/management/session-case/1")
        assert case_ok.status_code == 200
        assert case_ok.json()["target_id"] == 1
        assert case_ok.json()["checkin_row"]["ID"] == 1
        assert case_ok.json()["checkout_row"] is None

        case_missing = client.get("/api/management/session-case/9999")
        assert case_missing.status_code == 404

        # Force cache miss + mirror miss + repo failure -> 503 on session-case
        app.state.container.management_service.bump_version()
        app.state.container.warm_mirror.ready = False
        fake_mysql_store.fail_reads = True
        case_503 = client.get("/api/management/session-case/1")
        assert case_503.status_code == 503

        # Overview falls back gracefully when DB disconnected
        ov_down = client.get("/api/management/overview")
        assert ov_down.status_code == 200
        assert ov_down.json()["database_ready"] is False
        assert ov_down.json()["stats"] is None
        assert ov_down.json()["records"] == []

        # Reconnect failure -> 503, then recovery -> 200
        fake_mysql_store.fail_connect = True
        rec_fail = client.post("/api/management/reconnect")
        assert rec_fail.status_code == 503

        fake_mysql_store.fail_connect = False
        fake_mysql_store.fail_reads = False
        rec_ok = client.post("/api/management/reconnect")
        assert rec_ok.status_code == 200
        assert rec_ok.json() == {"status": "ok"}


def test_health_metrics_request_id_and_gzip(
    test_app_factory: Callable[..., Any],
    fake_mysql_store: InMemoryParkingRepository,
) -> None:
    # Seed 15 records so overview JSON exceeds 1024 bytes for GZipMiddleware
    for idx in range(15):
        fake_mysql_store.insert_plate_record(
            {
                "plate_number": f"59V1-100{idx:02d}",
                "direction": "IN",
                "recognized_at": datetime(2026, 11, 26, 8, idx, 0),
                "vote_count": 3,
                "sample_count": 3,
                "consensus_rate": 1.0,
                "face_detected": True,
                "face_confidence": 0.9,
                "face_embedding": [1.0] + [0.0] * 511,
                "camera_index": 0,
            }
        )

    app = test_app_factory(repo=fake_mysql_store, connect_db=True)
    with AsgiTestClient(app) as client:
        # Healthy when DB + models ready
        health = client.get("/api/health", headers={"X-Request-ID": "custom-req-42"})
        assert health.status_code == 200
        assert health.headers["x-request-id"] == "custom-req-42"
        h_json = health.json()
        assert EXPECTED_HEALTH_KEYS.issubset(h_json.keys())
        assert h_json["status"] == "ok"
        assert h_json["database_ready"] is True
        assert h_json["models_ready"] is True
        assert h_json["face_encoder_ready"] is True
        assert h_json["warm_mirror_ready"] is True
        assert h_json["version"] == "2.0.0"

        # Degraded when DB goes down
        app.state.container.management_service.set_db_status(False, "offline")
        health_deg = client.get("/api/health")
        assert health_deg.status_code == 200
        assert len(health_deg.headers["x-request-id"]) == 12
        assert health_deg.json()["status"] == "degraded"

        # Metrics payload matches MetricsResponse + latencies/errors
        metrics_res = client.get("/api/metrics")
        assert metrics_res.status_code == 200
        m_json = metrics_res.json()
        assert EXPECTED_METRIC_COUNTER_KEYS.issubset(m_json.keys())
        assert m_json["warm_mirror_count"] == 15
        assert "http_request" in m_json["latencies"]

        # Large response compressed when Accept-Encoding: gzip is sent
        app.state.container.management_service.set_db_status(True, None)
        gz = client.get(
            "/api/management/overview",
            params={"page_size": 20},
            headers={"Accept-Encoding": "gzip"},
        )
        assert gz.status_code == 200
        assert gz.headers.get("content-encoding") == "gzip"
        assert len(gz.json()["records"]) == 15


def test_real_frontend_serves_html_css_and_es_modules(
    test_app_factory: Callable[..., Any],
) -> None:
    app = test_app_factory(settings=Settings(force_cpu=True))
    css_paths = (
        "/css/tokens.css",
        "/css/layout.css",
        "/css/components.css",
        "/css/camera.css",
    )
    js_paths = (
        "/js/main.js",
        "/js/api.js",
        "/js/state.js",
        "/js/utils.js",
        "/js/overlay.js",
        "/js/gate_ui.js",
        "/js/camera.js",
        "/js/history.js",
        "/js/revenue.js",
        "/js/lost_case_modal.js",
        "/js/pdf_export.js",
    )

    with AsgiTestClient(app) as client:
        for page_path in ("/", "/ui"):
            res = client.get(page_path)
            assert res.status_code == 200
            assert "no-cache" in res.headers["cache-control"]
            assert '<script type="module" src="/js/main.js">' in res.text
            for css_path in css_paths:
                assert f'<link rel="stylesheet" href="{css_path}"' in res.text

        for asset_path in (*css_paths, *js_paths):
            asset_res = client.get(asset_path)
            assert asset_res.status_code == 200, f"Failed asset: {asset_path}"
            assert asset_res.text.strip(), f"Empty asset: {asset_path}"

