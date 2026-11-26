# progress.md — Trạng thái Hiện tại & Bước tiếp theo (DATN2)

**Repository:** https://github.com/thinhdang1104/ai-parking-gate  
**Cập nhật lần cuối:** 2026-11-26  
**Giai đoạn hiện tại:** Hoàn tất Nền tảng AI-Native (5 trụ cột) & Tài liệu nền (`Phase 0`)  
**Trạng thái tổng thể:** `3 / 27` tasks ứng dụng + **5/5 trụ cột AI-Native** hoàn tất và vượt qua `.\scripts\verify.ps1` (`VERIFY PASSED`, 8/8 unit tests observability) — đang dừng chờ người dùng review trước khi bắt đầu T0.3–T0.4 & Phase 1.

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
- Xác nhận dự án gốc `C:\Study\DATN` **không bị chỉnh sửa bất kỳ file nào**.

---

## 2. Việc đang làm
- Dừng chờ người dùng review toàn bộ **5 trụ cột nền tảng AI-Native** trước khi bắt đầu **Phase 0 (T0.3–T0.4)** và **Phase 1 (Domain Core)**.

---

## 3. Bước tiếp theo ngay sau khi được duyệt
1. **[T0.3]** Copy các tài nguyên chỉ đọc từ `C:\Study\DATN` sang `C:\Study\DATN2` (`weights/*.pt`, `datasets/*/data.yaml`, `.env.example`, `requirements.txt`, `.gitignore`).
2. **[T0.4]** Tạo khung package `src/backend/`, `src/frontend/`, `src/training/`, `tests/`.
3. **[Phase 1 — T1.1 -> T1.6]** Xây dựng `config.py` và toàn bộ tầng `src/backend/domain/` kèm bộ unit test vượt qua 100%.

---

## 4. Ghi chú & Điểm cần lưu ý
- **Phạm vi vận hành hiện tại:** Chỉ chạy **Local** kết nối **Local MySQL (MySQL Workbench)**; chưa tích hợp triển khai Hugging Face Spaces / Gradio.
- Không copy file `.env` chứa mật khẩu thật tự động nếu chưa có yêu cầu; chỉ copy `.env.example` và điền thông tin kết nối Local MySQL (`127.0.0.1:3306`).
- Giữ nguyên 100% hợp đồng API và schema MySQL (`plate_recognition_history`) để đảm bảo tương thích dữ liệu.
