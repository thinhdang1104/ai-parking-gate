"""Face embedding math, serialization, and sharpness-tiered candidate ranking."""

from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np


def cosine_similarity(vector_a: Sequence[float] | np.ndarray, vector_b: Sequence[float] | np.ndarray) -> float:
    """Compute cosine similarity in [-1.0, 1.0], returning 0.0 on zero vectors."""
    a = np.asarray(vector_a, dtype=np.float32)
    b = np.asarray(vector_b, dtype=np.float32)
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / norm)


def embedding_to_bytes(embedding: Sequence[float] | np.ndarray) -> bytes:
    """Serialize float32 face embedding vector into raw bytes for MySQL BLOB storage."""
    return np.asarray(embedding, dtype=np.float32).tobytes()


def embedding_from_bytes(
    raw: bytes | bytearray | memoryview | None,
    embedding_size: int = 512,
) -> list[float] | None:
    """Deserialize raw MySQL BLOB bytes back into a float list, validating length."""
    if not raw or len(raw) != embedding_size * 4:
        return None
    vector = np.frombuffer(raw, dtype=np.float32)
    if vector.size != embedding_size:
        return None
    return vector.astype(float).tolist()


def compute_face_score(confidence: float, area: int, sharpness: float) -> float:
    """Composite quality score combining detection confidence, area, and sharpness."""
    return (confidence ** 2) * math.pow(max(1.0, float(area)), 0.25) * max(1.0, float(sharpness))


def face_candidate_rank(
    score: float,
    sharpness: float,
    *,
    min_sharpness: float = 22.0,
    floor_sharpness: float = 15.0,
) -> tuple[int, float]:
    """Rank face candidates by sharpness tier so blurry large faces never beat sharp faces."""
    if sharpness >= min_sharpness:
        tier = 2
    elif sharpness >= floor_sharpness:
        tier = 1
    else:
        tier = 0
    return (tier, score)
