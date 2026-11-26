"""Unit tests for face embedding serialization, similarity, and sharpness ranking."""

from __future__ import annotations

import pytest

from src.backend.config import EMBEDDING_SIZE
from src.backend.domain.face_math import (
    compute_face_score,
    cosine_similarity,
    embedding_from_bytes,
    embedding_to_bytes,
    face_candidate_rank,
)


def test_cosine_similarity_and_serialization() -> None:
    vec = [float(i % 7) + 0.5 for i in range(EMBEDDING_SIZE)]
    raw = embedding_to_bytes(vec)
    assert len(raw) == EMBEDDING_SIZE * 4

    restored = embedding_from_bytes(raw)
    assert restored is not None
    assert len(restored) == 512
    assert cosine_similarity(vec, restored) == pytest.approx(1.0, abs=1e-5)
    assert cosine_similarity(vec, [-v for v in vec]) == pytest.approx(-1.0, abs=1e-5)
    assert cosine_similarity([0.0] * 512, vec) == 0.0
    assert embedding_from_bytes(b"invalid_short_bytes") is None
    assert embedding_from_bytes(None) is None


def test_compute_face_score_and_candidate_rank_tiers() -> None:
    blurry_big_score = compute_face_score(confidence=0.98, area=40_000, sharpness=12.0)
    sharp_small_score = compute_face_score(confidence=0.88, area=2_500, sharpness=25.0)

    rank_blurry = face_candidate_rank(blurry_big_score, sharpness=12.0)
    rank_floor = face_candidate_rank(50.0, sharpness=15.0)
    rank_standard = face_candidate_rank(sharp_small_score, sharpness=22.0)

    assert rank_blurry[0] == 0
    assert rank_floor[0] == 1
    assert rank_standard[0] == 2
    assert rank_standard > rank_floor > rank_blurry
