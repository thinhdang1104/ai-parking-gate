"""Unit tests for Vietnamese license plate normalization and canonical key cleaning."""

from __future__ import annotations

from src.backend.domain.plate_normalizer import clean_plate_key, normalize_plate


def test_normalize_plate_standard_and_confusable_chars() -> None:
    # 2-line and 1-line standard Vietnamese plates (5-digit and 4-digit serials)
    assert normalize_plate("59V1-79379") == ("59V179379", "59V1-79379")
    assert normalize_plate("30T4-1975") == ("30T41975", "30T4-1975")
    assert normalize_plate("59a112345") == ("59A112345", "59A1-12345")

    # Auto-correct confusable OCR characters (D<->0, B<->8, S<->5, Z<->2, G<->6)
    assert normalize_plate("5901-123B5") == ("59D112385", "59D1-12385")
    assert normalize_plate("DBB1-12345") == ("08B112345", "08B1-12345")

    # Double-letter series (e.g. electric motorbike / special plates)
    assert normalize_plate("59MD1-23456") == ("59MD123456", "59MD1-23456")
    assert normalize_plate("59AA-1234") == ("59AA1234", "59AA-1234")


def test_normalize_plate_rejects_invalid_strings() -> None:
    assert normalize_plate(None) is None
    assert normalize_plate("") is None
    assert normalize_plate("123") is None
    assert normalize_plate("ABCDEFGHIJK") is None
    assert normalize_plate("59-12") is None
    assert normalize_plate("59V1-12A") is None
    assert normalize_plate("5912-3456") is None


def test_clean_plate_key() -> None:
    assert clean_plate_key("59v1-793.79 ") == "59V179379"
    assert clean_plate_key(None) == ""
    assert clean_plate_key("") == ""
