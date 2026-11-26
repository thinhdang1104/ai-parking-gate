"""Character IoU deduplication and 1-line / 2-line plate text assembly."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from src.backend.domain.models import CharDetection

CharTuple = tuple[float, float, str, float, tuple[int, int, int, int]]
CharItem = CharDetection | CharTuple
TChar = TypeVar("TChar", CharDetection, CharTuple)


def _unpack_char(item: CharItem) -> tuple[float, float, str, float, tuple[int, int, int, int]]:
    if isinstance(item, CharDetection):
        return item.cx, item.cy, item.label, item.confidence, item.box
    return item[0], item[1], item[2], item[3], item[4]


def box_iou(
    box_a: tuple[int, int, int, int],
    box_b: tuple[int, int, int, int],
) -> float:
    """Compute Intersection-over-Union for two `(x1, y1, x2, y2)` boxes."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0, min(ay2, by2) - max(ay1, by1))
    inter_area = inter_w * inter_h
    if inter_area == 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union_area = area_a + area_b - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def deduplicate_chars(
    raw_chars: Sequence[TChar],
    iou_threshold: float = 0.55,
) -> list[TChar]:
    """Suppress overlapping character boxes, keeping highest confidence first."""
    kept: list[TChar] = []
    for candidate in sorted(raw_chars, key=lambda item: _unpack_char(item)[3], reverse=True):
        cand_box = _unpack_char(candidate)[4]
        if any(box_iou(cand_box, _unpack_char(existing)[4]) > iou_threshold for existing in kept):
            continue
        kept.append(candidate)
    return kept


def assemble_plate_text(chars: Sequence[CharItem]) -> str:
    """Assemble 1-line or 2-line Vietnamese plate text ordered left-to-right."""
    if not chars:
        return ""
    unpacked = [_unpack_char(c) for c in chars]
    if len(unpacked) == 1:
        return unpacked[0][2]

    y_values = [item[1] for item in unpacked]
    char_heights = [max(1, item[4][3] - item[4][1]) for item in unpacked]
    avg_char_height = sum(char_heights) / len(char_heights)

    if max(y_values) - min(y_values) < avg_char_height * 0.6:
        return "".join(item[2] for item in sorted(unpacked, key=lambda item: item[0]))

    threshold = (min(y_values) + max(y_values)) / 2.0
    line_top = sorted((c for c in unpacked if c[1] < threshold), key=lambda c: c[0])
    line_bottom = sorted((c for c in unpacked if c[1] >= threshold), key=lambda c: c[0])
    text_top = "".join(item[2] for item in line_top)
    text_bottom = "".join(item[2] for item in line_bottom)
    if text_top and text_bottom:
        return f"{text_top}-{text_bottom}"
    return text_top + text_bottom
