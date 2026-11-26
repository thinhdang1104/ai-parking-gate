/* ==========================================================================
   Two-Camera Status Sync, Latch Banner, Top-up Feedback & Security Alert UI
   ========================================================================== */

import {
  cancelLatch as apiCancelLatch,
  getCameraStatus,
  resolveAlert as apiResolveAlert,
} from "./api.js";
import { clearClientManagementCaches, getDom, state } from "./state.js";
import { showBanner } from "./utils.js";

const noop = () => {};

const cameraCallbacks = {
  renderDeviceSelects: noop,
  refreshCamControlButtons: noop,
  revealCamImagesIfReady: noop,
  stopBrowserWebRTCForCam: noop,
  hideCamStreamUI: noop,
  setPlaceholderText: noop,
  ensureBrowserFrameLoop: noop,
};

const recordsVersionListeners = [];

/**
 * Register camera UI callbacks implemented by camera.js to keep imports acyclic.
 * @param {Partial<typeof cameraCallbacks>} callbacks
 */
export function registerGateCameraCallbacks(callbacks = {}) {
  Object.keys(cameraCallbacks).forEach((key) => {
    if (typeof callbacks[key] === "function") {
      cameraCallbacks[key] = callbacks[key];
    }
  });
}

/**
 * Subscribe to records_version changes detected during camera status polling.
 * @param {(info: { recordsVersion: number, wasUninitialized: boolean }) => void} listener
 */
export function onRecordsVersionChanged(listener) {
  if (typeof listener === "function" && !recordsVersionListeners.includes(listener)) {
    recordsVersionListeners.push(listener);
  }
}

export function getSelectedDeviceLabel(camId) {
  if (state.activeCamDeviceLabels[camId]) {
    return state.activeCamDeviceLabels[camId];
  }
  const devId = state.selectedCamDeviceIds[camId];
  if (!devId) return "";
  const found = state.browserCamDevices.find((d) => d.deviceId === devId);
  return found ? found.label : "";
}

export function stopCommitStatusPoll() {
  if (state.commitPollTimer) {
    clearInterval(state.commitPollTimer);
    state.commitPollTimer = null;
  }
}

export function ensureCommitStatusPoll() {
  if (state.commitPollTimer) return;
  state.commitPollTimer = setInterval(async () => {
    if (state.commitPollInFlight || state.isStartingCamera) return;
    state.commitPollInFlight = true;
    try {
      await pollCameraStatusOnce();
    } finally {
      state.commitPollInFlight = false;
    }
  }, 180);
}

export function updateIdleBadgeForCam(camId) {
  if (state.camStreaming[camId]) return;
  const dom = getDom();
  const pillEl = camId === 1 ? dom.cam1VotePill : dom.cam2VotePill;
  if (!pillEl) return;
  const lbl = getSelectedDeviceLabel(camId);
  pillEl.className = "pill mono-num num";
  pillEl.textContent = lbl ? `${lbl} · Ngắt` : "Chưa chọn thiết bị · Ngắt";
}

export function updateSingleCamReadout(
  camId,
  camData,
  votePillEl,
  plateValueEl,
  faceValueEl,
  running
) {
  const plates = (camData && camData.current_plates) || [];
  const faces = (camData && camData.current_faces) || [];

  if (plateValueEl) {
    if (running && plates.length > 0) {
      plateValueEl.textContent = `Biển: ${plates.join(", ")}`;
      plateValueEl.classList.remove("hidden");
    } else {
      plateValueEl.classList.add("hidden");
    }
  }

  if (faceValueEl) {
    if (running && faces.length > 0) {
      const bestConf = Math.round(Math.max(...faces) * 100);
      faceValueEl.textContent = `Mặt: ${bestConf}%`;
      faceValueEl.classList.remove("hidden");
    } else {
      faceValueEl.classList.add("hidden");
    }
  }

  if (votePillEl) {
    const devLabel =
      state.activeCamDeviceLabels[camId] ||
      getSelectedDeviceLabel(camId) ||
      "Chưa chọn thiết bị";
    if (!running) {
      votePillEl.className = "pill mono-num num";
      votePillEl.textContent = `${devLabel} · Ngắt`;
    } else if (camData && camData.vote) {
      const pct = Math.round(camData.vote.vote_share * 100);
      votePillEl.className = "pill warn mono-num num";
      votePillEl.textContent = `${camData.vote.candidate} (${camData.vote.vote_count}/${camData.vote.sample_count} · ${pct}%)`;
    } else if (!state.modelsReady) {
      votePillEl.className = "pill warn mono-num num";
      votePillEl.textContent = `${devLabel} · Đang tải mô hình AI...`;
    } else {
      votePillEl.className = "pill mono-num num";
      votePillEl.textContent = `${devLabel} · Đang quét`;
    }
  }
}

export function syncSingleCamUI(camId, camState) {
  const slot = camId - 1;
  const ownsBrowserStream = Boolean(
    state.browserVideos[slot] && state.browserStreams[slot]
  );

  if (ownsBrowserStream) {
    if (!state.camStreaming[camId]) {
      state.camStreaming[camId] = true;
      cameraCallbacks.revealCamImagesIfReady();
    }
  } else {
    if (state.camStreaming[camId] && !state.camBusy[camId]) {
      cameraCallbacks.stopBrowserWebRTCForCam(camId);
      cameraCallbacks.hideCamStreamUI(camId);
    }
    if (
      camState &&
      camState.active &&
      camState.mode === "browser" &&
      !ownsBrowserStream &&
      !state.camBusy[camId]
    ) {
      cameraCallbacks.setPlaceholderText(
        camId,
        `Cam ${camId} đang mở ở phiên/tab khác — Chọn thiết bị và bấm "Kết nối" để phát từ tab này`
      );
    }
  }
  return ownsBrowserStream;
}

export async function applyCameraStatus(camStatus) {
  if (!camStatus || state.isStartingCamera) return;
  const dom = getDom();

  if (
    typeof camStatus.face_match_threshold === "number" &&
    camStatus.face_match_threshold > 0
  ) {
    state.faceMatchThreshold = camStatus.face_match_threshold;
  }
  if (typeof camStatus.models_ready === "boolean") {
    state.modelsReady = camStatus.models_ready;
  }

  const active1 = syncSingleCamUI(1, camStatus.cam1);
  const active2 = syncSingleCamUI(2, camStatus.cam2);

  cameraCallbacks.renderDeviceSelects();
  cameraCallbacks.refreshCamControlButtons();

  if (camStatus.error) {
    state.lastBackendError = camStatus.error;
    showBanner(dom.cameraAlertBox, "error", camStatus.error);
  } else if (state.lastBackendError) {
    if (
      dom.cameraAlertBox &&
      dom.cameraAlertBox.textContent === state.lastBackendError
    ) {
      showBanner(dom.cameraAlertBox, "", "");
    }
    state.lastBackendError = "";
  }

  if (
    camStatus.gate_feedback &&
    camStatus.gate_feedback.message &&
    camStatus.gate_feedback.seq !== state.lastFeedbackSeq
  ) {
    state.lastFeedbackSeq = camStatus.gate_feedback.seq;
    showBanner(
      dom.gateTopupBox || dom.cameraAlertBox,
      camStatus.gate_feedback.type || "success",
      camStatus.gate_feedback.message,
      2500
    );
  }

  updateSingleCamReadout(
    1,
    camStatus.cam1,
    dom.cam1VotePill,
    dom.cam1PlateValue,
    dom.cam1FaceValue,
    active1
  );
  updateSingleCamReadout(
    2,
    camStatus.cam2,
    dom.cam2VotePill,
    dom.cam2PlateValue,
    dom.cam2FaceValue,
    active2
  );

  // Two-Phase Latch UI (hiển thị gọn trong header-topup-slot, không làm nhảy khung Camera)
  if (camStatus.latched && !camStatus.security_alert) {
    if (dom.gateTopupBox) {
      showBanner(dom.gateTopupBox, "", "");
    }
    if (dom.latchStatusBox) dom.latchStatusBox.classList.remove("hidden");
    const isIn = camStatus.latched.direction === "IN";
    if (dom.latchDirectionBadge) {
      dom.latchDirectionBadge.className = isIn ? "pill pos" : "pill warn";
      dom.latchDirectionBadge.textContent = isIn
        ? "LƯU HỜ · ĐI VÀO"
        : "LƯU HỜ · ĐI RA";
    }
    if (dom.latchPlateText) {
      dom.latchPlateText.textContent = camStatus.latched.plate_number;
    }
    if (dom.latchStepText) {
      dom.latchStepText.textContent = camStatus.latched.sampling_face
        ? `Cam ${camStatus.latched.plate_cam} đã chốt biển — Đang chọn mặt nét nhất ở Cam ${camStatus.latched.required_face_cam}...`
        : `Cam ${camStatus.latched.plate_cam} đã chốt biển — Chờ khuôn mặt ở Cam ${camStatus.latched.required_face_cam} (${camStatus.latched.remaining_seconds}s)`;
    }
  } else if (dom.latchStatusBox) {
    dom.latchStatusBox.classList.add("hidden");
  }

  // Security Alert UI (Face mismatch on exit — Top-up in blue box area)
  if (camStatus.security_alert) {
    state.hasActiveSecurityAlert = true;
    state.activeSecurityAlertPlate = camStatus.security_alert.plate_number || "";
    if (!state.resolvingAlertInFlight) {
      if (dom.gateTopupBox) {
        showBanner(dom.gateTopupBox, "", "");
      }
      if (dom.securityAlertBox) {
        dom.securityAlertBox.classList.remove("hidden");
      }
      if (dom.alertScorePill) {
        dom.alertScorePill.textContent = `Độ khớp: ${camStatus.security_alert.match_score_pct}`;
      }
      if (dom.alertDetailText) {
        const threshPct = Math.round(state.faceMatchThreshold * 100);
        dom.alertDetailText.textContent =
          `Xe ${camStatus.security_alert.plate_number} (gửi lúc ${camStatus.security_alert.entry_time}) ` +
          `có khuôn mặt người lấy xe LỆCH so với lúc gửi xe vào bãi (Cosine ${camStatus.security_alert.match_score_pct} < ${threshPct}%).`;
      }
    }
  } else {
    state.hasActiveSecurityAlert = false;
    state.activeSecurityAlertPlate = "";
    if (dom.securityAlertBox) {
      dom.securityAlertBox.classList.add("hidden");
    }
  }

  if (dom.voteAmbiguousWarning) {
    dom.voteAmbiguousWarning.classList.toggle(
      "hidden",
      !camStatus.ambiguous_frame
    );
  }

  if (camStatus.committing) {
    ensureCommitStatusPoll();
  } else {
    stopCommitStatusPoll();
  }

  if (
    typeof camStatus.records_version === "number" &&
    camStatus.records_version !== state.lastRecordsVersion
  ) {
    const wasUninitialized = state.lastRecordsVersion < 0;
    state.lastRecordsVersion = camStatus.records_version;
    clearClientManagementCaches();
    recordsVersionListeners.forEach((listener) => {
      try {
        listener({
          recordsVersion: camStatus.records_version,
          wasUninitialized,
        });
      } catch (_) {}
    });
  }
}

export async function pollCameraStatusOnce() {
  if (state.isStartingCamera) return;
  try {
    const camStatus = await getCameraStatus();
    await applyCameraStatus(camStatus);
  } catch (_) {
    // Bỏ qua lỗi mạng tạm thời
  }
}

export async function cancelLatch() {
  const dom = getDom();
  if (dom.latchStatusBox) dom.latchStatusBox.classList.add("hidden");
  try {
    const data = await apiCancelLatch();
    if (data && data.camera_status) {
      await applyCameraStatus(data.camera_status);
      return;
    }
  } catch (_) {}
  await pollCameraStatusOnce();
}

export async function resolveAlert(action) {
  if (state.resolvingAlertInFlight) return;
  const dom = getDom();
  state.resolvingAlertInFlight = true;
  if (dom.btnApproveExit) dom.btnApproveExit.disabled = true;
  if (dom.btnRejectExit) dom.btnRejectExit.disabled = true;

  // Phản hồi giao diện tức thì (0 ms) ngay khi bấm nút; tự khôi phục hộp cảnh báo nếu ghi CSDL lỗi
  const plateText = state.activeSecurityAlertPlate || "";
  if (dom.securityAlertBox) {
    dom.securityAlertBox.classList.add("hidden");
  }
  const optimisticMsg =
    action === "approve"
      ? plateText
        ? `XE ${plateText} RA BÃI ĐƯỢC DUYỆT`
        : "ĐÃ DUYỆT CHO XE RA BÃI"
      : plateText
      ? `XE ${plateText} RA BÃI BỊ TỪ CHỐI`
      : "ĐÃ TỪ CHỐI CHO XE RA BÃI";
  const optimisticType = action === "approve" ? "warn" : "error";
  showBanner(
    dom.gateTopupBox || dom.cameraAlertBox,
    optimisticType,
    optimisticMsg,
    2500
  );

  try {
    const data = await apiResolveAlert(action);
    state.resolvingAlertInFlight = false;

    if (data && data.status === "db_error") {
      state.hasActiveSecurityAlert = true;
      if (dom.gateTopupBox) {
        showBanner(dom.gateTopupBox, "", "");
      }
      if (dom.securityAlertBox) {
        dom.securityAlertBox.classList.remove("hidden");
      }
      if (data.message) {
        showBanner(dom.cameraAlertBox, "error", data.message);
      }
      if (data.camera_status) {
        await applyCameraStatus(data.camera_status);
      }
      return;
    }

    state.hasActiveSecurityAlert = false;
    state.activeSecurityAlertPlate = "";
    if (
      data &&
      data.camera_status &&
      data.camera_status.gate_feedback &&
      typeof data.camera_status.gate_feedback.seq === "number"
    ) {
      state.lastFeedbackSeq = data.camera_status.gate_feedback.seq;
    }
    if (data && data.message) {
      showBanner(
        dom.gateTopupBox || dom.cameraAlertBox,
        data.type || optimisticType,
        data.message,
        2500
      );
    }
    if (data && data.camera_status) {
      await applyCameraStatus(data.camera_status);
    } else {
      pollCameraStatusOnce();
    }
    cameraCallbacks.ensureBrowserFrameLoop();
  } catch (_) {
    state.resolvingAlertInFlight = false;
    state.hasActiveSecurityAlert = true;
    if (dom.gateTopupBox) {
      showBanner(dom.gateTopupBox, "", "");
    }
    if (dom.securityAlertBox) {
      dom.securityAlertBox.classList.remove("hidden");
    }
    showBanner(
      dom.cameraAlertBox,
      "error",
      "Không gửi được yêu cầu duyệt cảnh báo, vui lòng thử lại."
    );
  } finally {
    state.resolvingAlertInFlight = false;
    if (dom.btnApproveExit) dom.btnApproveExit.disabled = false;
    if (dom.btnRejectExit) dom.btnRejectExit.disabled = false;
  }
}
