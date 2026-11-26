---
name: datn2-cv-eval
description: >-
  Deterministic computer vision smoke-evaluation protocol for DATN2
  (YOLOv8 plate/char OCR + FaceNet 512-D verification). Activate before
  changing AI thresholds or running Phase 6 local CV validation.
---

# DATN2 Computer Vision Smoke Evaluation

Verify real `weights/plate_best.pt`, `weights/chars_best.pt`, and `InceptionResnetV1(vggface2)` behavior rigorously without compromising metric integrity.

## 1. Locked Model & Threshold Baseline (`src/backend/config.py`)
- Plate detector: `CONF_PLATE = 0.40`, `PLATE_IMGSZ = 512`
- Char OCR: `CONF_CHAR = 0.35`, `CHAR_IMGSZ = 320`, `CHAR_IOU_DEDUP_THRESHOLD = 0.55`
- Consensus voting: `VOTE_MIN_SAMPLES = 3`, `VOTE_MIN_SHARE = 0.70`, `FAST_VOTE_MIN_SAMPLES = 2`, `FAST_VOTE_MIN_CHAR_CONF = 0.75`
- Face quality & match: `FACE_MIN_CONFIDENCE = 0.85`, `FACE_FLOOR_SHARPNESS = 15.0`, `FACE_MIN_SHARPNESS = 22.0` (70%-core Laplacian), `FACE_MATCH_THRESHOLD = 0.65`

## 2. Smoke Eval Rules (Pair with `eval-integrity`)
1. **Separate Sample Sets**: Never evaluate threshold changes using synthetic unit-test mocks; test against representative plate crops (1-line & 2-line) and paired same-person / different-person face crops.
2. **Required Smoke Assertions**:
   - Known valid VN plates normalize cleanly to `(plate_key, plate_display)` with expected majority consensus.
   - Blurry faces (`sharpness < 15.0`) never outrank sharp faces (`sharpness >= 22.0`).
   - Same-person pair yields cosine similarity `>= 0.65`; different-person pair yields `< 0.65` (triggers Security Alert).
3. **Report Exact Scope**: Always state exact sample count, CPU/GPU device (`FORCE_CPU`), and failure cases when reporting CV smoke results.
