"""MTCNN face detection and FaceNet (InceptionResnetV1) 512-D embedding adapter."""

from __future__ import annotations

from contextlib import nullcontext
import logging
import os
from typing import Any

import cv2
import numpy as np
from PIL import Image
import torch

from src.backend.config import Settings, load_settings
from src.backend.domain.models import FaceDetection

try:
    from facenet_pytorch import InceptionResnetV1, MTCNN
except ImportError:  # pragma: no cover - handled cleanly at load time
    InceptionResnetV1 = None
    MTCNN = None

logger = logging.getLogger(__name__)


class FaceService:
    """Biometric face detector and 512-D L2-normalized embedding service."""

    def __init__(
        self,
        settings: Settings | None = None,
        detector: Any = None,
        encoder: Any = None,
        load_models: bool = True,
    ) -> None:
        self.settings: Settings = settings if settings is not None else load_settings()
        self.detector: Any = detector
        self.encoder: Any = encoder
        self.encoder_error: str | None = None

        if self.settings.force_cpu or os.getenv("SPACE_ID"):
            self.device = "cpu"
        else:
            self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

        if load_models and (self.detector is None or self.encoder is None):
            if MTCNN is None or InceptionResnetV1 is None:
                raise RuntimeError(
                    "Chưa cài đặt thư viện 'facenet-pytorch'. Vui lòng chạy lệnh:\n"
                    "  pip install --no-deps facenet-pytorch==2.6.0"
                )
            if self.detector is None:
                min_face = 24 if self.device == "cpu" else 40
                self.detector = MTCNN(
                    keep_all=True,
                    device=self.device,
                    min_face_size=min_face,
                )
            if self.encoder is None:
                try:
                    self.encoder = (
                        InceptionResnetV1(pretrained="vggface2").eval().to(self.device)
                    )
                except Exception as err:  # noqa: BLE001 - degrade gracefully without encoder
                    self.encoder = None
                    self.encoder_error = str(err)
                    logger.warning(
                        "Không tải được FaceNet (InceptionResnetV1). "
                        "Hệ thống chỉ phát hiện khuôn mặt, không đối chiếu được: %s",
                        err,
                    )

    @property
    def can_embed(self) -> bool:
        """Return True when the FaceNet encoder is ready to compute embeddings."""
        return self.encoder is not None

    def detect_from_bgr(self, frame: np.ndarray) -> list[FaceDetection]:
        """Detect faces on a BGR frame, sorted by confidence descending."""
        if self.detector is None or frame is None:
            return []
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            return []

        scale = 1.0
        if self.device == "cpu" and width > 360:
            scale = 360.0 / float(width)
            small_w = 360
            small_h = max(60, int(round(height * scale)))
            small_bgr = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
            rgb_frame = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2RGB)
        else:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        image = Image.fromarray(rgb_frame)
        infer_ctx = torch.inference_mode() if hasattr(torch, "inference_mode") else nullcontext()
        with infer_ctx:
            boxes, probabilities = self.detector.detect(image)
        if boxes is None or probabilities is None:
            return []

        inv_scale = 1.0 / scale
        results: list[FaceDetection] = []
        for raw_box, probability in zip(boxes, probabilities, strict=False):
            if probability is None or np.isnan(probability):
                continue
            x1, y1, x2, y2 = [int(round(float(val) * inv_scale)) for val in raw_box]
            x1, x2 = max(0, x1), min(width, x2)
            y1, y2 = max(0, y1), min(height, y2)
            if x1 >= x2 or y1 >= y2:
                continue
            results.append(
                FaceDetection(
                    box=(x1, y1, x2, y2),
                    confidence=round(float(probability), 3),
                )
            )

        results.sort(key=lambda face: face.confidence, reverse=True)
        return results

    def embed_face(
        self,
        frame: np.ndarray,
        box: tuple[int, int, int, int],
    ) -> list[float] | None:
        """Extract an L2-normalized 512-D embedding vector for a detected face box."""
        if self.encoder is None or frame is None:
            return None

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb_frame)
        face_tensor = None
        if self.detector is not None:
            try:
                face_tensor = self.detector.extract(
                    image,
                    np.asarray([box], dtype=np.float32),
                    save_path=None,
                )
            except Exception:
                face_tensor = None

        if face_tensor is None:
            h, w = rgb_frame.shape[:2]
            x1, y1, x2, y2 = [int(round(v)) for v in box]
            x1, x2 = max(0, x1), min(w, x2)
            y1, y2 = max(0, y1), min(h, y2)
            if x1 >= x2 or y1 >= y2:
                return None
            crop = cv2.resize(
                rgb_frame[y1:y2, x1:x2],
                (160, 160),
                interpolation=cv2.INTER_AREA,
            )
            face_tensor = (
                torch.from_numpy(crop).permute(2, 0, 1).float().unsqueeze(0) - 127.5
            ) / 128.0
        elif face_tensor.dim() == 3:
            face_tensor = face_tensor.unsqueeze(0)

        with torch.inference_mode():
            vector = self.encoder(face_tensor.to(self.device))[0]
        vector = torch.nn.functional.normalize(vector, p=2, dim=0).cpu().numpy()
        return vector.astype(float).tolist()
