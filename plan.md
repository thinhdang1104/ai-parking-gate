# plan.md — Lộ trình triển khai theo Giai đoạn (DATN2)

Mỗi giai đoạn có mục tiêu rõ ràng, phạm vi file cụ thể và cổng kiểm chứng (Verification Gate) bắt buộc vượt qua trước khi chuyển sang giai đoạn tiếp theo.

---

## Phase 0: Thiết lập Dự án & Sao chép Tài nguyên tĩnh
**Mục tiêu:** Khởi tạo cấu trúc thư mục sạch cho `C:\Study\DATN2`, sao chép các tài nguyên chỉ đọc từ `C:\Study\DATN` (trọng số model, cấu hình dataset, file cấu hình mẫu).
- **Sản phẩm đầu ra:**
  - Bộ tài liệu dự án (`AGENTS.md`, `spec.md`, `architecture.md`, `plan.md`, `tasks.md`, `progress.md`, `README.md`).
  - Copy `weights/plate_best.pt`, `weights/chars_best.pt`, `datasets/*/data.yaml`, `.env.example`, `requirements.txt`, `.gitignore`.
  - Tạo khung gói Python trong `src/backend/`, `src/training/`, `src/frontend/`, `tests/`.
- **Verification Gate:** Kiểm tra đủ 2 file `.pt` trong `weights/`, cài đặt/kiểm tra import thư viện trên `C:\Python314\python.exe`, xác nhận `C:\Study\DATN` hoàn toàn không bị chỉnh sửa (`git status` sạch).

---

## Phase 1: Cấu hình & Tầng Domain Thuần (Pure Logic)
**Mục tiêu:** Xây dựng toàn bộ cấu hình và logic lõi không phụ thuộc I/O (chuẩn hóa biển số VN, gom dòng ký tự, bỏ phiếu đồng thuận & Fast-Confirm, toán học FaceNet 512-D, đo độ nét Laplacian & cắt ảnh).
- **Sản phẩm đầu ra:**
  - `src/backend/config.py`
  - `src/backend/domain/models.py`, `plate_normalizer.py`, `plate_assembly.py`, `voting.py`, `face_math.py`, `image_utils.py`
  - `tests/unit/test_*.py`
- **Verification Gate:** Chạy `pytest tests/unit/` — 100% pass trong < 2 giây, bao phủ đầy đủ các trường hợp biên (ký tự nhầm OCR, biển 1/2 dòng, Fast-Confirm vs Standard Vote, xếp hạng độ nét mặt 3 bậc).

---

## Phase 2: Tầng Lưu trữ MySQL, WarmDatabaseMirror & Presenter
**Mục tiêu:** Tách sạch kết nối MySQL, migration, truy vấn SQL, `WarmDatabaseMirror`, demo seeder và tầng định dạng dữ liệu (`presenters.py`).
- **Sản phẩm đầu ra:**
  - `src/backend/storage/exceptions.py`, `mysql_client.py`, `migrations.py`, `repository.py`, `warm_mirror.py`, `demo_seeder.py`
  - `src/backend/api/presenters.py`
  - `tests/unit/test_presenters.py`, `tests/integration/test_mysql_repository.py`, `tests/integration/test_warm_mirror.py`
- **Verification Gate:** Chạy `pytest tests/unit/ tests/integration/test_mysql_repository.py tests/integration/test_warm_mirror.py` — xác nhận timeout kết nối, giảm số câu SQL trên tab Lịch sử/Phân trang, short-circuit `IN_PARKING`, và 0 SQL read khi `WarmDatabaseMirror` ấm.

---

## Phase 3: Tầng AI Adapters & Động cơ Cổng 2 Camera (Services)
**Mục tiêu:** Tách riêng adapter YOLOv8 & FaceNet; xây dựng `CameraSessionManager`, `LatchCoordinator`, `GateService` và `ManagementService` với Dependency Injection.
- **Sản phẩm đầu ra:**
  - `src/backend/ai/plate_detector.py`, `face_service.py`
  - `src/backend/services/camera_session.py`, `latch_coordinator.py`, `gate_service.py`, `management_service.py`
  - `tests/integration/test_gate_service.py`, `tests/integration/test_management_service.py`
- **Verification Gate:** Vượt qua toàn bộ regression tests tương đương và mở rộng từ `DATN`:
  - Batch YOLO 2 camera + Fast-Confirm + chốt mặt tức thì trong 2 frame.
  - Async DB commit & khóa `committing_plates`, không báo thành công trước khi commit.
  - `stop_cameras()` không làm rớt bản ghi đang nằm trong hàng đợi ghi DB.
  - `resolve_security_alert()` giữ nguyên alert khi DB lỗi và xóa + đặt cooldown khi DB thành công.
  - `get_cached_overview()` không mất `stats`/`revenue` khi `records_version` tăng giữa chừng.

---

## Phase 4: Tầng HTTP FastAPI & Kiểm thử API
**Mục tiêu:** Lắp ghép FastAPI app, routes, schemas, middleware (`GZipMiddleware`), `lifespan`, phục vụ static frontend và kiểm thử toàn bộ REST API qua `TestClient`.
- **Sản phẩm đầu ra:**
  - `src/backend/api/schemas.py`, `camera_routes.py`, `management_routes.py`, `static_routes.py`
  - `src/backend/main.py`
  - `tests/integration/test_api_routes.py`, `tests/e2e/test_full_parking_flow.py`
- **Verification Gate:** Chạy toàn bộ `pytest tests/` (100% pass); khởi động thử server local bằng `uvicorn` và kiểm tra `/`, `/api/camera/status`, `/api/management/overview`.

---

## Phase 5: Viết lại Frontend theo Mô-đun (ES Modules & Modular CSS)
**Mục tiêu:** Tách `index.html`, `styles.css` và `app.js` (3.383 dòng) thành cấu trúc module sạch sẽ (`css/*.css`, `js/*.js`) với giao diện Dark Mode và hành vi giống 100% bản gốc.
- **Sản phẩm đầu ra:**
  - `src/frontend/index.html`
  - `src/frontend/css/tokens.css`, `layout.css`, `components.css`, `camera.css`
  - `src/frontend/js/main.js`, `api.js`, `state.js`, `utils.js`, `camera.js`, `overlay.js`, `gate_ui.js`, `history.js`, `revenue.js`, `lost_case_modal.js`, `pdf_export.js`
- **Verification Gate:**
  - Kiểm tra cú pháp toàn bộ file JS (`node --check` nếu có Node) và kiểm tra không lỗi console khi mở trên trình duyệt.
  - Kiểm thử trực quan đủ 3 màn hình (2 Camera, Lịch sử & Quản lý, Doanh thu), Modal tra cứu mất xe 3 khối và 3 luồng xuất PDF chuẩn A4.

---

## Phase 6: Training Scripts, Kiểm chứng Local MySQL & Nghiệm thu Toàn diện
**Mục tiêu:** Hoàn thiện script huấn luyện, kiểm chứng vận hành thực tế với Local MySQL (MySQL Workbench), kiểm tra đối chiếu 100% tiêu chí `spec.md` và hoàn thiện `README.md`.
- **Sản phẩm đầu ra:**
  - `src/training/train_plates.py`, `src/training/train_chars.py`
  - Hướng dẫn cấu hình schema/connection trên MySQL Workbench trong `README.md`
- **Verification Gate:**
  - Chạy toàn bộ bộ test tự động (`pytest`).
  - Kiểm tra compile toàn bộ file Python (`python -m compileall src tests`).
  - Kết nối thực tế tới Local MySQL (kiểm tra bảng `plate_recognition_history` hiển thị đúng trên MySQL Workbench) và chạy smoke test server local.
  - Đối chiếu checklist từng mục FR-1 -> FR-9 trong `spec.md`.
  - Xác nhận `C:\Study\DATN` nguyên vẹn 100%.
