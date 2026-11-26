# ai-parking-gate (DATN2) — AI-Native School Parking Management System

> **Repository:** https://github.com/thinhdang1104/ai-parking-gate  
> Phiên bản tái cấu trúc sạch (Clean Architecture) theo chuẩn **AI-Native** từ dự án đồ án tốt nghiệp **Hệ thống quản lý bãi giữ xe cho trường học với AI nhận diện khuôn mặt và biển số xe**.  
> Bảo toàn 100% tính năng, hợp đồng API và schema MySQL của bản gốc, tách bạch rõ các tầng **Domain / AI / Storage / Services / API / Modular Frontend** kèm bộ kiểm thử tự động và hạ tầng AI-Native đầy đủ.

---

## 1. Nền tảng AI-Native (5 Trụ cột)

| Trụ cột | Thành phần chính | Vai trò |
| :--- | :--- | :--- |
| **1. Agent Harness** | [`.agents/skills/datn2-workflow/SKILL.md`](.agents/skills/datn2-workflow/SKILL.md), [`.agents/memory/`](.agents/memory/decisions.md) | Quy trình làm việc Spec-Driven, bộ nhớ xuyên phiên (`decisions.md`, `gotchas.md`) và kỷ luật 4-Phase Verification |
| **2. Specs & Schemas** | [`schemas/mysql_schema.sql`](schemas/mysql_schema.sql), [`schemas/openapi.yaml`](schemas/openapi.yaml), [`schemas/gate_payloads.schema.json`](schemas/gate_payloads.schema.json) | Hợp đồng DB & REST API chuẩn máy đọc được để AI và test không phải đoán mò |
| **3. MCP Servers** | [`.agents/mcp_config.json`](.agents/mcp_config.json) | Cấu hình MySQL read-only MCP & GitHub MCP qua biến môi trường (không hardcode secret) |
| **4. Test & CI/CD** | [`scripts/verify.ps1`](scripts/verify.ps1), [`scripts/check_guardrails.py`](scripts/check_guardrails.py), [`scripts/validate_schemas.py`](scripts/validate_schemas.py), [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Hàng rào kiểm định 5 cổng tự động tại local & GitHub Actions |
| **5. Docker & Observability** | [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml), [`docker-compose.gpu.yml`](docker-compose.gpu.yml), [`src/backend/observability/`](src/backend/observability/logging_config.py) | Môi trường chạy cô lập (FastAPI + MySQL 8.0), JSON structured logs (`request_id`) và metrics (`/api/health`, `/api/metrics`) |

---

## 2. Bản đồ tài liệu dự án

| Tài liệu | Nội dung |
| :--- | :--- |
| [`AGENTS.md`](AGENTS.md) | Quy tắc làm việc cho AI & lập trình viên, mức độ tự chủ, tiêu chuẩn code |
| [`spec.md`](spec.md) | Đặc tả đầy đủ yêu cầu chức năng (FR-1 → FR-9), REST API và schema MySQL |
| [`architecture.md`](architecture.md) | Phân tích vấn đề bản cũ, kiến trúc 4 tầng, cấu trúc `src/` & `tests/`, ADRs |
| [`plan.md`](plan.md) | Lộ trình triển khai 6 giai đoạn (Phase 0 → Phase 6) kèm cổng kiểm chứng |
| [`tasks.md`](tasks.md) | Checklist chi tiết từng task, phụ thuộc và trạng thái thực hiện |
| [`progress.md`](progress.md) | Trạng thái hiện tại, hạng mục đã xong và bước tiếp theo |

---

## 3. Cấu trúc thư mục

```text
ai-parking-gate/ (C:\Study\DATN2)
├── .agents/            # Agent Harness (skills, memory) & MCP config
├── .github/workflows/  # CI/CD pipelines (ci.yml)
├── schemas/            # MySQL DDL, OpenAPI 3.1.0, JSON Schema payloads
├── scripts/            # verify.ps1, check_guardrails.py, validate_schemas.py
├── src/                # Mã nguồn (backend/, frontend/, training/)
├── tests/              # Automated tests (unit/, integration/, e2e/)
├── Dockerfile          # Container cho backend FastAPI
├── docker-compose.yml  # Stack cô lập FastAPI + MySQL 8.0 (+ docker-compose.gpu.yml)
├── AGENTS.md           # Luật AI, workflow, mức độ tự chủ
├── spec.md             # Yêu cầu và hành vi phần mềm
├── plan.md             # Roadmap và các giai đoạn
├── tasks.md            # Checklist task, dependencies, status
├── architecture.md     # Kiến trúc và technical decisions
├── progress.md         # Trạng thái hiện tại, việc tiếp theo
└── README.md           # Hướng dẫn project
```

---

## 4. Tính năng cốt lõi

- **Giám sát 2 Camera AI WebRTC đối xứng (`Cam 1` & `Cam 2`)**: Chọn thiết bị theo tên (`deviceId: { exact }`), chống trùng thiết bị, bật/tắt độc lập, vẽ khung nhận diện trực tiếp trên `<canvas>`.
- **Nhận diện Biển số xe Việt Nam 2 giai đoạn (YOLOv8)**: Phát hiện biển số (`plate_best.pt`), OCR 31 lớp ký tự (`chars_best.pt`), gom 1/2 dòng, tự sửa ký tự dễ nhầm, bỏ phiếu đồng thuận & Fast-Confirm.
- **Xác thực Khuôn mặt Sinh trắc học (FaceNet 512-D)**: `MTCNN` + `InceptionResnetV1(vggface2)`, lọc độ sắc nét Laplacian vùng lõi 70%, đối chiếu Cosine Similarity (`>= 0.65`).
- **Two-Phase Latch đối xứng (`4.0s`) & Cảnh báo lệch mặt**: Tự xác định chiều `IN`/`OUT`, chỉ báo thành công sau khi MySQL commit, cảnh báo tức thì kèm nút **Cho phép ra / Từ chối** khi lệch khuôn mặt.
- **Quản lý Lịch sử, Tra cứu mất xe & Doanh thu**: Tìm kiếm, lọc, phân trang 0ms qua `WarmDatabaseMirror`, Modal đối chiếu 3 khối (`Check-in · Check-out · Người lấy xe`), thống kê doanh thu `2.000 đ / lượt` theo Ngày/Tháng/Năm và xuất báo cáo PDF chuẩn A4.

---

## 5. Cài đặt & Khởi chạy (Sau khi hoàn tất triển khai)

### Yêu cầu môi trường
- Python `3.10` – `3.14` (Local: `C:\Python314\python.exe`)
- **Local MySQL Server** (quản lý trực quan qua **MySQL Workbench**)

### Cài đặt thư viện
```bash
pip install -r requirements.txt
pip install --no-deps facenet-pytorch==2.6.0
```

### Cấu hình Local MySQL (MySQL Workbench)
1. Mở **MySQL Workbench**, tạo schema/database mới (VD: `CREATE DATABASE IF NOT EXISTS datn_parking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` hoặc dùng `defaultdb`).
2. Sao chép `.env.example` thành `.env` và điền thông tin kết nối cục bộ:
```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_local_mysql_password
MYSQL_DATABASE=defaultdb
```
*(Bảng `plate_recognition_history` và các index sẽ được backend tự động khởi tạo khi chạy lần đầu).*

### Chạy ứng dụng cục bộ
```bash
python -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8000
```
Truy cập: `http://127.0.0.1:8000`

### Chạy bộ kiểm chứng & kiểm thử tự động (Harness)
```powershell
.\scripts\verify.ps1
```
Hoặc chạy riêng `pytest`:
```bash
pytest tests/ -v
```
