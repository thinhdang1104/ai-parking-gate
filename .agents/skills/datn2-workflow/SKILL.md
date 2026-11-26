---
name: datn2-workflow
description: >-
  Spec-driven development, verification, and architecture discipline for DATN2
  (AI-Native School Parking Management System). Activate before implementing,
  reviewing, or modifying any module, schema, test, or config in C:\Study\DATN2.
---

# DATN2 AI-Native Development Workflow

Follow this strict loop for every task in `C:\Study\DATN2`:

## 1. Hard Boundaries
- **NEVER modify, create, or delete any file in `C:\Study\DATN`** (strictly read-only reference).
- **Single Responsibility & File Size**: Every `.py` and `.js` file under `src/` must stay `<= 400` lines (target 100–350 lines).
- **Pure Domain Layer**: `src/backend/domain/` must never import `fastapi`, `pydantic`, `mysql`, `ultralytics`, `torch`, `facenet_pytorch`, `uvicorn`, or `starlette`.
- **Schema-First Contracts**: Any REST endpoint or MySQL table change must match `schemas/openapi.yaml`, `schemas/gate_payloads.schema.json`, and `schemas/mysql_schema.sql`.

## 2. Spec-Driven Execution Loop
1. **Orient**: Read `progress.md`, `tasks.md`, `.agents/memory/decisions.md`, and `.agents/memory/gotchas.md`.
2. **Contract Check**: Cross-check requirements in `spec.md`, `architecture.md`, and `schemas/`.
3. **Implement + Test**: Write clean, DI-friendly code in `src/` alongside targeted tests in `tests/`.
4. **4-Phase Verification**:
   - Read every changed file and verify against the spec.
   - Run `.\scripts\verify.ps1` and require `VERIFY PASSED` (all 5 gates: `compileall`, `check_guardrails.py`, `validate_schemas.py`, `node --check`, `pytest`).
   - Perform hands-on QA (API / browser / DB check) for user-facing changes.
   - Only then mark `[x]` in `tasks.md` and log progress in `progress.md`.
5. **Memory Update**: Record any new architectural decision in `.agents/memory/decisions.md` and any non-obvious bug/pitfall in `.agents/memory/gotchas.md`.
