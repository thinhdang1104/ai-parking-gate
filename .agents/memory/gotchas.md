# Known Gotchas & Invariants (DATN2)

Critical behavioral edge cases inherited from `C:\Study\DATN` that MUST NEVER regress:

1. **UTC+7 Naive Timestamps**: MySQL `recognized_at` and `created_at` store Vietnam local time (UTC+7) as naive `DATETIME` values (consistent with existing `plate_recognition_history` records in MySQL Workbench). Never mix UTC and UTC+7.
2. **No Data Loss on Async DB Commit**: Only emit `VÀO / RA BÃI THÀNH CÔNG` and start cooldown *after* MySQL commit succeeds. In-flight jobs in `ThreadPoolExecutor(max_workers=1)` must never be canceled when cameras stop or server shuts down.
3. **Lock Hygiene**: Never hold `state_lock` while running YOLO/FaceNet inference or executing MySQL queries. Use non-blocking `infer_lock.acquire(blocking=False)` so browser frame loops never pile up.
4. **70%-Core Laplacian Sharpness**: Face sharpness must be computed on the inner 70% core crop (ignoring background edges) with thresholds `15.0` (floor), `22.0` (standard), and `0.88` confidence instant-accept.
5. **Single Source of Truth for Plate Keys**: `clean_plate_key()` lives exclusively in `src/backend/domain/plate_normalizer.py` and is reused by voting, repository search, and `WarmDatabaseMirror`.
6. **WarmDatabaseMirror Parity**: Capped at 600 recent image records in RAM; must stay 1-to-1 synchronized with MySQL writes and fall back cleanly to MySQL on cache miss.
7. **Revenue Counting**: Fee (`2.000 VNĐ/lượt`) is counted strictly on `IN` records only — never double-counted on `OUT`.
8. **Environment Python Path**: On this workstation, verify which Python interpreter has `pytest` and ML dependencies installed before running `verify.ps1` (do not assume `C:\Python314\python.exe` has all packages).
