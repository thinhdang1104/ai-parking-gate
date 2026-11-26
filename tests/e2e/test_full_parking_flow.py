"""End-to-end parking lifecycle tests over FastAPI HTTP endpoints."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import time
from typing import Any

from src.backend.ai.plate_detector import PlateDetectionResult
from tests.conftest import (
    AsgiTestClient,
    InMemoryParkingRepository,
    StubFaceService,
    StubPlateDetector,
    encode_b64_jpeg,
    make_sharp_frame,
)


def _wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for condition")


def test_full_e2e_parking_in_out_security_alert_and_session_case(
    test_app_factory: Callable[..., Any],
    fake_mysql_store: InMemoryParkingRepository,
) -> None:
    clk = {"mono": 100.0, "now": datetime(2026, 11, 26, 15, 0, 0)}
    plate_visible = {"flag": True}
    active_embedding = {"vec": [1.0] + [0.0] * 511}

    def plate_fn(mode: str, frame: Any, idx: int = 0) -> PlateDetectionResult:
        del mode, frame
        if plate_visible["flag"] and idx == 0:
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
                plate_crops={"59V179379": (45.0, "data:image/jpeg;base64,PLATE")},
                reading_confs={"59V179379": 0.90},
            )
        return PlateDetectionResult()

    detector = StubPlateDetector(per_frame_fn=plate_fn)
    face_service = StubFaceService(
        embed_fn=lambda _frame, _box: list(active_embedding["vec"]),
    )
    app = test_app_factory(
        repo=fake_mysql_store,
        plate_detector=detector,
        face_service=face_service,
        clock=clk,
        connect_db=False,
    )

    f1_b64 = encode_b64_jpeg(make_sharp_frame(1))
    f2_b64 = encode_b64_jpeg(make_sharp_frame(2))
    empty_b64 = encode_b64_jpeg(make_sharp_frame(3))

    with AsgiTestClient(app) as client:
        # 1. Initially DB not connected -> health degraded, then reconnect -> ok
        assert client.get("/api/health").json()["status"] == "degraded"
        assert client.post("/api/management/reconnect").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"

        # 2. Start Cam 1 & Cam 2
        assert client.post("/api/camera/1/start").status_code == 200
        assert client.post("/api/camera/2/start").status_code == 200

        # 3. Vehicle IN via 2 browser-frame requests (Fast-Confirm + Cam 2 face)
        res_in_1 = client.post(
            "/api/camera/browser-frame",
            json={"cam1_image": f1_b64, "cam2_image": f2_b64},
        )
        assert res_in_1.status_code == 200
        assert res_in_1.json()["processed"] is True

        clk["mono"] = 100.12
        res_in_2 = client.post(
            "/api/camera/browser-frame",
            json={"cam1_image": f1_b64, "cam2_image": f2_b64},
        )
        assert res_in_2.status_code == 200

        _wait_until(
            lambda: (
                not client.get("/api/camera/status").json()["committing"]
                and client.get("/api/camera/status").json()["records_version"] >= 2
            )
        )
        status_after_in = client.get("/api/camera/status").json()
        assert "VÀO BÃI THÀNH CÔNG" in status_after_in["gate_feedback"]["message"]

        # 4. Overview reflects IN_PARKING & 2.000 d revenue
        ov_in = client.get("/api/management/overview", params={"include_revenue": True}).json()
        assert ov_in["stats"]["in_parking"] == 1
        assert ov_in["stats"]["total_in"] == 1
        assert ov_in["revenue"]["today"]["revenue"] == 2000
        assert ov_in["records"][0]["Biển số"] == "59V1-79379"
        assert ov_in["records"][0]["parking_status_code"] == "IN_PARKING"

        # 5. Vehicle leaves camera view (>1.5s) & cooldown expires (>20s), then returns for OUT with mismatched face
        plate_visible["flag"] = False
        clk["mono"] = 103.0
        client.post(
            "/api/camera/browser-frame",
            json={"cam1_image": empty_b64, "cam2_image": f2_b64},
        )

        plate_visible["flag"] = True
        active_embedding["vec"] = [0.0, 1.0] + [0.0] * 510  # cosine_similarity = 0.0 < 0.65
        clk["now"] = datetime(2026, 11, 26, 16, 15, 0)
        clk["mono"] = 125.0
        client.post("/api/camera/browser-frame", json={"cam1_image": f1_b64, "cam2_image": f2_b64})
        clk["mono"] = 125.12
        res_out_2 = client.post(
            "/api/camera/browser-frame",
            json={"cam1_image": f1_b64, "cam2_image": f2_b64},
        )
        assert res_out_2.status_code == 200

        alert_status = client.get("/api/camera/status").json()
        assert alert_status["security_alert"] is not None
        assert alert_status["security_alert"]["plate_number"] == "59V1-79379"

        # 6. Approve security alert via HTTP
        resolved = client.post("/api/camera/resolve-alert", json={"action": "approve"})
        assert resolved.status_code == 200
        res_json = resolved.json()
        assert res_json["status"] == "approved"
        assert "ĐƯỢC DUYỆT" in res_json["message"]
        assert res_json["camera_status"]["security_alert"] is None

        # 7. Overview & session-case show paired Check-in (COMPLETED) + Check-out (EXITED)
        ov_out = client.get("/api/management/overview", params={"include_revenue": True}).json()
        assert ov_out["stats"]["in_parking"] == 0
        assert ov_out["stats"]["total_in"] == 1
        assert ov_out["stats"]["total_out"] == 1
        assert ov_out["revenue"]["today"]["revenue"] == 2000
        assert len(ov_out["records"]) == 2
        out_row = ov_out["records"][0]
        assert out_row["direction_code"] == "OUT"
        assert out_row["parking_status_code"] == "EXITED"

        case_res = client.get(f"/api/management/session-case/{out_row['ID']}")
        assert case_res.status_code == 200
        case_json = case_res.json()
        assert case_json["plate_number"] == "59V1-79379"
        assert case_json["checkin_row"]["direction_code"] == "IN"
        assert case_json["checkin_row"]["parking_status_code"] == "COMPLETED"
        assert case_json["checkout_row"]["ID"] == out_row["ID"]
        assert case_json["session_closed_missing_exit"] is False

        # 8. Metrics & health reflect full lifecycle
        metrics_json = client.get("/api/metrics").json()
        assert metrics_json["frames_received"] == 5
        assert metrics_json["frames_processed"] == 5
        assert metrics_json["latches_started"] == 2
        assert metrics_json["latches_committed"] == 2
        assert metrics_json["security_alerts_triggered"] == 1
        assert metrics_json["security_alerts_approved"] == 1
        assert metrics_json["db_commits_succeeded"] == 2
        assert metrics_json["warm_mirror_count"] == 2
        assert client.get("/api/health").json()["status"] == "ok"

        # 9. Stop cameras cleanly
        assert client.post("/api/camera/stop").json() == {"status": "stopped"}
