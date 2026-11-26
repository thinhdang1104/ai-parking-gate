"""AI model adapters (YOLOv8 plate/character detection and FaceNet)."""

from __future__ import annotations

from src.backend.ai.face_service import FaceService
from src.backend.ai.plate_detector import PlateDetectionResult, PlateDetector

__all__ = [
    "FaceService",
    "PlateDetectionResult",
    "PlateDetector",
]
