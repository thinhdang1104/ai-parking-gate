# Architectural Decisions Log (DATN2)

Persistent cross-session memory of locked architectural decisions. Do not reverse these without explicit user approval.

| ID | Decision | Rationale |
| :--- | :--- | :--- |
| **ADR-01** | Direct MySQL connections with explicit timeouts (`connection_timeout=8`, `read_timeout=10`, `write_timeout=10`, `use_pure=True`) instead of `MySQLConnectionPool` | Prevents stale socket hangs after MySQL `wait_timeout` during overnight runs; `WarmDatabaseMirror` absorbs read load. |
| **ADR-02** | Separate raw-dict Storage (`repository.py`, `warm_mirror.py`) from Vietnamese API Presenters (`api/presenters.py`) | Eliminates duplicated SQL/RAM formatting logic while preserving 100% legacy frontend JSON contract. |
| **ADR-03** | Split legacy `SystemState` into `CameraSessionManager`, `LatchCoordinator`, `GateService`, and `ManagementService` | Enables constructor Dependency Injection, isolated unit testing without `mock.patch` sprawl, and minimal lock scopes. |
| **ADR-04** | Vanilla ES Modules (`src/frontend/js/*.js`) + 4 CSS files with zero build step | Fast local startup via FastAPI `StaticFiles` without Node/Vite toolchain overhead. |
| **ADR-05** | Local-first FastAPI entrypoint (`src/backend/main.py`) with optional Docker stack | Focuses on Local MySQL (MySQL Workbench) and isolated Docker runs; cloud/HF Spaces adapters remain out of scope. |
| **ADR-06** | 5-Pillar AI-Native Foundation (`.agents/`, `schemas/`, MCP config, CI/CD + 5-gate `verify.ps1`, Docker + `observability/`) | Gives AI agents machine-readable contracts, persistent memory, automated guardrails, isolated runtime, and structured telemetry. |
