"""Vietnamese license plate normalization and canonical key helper."""

from __future__ import annotations

import re

PLATE_SERIES_RE = re.compile(r"^\d{2}[A-Z]{1,2}\d?$")
PLATE_NUMBER_RE = re.compile(r"^\d{4,5}$")

TO_DIGIT: dict[str, str] = {"D": "0", "B": "8", "S": "5", "Z": "2", "G": "6"}
TO_LETTER: dict[str, str] = {"0": "D", "8": "B", "5": "S", "2": "Z", "6": "G", "4": "A"}


def clean_plate_key(text: str | None) -> str:
    """Return canonical uppercase alphanumeric plate key (single source of truth)."""
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


def _try_parse_series_number(raw_chars: list[str], split_at: int) -> tuple[str, str] | None:
    if split_at < 3 or len(raw_chars) - split_at not in (4, 5):
        return None
    chars = list(raw_chars)
    for idx in (0, 1):
        chars[idx] = TO_DIGIT.get(chars[idx], chars[idx])
    chars[2] = TO_LETTER.get(chars[2], chars[2])
    # Force all 4 or 5 trailing serial digits to numeric characters
    for idx in range(split_at, len(chars)):
        chars[idx] = TO_DIGIT.get(chars[idx], chars[idx])

    series = "".join(chars[:split_at])
    number = "".join(chars[split_at:])
    if PLATE_SERIES_RE.match(series) and PLATE_NUMBER_RE.match(number):
        return f"{series}{number}", f"{series}-{number}"
    return None


def normalize_plate(raw_text: str | None) -> tuple[str, str] | None:
    """Normalize raw OCR text into `(plate_key, plate_display)` or `None`."""
    if not raw_text:
        return None
    upper = raw_text.upper()
    chars = [ch for ch in upper if ch.isalnum()]
    if not 7 <= len(chars) <= 10:
        return None

    if upper.count("-") == 1:
        split_at = sum(ch.isalnum() for ch in upper.split("-")[0])
        parsed = _try_parse_series_number(chars, split_at)
        if parsed:
            return parsed

    for num_len in (5, 4):
        parsed = _try_parse_series_number(chars, len(chars) - num_len)
        if parsed:
            return parsed
    return None
