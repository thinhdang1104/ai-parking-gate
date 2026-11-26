# AGENTS.md — Quy tắc vận hành AI & Quy trình phát triển (DATN2)

Tài liệu này quy định luật làm việc, phạm vi tự chủ và tiêu chuẩn kỹ thuật cho mọi tác nhân AI (và lập trình viên) tham gia xây dựng lại dự án **DATN2** (Hệ thống Quản lý Bãi giữ xe Trường học với AI Nhận diện Khuôn mặt và Biển số xe).

---

## 1. Nguyên tắc bất di bất dịch (Hard Constraints)

1. **TUYỆT ĐỐI KHÔNG SỬA `C:\Study\DATN`**:
   - Thư mục gốc `C:\Study\DATN` là bản tham chiếu chỉ đọc (read-only).
   - Không sửa, xóa, format, git commit hay ghi bất kỳ file nào vào `C:\Study\DATN`.
   - Chỉ được phép **đọc** để đối chiếu nghiệp vụ và **sao chép** tài nguyên tĩnh cần thiết (VD: `weights/*.pt`, `datasets/*/data.yaml`, `.env.example`) sang `C:\Study\DATN2`.
2. **Bảo toàn 100% chức năng & tương thích dữ liệu**:
   - Mọi tính năng của hệ thống gốc (2 Camera WebRTC đối xứng, YOLOv8 biển số + ký tự, FaceNet 512-D, Two-Phase Latch 4s, Cảnh báo lệch mặt, Lịch sử & Phân trang, Tra cứu mất xe 3 khối, Doanh thu 2.000 đ/lượt, Xuất PDF A4, Local MySQL quản lý qua MySQL Workbench) phải hoạt động đầy đủ và chính xác hơn.
   - Phạm vi hiện tại tập trung chạy **Local** (chưa triển khai Hugging Face Spaces / Gradio).
   - Giữ tương thích schema bảng `plate_recognition_history` trên MySQL để có thể dùng chung dữ liệu thực tế hiện có mà không mất bản ghi.
3. **Không đánh mất dữ liệu khi đang ghi DB**:
   - Chỉ thông báo **VÀO / RA BÃI THÀNH CÔNG** sau khi MySQL commit thành công.
   - Mọi bản ghi đã xác thực nằm trong hàng đợi ghi DB không được bị hủy kể cả khi người dùng tắt camera hoặc dừng server.

---

## 2. Quy chuẩn lập trình (Karpathy Guidelines)

Mọi thay đổi mã nguồn đều tuân thủ 4 nguyên tắc sau:

1. **Think Before Coding (Suy nghĩ trước khi code)**:
   - Không tự suy diễn yêu cầu mơ hồ; nêu rõ giả định và hỏi lại người dùng khi có nhiều hướng thiết kế.
   - Đọc `spec.md`, `architecture.md`, `tasks.md` và `progress.md` trước khi bắt đầu một task mới.
2. **Simplicity First (Đơn giản trước tiên)**:
   - Viết lượng code tối thiểu giải quyết đúng bài toán; không tạo abstraction/framework thừa chỉ dùng một lần.
   - Không cài thêm thư viện nặng (như React/Webpack/SQLAlchemy) nếu Vanilla ES Modules và `mysql-connector-python` đã giải quyết sạch sẽ.
3. **Surgical Changes (Chỉnh sửa gọn, đúng phạm vi)**:
   - Mỗi module chỉ đảm nhiệm một trách nhiệm rõ ràng (Single Responsibility), ưu tiên code sạch và dễ đọc (không áp đặt giới hạn cứng số dòng/file).
   - Không chỉnh sửa lan man các module không liên quan tới task hiện tại; tự dọn sạch import/biến/hàm thừa sau khi sửa.
4. **Goal-Driven Execution (Thực thi hướng mục tiêu & Kiểm chứng)**:
   - Mọi task phải có tiêu chí kiểm chứng cụ thể (`[Bước] -> verify: [Lệnh test/check]`).
   - **Bắt buộc chạy lệnh harness `.\scripts\verify.ps1` đạt `VERIFY PASSED`** trước khi đánh dấu `[x]` bất kỳ task code/test nào trong `tasks.md`.

---

## 3. Quy trình làm việc chuẩn (Spec-Driven Workflow)

```text
1. Nạp ngữ cảnh 2 tầng:
   - Luôn đọc trước: progress.md, tasks.md, .agents/memory/decisions.md, .agents/memory/gotchas.md
   - Chỉ đọc khi cần theo phạm vi task: mục liên quan trong spec.md / architecture.md, schemas/*, và file tham chiếu ở C:\Study\DATN
2. Triển khai code trong src/ kèm unit/integration test tương ứng trong tests/
3. Chạy harness kiểm chứng 6 cổng: .\scripts\verify.ps1 (compileall + guardrails + schema validation + ruff + JS check + pytest) -> phải đạt VERIFY PASSED
4. Cổng kết thúc Phase (Review-Fix Loop):
   - Đọc & review lại 100% mã nguồn và test của Phase vừa làm
   - Nếu còn bất kỳ điểm chưa ổn nào (logic, edge case, encapsulation, lint, contract drift, thiếu test) -> sửa dứt điểm và lặp lại bước 3–4 cho tới khi review hoàn toàn tốt & VERIFY PASSED
   - Chỉ khi đã ổn và tốt mới cập nhật tasks.md, progress.md, rồi commit & push lên GitHub (origin main) trước khi sang Phase tiếp theo
```

---

## 4. Mức độ tự chủ của AI (Autonomy Levels)

### Được làm tự chủ (Autonomous — không cần hỏi trước khi đang trong giai đoạn thực thi đã duyệt)
- Đọc mã nguồn tham chiếu từ `C:\Study\DATN` và đọc/ghi các file trong `C:\Study\DATN2`.
- Viết code mới, tách module, viết và chạy automated tests trong `C:\Study\DATN2`.
- Sửa lỗi biên dịch, lỗi logic nội bộ, lỗi test trong `C:\Study\DATN2`.
- Cập nhật `tasks.md` và `progress.md` sau mỗi task hoàn tất.

### Phải hỏi ý kiến người dùng trước (Ask First)
- Thay đổi yêu cầu nghiệp vụ trong `spec.md` hoặc thay đổi kiến trúc lớn trong `architecture.md`.
- Thay đổi cấu trúc bảng MySQL có tính phá vỡ (DROP/RENAME cột, đổi kiểu dữ liệu) hoặc xóa dữ liệu trên DB thật.
- Thay đổi hợp đồng REST API (đổi URL, đổi cấu trúc JSON phá vỡ tương thích frontend).
- Cài đặt thêm dependency mới ngoài `requirements.txt` chuẩn.
- Thực hiện `git commit` hoặc `git push`.

### Quy trình phản hồi khi người dùng hỏi / báo lỗi
Khi người dùng đặt câu hỏi (*"tại sao..."*, *"kiểm tra..."*) hoặc nêu hiện tượng lỗi:
1. **Trả lời**: Đọc/kiểm tra để xác định đúng nguyên nhân và giải thích rõ ràng.
2. **Đề xuất**: Trình bày ngắn gọn phương án xử lý (kèm đánh đổi nếu có).
3. **Chờ xác nhận**: Dừng lại chờ người dùng đồng ý trước khi sửa file.

---

## 5. Quy ước mã nguồn & Kiểm thử

- **Môi trường Python**: `C:\Python314\python.exe` (tương thích Python 3.10–3.14).
- **Python style**: Type hints chuẩn (`str | None`, `list[dict]`), `dataclasses` cho DTO/domain objects, không dùng biến global ẩn; truyền dependency qua constructor (Dependency Injection) để dễ unit test không cần `mock.patch` tràn lan.
- **Frontend style**: HTML5 + CSS3 + Vanilla JavaScript **ES Modules** (`<script type="module" src="/js/main.js">`), tách rõ API client, state, WebRTC camera, overlay, history, revenue, lost-case modal và PDF exporter.
- **Kiểm thử bắt buộc**:
  - Domain logic (chuẩn hóa biển số, voting, cosine similarity, sharpness, ranking): unit test thuần, chạy < 1 giây.
  - Storage & Warm Mirror: test đồng bộ RAM/SQL, phân trang, sắp xếp, tra cứu mất xe, doanh thu.
  - Gate Engine (Latch 2 pha, Fast-Confirm, Security Alert, Async Commit, Stop Camera safety): regression test đầy đủ như bản gốc và mở rộng thêm.
  - API Routes: test bằng `fastapi.testclient.TestClient`.
