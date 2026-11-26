# spec.md — Đặc tả Yêu cầu & Hành vi Phần mềm (DATN2)

**Tên dự án:** Hệ thống Quản lý Bãi giữ xe Trường học với AI Nhận diện Khuôn mặt và Biển số xe (Phiên bản tái cấu trúc sạch — `DATN2`).  
**Mục tiêu:** Giữ nguyên 100% tính năng, trải nghiệm người dùng và tương thích dữ liệu của hệ thống `DATN`, nhưng viết lại hoàn toàn theo kiến trúc phân lớp sạch sẽ, dễ bảo trì và có kiểm thử tự động toàn diện.

---

## 1. Tổng quan hệ thống & Vai trò người dùng

- **Người vận hành (Bảo vệ bãi xe):**
  - Mở trình duyệt kết nối 1 hoặc 2 camera USB/Webcam/DroidCam (`Cam 1`, `Cam 2`).
  - Giám sát nhận diện tự động xe vào/ra theo thời gian thực.
  - Xử lý cảnh báo an ninh (duyệt **Cho phép ra** hoặc **Từ chối**) khi khuôn mặt người lấy xe không khớp với người gửi xe.
  - Tra cứu lịch sử xe vào/ra, xử lý biên bản đối chiếu khi xảy ra mất xe (`Check-in · Check-out · Người lấy xe`).
  - Theo dõi doanh thu giữ xe (`2.000 đ / lượt`) theo Ngày, Tháng, Năm và xuất báo cáo PDF chuẩn A4.

---

## 2. Yêu cầu chức năng (Functional Requirements)

### FR-1: Quản lý 2 Camera WebRTC đối xứng (`Cam 1` & `Cam 2`)
- **FR-1.1 Tìm thiết bị theo tên**: Nút **"Tìm camera"** gọi `navigator.mediaDevices.getUserMedia` (xin quyền nếu chưa có) và `enumerateDevices()`, liệt kê danh sách `videoinput` theo `label` thực tế vào dropdown của `Cam 1` và `Cam 2`.
- **FR-1.2 Mở chính xác & Chống trùng thiết bị**: Mở luồng bằng `deviceId: { exact }`. Nếu một thiết bị đang được chọn/chạy ở `Cam 1` thì không được trùng với `Cam 2` (và ngược lại). Tự lắng nghe sự kiện `devicechange` và `track.onended` khi camera bị rút đột ngột.
- **FR-1.3 Bật/tắt độc lập & đồng thời**: Hỗ trợ nút **"Kết nối" / "Tắt"** riêng cho từng camera và nút **"Bật cả 2" / "Tắt tất cả"**. Tắt 1 camera không làm gián đoạn camera còn lại.
- **FR-1.4 Luồng gửi khung hình & Overlay**:
  - Video hiển thị trực tiếp từ WebRTC `<video>` trên trình duyệt, phủ `<canvas>` vẽ Bounding Box biển số (hợp lệ / chưa hợp lệ) và khuôn mặt kèm độ tin cậy.
  - Gửi khung hình JPEG nén (chiều rộng tối đa `640px`, giới hạn payload base64 `<= 2.500.000` ký tự) lên `/api/camera/browser-frame` theo chu kỳ `~140 ms`, bỏ qua nhịp nếu request trước chưa xong (không chồng chéo request).
  - Nếu 2 camera vô tình gửi ảnh base64 giống hệt nhau, backend bỏ qua `frame2` để tránh nhận diện trùng.

### FR-2: Nhận diện Biển số xe Việt Nam 2 giai đoạn (YOLOv8) & Bỏ phiếu đồng thuận
- **FR-2.1 Phát hiện biển số & OCR ký tự**:
  - Model 1 (`weights/plate_best.pt`): phát hiện vùng biển số (`conf=0.40`, `iou=0.5`, `imgsz=512`). Khi cả 2 camera đều cần quét biển số trong cùng 1 nhịp, gọi **batch predict** `[frame1, frame2]` trong 1 lần suy luận.
  - Model 2 (`weights/chars_best.pt`): nhận diện 31 lớp ký tự (`0-9`, `A-Z`) trên ảnh cắt biển số (`conf=0.35`, `iou=0.5`, `imgsz=320`).
  - Khử ký tự trùng vị trí theo IoU (`> 0.55`, ưu tiên độ tin cậy cao hơn).
  - Gom dòng thông minh: phân biệt biển 1 dòng (`max(y) - min(y) < 0.6 * avg_char_height`) và biển 2 dòng (chia theo trung điểm `y`, sắp xếp trái -> phải, nối bằng `-`).
- **FR-2.2 Chuẩn hóa biển số Việt Nam**:
  - Độ dài ký tự chữ-số từ `7` đến `10`.
  - Định dạng hợp lệ: `series` khớp `^\d{2}[A-Z]{1,2}\d?$` và `number` khớp `^\d{4,5}$` (VD: `59V1-79379`, `30T4-1975`).
  - Tự sửa ký tự dễ nhầm OCR theo vị trí: `TO_DIGIT = {D:0, B:8, S:5, Z:2, G:6}` ở 2 ký tự mã tỉnh và toàn bộ 4–5 ký tự phần số; `TO_LETTER = {0:D, 8:B, 5:S, 2:Z, 6:G, 4:A}` ở ký tự thứ 3 (mã seri).
  - Trả về cặp `(plate_key, plate_display)` (VD: `("59V179379", "59V1-79379")`).
- **FR-2.3 Bỏ phiếu đồng thuận (Majority Voting & Fast-Confirm)**:
  - Cửa sổ bỏ phiếu `3.0s`, giãn cách lấy mẫu `0.08s`. Nếu 1 khung hình có > 1 biển số hợp lệ (`ambiguous_frame`), bỏ qua mẫu đó và hiển thị cảnh báo.
  - Reset bộ phiếu của camera nếu không thấy biển số trong `1.5s`.
  - **Chốt chuẩn**: `sample_count >= 3` và `vote_share >= 0.70`.
  - **Chốt nhanh (Fast-Confirm)**: `>= 2` mẫu liên tiếp cuối cùng khớp cùng `plate_key`, `vote_share >= 0.70` và mỗi mẫu có độ tin cậy trung bình ký tự `>= 0.75`.
  - Lưu ảnh cắt biển số sắc nét nhất (theo Laplacian Variance) dạng JPEG Data URL (`max 360x180`, quality 92).

### FR-3: Phát hiện & Xác thực Khuôn mặt Sinh trắc học (FaceNet 512-D)
- **FR-3.1 Phát hiện khuôn mặt**: Dùng `MTCNN(keep_all=True)` (`min_face_size=24` trên CPU, `40` trên GPU; trên CPU tự thu nhỏ ảnh về rộng `360px` rồi quy đổi tọa độ box về ảnh gốc).
- **FR-3.2 Lọc chất lượng & độ sắc nét**:
  - Ngưỡng tin cậy tối thiểu `FACE_MIN_CONFIDENCE = 0.85`.
  - Đo độ sắc nét Laplacian Variance trên vùng lõi `70%` khuôn mặt (chuẩn hóa `128x128`):
    - Ngưỡng sàn: `FACE_FLOOR_SHARPNESS = 15.0` (chấp nhận sau `0.40s` chờ).
    - Ngưỡng chuẩn: `FACE_MIN_SHARPNESS = 22.0` (chấp nhận sau `0.15s` chờ).
    - Chốt tức thì: `confidence >= 0.88` và `sharpness >= 22.0`.
  - Xếp hạng ứng viên theo bậc `(tier, score)` để mặt lớn nhưng mờ (`< 15.0`) không ghi đè mặt đủ nét.
- **FR-3.3 Trích xuất vector & Đối chiếu**:
  - Dùng `InceptionResnetV1(pretrained="vggface2")` trích xuất vector `512` chiều chuẩn hóa L2 (có fallback cắt trực tiếp `160x160` nếu `detector.extract()` trả `None` sát biên ảnh).
  - Tính **Cosine Similarity** giữa khuôn mặt lúc ra (`OUT`) và khuôn mặt lúc vào (`IN_PARKING`); ngưỡng khớp `FACE_MATCH_THRESHOLD = 0.65`.
  - Cắt ảnh khuôn mặt (`max 320x320`, `pad_ratio=0.22`, quality 92) lưu cùng bản ghi.

### FR-4: Cơ chế Chốt 2 Pha đối xứng (Two-Phase Latch) & Tự động phân luồng VÀO/RA
- **FR-4.1 Phối hợp 2 Camera thông minh**:
  - Trong chế độ 2 camera: camera nào đạt đồng thuận biển số trước (`plate_cam`) thì **camera đối diện (`3 - plate_cam`)** bắt buộc cung cấp khuôn mặt (`required_face_cam`).
  - Trong chế độ 1 camera: cùng 1 camera đảm nhận cả biển số và khuôn mặt.
  - Khi 1 cam đang thấy biển số còn cam kia chưa có biển, ưu tiên quét MTCNN ở cam đối diện và giảm quét biển số dư thừa để tăng FPS.
- **FR-4.2 Xác định chiều VÀO / RA tự động**:
  - Truy vấn phiên `IN_PARKING` gần nhất của `plate_key` (đọc tức thì từ `WarmDatabaseMirror` hoặc fallback MySQL).
  - Có phiên `IN_PARKING` -> chiều `OUT` (`parking_status='EXITED'`, `fee_amount=0`).
  - Không có phiên `IN_PARKING` -> chiều `IN` (`parking_status='IN_PARKING'`, `fee_amount=2000`).
  - Nếu MySQL chưa sẵn sàng -> hủy bỏ phiếu và báo lỗi `"LỖI KẾT NỐI CSDL — TẠM HOÃN XÁC THỰC XE ..."`.
- **FR-4.3 Quản lý vòng đời Latch (`4.0s`)**:
  - Tận dụng bộ đệm khuôn mặt trước khi chốt (`FACE_PRE_LATCH_LOOKBACK_SECONDS = 1.80s`) để có thể chốt tức thì ngay trong frame đạt đồng thuận.
  - Hủy Latch ngay nếu:
    - Biển số khác xuất hiện trên `plate_cam` -> báo `HỦY LƯU HỜ (ĐÃ ĐỔI XE MỚI)`.
    - Quá `4.0s` chưa có mặt đạt chuẩn -> báo `KHUÔN MẶT BỊ MỜ, VUI LÒNG QUÉT LẠI` hoặc `THIẾU KHUÔN MẶT`.
    - Người dùng bấm nút **Hủy** (`/api/camera/cancel-latch`).
- **FR-4.4 Chống ghi trùng & Commit an toàn**:
  - Khóa `committing_plates` trong lúc ghi MySQL bất đồng bộ (`ThreadPoolExecutor(max_workers=1)`).
  - Chỉ đặt cooldown (`20.0s` cùng chiều, `6.0s` chiều ngược lại), thêm vào `plates_must_leave` (cho tới khi biển rời khung hình `1.5s`) và phát thông báo `VÀO/RA BÃI THÀNH CÔNG` **sau khi MySQL commit thành công**.
  - Nếu ghi MySQL thất bại -> gỡ khóa, báo lỗi yêu cầu quét lại.
  - Tắt camera / tắt server không được hủy các bản ghi đã xác thực đang nằm trong hàng đợi ghi DB.

### FR-5: Cảnh báo an ninh lệch khuôn mặt (Security Alert)
- Khi xe chiều `OUT` có `cosine_similarity < 0.65` (hoặc không có embedding phiên vào):
  - Không ghi DB ngay; tạm dừng xử lý frame mới và bật **Top-up Security Alert** hiển thị biển số, thời gian vào và `%` tương đồng.
  - Bảo vệ chọn:
    - **Cho phép ra (`approve`)**: ghi bản ghi `OUT` (kèm `face_match_score` thực tế) vào MySQL. Nếu MySQL lỗi -> **giữ nguyên alert** để bảo vệ bấm duyệt lại được; nếu thành công -> xóa alert, đặt cooldown, báo `XE ... RA BÃI ĐƯỢC DUYỆT`.
    - **Từ chối (`reject`)**: không ghi DB, xóa alert, xóa cooldown `OUT`, báo `XE ... RA BÃI BỊ TỪ CHỐI`.

### FR-6: Màn hình Lịch sử & Quản lý
- 3 thẻ KPI: **Đang gửi trong bãi**, **Lượt vào / ra hôm nay**, **Tổng lượt lưu trữ**.
- 4 tab lọc trạng thái kèm bộ đếm: `all` (Tất cả), `in_parking` (Đang gửi trong bãi), `direction_in` (Lượt vào), `direction_out` (Lượt ra).
- Ô tìm kiếm theo biển số (debounce, không phân biệt hoa thường/dấu gạch ngang).
- Sắp xếp theo cột Luồng / Đối chiếu khi cần (`mismatch_first` / `matched_first`).
- Phân trang (`10 / 20 / 50 / 100` dòng/trang), cache phía client theo `records_version` và prefetch trang kế tiếp.
- Bảng hiển thị: Biển số xe, Ảnh cắt (Biển & Mặt — có fallback SVG nếu bản ghi cũ không có ảnh), Luồng + Đối chiếu, Thời gian, Mã ghi (`#ID`), nút **Tra cứu mất xe**.
- Nút **Xuất PDF** báo cáo lịch sử chuẩn A4 (tối đa theo bộ lọc hiện tại).

### FR-7: Tra cứu sự cố mất xe (Modal 3 khối & Xem ảnh cắt)
- Bấm vào nút **Tra cứu mất xe** trên bất kỳ dòng `IN` hay `OUT` nào -> gọi `/api/management/session-case/{record_id}`:
  - Ghép cặp bản ghi `Check-in` và `Check-out` theo `entry_record_id` (có cơ chế fallback theo `plate_key` + thứ tự thời gian cho dữ liệu cũ; short-circuit 1 query nếu bản ghi `IN` vẫn đang `IN_PARKING`).
  - Hiển thị Modal 3 khối song song:
    1. **CHECK IN (Lúc gửi xe)**: `#ID`, thời gian vào, biển số, nhận diện mặt, ảnh biển số & ảnh người gửi.
    2. **CHECK OUT (Lúc lấy xe)**: `#ID`, thời gian ra, trạng thái bãi, kết quả đối chiếu FaceNet, ảnh biển số lúc ra.
    3. **NGƯỜI LẤY XE**: ảnh khuôn mặt người lấy xe phóng lớn + kết luận đối chiếu (Khớp / Lệch / Chưa lấy xe / Thiếu bản ghi ra).
  - Nút **Xuất PDF biên bản** chuẩn A4 in đầy đủ thông tin và ảnh đối chiếu.
- Bấm trực tiếp vào thumbnail ảnh cắt -> mở chế độ xem ảnh cắt đơn của bản ghi đó.

### FR-8: Màn hình Quản lý Doanh thu
- Đơn giá cố định: `2.000 VNĐ / lượt` (chỉ tính trên chiều `IN`; chiều `OUT` luôn `fee_amount = 0`).
- 4 thẻ tổng hợp: **Doanh thu hôm nay**, **Doanh thu tháng này**, **Doanh thu năm nay**, **Tổng doanh thu tích lũy** (kèm số lượt gửi xe).
- Bấm vào thẻ Hôm nay / Tháng này / Năm nay để chuyển bảng chi tiết theo **Ngày (`DD/MM/YYYY`)**, **Tháng (`Tháng MM/YYYY`)**, hoặc **Năm (`Năm YYYY`)** kèm phân trang (`10 / 20 / 50` dòng).
- Nút **Xuất PDF** báo cáo doanh thu chuẩn A4.

### FR-9: Lưu trữ Local MySQL (MySQL Workbench) & Tiện ích
- Thuần **Local MySQL** (quản lý trực quan qua **MySQL Workbench**) cấu hình qua file `.env` (`MYSQL_HOST=127.0.0.1`, `MYSQL_PORT=3306`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`).
- Múi giờ chuẩn **Việt Nam (UTC+7)** cho toàn bộ mốc thời gian `recognized_at`.
- Tự động tạo bảng `plate_recognition_history` và migrate cột/index khi khởi động; tự động thử kết nối lại mỗi `15s` khi mất kết nối MySQL.
- `WarmDatabaseMirror` trên RAM: giữ 100% metadata và ảnh Base64 cho `600` lượt gần nhất; tự đồng bộ khi có bản ghi mới commit và fallback sang MySQL khi cần bản ghi cũ hơn 600 dòng.
- Cờ tùy chọn qua biến môi trường: `SAVE_DISK_SNAPSHOTS=1` (lưu thêm file `.jpg` vào `data/snapshots/`), `SEED_DEMO_DATA=1` (nạp 38 bản ghi demo nếu DB trống), `FORCE_CPU=1` (ép chạy CPU trên máy không có GPU).
- *(Ngoài phạm vi hiện tại)*: Chưa tích hợp triển khai cloud (Hugging Face Spaces / Gradio wrapper).

---

### 2.1 Bảng Chuyển Trạng Thái — Two-Phase Latch, Async Commit & Security Alert

Mọi triển khai tại `LatchCoordinator` và `GateService` (Phase 3) phải tuân thủ chính xác bảng chuyển trạng thái dưới đây:

| Trạng thái hiện tại | Sự kiện (Event) | Điều kiện (Guard) | Trạng thái mới | Hành động & Bất biến |
| :--- | :--- | :--- | :--- | :--- |
| `IDLE` | Frame có biển số hợp lệ | Không có `security_alert`, `plate_key` không bị cooldown/must-leave/committing | `VOTING` | Ghi nhận mẫu phiếu (giãn cách `>= 0.08s`, cửa sổ `3.0s`), lưu crop biển sắc nét nhất |
| `VOTING` | Mất biển số quá `1.5s` | Không thấy `plate_key` trên cam | `IDLE` | Reset `observations`, `plate_crops`, gỡ cờ `plates_must_leave` cho biển đã rời khung hình |
| `VOTING` | Đạt đồng thuận (`>= 3` mẫu & `>= 70%`, hoặc Fast-Confirm `>= 2` liên tiếp & char conf `>= 0.75`) | MySQL chưa sẵn sàng (`not database_ready`) | `IDLE` | Hủy bỏ phiếu, phát feedback lỗi `"LỖI KẾT NỐI CSDL — TẠM HOÃN XÁC THỰC XE ..."` |
| `VOTING` | Đạt đồng thuận biển số | `database_ready == True`; tra `WarmDatabaseMirror`/MySQL xác định `IN` hoặc `OUT`; không có face đạt chuẩn trong `1.80s` pre-latch lookback | `LATCHED` | Khởi tạo `LatchState` (`4.0s`), gắn `required_face_cam` (`3 - plate_cam` khi 2 cam, hoặc `plate_cam` khi 1 cam) |
| `VOTING` / `LATCHED` | Đã có khuôn mặt đạt chuẩn (`pre-latch lookback <= 1.80s` hoặc đúng `required_face_cam` đạt tier `>= 22.0` tức thì / sau `0.15s`, hoặc sàn `>= 15.0` sau `0.40s`) | Biển số đã đạt đồng thuận; `plate_key` chưa nằm trong `committing_plates` | `COMMITTING` (hoặc `SECURITY_ALERT`) | Thêm `plate_key` vào `committing_plates`; nếu `OUT` và `cosine_similarity < 0.65` (hoặc thiếu embedding vào) -> chuyển `SECURITY_ALERT`; ngược lại đẩy vào `ThreadPoolExecutor(max_workers=1)` |
| `LATCHED` | Biển số khác xuất hiện trên `plate_cam` | `new_plate_key != latched.plate_key` | `IDLE` | Hủy Latch ngay, phát feedback `HỦY LƯU HỜ (ĐÃ ĐỔI XE MỚI)` |
| `LATCHED` | Quá `LATCH_TIMEOUT_SECONDS` (`4.0s`) hoặc gọi `/api/camera/cancel-latch` | Chưa có mặt đạt chuẩn | `IDLE` | Hủy Latch; timeout báo `KHUÔN MẶT BỊ MỜ, VUI LÒNG QUÉT LẠI` (nếu từng thấy mặt) hoặc `THIẾU KHUÔN MẶT` |
| `COMMITTING` | Async DB commit thành công | `session_id` khớp hoặc lệch (không hủy job đang ghi) | `COOLDOWN` | Cập nhật `WarmDatabaseMirror`, bump `records_version`, đặt cooldown `20.0s` cùng chiều & `6.0s` chiều ngược lại, thêm `plates_must_leave`, gỡ `committing_plates`, phát `VÀO/RA BÃI THÀNH CÔNG` |
| `COMMITTING` | Async DB commit lỗi (`DatabaseOperationError`) | MySQL lỗi hoặc timeout | `IDLE` | Gỡ `committing_plates`, **không** đặt cooldown, phát feedback lỗi yêu cầu quét lại |
| `COMMITTING` | Người dùng tắt camera / dừng server | Job đã submit vào `commit_executor` | `COMMITTING` -> `DONE` | **Bất biến**: không hủy future đang chạy; đợi commit hoàn tất an toàn khi shutdown |
| `SECURITY_ALERT` | `/api/camera/resolve-alert` (`approve`) | MySQL ghi `OUT` thành công | `COOLDOWN` | Lưu `OUT` kèm `face_match_score` thực tế, đồng bộ `WarmDatabaseMirror`, xóa alert, đặt cooldown `20s`/`6s`, trả `camera_status` |
| `SECURITY_ALERT` | `/api/camera/resolve-alert` (`approve`) | MySQL lỗi ghi DB | `SECURITY_ALERT` | **Giữ nguyên** `security_alert` để bảo vệ bấm duyệt lại được; trả `status: "db_error"` |
| `SECURITY_ALERT` | `/api/camera/resolve-alert` (`reject`) | Bảo vệ từ chối | `IDLE` | Không ghi DB, xóa alert, không đặt cooldown `OUT`, báo `XE ... RA BÃI BỊ TỪ CHỐI` |

---

## 3. Hợp đồng REST API (Bảo toàn tương thích)

| Method | Endpoint | Mô tả |
| :--- | :--- | :--- |
| `GET/HEAD` | `/`, `/ui` | Phục vụ giao diện web `index.html` (`no-cache`) |
| `GET` | `/api/camera/status` | Trạng thái 2 camera, latch, security alert, feedback, `records_version`, `database_ready`, `models_ready` |
| `POST` | `/api/camera/{cam_id}/start` | Bật camera trình duyệt (`cam_id` ∈ `{1, 2}`) |
| `POST` | `/api/camera/{cam_id}/stop` | Tắt riêng 1 camera |
| `POST` | `/api/camera/stop` | Tắt cả 2 camera |
| `POST` | `/api/camera/browser-frame` | Gửi khung hình base64 `{ cam1_image, cam2_image }`, nhận bounding boxes + status |
| `POST` | `/api/camera/cancel-latch` | Hủy trạng thái Lưu hờ (Latch) hiện tại |
| `POST` | `/api/camera/resolve-alert` | Xử lý cảnh báo lệch mặt `{ action: "approve" \| "reject" }` |
| `GET` | `/api/management/overview` | Thống kê KPI, doanh thu (tùy chọn) và danh sách bản ghi phân trang (`q`, `status`, `limit`, `page`, `page_size`, `include_records`, `include_revenue`, `sort`) |
| `GET` | `/api/management/session-case/{record_id}` | Tra cứu hồ sơ cặp Check-in / Check-out theo `record_id` |
| `POST` | `/api/management/reconnect` | Thử kết nối lại MySQL thủ công |

---

## 4. Schema Cơ sở dữ liệu (`plate_recognition_history`)

Giữ nguyên 100% tên bảng, tên cột và index của `DATN`:
- `id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY`
- `plate_number VARCHAR(32) NOT NULL`, `plate_key VARCHAR(32) NULL`
- `direction VARCHAR(8) NOT NULL DEFAULT 'IN'` (`IN` | `OUT`)
- `parking_status VARCHAR(16) NOT NULL DEFAULT 'IN_PARKING'` (`IN_PARKING` | `COMPLETED` | `EXITED`)
- `entry_record_id BIGINT UNSIGNED NULL`
- `fee_amount INT UNSIGNED NOT NULL DEFAULT 2000`
- `recognized_at DATETIME NOT NULL` (UTC+7 naive)
- `vote_count SMALLINT UNSIGNED`, `sample_count SMALLINT UNSIGNED`, `consensus_rate DECIMAL(5, 4)`
- `face_detected TINYINT(1)`, `face_confidence DECIMAL(5, 4)`, `face_embedding BLOB` (512 × float32 = 2048 bytes), `face_match_score DECIMAL(5, 4)`
- `plate_image LONGTEXT`, `face_image LONGTEXT`
- `camera_index SMALLINT UNSIGNED`, `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
- Indexes: `idx_plate_recognized_at`, `idx_recognized_at`, `idx_plate_status`, `idx_status_dir`, `idx_plate_key_dir_status`, `idx_entry_record_id`.

---

## 5. Yêu cầu phi chức năng (Non-Functional Requirements)

- **NFR-1 Hiệu năng đọc quản lý**: Mọi thao tác chuyển tab, lọc, tìm kiếm, phân trang, xem doanh thu, mở hồ sơ mất xe đạt thời gian phản hồi `< 20 ms` trên server khi `WarmDatabaseMirror` sẵn sàng (0 truy vấn SQL phụ).
- **NFR-2 Độ sạch & Khả năng bảo trì**: Không còn God file; mỗi file code Python/JS tập trung 1 trách nhiệm (mục tiêu `<= 350` dòng).
- **NFR-3 Khả năng kiểm thử**: Tách biệt hoàn toàn pure logic (domain), I/O (DB/AI) và HTTP layer; toàn bộ unit test và regression test chạy độc lập không cần kết nối MySQL thật hay GPU.
- **NFR-4 Khả năng chịu lỗi**: Lỗi tải FaceNet hoặc mất kết nối MySQL không làm sập server; có cảnh báo rõ ràng trên UI và tự phục hồi khi DB kết nối lại.
