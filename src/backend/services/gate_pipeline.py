"""Stateless dual-camera AI scheduling, inference, and tracking helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

from src.backend.ai.face_service import FaceService
from src.backend.ai.plate_detector import PlateDetectionResult, PlateDetector
from src.backend.config import Settings
from src.backend.domain.face_math import compute_face_score, cosine_similarity, face_candidate_rank
from src.backend.domain.image_utils import crop_to_data_url, decode_base64_frame, region_sharpness
from src.backend.domain.models import FaceDetection, LatchState, SecurityAlert, VoteObservation
from src.backend.domain.voting import get_vote_result, is_vote_confirmed
from src.backend.services.camera_session import CameraUnitState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CamSchedule:
    """Per-frame scheduling flags coordinating dual-camera YOLO & MTCNN passes."""

    dual_cam_mode: bool
    run_face_idle: bool
    prioritize_face_1: bool
    prioritize_face_2: bool
    skip_plate_1: bool
    skip_plate_2: bool


@dataclass(slots=True)
class CamFrameAnalysis:
    """Structured AI detection output for one camera frame."""

    plate_present: bool = False
    readings: dict[str, str] = field(default_factory=dict)
    reading_confs: dict[str, float] = field(default_factory=dict)
    plate_crops: dict[str, tuple[float, str]] = field(default_factory=dict)
    faces: list[FaceDetection] = field(default_factory=list)
    overlay_boxes: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"plates": [], "faces": []},
    )
    skipped_plate_ocr: bool = False


def compute_cam_schedule(
    *,
    active1: bool,
    active2: bool,
    current_frame_idx: int,
    required_face_cam: int | None,
    latched_plate_cam: int | None,
    cam1_has_plate: bool,
    cam2_has_plate: bool,
    face_idle_every_n_frames: int = 2,
) -> CamSchedule:
    """Compute symmetric dual-cam OCR skipping and MTCNN prioritization schedule."""
    dual = bool(active1 and active2)
    run_idle = current_frame_idx % max(1, int(face_idle_every_n_frames)) == 0
    prio_1 = bool(dual and required_face_cam is None and cam2_has_plate and not cam1_has_plate)
    prio_2 = bool(dual and required_face_cam is None and cam1_has_plate and not cam2_has_plate)
    odd = current_frame_idx % 2 == 1

    skip_1 = bool(
        dual
        and (
            (
                required_face_cam is not None
                and (required_face_cam == 1 or (latched_plate_cam == 1 and odd))
            )
            or (prio_1 and current_frame_idx % 3 != 0)
        )
    )
    skip_2 = bool(
        dual
        and (
            (
                required_face_cam is not None
                and (required_face_cam == 2 or (latched_plate_cam == 2 and odd))
            )
            or (prio_2 and current_frame_idx % 3 != 0)
        )
    )
    return CamSchedule(
        dual_cam_mode=dual,
        run_face_idle=run_idle,
        prioritize_face_1=prio_1,
        prioritize_face_2=prio_2,
        skip_plate_1=skip_1,
        skip_plate_2=skip_2,
    )


def decode_browser_pair(
    cam1_b64: str | None,
    cam2_b64: str | None,
    *,
    active1: bool,
    active2: bool,
    max_chars: int,
) -> tuple[Any, Any, bool]:
    """Decode browser JPEG payloads and suppress duplicate frame2 when identical to frame1."""
    frame1 = decode_base64_frame(cam1_b64, max_b64_chars=max_chars) if active1 else None
    if active1 and active2 and cam1_b64 and cam2_b64 and cam2_b64 == cam1_b64:
        return frame1, None, True
    frame2 = decode_base64_frame(cam2_b64, max_b64_chars=max_chars) if active2 else None
    return frame1, frame2, False


def build_face_overlay_boxes(
    faces: Sequence[FaceDetection],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """Convert pixel face boxes into normalized `[0..1]` overlay dicts."""
    if width <= 0 or height <= 0:
        return []
    return [
        {
            "x1": round(f.box[0] / width, 4),
            "y1": round(f.box[1] / height, 4),
            "x2": round(f.box[2] / width, 4),
            "y2": round(f.box[3] / height, 4),
            "label": f"Mặt {idx} ({f.confidence:.0%})",
        }
        for idx, f in enumerate(faces, start=1)
    ]


def _analyze_single_cam(
    frame: Any,
    plate_detector: PlateDetector | None,
    face_service: FaceService | None,
    *,
    run_face_idle: bool,
    is_required_face_cam: bool,
    skip_plate_ocr: bool,
    precomputed_plate: PlateDetectionResult | None,
) -> CamFrameAnalysis:
    if precomputed_plate is not None:
        plate_res = precomputed_plate
    elif not skip_plate_ocr and plate_detector is not None and plate_detector.is_ready:
        plate_res = plate_detector.detect(frame)
    else:
        plate_res = PlateDetectionResult()

    should_run_face = (
        face_service is not None
        and (plate_res.plate_present or is_required_face_cam or run_face_idle)
    )
    faces = face_service.detect_from_bgr(frame) if should_run_face else []
    height, width = frame.shape[:2]
    return CamFrameAnalysis(
        plate_present=plate_res.plate_present,
        readings=plate_res.readings,
        reading_confs=plate_res.reading_confs,
        plate_crops=plate_res.plate_crops,
        faces=faces,
        overlay_boxes={
            "plates": plate_res.plate_boxes,
            "faces": build_face_overlay_boxes(faces, width, height),
        },
        skipped_plate_ocr=skip_plate_ocr,
    )


def _extra_face_pass(
    analysis: CamFrameAnalysis,
    frame: Any,
    face_service: FaceService,
) -> CamFrameAnalysis:
    extra_faces = face_service.detect_from_bgr(frame)
    height, width = frame.shape[:2]
    analysis.faces = extra_faces
    analysis.overlay_boxes = {
        "plates": analysis.overlay_boxes["plates"],
        "faces": build_face_overlay_boxes(extra_faces, width, height),
    }
    return analysis


def analyze_dual_frames(
    *,
    frame1: Any,
    frame2: Any,
    active1: bool,
    active2: bool,
    schedule: CamSchedule,
    required_face_cam: int | None,
    plate_detector: PlateDetector | None,
    face_service: FaceService | None,
) -> tuple[CamFrameAnalysis | None, CamFrameAnalysis | None]:
    """Run batched/single-cam YOLO plate OCR and MTCNN face detection outside locks."""
    models_ok = plate_detector is not None and plate_detector.is_ready
    need_1 = bool(active1 and frame1 is not None and not schedule.skip_plate_1 and models_ok)
    need_2 = bool(active2 and frame2 is not None and not schedule.skip_plate_2 and models_ok)

    if need_1 and need_2 and plate_detector is not None:
        pre_1, pre_2 = plate_detector.detect_batch([frame1, frame2])[:2]
    else:
        pre_1, pre_2 = None, None

    idle_1 = (schedule.run_face_idle or schedule.prioritize_face_1) and required_face_cam is None
    idle_2 = (schedule.run_face_idle or schedule.prioritize_face_2) and required_face_cam is None

    res1 = (
        _analyze_single_cam(
            frame1,
            plate_detector,
            face_service,
            run_face_idle=idle_1,
            is_required_face_cam=(required_face_cam == 1 or not schedule.dual_cam_mode),
            skip_plate_ocr=schedule.skip_plate_1,
            precomputed_plate=pre_1,
        )
        if active1 and frame1 is not None
        else None
    )
    res2 = (
        _analyze_single_cam(
            frame2,
            plate_detector,
            face_service,
            run_face_idle=idle_2,
            is_required_face_cam=(required_face_cam == 2 or not schedule.dual_cam_mode),
            skip_plate_ocr=schedule.skip_plate_2,
            precomputed_plate=pre_2,
        )
        if active2 and frame2 is not None
        else None
    )

    if schedule.dual_cam_mode and required_face_cam is None and face_service is not None:
        if (
            res1 is not None
            and res1.plate_present
            and res2 is not None
            and not res2.plate_present
            and not res2.faces
            and not idle_2
            and frame2 is not None
        ):
            res2 = _extra_face_pass(res2, frame2, face_service)
        elif (
            res2 is not None
            and res2.plate_present
            and res1 is not None
            and not res1.plate_present
            and not res1.faces
            and not idle_1
            and frame1 is not None
        ):
            res1 = _extra_face_pass(res1, frame1, face_service)

    return res1, res2


def update_cam_tracking_locked(
    *,
    cam: CameraUnitState,
    analysis: CamFrameAnalysis,
    raw_frame: Any,
    now: float,
    settings: Settings,
    plates_must_leave: set[str],
    committing_plates: set[str],
    plate_last_seen_global: dict[str, float],
) -> None:
    """Update camera crops, vote buffer, recent face buffer, and overlay state under lock."""
    for p_key, (p_sharp, p_url) in analysis.plate_crops.items():
        prev = cam.plate_crops.get(p_key)
        if prev is None or p_sharp >= prev[0]:
            if (
                p_key not in cam.plate_crops
                and len(cam.plate_crops) >= settings.max_plate_crops_per_cam
            ):
                cam.plate_crops.pop(next(iter(cam.plate_crops)), None)
            cam.plate_crops[p_key] = (p_sharp, p_url)

    while cam.observations:
        oldest = cam.observations[0]
        oldest_ts = oldest.timestamp if isinstance(oldest, VoteObservation) else oldest[0]
        if now - oldest_ts <= settings.vote_window_seconds:
            break
        cam.observations.popleft()

    if not analysis.skipped_plate_ocr:
        if analysis.plate_present:
            cam.last_plate_seen = now
        elif (
            cam.last_plate_seen is not None
            and now - cam.last_plate_seen >= settings.plate_lost_reset_seconds
        ):
            cam.observations.clear()
            cam.last_plate_seen = None

        if (
            len(analysis.readings) == 1
            and now - cam.last_sample_time >= settings.vote_sample_interval_seconds
        ):
            key, display = next(iter(analysis.readings.items()))
            plate_last_seen_global[key] = now
            if key not in plates_must_leave and key not in committing_plates:
                cam.observations.append(
                    VoteObservation(now, key, display, analysis.reading_confs.get(key, 0.0)),
                )
                cam.last_sample_time = now
        elif analysis.readings:
            for r_key in analysis.readings:
                plate_last_seen_global[r_key] = now

    while cam.recent_faces and now - cam.recent_faces[0][0] > settings.face_recent_buffer_seconds:
        cam.recent_faces.popleft()

    valid_faces = [f for f in analysis.faces if f.confidence >= settings.face_min_confidence]
    if valid_faces and raw_frame is not None:
        scored = []
        for face in valid_faces:
            sharp = region_sharpness(raw_frame, face.box, inner_ratio=0.70)
            score = compute_face_score(face.confidence, face.area, sharp)
            scored.append((score, sharp, face))

        best_score, best_sharp, best_face = max(
            scored,
            key=lambda item: face_candidate_rank(
                item[0],
                item[1],
                min_sharpness=settings.face_min_sharpness,
                floor_sharpness=settings.face_floor_sharpness,
            ),
        )
        cam.recent_faces.append(
            (now, best_score, best_face.confidence, raw_frame, best_face.box, best_sharp),
        )

    if not cam.active:
        return

    if not analysis.skipped_plate_ocr:
        cam.ambiguous_frame = len(analysis.readings) > 1
        cam.plate_in_view = analysis.plate_present
        cam.current_plates = list(analysis.readings.values())
        cam.latest_boxes = analysis.overlay_boxes
    else:
        cam.latest_boxes = {
            "plates": cam.latest_boxes.get("plates", []),
            "faces": analysis.overlay_boxes.get("faces", []),
        }
    cam.current_faces = [f.confidence for f in analysis.faces]


def apply_analysis_and_collect_locked(
    *,
    cams: dict[int, CameraUnitState],
    res1: CamFrameAnalysis | None,
    res2: CamFrameAnalysis | None,
    frame1: Any,
    frame2: Any,
    settings: Settings,
    plates_must_leave: set[str],
    committing_plates: set[str],
    recent_confirms: dict[str, float],
    plate_last_seen_global: dict[str, float],
    now: float,
    allow_new_latch: bool,
) -> dict[int, str]:
    """Update both cams from analysis, prune expired locks, and return confirmed vote candidates."""
    for cid, res, raw_f in ((1, res1, frame1), (2, res2, frame2)):
        if res is not None:
            update_cam_tracking_locked(
                cam=cams[cid],
                analysis=res,
                raw_frame=raw_f,
                now=now,
                settings=settings,
                plates_must_leave=plates_must_leave,
                committing_plates=committing_plates,
                plate_last_seen_global=plate_last_seen_global,
            )

    for pk in list(plates_must_leave):
        if now - plate_last_seen_global.get(pk, 0.0) >= settings.plate_lost_reset_seconds:
            plates_must_leave.discard(pk)
            plate_last_seen_global.pop(pk, None)

    candidates: dict[int, str] = {}
    if not allow_new_latch:
        return candidates

    for cid in (1, 2):
        cam = cams[cid]
        v_check = get_vote_result(cam.observations)
        if v_check is not None and is_vote_confirmed(
            v_check,
            cam.observations,
            min_samples=settings.vote_min_samples,
            min_share=settings.vote_min_share,
            fast_min_samples=settings.fast_vote_min_samples,
            fast_min_char_conf=settings.fast_vote_min_char_conf,
        ):
            key = v_check.plate_key
            both_directions_locked = (
                f"{key}:IN" in recent_confirms and f"{key}:OUT" in recent_confirms
            )
            if key in plates_must_leave or key in committing_plates or both_directions_locked:
                cam.observations.clear()
            else:
                candidates[cid] = v_check.plate_display
    return candidates


def build_latched_record(
    info: LatchState,
    best_face: tuple[float, float, Any, tuple[int, int, int, int], float],
    *,
    session_id: int,
    camera_index: int,
    fee_vnd: int,
    recognized_at: datetime,
) -> dict[str, Any]:
    """Construct an un-embedded parking record dict ready for `commit_latched_pair()`."""
    return {
        "_session_id": session_id,
        "_plate_key": info.plate_key,
        "_active_session": info.active_session,
        "plate_number": info.plate_number,
        "plate_image": info.plate_image,
        "direction": info.direction,
        "parking_status": "IN_PARKING" if info.direction == "IN" else "EXITED",
        "fee_amount": fee_vnd if info.direction == "IN" else 0,
        "recognized_at": recognized_at,
        "vote_count": info.vote_count,
        "sample_count": info.sample_count,
        "consensus_rate": info.consensus_rate,
        "face_detected": True,
        "face_confidence": best_face[1],
        "camera_index": camera_index,
    }


def extract_face_crop_and_embedding(
    face_service: FaceService,
    best_face: Any,
) -> tuple[str | None, list[float] | None]:
    """Crop padded face Data URL and compute 512-D embedding outside locks."""
    if best_face is None:
        return None, None
    face_image = crop_to_data_url(
        best_face[2],
        best_face[3],
        max_w=320,
        max_h=320,
        pad_ratio=0.22,
    )
    try:
        embedding = face_service.embed_face(best_face[2], best_face[3])
    except Exception as err:  # noqa: BLE001
        logger.warning("Không trích xuất được vector khuôn mặt: %s", err)
        embedding = None
    return face_image, embedding


def evaluate_out_face_match(
    record: dict[str, Any],
    *,
    plate_key: str,
    embedding: Sequence[float],
    active_session: dict[str, Any] | None,
    match_threshold: float,
) -> SecurityAlert | None:
    """Score OUT face against entry embedding; return SecurityAlert on mismatch."""
    sess = active_session or {}
    prev_emb = sess.get("embedding")
    score_val = (
        max(-1.0, min(1.0, cosine_similarity(embedding, prev_emb)))
        if prev_emb
        else None
    )
    record["entry_record_id"] = sess.get("id")
    record["face_match_score"] = score_val
    if score_val is not None and score_val >= match_threshold:
        return None

    score_pct = f"{max(0.0, float(score_val)):.0%}" if score_val is not None else "0%"
    return SecurityAlert(
        plate_key=plate_key,
        plate_number=str(record["plate_number"]),
        entry_time=str(sess.get("recognized_at") or "-"),
        match_score_pct=score_pct,
        record=record,
    )
