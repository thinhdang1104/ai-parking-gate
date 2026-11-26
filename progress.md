# progress.md — Trạng thái Hiện tại & Bước tiếp theo (DATN2)

**Repository:** https://github.com/thinhdang1104/ai-parking-gate  
**Cập nhật lần cuối:** 2026-11-26  
**Giai đoạn hiện tại:** Hoàn tất Phase 2 (`T2.1`–`T2.6` — MySQL Storage, WarmDatabaseMirror, Demo Seeder & API Presenters)  
**Trạng thái tổng thể:** `17 / 27` tasks hoàn tất (+ 5/5 trụ cột AI-Native) — `.\scripts\verify.ps1` đạt **`VERIFY PASSED`** (`38 passed in 0.79s`). Sẵn sàng bước vào **Phase 3 (T3.1–T3.7: AI Adapters & Services Điều phối)**.

---

## 1. Đã hoàn thành
- **[T0.1]** Rà soát toàn diện mã nguồn gốc tại `C:\Study\DATN`:
  - Backend: `main.py` (2.032 dòng), `database.py` (1.555 dòng), `face_service.py` (160 dòng), `app.py` (136 dòng), `deploy_hf.py` (56 dòng).
  - Frontend: `frontend/index.html` (585 dòng), `frontend/styles.css`, `frontend/app.js` (3.383 dòng).
  - Kiểm thử & Huấn luyện: `tests/test_core_logic.py` (726 dòng), `training/train_plates.py`, `training/train_chars.py`.
  - Xác định rõ các điểm chồng chéo (3 God files, trùng lặp logic SQL/RAM Mirror & plate key, trộn presenter tiếng Việt vào tầng DB, khó tiêm dependency khi test).
- **[T0.2 & T0.2b]** Khởi tạo bộ tài liệu định hướng & Verification Harness (`AGENTS.md`, `spec.md`, `architecture.md`, `plan.md`, `tasks.md`, `progress.md`, `README.md`, `pyproject.toml`, `scripts/check_guardrails.py`, `scripts/verify.ps1`).
- **[AI-Native Foundation — 5 Trụ cột]**:
  1. **Agent Harness**: `.agents/skills/datn2-workflow/SKILL.md`, `.agents/memory/decisions.md`, `.agents/memory/gotchas.md`, `.agents/README.md`.
  2. **Specs & Schemas**: `schemas/mysql_schema.sql` (19 cột, 6 index), `schemas/openapi.yaml` (OpenAPI 3.1.0, 14 paths, 27 schemas), `schemas/gate_payloads.schema.json` (Draft 2020-12).
  3. **MCP Servers**: `.agents/mcp_config.json` (MySQL read-only MCP + GitHub MCP dùng biến môi trường, không hardcode secret).
  4. **Test & CI/CD**: `.github/workflows/ci.yml`, `scripts/validate_schemas.py`, nâng cấp `scripts/verify.ps1` thành 5 cổng tự động nhận diện Python có `pytest`.
  5. **Docker & Observability**: `Dockerfile`, `docker-compose.yml`, `docker-compose.gpu.yml`, `.dockerignore`, `src/backend/observability/{logging_config.py,metrics.py}` + `tests/unit/test_observability.py` (8/8 pass).
- **[T0.3 & T0.4]** Sao chép tài nguyên chỉ đọc từ `C:\Study\DATN` (`weights/plate_best.pt`, `weights/chars_best.pt`, `datasets/*/data.yaml`, `requirements.txt`), tạo `.env.example` & `.gitignore`, khởi tạo cây package `src/backend/`, `src/frontend/`, `src/training/`, `tests/`.
- **[Phase 1 — T1.1 -> T1.6]** Hoàn tất tầng cấu hình & Domain thuần (`config.py`, `domain/{models,plate_normalizer,plate_assembly,voting,face_math,image_utils}.py`) cùng 16 unit tests mới trong `tests/unit/` (tổng `24 / 24` tests pass, guardrails `<= 400` dòng/file & domain purity đạt 100%).
- **[Phase 2 — T2.1 -> T2.6]** Hoàn tất tầng Storage & Presentation:
  - `src/backend/storage/{exceptions,mysql_client,migrations,query_helpers,sql_queries,repository,mirror_helpers,warm_mirror,demo_seeder}.py` (tất cả `<= 334` dòng, trả về raw domain dicts thuần theo ADR-01 & ADR-02).
  - `src/backend/api/presenters.py` (`156` dòng, định dạng nhãn tiếng Việt chuẩn `schemas/gate_payloads.schema.json`).
  - Bộ test offline (`test_presenters.py`, `test_mysql_repository.py`, `test_warm_mirror.py`) nâng tổng số test pass lên `38 / 38`.
- Xác nhận dự án gốc `C:\Study\DATN` **không bị chỉnh sửa bất kỳ file nào**.

---

## 2. Việc đang làm
- Sẵn sàng triển khai **Phase 3 (`T3.1`–`T3.7`)**: AI Adapters (`YOLOv8` batch & `FaceNet 512-D`) và Services điều phối (`CameraSessionManager`, `LatchCoordinator`, `ManagementService`, `GateService`).

---

## 3. Bước tiếp theo ngay sau khi được duyệt
1. **[Phase 3 — T3.1 -> T3.7]** Viết `src/backend/ai/{plate_detector,face_service}.py`, `src/backend/services/{camera_session,latch_coordinator,management_service,gate_service}.py` và regression/integration tests.
2. **[Phase 4 — T4.1 -> T4.3]** Viết tầng HTTP FastAPI (`schemas.py`, `camera_routes.py`, `management_routes.py`, `static_routes.py`, `main.py`) & API/E2E tests.

---

## 4. Ghi chú & Điểm cần lưu ý
- **Phạm vi vận hành hiện tại:** Chỉ chạy **Local** kết nối **Local MySQL (MySQL Workbench)**; chưa tích hợp triển khai Hugging Face Spaces / Gradio.
- Không copy file `.env` chứa mật khẩu thật tự động nếu chưa có yêu cầu; chỉ copy `.env.example` và điền thông tin kết nối Local MySQL (`127.0.0.1:3306`).
- Giữ nguyên 100% hợp đồng API và schema MySQL (`plate_recognition_history`) để đảm bảo tương thích dữ liệu.
