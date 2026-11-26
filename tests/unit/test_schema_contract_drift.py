"""Contract-drift tests linking schemas/* against runtime SQL DDL and API presenters."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from src.backend.api.presenters import format_record_row
from src.backend.storage.migrations import _INDEX_MIGRATIONS

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = ROOT / "schemas"
MIGRATIONS_PATH = ROOT / "src" / "backend" / "storage" / "migrations.py"

DOCUMENTED_OPENAPI_PATHS = (
    "/",
    "/ui",
    "/api/camera/status",
    "/api/camera/{cam_id}/start",
    "/api/camera/{cam_id}/stop",
    "/api/camera/stop",
    "/api/camera/browser-frame",
    "/api/camera/cancel-latch",
    "/api/camera/resolve-alert",
    "/api/management/overview",
    "/api/management/session-case/{record_id}",
    "/api/management/reconnect",
    "/api/health",
    "/api/metrics",
)


def _extract_table_columns_and_indexes(sql_text: str) -> tuple[list[str], list[str]]:
    table_match = re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+plate_recognition_history\s*\((.*?)\)\s*ENGINE=",
        sql_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert table_match is not None, "Could not locate plate_recognition_history CREATE TABLE block"
    body = table_match.group(1)

    columns_section = re.split(r"\bINDEX\s+", body, maxsplit=1, flags=re.IGNORECASE)[0]
    columns: list[str] = []
    for raw_line in columns_section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        col_match = re.match(r"^`?([A-Za-z_][A-Za-z0-9_]*)`?\s+", line)
        if col_match:
            columns.append(col_match.group(1))

    indexes = re.findall(r"\bINDEX\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", body, flags=re.IGNORECASE)
    return columns, indexes


def _extract_openapi_paths(yaml_text: str) -> set[str]:
    if yaml is not None:
        doc = yaml.safe_load(yaml_text)
        assert isinstance(doc, dict), "openapi.yaml root must be a mapping"
        paths = doc.get("paths")
        assert isinstance(paths, dict), "openapi.yaml must define a 'paths' mapping"
        return {str(key) for key in paths}

    paths_block = re.split(r"(?m)^paths\s*:\s*$", yaml_text, maxsplit=1)
    assert len(paths_block) == 2, "openapi.yaml missing top-level 'paths:' section"
    after_paths = re.split(r"(?m)^[A-Za-z_][A-Za-z0-9_-]*\s*:", paths_block[1], maxsplit=1)[0]
    return {
        m.group(2)
        for m in re.finditer(r"(?m)^  (['\"]?)(/[^'\":\s]*)\1\s*:", after_paths)
    }


def test_mysql_schema_sql_matches_migrations() -> None:
    sql_text = (SCHEMAS_DIR / "mysql_schema.sql").read_text(encoding="utf-8")
    migrations_text = MIGRATIONS_PATH.read_text(encoding="utf-8")

    sql_columns, sql_indexes = _extract_table_columns_and_indexes(sql_text)
    ddl_columns, ddl_indexes = _extract_table_columns_and_indexes(migrations_text)
    migration_index_names = [name for name, _ddl in _INDEX_MIGRATIONS]

    assert sql_columns, "Expected non-empty column list in schemas/mysql_schema.sql"
    assert set(sql_columns) == set(ddl_columns)
    assert sql_columns == ddl_columns

    assert len(sql_indexes) == 6
    assert len(migration_index_names) == 6
    assert set(sql_indexes) == set(ddl_indexes) == set(migration_index_names)


def test_gate_payloads_schema_matches_presenter_row() -> None:
    schema = json.loads((SCHEMAS_DIR / "gate_payloads.schema.json").read_text(encoding="utf-8"))
    row_schema = schema["$defs"]["ParkingRecordRow"]
    required_keys = set(row_schema["required"])
    property_keys = set(row_schema["properties"].keys())

    assert required_keys == property_keys

    sample_in = {
        "id": 1,
        "plate_number": "59V1-79379",
        "direction": "IN",
        "parking_status": "IN_PARKING",
        "entry_record_id": None,
        "recognized_at": datetime(2026, 11, 26, 8, 0, 0),
        "face_detected": True,
        "face_confidence": 0.96,
        "face_embedding": b"vec",
        "face_match_score": None,
        "plate_image": "data:image/jpeg;base64,PLATE",
        "face_image": "data:image/jpeg;base64,FACE",
    }
    sample_out = {
        "id": 2,
        "plate_number": "59V1-79379",
        "direction": "OUT",
        "parking_status": "EXITED",
        "entry_record_id": 1,
        "recognized_at": datetime(2026, 11, 26, 9, 30, 0),
        "face_detected": True,
        "face_confidence": 0.91,
        "face_embedding": b"vec2",
        "face_match_score": 0.89,
        "plate_image": None,
        "face_image": None,
    }

    for rec in (sample_in, sample_out):
        row = format_record_row(rec["id"], rec)
        row_keys = set(row.keys())
        missing = required_keys - row_keys
        extra = row_keys - property_keys
        assert not missing, f"format_record_row missing required keys: {sorted(missing)}"
        assert not extra, f"format_record_row emitted unexpected keys: {sorted(extra)}"


def test_openapi_paths_cover_documented_endpoints() -> None:
    yaml_text = (SCHEMAS_DIR / "openapi.yaml").read_text(encoding="utf-8")
    documented = set(DOCUMENTED_OPENAPI_PATHS)
    assert len(documented) == 14

    actual_paths = _extract_openapi_paths(yaml_text)
    missing = documented - actual_paths
    assert not missing, f"schemas/openapi.yaml missing documented paths: {sorted(missing)}"


def _collect_route_methods(routes: list[object]) -> dict[str, set[str]]:
    from fastapi.routing import APIRoute

    route_methods: dict[str, set[str]] = {}
    for route in routes:
        if isinstance(route, APIRoute):
            route_methods.setdefault(route.path, set()).update(route.methods or set())
        else:
            orig_router = getattr(route, "original_router", None)
            if orig_router is not None:
                for path, methods in _collect_route_methods(list(orig_router.routes)).items():
                    route_methods.setdefault(path, set()).update(methods)
    return route_methods


def test_fastapi_app_registers_all_openapi_routes() -> None:
    from src.backend.main import create_app

    app = create_app(enable_lifespan_startup=False)
    try:
        route_methods = _collect_route_methods(list(app.routes))

        expected_paths = set(DOCUMENTED_OPENAPI_PATHS)
        actual_paths = set(route_methods.keys())
        missing = expected_paths - actual_paths
        assert not missing, f"FastAPI app missing OpenAPI paths: {sorted(missing)}"

        assert {"GET", "HEAD"}.issubset(route_methods["/"])
        assert {"GET", "HEAD"}.issubset(route_methods["/ui"])
        assert "GET" in route_methods["/api/camera/status"]
        assert "POST" in route_methods["/api/camera/{cam_id}/start"]
        assert "POST" in route_methods["/api/camera/{cam_id}/stop"]
        assert "POST" in route_methods["/api/camera/stop"]
        assert "POST" in route_methods["/api/camera/browser-frame"]
        assert "POST" in route_methods["/api/camera/cancel-latch"]
        assert "POST" in route_methods["/api/camera/resolve-alert"]
        assert "GET" in route_methods["/api/management/overview"]
        assert "GET" in route_methods["/api/management/session-case/{record_id}"]
        assert "POST" in route_methods["/api/management/reconnect"]
        assert "GET" in route_methods["/api/health"]
        assert "GET" in route_methods["/api/metrics"]
    finally:
        app.state.container.gate_service.shutdown(timeout=1.0)
