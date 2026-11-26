---
name: datn2-contract-guard
description: >-
  Schema and API contract enforcement for DATN2 (ai-parking-gate). Activate
  before modifying MySQL migrations, repository queries, FastAPI routes,
  Pydantic schemas, API presenters, or schemas/* files.
---

# DATN2 Contract Guard

Prevent silent drift between `schemas/`, MySQL storage, FastAPI endpoints, and frontend API consumers.

## 1. Authoritative Contracts
- **MySQL DDL**: [mysql_schema.sql](file:///c:/Study/DATN2/schemas/mysql_schema.sql) <-> `src/backend/storage/migrations.py`
- **REST API**: [openapi.yaml](file:///c:/Study/DATN2/schemas/openapi.yaml) <-> `src/backend/api/{schemas,camera_routes,management_routes,static_routes}.py`
- **Payload Shapes**: [gate_payloads.schema.json](file:///c:/Study/DATN2/schemas/gate_payloads.schema.json) <-> `src/backend/api/presenters.py` & Gate status serializers

## 2. Mandatory Checks on Any Contract Change
1. **Update Schema First** if adding/changing a column, index, endpoint, or response field; never silently diverge in Python code.
2. **Preserve Raw-vs-Presenter Split (ADR-02)**: Keep Vietnamese UI keys (`Biển số`, `Luồng`, `Trạng thái bãi`, `Đối chiếu`) strictly in `src/backend/api/presenters.py`, never in `src/backend/storage/`.
3. **Run Contract Drift & Static Gates**:
   - `python -m pytest tests/unit/test_schema_contract_drift.py`
   - `ruff check src tests scripts` (when `ruff` is installed)
   - `.\scripts\verify.ps1` -> must exit `0` with `VERIFY PASSED`.
