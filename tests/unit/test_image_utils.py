"""Unit tests for image sharpness, JPEG Data URL roundtrip, and disk snapshots."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.backend.domain.image_utils import (
    crop_to_data_url,
    decode_base64_frame,
    region_sharpness,
    save_snapshot_to_disk,
)


def test_region_sharpness_inner_core_ignores_sharp_background_border() -> None:
    # Build a 200x200 frame with high-frequency checkerboard in outer border
    # and flat blur inside the inner 70% core of box (20, 20, 180, 180).
    frame = np.full((200, 200, 3), 120, dtype=np.uint8)
    for y in range(20, 180):
        for x in range(20, 180):
            in_core = 44 <= x < 156 and 44 <= y < 156
            if not in_core and ((x + y) % 2 == 0):
                frame[y, x] = (255, 255, 255)
            elif not in_core:
                frame[y, x] = (0, 0, 0)

    full_box_sharpness = region_sharpness(frame, (20, 20, 180, 180), inner_ratio=1.0)
    core_sharpness = region_sharpness(frame, (20, 20, 180, 180), inner_ratio=0.70)

    assert full_box_sharpness > 100.0
    assert core_sharpness == pytest.approx(0.0, abs=1e-6)
    assert region_sharpness(None, (0, 0, 50, 50)) == 0.0
    assert region_sharpness(frame, (0, 0, 4, 4)) == 0.0


def test_crop_to_data_url_and_decode_base64_roundtrip_and_guards() -> None:
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 256, size=(240, 480, 3), dtype=np.uint8)

    data_url = crop_to_data_url(frame, (40, 20, 440, 220), max_w=200, max_h=100, pad_ratio=0.0)
    assert data_url is not None
    assert data_url.startswith("data:image/jpeg;base64,")

    decoded = decode_base64_frame(data_url)
    assert decoded is not None
    assert decoded.shape[:2] == (100, 200)

    # Also accepts raw base64 without Data URL prefix
    raw_b64 = data_url.split(",", 1)[1]
    assert decode_base64_frame(raw_b64) is not None

    # Guards
    assert decode_base64_frame(None) is None
    assert decode_base64_frame("") is None
    assert decode_base64_frame("not-valid-base64!!!") is None
    assert decode_base64_frame(data_url, max_b64_chars=10) is None
    assert crop_to_data_url(None, (0, 0, 10, 10)) is None
    assert crop_to_data_url(frame, (10, 10, 10, 10)) is None


def test_save_snapshot_to_disk_enabled_and_disabled(tmp_path: Path) -> None:
    frame = np.full((64, 64, 3), 180, dtype=np.uint8)
    data_url = crop_to_data_url(frame, (0, 0, 64, 64), max_w=64, max_h=64, pad_ratio=0.0)
    assert data_url is not None

    disabled_out = save_snapshot_to_disk(
        "plate",
        "59V1-79379",
        data_url,
        snapshot_dir=tmp_path,
        enabled=False,
        timestamp_str="20261126_200000",
    )
    assert disabled_out is None
    assert list(tmp_path.iterdir()) == []

    saved_path = save_snapshot_to_disk(
        "plate",
        "59V1-79379",
        data_url,
        snapshot_dir=tmp_path,
        enabled=True,
        timestamp_str="20261126_200000",
    )
    assert saved_path is not None
    assert saved_path.name == "20261126_200000_59V1-79379_plate.jpg"
    assert saved_path.is_file()
    assert saved_path.read_bytes()[:2] == b"\xff\xd8"
