"""Pure domain dataclasses for DATN2 parking gate & record workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CharDetection:
    """Single detected character inside a cropped license plate region."""

    cx: float
    cy: float
    label: str
    confidence: float
    box: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class FaceDetection:
    """Detected face bounding box and MTCNN confidence."""

    box: tuple[int, int, int, int]
    confidence: float

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.box
        return max(0, x2 - x1) * max(0, y2 - y1)


@dataclass(frozen=True, slots=True)
class PlateBox:
    """Normalized [0..1] bounding box for frontend canvas overlay."""

    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    valid: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "label": self.label,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class VoteObservation:
    """Single timestamped plate reading added to a camera's vote window."""

    timestamp: float
    plate_key: str
    plate_display: str
    char_confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class VoteResult:
    """Aggregated consensus result for a camera's observation window."""

    plate_key: str
    plate_display: str
    vote_count: int
    vote_share: float
    sample_count: int


@dataclass(slots=True)
class LatchState:
    """Active Two-Phase Latch waiting for a sharp face on the target camera."""

    direction: str
    plate_key: str
    plate_number: str
    plate_image: str | None
    vote_count: int
    sample_count: int
    consensus_rate: float
    plate_cam: int
    required_face_cam: int
    latched_at: float
    active_session: dict[str, Any] | None = None

    def to_status_dict(self, *, remaining_seconds: int, sampling_face: bool) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "plate_number": self.plate_number,
            "plate_cam": self.plate_cam,
            "required_face_cam": self.required_face_cam,
            "remaining_seconds": remaining_seconds,
            "sampling_face": sampling_face,
        }


@dataclass(slots=True)
class SecurityAlert:
    """Top-up security alert raised when an OUT face fails FaceNet match."""

    plate_key: str
    plate_number: str
    entry_time: str
    match_score_pct: str
    record: dict[str, Any] | None = None

    def to_status_dict(self) -> dict[str, str]:
        return {
            "plate_number": self.plate_number,
            "entry_time": self.entry_time,
            "match_score_pct": self.match_score_pct,
        }


@dataclass(slots=True)
class ParkingRecord:
    """19-field domain entity matching `schemas/mysql_schema.sql`."""

    id: int | None = None
    plate_number: str = ""
    plate_key: str | None = None
    direction: str = "IN"
    parking_status: str = "IN_PARKING"
    entry_record_id: int | None = None
    fee_amount: int = 2000
    recognized_at: datetime | str | None = None
    vote_count: int = 0
    sample_count: int = 0
    consensus_rate: float = 0.0
    face_detected: bool = False
    face_confidence: float | None = None
    face_embedding: list[float] | bytes | None = None
    face_match_score: float | None = None
    plate_image: str | None = None
    face_image: str | None = None
    camera_index: int = 1
    created_at: datetime | str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
