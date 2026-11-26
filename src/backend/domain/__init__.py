"""Pure domain layer for DATN2 (no framework, DB, or ML runtime dependencies)."""

from src.backend.domain.face_math import (
    compute_face_score,
    cosine_similarity,
    embedding_from_bytes,
    embedding_to_bytes,
    face_candidate_rank,
)
from src.backend.domain.image_utils import (
    crop_to_data_url,
    decode_base64_frame,
    region_sharpness,
    save_snapshot_to_disk,
)
from src.backend.domain.models import (
    CharDetection,
    FaceDetection,
    LatchState,
    ParkingRecord,
    PlateBox,
    SecurityAlert,
    VoteObservation,
    VoteResult,
)
from src.backend.domain.plate_assembly import (
    assemble_plate_text,
    box_iou,
    deduplicate_chars,
)
from src.backend.domain.plate_normalizer import (
    PLATE_NUMBER_RE,
    PLATE_SERIES_RE,
    TO_DIGIT,
    TO_LETTER,
    clean_plate_key,
    normalize_plate,
)
from src.backend.domain.voting import get_vote_result, is_vote_confirmed

__all__ = [
    "CharDetection",
    "FaceDetection",
    "LatchState",
    "PLATE_NUMBER_RE",
    "PLATE_SERIES_RE",
    "ParkingRecord",
    "PlateBox",
    "SecurityAlert",
    "TO_DIGIT",
    "TO_LETTER",
    "VoteObservation",
    "VoteResult",
    "assemble_plate_text",
    "box_iou",
    "clean_plate_key",
    "compute_face_score",
    "cosine_similarity",
    "crop_to_data_url",
    "decode_base64_frame",
    "deduplicate_chars",
    "embedding_from_bytes",
    "embedding_to_bytes",
    "face_candidate_rank",
    "get_vote_result",
    "is_vote_confirmed",
    "normalize_plate",
    "region_sharpness",
    "save_snapshot_to_disk",
]
