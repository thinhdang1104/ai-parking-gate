"""Image sharpness, JPEG Data URL cropping, Base64 decoding, and disk snapshots."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

VN_TZ = timezone(timedelta(hours=7))


def region_sharpness(
    frame: np.ndarray | None,
    box: tuple[int, int, int, int],
    inner_ratio: float = 1.0,
) -> float:
    """Compute 128x128 normalized Laplacian variance sharpness on a box or inner core."""
    if frame is None:
        return 0.0
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = map(int, box)
    if 0.2 <= inner_ratio < 1.0:
        bw, bh = x2 - x1, y2 - y1
        mx = int(round(bw * (1.0 - inner_ratio) * 0.5))
        my = int(round(bh * (1.0 - inner_ratio) * 0.5))
        x1, x2 = x1 + mx, x2 - mx
        y1, y2 = y1 + my, y2 - my
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return 0.0
    roi = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    gray = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def crop_to_data_url(
    frame: np.ndarray | None,
    box: tuple[int, int, int, int],
    max_w: int = 360,
    max_h: int = 180,
    pad_ratio: float = 0.06,
    jpeg_quality: int = 92,
) -> str | None:
    """Crop padded ROI, downscale within bounds, and encode as JPEG Data URL."""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = map(int, box)
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    px, py = int(round(bw * pad_ratio)), int(round(bh * pad_ratio))
    cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
    cx2, cy2 = min(w, x2 + px), min(h, y2 + py)
    if cx1 >= cx2 or cy1 >= cy2:
        return None
    crop = frame[cy1:cy2, cx1:cx2]
    ch, cw = crop.shape[:2]
    scale = min(max_w / cw, max_h / ch, 1.0)
    if scale < 1.0:
        crop = cv2.resize(
            crop,
            (max(1, round(cw * scale)), max(1, round(ch * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        return None
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def decode_base64_frame(
    data_str: str | None,
    max_b64_chars: int = 2_500_000,
) -> np.ndarray | None:
    """Decode a Base64 JPEG or Data URL string into an OpenCV BGR image array."""
    if not data_str or len(data_str) > max_b64_chars:
        return None
    try:
        raw_b64 = data_str.split(",", 1)[1] if "," in data_str else data_str
        buf = np.frombuffer(base64.b64decode(raw_b64), dtype=np.uint8)
        if buf.size == 0:
            return None
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def save_snapshot_to_disk(
    kind: str,
    plate_number: str,
    data_url: str | None,
    *,
    snapshot_dir: Path,
    enabled: bool = False,
    timestamp_str: str | None = None,
) -> Path | None:
    """Optionally persist a JPEG Data URL snapshot to disk when enabled."""
    if not enabled or not data_url or "," not in data_url:
        return None
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        safe_plate = "".join(ch for ch in str(plate_number) if ch.isalnum() or ch in "-_")
        ts = timestamp_str or datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
        raw_bytes = base64.b64decode(data_url.split(",", 1)[1])
        out_path = snapshot_dir / f"{ts}_{safe_plate}_{kind}.jpg"
        out_path.write_bytes(raw_bytes)
        return out_path
    except Exception:
        return None
