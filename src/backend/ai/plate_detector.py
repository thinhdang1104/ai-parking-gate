"""YOLOv8 two-stage license plate detector and character OCR adapter."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import os
from typing import Any

from src.backend.config import Settings, load_settings
from src.backend.domain.image_utils import crop_to_data_url, region_sharpness
from src.backend.domain.plate_assembly import assemble_plate_text, deduplicate_chars
from src.backend.domain.plate_normalizer import normalize_plate


@dataclass(slots=True)
class PlateDetectionResult:
    """Structured result of running plate + character YOLO inference on one frame."""

    plate_present: bool = False
    readings: dict[str, str] = field(default_factory=dict)
    plate_boxes: list[dict[str, Any]] = field(default_factory=list)
    plate_crops: dict[str, tuple[float, str]] = field(default_factory=dict)
    reading_confs: dict[str, float] = field(default_factory=dict)


class PlateDetector:
    """Two-stage YOLOv8 detector for Vietnamese license plates and characters."""

    def __init__(
        self,
        settings: Settings | None = None,
        plate_model: Any = None,
        char_model: Any = None,
    ) -> None:
        self.settings: Settings = settings if settings is not None else load_settings()
        self.plate_model: Any = plate_model
        self.char_model: Any = char_model

    @property
    def is_ready(self) -> bool:
        """Return True when both plate and character YOLO models are loaded."""
        return self.plate_model is not None and self.char_model is not None

    def device_kwargs(self) -> dict[str, str]:
        """Return explicit CPU device override when configured or running in Spaces."""
        if self.settings.force_cpu or os.getenv("SPACE_ID"):
            return {"device": "cpu"}
        return {}

    def load(self) -> None:
        """Validate weight files and load YOLOv8 plate and character models."""
        if not self.settings.plate_model_path.is_file():
            raise RuntimeError(
                f"Không tìm thấy model biển số: {self.settings.plate_model_path}"
            )
        if not self.settings.char_model_path.is_file():
            raise RuntimeError(
                f"Không tìm thấy model ký tự: {self.settings.char_model_path}"
            )
        from ultralytics import YOLO

        self.plate_model = YOLO(str(self.settings.plate_model_path))
        self.char_model = YOLO(str(self.settings.char_model_path))

    def extract_from_result(self, frame: Any, result: Any) -> PlateDetectionResult:
        """Extract normalized readings, overlay boxes, and sharpest crops from one YOLO result."""
        if self.char_model is None:
            raise RuntimeError("Character model is not loaded")
        if frame is None or result is None or getattr(result, "boxes", None) is None:
            return PlateDetectionResult()

        names = self.char_model.names
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            return PlateDetectionResult()

        device_kw = self.device_kwargs()
        plate_present = False
        readings: dict[str, str] = {}
        reading_confs: dict[str, float] = {}
        plate_boxes: list[dict[str, Any]] = []
        plate_crops: dict[str, tuple[float, str]] = {}

        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            x1, x2 = max(0, x1), min(width, x2)
            y1, y2 = max(0, y1), min(height, y2)
            if x1 >= x2 or y1 >= y2:
                continue

            plate_present = True
            crop = frame[y1:y2, x1:x2]
            char_res = self.char_model.predict(
                crop,
                conf=self.settings.conf_char,
                iou=0.5,
                imgsz=self.settings.char_imgsz,
                verbose=False,
                **device_kw,
            )[0]

            raw_chars: list[tuple[float, float, str, float, tuple[int, int, int, int]]] = []
            for char_box in getattr(char_res, "boxes", ()):
                cx1, cy1, cx2, cy2 = map(int, char_box.xyxy[0])
                raw_chars.append(
                    (
                        (cx1 + cx2) / 2.0,
                        (cy1 + cy2) / 2.0,
                        names[int(char_box.cls[0])],
                        float(char_box.conf[0]),
                        (cx1, cy1, cx2, cy2),
                    )
                )

            chars = deduplicate_chars(
                raw_chars, iou_threshold=self.settings.char_iou_dedup_threshold
            )
            raw_text = assemble_plate_text(chars) if chars else ""
            avg_char_conf = (
                round(sum(item[3] for item in chars) / len(chars), 4) if chars else 0.0
            )

            normalized = normalize_plate(raw_text)
            label = normalized[1] if normalized else (raw_text or "?")
            if normalized:
                p_key, p_disp = normalized
                readings[p_key] = p_disp
                if avg_char_conf > reading_confs.get(p_key, 0.0):
                    reading_confs[p_key] = avg_char_conf

                plate_sharpness = region_sharpness(frame, (x1, y1, x2, y2))
                crop_url = crop_to_data_url(
                    frame,
                    (x1, y1, x2, y2),
                    max_w=360,
                    max_h=180,
                    pad_ratio=0.06,
                )
                if crop_url:
                    prev = plate_crops.get(p_key)
                    if prev is None or plate_sharpness >= prev[0]:
                        plate_crops[p_key] = (plate_sharpness, crop_url)

            plate_boxes.append(
                {
                    "x1": round(x1 / width, 4),
                    "y1": round(y1 / height, 4),
                    "x2": round(x2 / width, 4),
                    "y2": round(y2 / height, 4),
                    "label": label,
                    "valid": bool(normalized),
                }
            )

        return PlateDetectionResult(
            plate_present=plate_present,
            readings=readings,
            plate_boxes=plate_boxes,
            plate_crops=plate_crops,
            reading_confs=reading_confs,
        )

    def detect(self, frame: Any) -> PlateDetectionResult:
        """Run two-stage license plate detection and OCR on a single BGR frame."""
        if not self.is_ready:
            raise RuntimeError("PlateDetector models are not loaded")
        result = self.plate_model.predict(
            frame,
            conf=self.settings.conf_plate,
            iou=0.5,
            imgsz=self.settings.plate_imgsz,
            verbose=False,
            **self.device_kwargs(),
        )[0]
        return self.extract_from_result(frame, result)

    def detect_batch(self, frames: Sequence[Any]) -> list[PlateDetectionResult]:
        """Run batched plate detection on multiple frames in one YOLO predict call."""
        frame_list = list(frames)
        if not frame_list:
            return []
        if not self.is_ready:
            raise RuntimeError("PlateDetector models are not loaded")
        results = self.plate_model.predict(
            frame_list,
            conf=self.settings.conf_plate,
            iou=0.5,
            imgsz=self.settings.plate_imgsz,
            verbose=False,
            **self.device_kwargs(),
        )
        return [
            self.extract_from_result(frame, res)
            for frame, res in zip(frame_list, results, strict=False)
        ]
