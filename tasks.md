# tasks.md — Danh sách Công việc, Phụ thuộc & Trạng thái (DATN2)

**Ký hiệu trạng thái:** `[ ]` Chưa làm · `[/]` Đang làm · `[x]` Hoàn tất · `[!]` Bị chặn

---

## Phase 0: Thiết lập Dự án & Sao chép Tài nguyên
- [x] **T0.1** Rà soát toàn bộ codebase gốc tại `C:\Study\DATN` (backend, database, face_service, frontend, tests, deploy) — *Deps: none*
- [x] **T0.2** Viết bộ tài liệu nền tảng (`AGENTS.md`, `spec.md`, `architecture.md`, `plan.md`, `tasks.md`, `progress.md`, `README.md`) và tạo thư mục `src/`, `tests/` tại `C:\Study\DATN2` — *Deps: T0.1*
- [x] **T0.2b** Thiết lập Verification Harness (`pyproject.toml`, `scripts/check_guardrails.py`, `scripts/verify.ps1`) — *Deps: T0.2* · *Verify: `.\scripts\verify.ps1` trả `VERIFY PASSED`*
- [x] **T0.3** Sao chép tài nguyên chỉ đọc từ `C:\Study\DATN` sang `C:\Study\DATN2` (`weights/*.pt`, `datasets/*/data.yaml`, `.env.example`, `requirements.txt`, `.gitignore`) — *Deps: T0.2b* · *Verify: tồn tại đủ file weights & config*
- [x] **T0.4** Khởi tạo cây package `src/backend/`, `src/frontend/`, `src/training/`, `tests/` — *Deps: T0.3*

## Phase 1: Cấu hình & Tầng Domain Thuần
- [x] **T1.1** Viết `src/backend/config.py` (gom toàn bộ hằng số ngưỡng AI, Latch, Cooldown, Fee, Cache, Env) — *Deps: T0.4*
- [x] **T1.2** Viết `src/backend/domain/models.py` (dataclasses cho `FaceDetection`, `PlateBox`, `VoteResult`, `LatchState`, `SecurityAlert`, `ParkingRecord`) — *Deps: T1.1*
- [x] **T1.3** Viết `src/backend/domain/plate_normalizer.py` & `plate_assembly.py` (IoU dedup, 1/2 dòng, chuẩn hóa biển VN, `clean_plate_key`) — *Deps: T1.2*
- [x] **T1.4** Viết `src/backend/domain/voting.py` (Majority Voting & Fast-Confirm) — *Deps: T1.2*
- [x] **T1.5** Viết `src/backend/domain/face_math.py` & `image_utils.py` (Cosine similarity, bytes serialization 512-D, Laplacian sharpness vùng lõi 70%, xếp hạng độ nét, crop JPEG, decode base64, disk snapshot) — *Deps: T1.2*
- [x] **T1.6** Viết unit tests cho toàn bộ tầng Domain (`tests/unit/test_*.py`) — *Deps: T1.3, T1.4, T1.5* · *Verify: `pytest tests/unit/` pass 100%*

## Phase 2: Tầng Lưu trữ MySQL, WarmDatabaseMirror & Presenter
- [ ] **T2.1** Viết `src/backend/storage/exceptions.py`, `mysql_client.py` (direct connect + timeouts + `now_vn`) và `migrations.py` — *Deps: T1.1*
- [ ] **T2.2** Viết `src/backend/storage/repository.py` (insert, find_active_session, fetch_overview, fetch_revenue_report, fetch_parking_session_case — trả raw dicts) — *Deps: T2.1, T1.3, T1.5*
- [ ] **T2.3** Viết `src/backend/storage/warm_mirror.py` (RAM mirror đồng bộ 1-1, giới hạn 600 ảnh, fallback MySQL) — *Deps: T2.2*
- [ ] **T2.4** Viết `src/backend/storage/demo_seeder.py` (nạp 38 bản ghi mẫu khi `SEED_DEMO_DATA=1`) — *Deps: T2.2*
- [ ] **T2.5** Viết `src/backend/api/presenters.py` (định dạng nhãn tiếng Việt chuẩn API `format_record_row`, `format_vnd`, `format_match_label`, ...) — *Deps: T1.2*
- [ ] **T2.6** Viết tests cho Presenter, Repository & WarmDatabaseMirror (`tests/unit/test_presenters.py`, `tests/integration/test_mysql_repository.py`, `tests/integration/test_warm_mirror.py`) — *Deps: T2.3, T2.4, T2.5* · *Verify: `pytest` pass 100%*

## Phase 3: Tầng AI Adapters & Services Điều phối
- [ ] **T3.1** Viết `src/backend/ai/plate_detector.py` (YOLOv8 plate + char detector, hỗ trợ batch 2 ảnh) — *Deps: T1.3, T1.5*
- [ ] **T3.2** Viết `src/backend/ai/face_service.py` (MTCNN + InceptionResnetV1 vggface2, fallback crop 160x160, tự chọn CUDA/CPU hoặc ép CPU khi `FORCE_CPU=1`) — *Deps: T1.2, T1.5*
- [ ] **T3.3** Viết `src/backend/services/camera_session.py` (`CameraUnitState` & `CameraSessionManager` bật/tắt độc lập 2 cam) — *Deps: T1.2, T1.4*
- [ ] **T3.4** Viết `src/backend/services/latch_coordinator.py` (Two-Phase Latch 4s, pre-latch lookback 1.8s, swapped-plate cancel, sharpness tier check) — *Deps: T1.5, T3.3*
- [ ] **T3.5** Viết `src/backend/services/management_service.py` (overview cache, session-case cache, version bump, DB reconnect background loop) — *Deps: T2.3, T2.5*
- [ ] **T3.6** Viết `src/backend/services/gate_service.py` (ingest dual frames, smart 2-cam scheduling, FaceNet matching, Security Alert, async DB commit executor an toàn) — *Deps: T3.1, T3.2, T3.4, T3.5*
- [ ] **T3.7** Viết regression & integration tests (`tests/integration/test_gate_service.py`, `tests/integration/test_management_service.py`) — *Deps: T3.6* · *Verify: pass toàn bộ regression scenarios*

## Phase 4: Tầng HTTP FastAPI & API Tests
- [ ] **T4.1** Viết `src/backend/api/schemas.py`, `camera_routes.py`, `management_routes.py`, `static_routes.py` — *Deps: T3.5, T3.6*
- [ ] **T4.2** Viết `src/backend/main.py` (DI wiring, `lifespan`, `GZipMiddleware`, `uvicorn` runner) — *Deps: T4.1*
- [ ] **T4.3** Viết API tests & E2E flow tests (`tests/integration/test_api_routes.py`, `tests/e2e/test_full_parking_flow.py`) — *Deps: T4.2* · *Verify: `pytest tests/` pass 100%*

## Phase 5: Viết lại Frontend theo Mô-đun (ES Modules & CSS)
- [ ] **T5.1** Tạo `src/frontend/index.html` và tách CSS thành 4 file (`tokens.css`, `layout.css`, `components.css`, `camera.css`) — *Deps: T4.2*
- [ ] **T5.2** Viết nền tảng JS (`js/api.js`, `js/state.js`, `js/utils.js`) — *Deps: T5.1*
- [ ] **T5.3** Viết cụm Camera & Gate UI (`js/camera.js`, `js/overlay.js`, `js/gate_ui.js`) — *Deps: T5.2*
- [ ] **T5.4** Viết cụm Quản lý, Doanh thu, Mất xe & Xuất PDF (`js/history.js`, `js/revenue.js`, `js/lost_case_modal.js`, `js/pdf_export.js`, `js/main.js`) — *Deps: T5.2*
- [ ] **T5.5** Kiểm tra cú pháp JS & kiểm thử trực quan toàn bộ 3 màn hình + Modal + PDF trên trình duyệt — *Deps: T5.3, T5.4*

## Phase 6: Training Scripts, Kiểm chứng Local MySQL & Nghiệm thu
- [ ] **T6.1** Sao chép/cập nhật `src/training/train_plates.py`, `src/training/train_chars.py` — *Deps: T0.4*
- [ ] **T6.2** Kiểm thử kết nối thực tế Local MySQL (MySQL Workbench), xác nhận auto-migration bảng `plate_recognition_history` và chạy smoke test server local — *Deps: T4.2, T5.4*
- [ ] **T6.3** Chạy kiểm chứng toàn diện (`python -m compileall src tests`, `pytest tests/`) — *Deps: T6.1, T6.2*
- [ ] **T6.4** Rà soát 100% đối chiếu với `spec.md`, cập nhật `progress.md` và xác nhận `C:\Study\DATN` không bị thay đổi — *Deps: T6.3*
