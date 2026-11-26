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
- **Single Responsibility & Readability**: Organize every `.py` and `.js` module around one clear responsibility with clean, idiomatic multi-line formatting (no artificial per-file line-count cap).
- **Pure Domain Layer**: `src/backend/domain/` must never import `fastapi`, `pydantic`, `mysql`, `ultralytics`, `torch`, `facenet_pytorch`, `uvicorn`, or `starlette`.
- **Schema-First Contracts**: Any REST endpoint or MySQL table change must match `schemas/openapi.yaml`, `schemas/gate_payloads.schema.json`, and `schemas/mysql_schema.sql`.

## 2. Context Loading Strategy (2-Tier Progressive Disclosure)
- **Tier 1 (Always Read First)**: `AGENTS.md`, `progress.md`, `tasks.md`, `.agents/memory/decisions.md`, `.agents/memory/gotchas.md`.
- **Tier 2 (Read On-Demand by Scope)**:
  - **DB / SQL / Storage**: `schemas/mysql_schema.sql`, `datn2-contract-guard`, relevant parts of `C:\Study\DATN\database.py` (read-only).
  - **API / Presenters**: `schemas/openapi.yaml`, `schemas/gate_payloads.schema.json`, `datn2-contract-guard`.
  - **AI / Latch / Gate**: `spec.md` (FR-1..FR-5 & Section 2.1), `architecture.md` (Concurrency Model), relevant parts of `C:\Study\DATN\main.py` & `face_service.py` (read-only).
  - **Frontend**: `spec.md` (FR-1, FR-6..FR-8), `C:\Study\DATN\frontend\*` (read-only), `frontend`, `visual-qa`.
  - **CV Smoke Eval**: `datn2-cv-eval`, `eval-integrity`.

## 3. Spec-Driven Execution & Per-Phase Gate Loop
1. **Orient (Tier 1)**: Read `progress.md`, `tasks.md`, `.agents/memory/decisions.md`, and `.agents/memory/gotchas.md`.
2. **Contract Check (Tier 2)**: Read only the relevant sections of `spec.md`, `architecture.md`, and `schemas/` for the active task scope.
3. **Implement + Test**: Write clean, DI-friendly code in `src/` alongside targeted tests in `tests/` (`test-driven-development`).
4. **Per-Phase Review-Fix Loop (Mandatory before Commit/Push)**:
   - Read and review **100% of every new/modified source and test file** in the phase.
   - Run `.\scripts\verify.ps1` and require `VERIFY PASSED` across all 6 gates (`compileall`, `check_guardrails.py`, `validate_schemas.py`, `ruff`, `node --check`, `pytest`).
   - Perform hands-on QA (API / browser / DB check) for user-facing changes.
   - **If ANY issue is found** (logic, edge case, encapsulation, lint, contract drift, or missing test): fix it and **repeat the full review + `verify.ps1` loop** until review is completely clean and `VERIFY PASSED`.
   - **ONLY when review is clean and `VERIFY PASSED`**: update `tasks.md` (`[x]`) and `progress.md`, then commit and push cleanly to `origin main` before starting the next phase.
5. **Memory Update**: Record any new architectural decision in `.agents/memory/decisions.md` and any non-obvious bug/pitfall in `.agents/memory/gotchas.md`.
