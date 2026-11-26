"""Unit tests for character IoU deduplication and 1-line/2-line plate assembly."""

from __future__ import annotations

import pytest

from src.backend.domain.models import CharDetection
from src.backend.domain.plate_assembly import (
    assemble_plate_text,
    box_iou,
    deduplicate_chars,
)


def test_box_iou_edge_cases() -> None:
    assert box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert box_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)


def test_deduplicate_and_assemble_plate_text_legacy_tuples() -> None:
    # Overlapping char boxes (IoU > 0.55) keep the higher-confidence detection
    raw_chars = [
        (10.0, 10.0, "5", 0.95, (0, 0, 20, 30)),
        (11.0, 10.0, "S", 0.60, (1, 0, 21, 30)),
        (35.0, 10.0, "9", 0.92, (25, 0, 45, 30)),
        (60.0, 10.0, "V", 0.91, (50, 0, 70, 30)),
        (85.0, 10.0, "1", 0.90, (75, 0, 95, 30)),
        # Bottom line (y = 55)
        (15.0, 55.0, "7", 0.94, (5, 40, 25, 70)),
        (40.0, 55.0, "9", 0.93, (30, 40, 50, 70)),
        (65.0, 55.0, "3", 0.92, (55, 40, 75, 70)),
        (90.0, 55.0, "7", 0.91, (80, 40, 100, 70)),
        (115.0, 55.0, "9", 0.95, (105, 40, 125, 70)),
    ]
    deduped = deduplicate_chars(raw_chars)
    assert len(deduped) == 9
    assert assemble_plate_text(deduped) == "59V1-79379"

    # Single-line horizontal plate
    single_line = [
        (80.0, 12.0, "1", 0.90, (70, 0, 90, 24)),
        (10.0, 10.0, "5", 0.95, (0, 0, 20, 24)),
        (35.0, 11.0, "9", 0.92, (25, 0, 45, 24)),
        (60.0, 10.0, "A", 0.93, (50, 0, 70, 24)),
    ]
    assert assemble_plate_text(single_line) == "59A1"


def test_deduplicate_and_assemble_with_char_detection_dataclasses() -> None:
    detections = [
        CharDetection(cx=10.0, cy=10.0, label="3", confidence=0.94, box=(0, 0, 20, 28)),
        CharDetection(cx=11.0, cy=10.0, label="8", confidence=0.55, box=(1, 0, 21, 28)),
        CharDetection(cx=32.0, cy=10.0, label="0", confidence=0.92, box=(22, 0, 42, 28)),
        CharDetection(cx=54.0, cy=10.0, label="T", confidence=0.91, box=(44, 0, 64, 28)),
        CharDetection(cx=76.0, cy=10.0, label="4", confidence=0.90, box=(66, 0, 86, 28)),
        CharDetection(cx=16.0, cy=50.0, label="1", confidence=0.93, box=(6, 36, 26, 64)),
        CharDetection(cx=38.0, cy=50.0, label="9", confidence=0.92, box=(28, 36, 48, 64)),
        CharDetection(cx=60.0, cy=50.0, label="7", confidence=0.91, box=(50, 36, 70, 64)),
        CharDetection(cx=82.0, cy=50.0, label="5", confidence=0.95, box=(72, 36, 92, 64)),
    ]
    deduped = deduplicate_chars(detections)
    assert len(deduped) == 8
    assert all(isinstance(item, CharDetection) for item in deduped)
    assert assemble_plate_text(deduped) == "30T4-1975"
    assert assemble_plate_text([]) == ""
    assert assemble_plate_text([detections[0]]) == "3"
