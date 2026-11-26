/* ==========================================================================
   WebRTC Camera Discovery, Device Locking, Stream Lifecycle & Frame Loop
   ========================================================================== */

import {
  sendBrowserFrame,
  startCamera,
  stopAllCameras,
  stopCamera,
} from "./api.js";
import {
  applyCameraStatus,
  getSelectedDeviceLabel,
  pollCameraStatusOnce,
  stopCommitStatusPoll,
  updateIdleBadgeForCam,
} from "./gate_ui.js";
import { clearOverlayCanvas, drawOverlayBoxes } from "./overlay.js";
import { getDom, state } from "./state.js";
import { escapeHtml, showBanner } from "./utils.js";

export function normalizeVideoInputDevices(rawDevices) {
  const videoInputs = (rawDevices || []).filter(
    (d) =>
      d && d.kind === "videoinput" && String(d.deviceId || "").trim() !== ""
  );
  const baseLabels = videoInputs.map((d, idx) => {
    const cleaned = String(d.label || "").trim();
    return cleaned || `Camera ${idx + 1}`;
  });
  const counts = new Map();
  baseLabels.forEach((lbl) => {
    counts.set(lbl, (counts.get(lbl) || 0) + 1);
  });
  const seen = new Map();
  return videoInputs.map((d, idx) => {
    const base = baseLabels[idx];
    let finalLabel = base;
    if ((counts.get(base) || 0) > 1) {
      const nextIdx = (seen.get(base) || 0) + 1;
      seen.set(base, nextIdx);
      finalLabel = `${base} (${nextIdx})`;
    }
    return {
      deviceId: String(d.deviceId),
      label: finalLabel,
    };
  });
}

export function formatMediaError(err, deviceLabel = "") {
  if (
    !window.isSecureContext ||
    !navigator.mediaDevices ||
    typeof navigator.mediaDevices.getUserMedia !== "function" ||
    typeof navigator.mediaDevices.enumerateDevices !== "function"
  ) {
    return "Trình duyệt không hỗ trợ WebRTC Camera hoặc trang không ở ngữ cảnh bảo mật (HTTPS / localhost).";
  }
  const name = (err && err.name) || "";
  if (
    name === "NotAllowedError" ||
    name === "PermissionDeniedError" ||
    name === "SecurityError"
  ) {
    const inIframe = window.self !== window.top;
    const directOrigin =
      (window.location && window.location.origin) ||
      (window.location && window.location.href) ||
      "trang trực tiếp";
    return inIframe
      ? `Trình duyệt chặn quyền Camera trong khung nhúng. Vui lòng cấp quyền Camera trên thanh địa chỉ hoặc mở trực tiếp ${directOrigin}`
      : "Bạn đã từ chối cấp quyền truy cập Camera. Vui lòng cho phép quyền Camera trên thanh địa chỉ trình duyệt rồi thử lại.";
  }
  if (
    name === "NotFoundError" ||
    name === "DevicesNotFoundError" ||
    name === "OverconstrainedError"
  ) {
    return deviceLabel
      ? `Thiết bị "${deviceLabel}" không còn tồn tại hoặc không đáp ứng kết nối. Vui lòng chọn thiết bị khác.`
      : "Không tìm thấy thiết bị Camera nào được kết nối với máy của bạn.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return deviceLabel
      ? `Thiết bị "${deviceLabel}" đang bận hoặc không mở được (có thể đang được dùng bởi ứng dụng khác).`
      : "Thiết bị Camera đang bận hoặc không mở được.";
  }
  return (err && err.message) || "Không thể truy cập thiết bị Camera.";
}

export function setPlaceholderText(camId, text) {
  const dom = getDom();
  const phEl = camId === 1 ? dom.cam1Placeholder : dom.cam2Placeholder;
  if (!phEl) return;
  const span = phEl.querySelector(".standby-text");
  if (span) {
    span.textContent = text;
  }
}

export function renderDeviceSelects() {
  const dom = getDom();
  [1, 2].forEach((camId) => {
    const selectEl = camId === 1 ? dom.cam1DeviceSelect : dom.cam2DeviceSelect;
    if (!selectEl) return;
    const otherId = 3 - camId;
    const otherReservedId = state.activeCamDeviceIds[otherId] || "";
    const currentVal = state.selectedCamDeviceIds[camId] || "";
    const isDisabled = Boolean(
      state.camStreaming[camId] ||
        state.camBusy[camId] ||
        state.browserCamDevices.length === 0
    );
    const devListSig = state.browserCamDevices
      .map((d) => `${d.deviceId}:${d.label}`)
      .join("|");
    const nextSig = `${isDisabled ? 1 : 0}::${currentVal}::${otherReservedId}::${devListSig}`;

    if (state.lastDeviceSelectSig[camId] === nextSig) {
      if (selectEl.value !== currentVal) {
        selectEl.value = currentVal;
      }
      if (selectEl.disabled !== isDisabled) {
        selectEl.disabled = isDisabled;
      }
      return;
    }
    state.lastDeviceSelectSig[camId] = nextSig;

    const optionsHtml = [];
    if (state.browserCamDevices.length === 0) {
      optionsHtml.push(`<option value="">-- Bấm "Tìm camera" --</option>`);
    } else {
      optionsHtml.push(`<option value="">-- Chọn thiết bị camera --</option>`);
      state.browserCamDevices.forEach((dev) => {
        const usedByOther = Boolean(
          otherReservedId && otherReservedId === dev.deviceId
        );
        const suffix = usedByOther ? ` (Đang dùng ở Cam ${otherId})` : "";
        const selectedAttr = currentVal === dev.deviceId ? " selected" : "";
        const disabledAttr = usedByOther ? " disabled" : "";
        optionsHtml.push(
          `<option value="${escapeHtml(dev.deviceId)}"${selectedAttr}${disabledAttr}>${escapeHtml(dev.label + suffix)}</option>`
        );
      });
    }

    selectEl.innerHTML = optionsHtml.join("");
    selectEl.value = currentVal;
    selectEl.disabled = isDisabled;
  });
}

export function refreshCamControlButtons() {
  const dom = getDom();
  const anyBusy = Boolean(
    state.camBusy[1] || state.camBusy[2] || state.isStartingCamera
  );
  const active1 = Boolean(state.camStreaming[1]);
  const active2 = Boolean(state.camStreaming[2]);
  state.isCameraStreaming = Boolean(active1 || active2);

  if (dom.streamLiveDot) {
    dom.streamLiveDot.classList.toggle("online", state.isCameraStreaming);
  }

  [1, 2].forEach((camId) => {
    const startBtn = camId === 1 ? dom.btnCam1Start : dom.btnCam2Start;
    const stopBtn = camId === 1 ? dom.btnCam1Stop : dom.btnCam2Stop;
    const otherId = 3 - camId;
    const selId = state.selectedCamDeviceIds[camId] || "";
    const isUsedByOther = Boolean(
      selId &&
        state.activeCamDeviceIds[otherId] &&
        state.activeCamDeviceIds[otherId] === selId
    );
    const canConnect = Boolean(
      !state.camStreaming[camId] &&
        !state.camBusy[camId] &&
        state.browserCamDevices.length > 0 &&
        selId &&
        !isUsedByOther
    );
    if (startBtn) startBtn.disabled = !canConnect;
    if (stopBtn) {
      stopBtn.disabled = Boolean(
        !state.camStreaming[camId] || state.camBusy[camId]
      );
    }
  });

  if (dom.btnStartCamera) {
    dom.btnStartCamera.disabled = Boolean(
      anyBusy || (active1 && active2) || state.browserCamDevices.length === 0
    );
  }
  if (dom.btnStopCamera) {
    dom.btnStopCamera.disabled = Boolean(anyBusy || !state.isCameraStreaming);
  }
}

export function attachDeviceChangeListenerOnce() {
  if (state.deviceChangeBound) return;
  if (
    navigator.mediaDevices &&
    typeof navigator.mediaDevices.addEventListener === "function"
  ) {
    state.deviceChangeBound = true;
    navigator.mediaDevices.addEventListener("devicechange", () => {
      discoverCameraDevices({
        requestPermission: false,
        isInitialAssign: false,
      }).catch(() => {});
    });
  }
}

export async function discoverCameraDevices({
  requestPermission = false,
  isInitialAssign = false,
} = {}) {
  if (
    !window.isSecureContext ||
    !navigator.mediaDevices ||
    typeof navigator.mediaDevices.getUserMedia !== "function" ||
    typeof navigator.mediaDevices.enumerateDevices !== "function"
  ) {
    throw new Error(formatMediaError(null));
  }

  attachDeviceChangeListenerOnce();

  let rawDevices = await navigator.mediaDevices.enumerateDevices();
  const hasLabeledVideo = rawDevices.some(
    (d) =>
      d &&
      d.kind === "videoinput" &&
      String(d.deviceId || "").trim() !== "" &&
      String(d.label || "").trim() !== ""
  );
  const hasActiveStream = Boolean(
    state.browserStreams[0] || state.browserStreams[1]
  );
  if (hasLabeledVideo || hasActiveStream) {
    state.cameraPermissionGranted = true;
  }

  if (requestPermission && !state.cameraPermissionGranted) {
    let tempStream = null;
    try {
      tempStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
      state.cameraPermissionGranted = true;
    } catch (err) {
      if (
        err &&
        (err.name === "NotAllowedError" ||
          err.name === "PermissionDeniedError" ||
          err.name === "SecurityError")
      ) {
        state.cameraPermissionGranted = false;
      }
      throw new Error(formatMediaError(err));
    } finally {
      if (tempStream) {
        tempStream.getTracks().forEach((t) => t.stop());
      }
    }
    rawDevices = await navigator.mediaDevices.enumerateDevices();
  }

  state.browserCamDevices = normalizeVideoInputDevices(rawDevices);

  // Giữ nguyên lựa chọn hiện tại nếu deviceId vẫn còn tồn tại; không tự ý đổi sang thiết bị khác nếu bị rút
  [1, 2].forEach((camId) => {
    if (state.camStreaming[camId] || state.camBusy[camId]) {
      if (state.activeCamDeviceIds[camId]) {
        state.selectedCamDeviceIds[camId] = state.activeCamDeviceIds[camId];
      }
      return;
    }
    const prevId = state.selectedCamDeviceIds[camId];
    if (prevId) {
      const stillExists = state.browserCamDevices.some(
        (d) => d.deviceId === prevId
      );
      if (!stillExists) {
        state.selectedCamDeviceIds[camId] = "";
      }
    }
  });

  if (
    !state.hasDiscoveredOnce &&
    isInitialAssign &&
    state.browserCamDevices.length > 0
  ) {
    state.hasDiscoveredOnce = true;
    if (!state.selectedCamDeviceIds[1] && !state.activeCamDeviceIds[1]) {
      state.selectedCamDeviceIds[1] = state.browserCamDevices[0].deviceId;
    }
    if (!state.selectedCamDeviceIds[2] && !state.activeCamDeviceIds[2]) {
      const secondDev = state.browserCamDevices.find(
        (d) => d.deviceId !== state.selectedCamDeviceIds[1]
      );
      state.selectedCamDeviceIds[2] = secondDev ? secondDev.deviceId : "";
    }
  }

  renderDeviceSelects();
  updateIdleBadgeForCam(1);
  updateIdleBadgeForCam(2);
  refreshCamControlButtons();
  return state.browserCamDevices;
}

export async function waitVideoReady(video, timeoutMs = 1800) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
      return true;
    }
    await new Promise((r) => setTimeout(r, 60));
  }
  return video.videoWidth > 0 && video.videoHeight > 0;
}

export async function tryOpenStreamWithVideo(constraints) {
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  const video = document.createElement("video");
  video.playsInline = true;
  video.muted = true;
  video.autoplay = true;
  video.style.cssText =
    "position:fixed;left:-9999px;top:-9999px;width:2px;height:2px;opacity:0;pointer-events:none;";
  document.body.appendChild(video);
  video.srcObject = stream;
  try {
    await video.play();
  } catch (_) {}
  const ready = await waitVideoReady(video, 1800);
  if (!ready) {
    stream.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
    video.remove();
    throw new Error(
      "Thiết bị camera không trả về khung hình (videoWidth = 0)."
    );
  }
  return { stream, video };
}

export function captureVideoToJpegDataUrl(video) {
  if (!video || video.readyState < 2 || !video.videoWidth) return null;
  if (!state.browserCanvas) {
    state.browserCanvas = document.createElement("canvas");
  }
  const targetW = 640;
  const scale = targetW / video.videoWidth;
  const targetH = Math.max(240, Math.round(video.videoHeight * scale));
  state.browserCanvas.width = targetW;
  state.browserCanvas.height = targetH;
  const ctx = state.browserCanvas.getContext("2d");
  ctx.drawImage(video, 0, 0, targetW, targetH);
  return state.browserCanvas.toDataURL("image/jpeg", 0.78);
}

export function revealCamImagesIfReady() {
  const dom = getDom();
  if (state.camStreaming[1] && state.browserVideos[0] && dom.cam1LiveVideo) {
    dom.cam1LiveVideo.classList.remove("hidden");
    if (dom.cam1OverlayCanvas) dom.cam1OverlayCanvas.classList.remove("hidden");
    if (dom.cam1Placeholder) dom.cam1Placeholder.classList.add("hidden");
  }
  if (state.camStreaming[2] && state.browserVideos[1] && dom.cam2LiveVideo) {
    dom.cam2LiveVideo.classList.remove("hidden");
    if (dom.cam2OverlayCanvas) dom.cam2OverlayCanvas.classList.remove("hidden");
    if (dom.cam2Placeholder) dom.cam2Placeholder.classList.add("hidden");
  }
}

export async function runBrowserFrameTick() {
  state.browserFrameTimer = null;
  if (!state.browserWebRTCActive) return;
  if (state.hasActiveSecurityAlert || state.resolvingAlertInFlight) {
    // Tạm ngưng gửi ảnh nặng khi đang hiện hộp Cảnh báo an ninh để thao tác bấm Duyệt / Từ chối phản hồi tức thì
    state.browserFrameTimer = setTimeout(runBrowserFrameTick, 120);
    return;
  }
  if (state.browserInFlight) {
    state.browserFrameTimer = setTimeout(runBrowserFrameTick, 35);
    return;
  }
  const v1 = state.browserVideos[0];
  const v2 = state.browserVideos[1];
  if (!v1 && !v2) return;

  const img1 = v1 ? captureVideoToJpegDataUrl(v1) : null;
  const img2 = v2 ? captureVideoToJpegDataUrl(v2) : null;
  if (!img1 && !img2) {
    state.browserFrameTimer = setTimeout(runBrowserFrameTick, 80);
    return;
  }

  const dom = getDom();
  const t0 = performance.now();
  state.browserInFlight = true;
  try {
    const out = await sendBrowserFrame(img1, img2);
    if (v1 && out.cam1_boxes) {
      drawOverlayBoxes(
        dom.cam1LiveVideo || v1,
        dom.cam1OverlayCanvas,
        out.cam1_boxes
      );
    }
    if (v2 && out.cam2_boxes) {
      drawOverlayBoxes(
        dom.cam2LiveVideo || v2,
        dom.cam2OverlayCanvas,
        out.cam2_boxes
      );
    }
    if (out.status) {
      await applyCameraStatus(out.status);
    }
  } catch (_) {
    // Bỏ qua lỗi mạng tạm thời
  } finally {
    state.browserInFlight = false;
    if (state.browserWebRTCActive && !state.browserFrameTimer) {
      const elapsed = performance.now() - t0;
      const nextDelay = Math.max(25, Math.round(115 - elapsed));
      state.browserFrameTimer = setTimeout(runBrowserFrameTick, nextDelay);
    }
  }
}

export function ensureBrowserFrameLoop() {
  if (state.browserFrameTimer || state.browserInFlight) return;
  state.browserFrameTimer = setTimeout(runBrowserFrameTick, 20);
}

export function detachTrackEndedHandler(camId, stream) {
  const handler = state.trackEndedHandlers[camId];
  if (handler && stream) {
    stream.getVideoTracks().forEach((t) => {
      try {
        t.removeEventListener("ended", handler);
      } catch (_) {}
    });
  }
  state.trackEndedHandlers[camId] = null;
}

export function attachTrackEndedHandler(camId, stream, deviceLabel) {
  const slot = camId - 1;
  detachTrackEndedHandler(camId, stream);
  const tracks = stream ? stream.getVideoTracks() : [];
  if (!tracks.length) return;

  const handler = () => {
    if (state.manualStoppingCam[camId]) return;
    if (state.browserStreams[slot] !== stream) return;
    handleUnexpectedTrackEnded(camId, deviceLabel);
  };
  state.trackEndedHandlers[camId] = handler;
  tracks.forEach((t) => {
    try {
      t.addEventListener("ended", handler, { once: true });
    } catch (_) {
      t.onended = handler;
    }
  });
}

export async function handleUnexpectedTrackEnded(camId, lostLabel) {
  const dom = getDom();
  const labelText =
    lostLabel || state.activeCamDeviceLabels[camId] || `Cam ${camId}`;
  stopBrowserWebRTCForCam(camId);
  hideCamStreamUI(camId);
  setPlaceholderText(
    camId,
    `Thiết bị "${labelText}" đã bị ngắt kết nối. Vui lòng chọn thiết bị và kết nối lại.`
  );
  updateIdleBadgeForCam(camId);
  renderDeviceSelects();
  refreshCamControlButtons();
  showBanner(
    dom.cameraAlertBox,
    "error",
    `Cam ${camId} (${labelText}) đã bị ngắt kết nối thiết bị. Vui lòng kiểm tra lại camera và kết nối lại.`
  );
  try {
    await stopCamera(camId);
  } catch (_) {}
  try {
    await discoverCameraDevices({
      requestPermission: false,
      isInitialAssign: false,
    });
  } catch (_) {}
}

export function stopBrowserWebRTCForCam(camId) {
  const dom = getDom();
  const slot = camId - 1;
  const otherSlot = 1 - slot;
  const s = state.browserStreams[slot];
  const v = state.browserVideos[slot];

  state.manualStoppingCam[camId] = true;
  try {
    if (s) {
      detachTrackEndedHandler(camId, s);
    }
    state.browserStreams[slot] = null;
    state.browserVideos[slot] = null;
    state.activeCamDeviceIds[camId] = null;
    state.activeCamDeviceLabels[camId] = null;

    const liveVideoEl = camId === 1 ? dom.cam1LiveVideo : dom.cam2LiveVideo;
    const overlayCanvasEl =
      camId === 1 ? dom.cam1OverlayCanvas : dom.cam2OverlayCanvas;
    if (liveVideoEl) {
      liveVideoEl.srcObject = null;
      liveVideoEl.classList.add("hidden");
    }
    if (overlayCanvasEl) {
      clearOverlayCanvas(overlayCanvasEl);
      overlayCanvasEl.classList.add("hidden");
    }

    if (s && state.browserStreams[otherSlot] !== s) {
      s.getTracks().forEach((t) => t.stop());
    }
    if (v && state.browserVideos[otherSlot] !== v) {
      v.srcObject = null;
      v.remove();
    }

    state.browserWebRTCActive = Boolean(
      state.browserVideos[0] || state.browserVideos[1]
    );
    if (!state.browserWebRTCActive) {
      stopCommitStatusPoll();
      if (state.browserFrameTimer) {
        clearTimeout(state.browserFrameTimer);
        state.browserFrameTimer = null;
      }
    }
  } finally {
    state.manualStoppingCam[camId] = false;
  }
}

export function stopBrowserWebRTC() {
  stopBrowserWebRTCForCam(1);
  stopBrowserWebRTCForCam(2);
}

export function hideCamStreamUI(camId) {
  const dom = getDom();
  state.camStreaming[camId] = false;
  state.isCameraStreaming = Boolean(
    state.camStreaming[1] || state.camStreaming[2]
  );
  const liveVideoEl = camId === 1 ? dom.cam1LiveVideo : dom.cam2LiveVideo;
  const overlayCanvasEl =
    camId === 1 ? dom.cam1OverlayCanvas : dom.cam2OverlayCanvas;
  const phEl = camId === 1 ? dom.cam1Placeholder : dom.cam2Placeholder;
  if (liveVideoEl) {
    liveVideoEl.srcObject = null;
    liveVideoEl.classList.add("hidden");
  }
  if (overlayCanvasEl) {
    clearOverlayCanvas(overlayCanvasEl);
    overlayCanvasEl.classList.add("hidden");
  }
  if (phEl) {
    phEl.classList.remove("hidden");
  }
}

export async function startSingleCamUI(
  camId,
  { silentSuccessBanner = false } = {}
) {
  if (state.camBusy[camId] || state.camStreaming[camId]) {
    return Boolean(state.camStreaming[camId]);
  }
  const dom = getDom();
  const slot = camId - 1;
  const otherId = 3 - camId;
  const selectEl = camId === 1 ? dom.cam1DeviceSelect : dom.cam2DeviceSelect;
  state.lastCamError[camId] = "";

  let selectedId =
    (selectEl && selectEl.value) || state.selectedCamDeviceIds[camId] || "";

  if (state.browserCamDevices.length === 0) {
    try {
      await discoverCameraDevices({
        requestPermission: true,
        isInitialAssign: true,
      });
      selectedId =
        (selectEl && selectEl.value) || state.selectedCamDeviceIds[camId] || "";
    } catch (err) {
      state.lastCamError[camId] = err.message;
      setPlaceholderText(camId, err.message);
      showBanner(dom.cameraAlertBox, "error", `Cam ${camId}: ${err.message}`);
      return false;
    }
  }

  if (state.browserCamDevices.length === 0) {
    const msg = "Không tìm thấy thiết bị Camera nào để kết nối.";
    state.lastCamError[camId] = msg;
    setPlaceholderText(camId, msg);
    showBanner(dom.cameraAlertBox, "error", `Cam ${camId}: ${msg}`);
    return false;
  }

  if (!selectedId) {
    let msg = `Vui lòng chọn thiết bị camera cho Cam ${camId} trước khi kết nối.`;
    if (
      state.browserCamDevices.length === 1 &&
      state.activeCamDeviceIds[otherId] === state.browserCamDevices[0].deviceId
    ) {
      msg = `Máy chỉ có 1 thiết bị Camera (${state.browserCamDevices[0].label}) và đang được sử dụng ở Cam ${otherId}. Không thể mở cùng 1 thiết bị cho cả 2 ô.`;
    }
    state.lastCamError[camId] = msg;
    setPlaceholderText(camId, msg);
    showBanner(dom.cameraAlertBox, "error", msg);
    return false;
  }

  if (
    state.activeCamDeviceIds[otherId] &&
    state.activeCamDeviceIds[otherId] === selectedId
  ) {
    const dupDev = state.browserCamDevices.find(
      (d) => d.deviceId === selectedId
    );
    const dupName = (dupDev && dupDev.label) || "đã chọn";
    const msg = `Thiết bị "${dupName}" đang được sử dụng ở Cam ${otherId}. Vui lòng chọn thiết bị khác cho Cam ${camId}.`;
    state.lastCamError[camId] = msg;
    setPlaceholderText(camId, msg);
    showBanner(dom.cameraAlertBox, "error", msg);
    return false;
  }

  // Đặt khóa & giữ chỗ thiết bị ĐỒNG BỘ trước lệnh await đầu tiên để chống race condition khi bấm 2 ô liên tiếp
  state.camBusy[camId] = true;
  state.selectedCamDeviceIds[camId] = selectedId;
  state.activeCamDeviceIds[camId] = selectedId;
  renderDeviceSelects();
  refreshCamControlButtons();

  let openedCamObj = null;
  try {
    const latestRaw = await navigator.mediaDevices.enumerateDevices();
    state.browserCamDevices = normalizeVideoInputDevices(latestRaw);
    const targetDev = state.browserCamDevices.find(
      (d) => d.deviceId === selectedId
    );
    if (!targetDev) {
      state.selectedCamDeviceIds[camId] = "";
      throw new Error(
        `Thiết bị đã chọn cho Cam ${camId} không còn tồn tại. Vui lòng chọn thiết bị khác.`
      );
    }

    state.activeCamDeviceLabels[camId] = targetDev.label;
    showBanner(
      dom.cameraAlertBox,
      "",
      `Đang kết nối Cam ${camId} (${targetDev.label})...`
    );

    try {
      openedCamObj = await tryOpenStreamWithVideo({
        video: { deviceId: { exact: selectedId } },
        audio: false,
      });
    } catch (openErr) {
      throw new Error(formatMediaError(openErr, targetDev.label));
    }

    try {
      await startCamera(camId);
    } catch (apiErr) {
      throw new Error(
        (apiErr && apiErr.data && apiErr.data.detail) ||
          `Không thể đăng ký phiên Cam ${camId} trên máy chủ.`
      );
    }

    state.browserStreams[slot] = openedCamObj.stream;
    state.browserVideos[slot] = openedCamObj.video;
    openedCamObj = null;
    state.browserWebRTCActive = Boolean(
      state.browserVideos[0] || state.browserVideos[1]
    );
    state.camStreaming[camId] = true;
    state.isCameraStreaming = Boolean(
      state.camStreaming[1] || state.camStreaming[2]
    );

    attachTrackEndedHandler(camId, state.browserStreams[slot], targetDev.label);

    const liveVideoEl = camId === 1 ? dom.cam1LiveVideo : dom.cam2LiveVideo;
    if (liveVideoEl) {
      liveVideoEl.srcObject = state.browserStreams[slot];
      try {
        await liveVideoEl.play();
      } catch (_) {}
    }

    revealCamImagesIfReady();
    ensureBrowserFrameLoop();

    const votePillEl = camId === 1 ? dom.cam1VotePill : dom.cam2VotePill;
    if (votePillEl) {
      votePillEl.className = "pill mono-num num";
      votePillEl.textContent = state.modelsReady
        ? `${targetDev.label} · Đang quét`
        : `${targetDev.label} · Đang tải mô hình AI...`;
    }

    if (!silentSuccessBanner) {
      showBanner(
        dom.cameraAlertBox,
        "success",
        `Đã kết nối Cam ${camId}: ${targetDev.label}`,
        1000
      );
    }
    return true;
  } catch (err) {
    if (openedCamObj) {
      try {
        openedCamObj.stream.getTracks().forEach((t) => t.stop());
      } catch (_) {}
      try {
        openedCamObj.video.srcObject = null;
        openedCamObj.video.remove();
      } catch (_) {}
      openedCamObj = null;
    }
    stopBrowserWebRTCForCam(camId);
    hideCamStreamUI(camId);
    if (
      selectedId &&
      state.browserCamDevices.some((d) => d.deviceId === selectedId)
    ) {
      state.selectedCamDeviceIds[camId] = selectedId;
    }
    state.lastCamError[camId] = err.message;
    setPlaceholderText(camId, `Lỗi kết nối Cam ${camId}: ${err.message}`);
    updateIdleBadgeForCam(camId);
    if (!silentSuccessBanner) {
      showBanner(dom.cameraAlertBox, "error", `Cam ${camId}: ${err.message}`);
    }
    return false;
  } finally {
    state.camBusy[camId] = false;
    renderDeviceSelects();
    refreshCamControlButtons();
  }
}

export async function stopSingleCamUI(camId) {
  if (state.camBusy[camId]) return;
  const dom = getDom();
  state.camBusy[camId] = true;
  renderDeviceSelects();
  refreshCamControlButtons();

  stopBrowserWebRTCForCam(camId);
  hideCamStreamUI(camId);
  setPlaceholderText(camId, `Chưa kết nối Cam ${camId}`);
  updateIdleBadgeForCam(camId);
  try {
    await stopCamera(camId);
  } catch (err) {
    showBanner(dom.cameraAlertBox, "error", err.message);
  } finally {
    state.camBusy[camId] = false;
    renderDeviceSelects();
    refreshCamControlButtons();
  }
  await pollCameraStatusOnce();
}

export async function scanCameraDevicesUI() {
  const dom = getDom();
  if (dom.btnScanCamera) dom.btnScanCamera.disabled = true;
  showBanner(dom.cameraAlertBox, "", "Đang xin quyền và tìm thiết bị camera...");
  try {
    const devices = await discoverCameraDevices({
      requestPermission: true,
      isInitialAssign: true,
    });
    if (devices.length === 0) {
      setPlaceholderText(1, "Không tìm thấy thiết bị Camera nào.");
      setPlaceholderText(2, "Không tìm thấy thiết bị Camera nào.");
      showBanner(
        dom.cameraAlertBox,
        "error",
        "Không tìm thấy thiết bị Camera nào được kết nối với máy của bạn."
      );
    } else if (devices.length === 1) {
      showBanner(
        dom.cameraAlertBox,
        "warn",
        `Tìm thấy 1 thiết bị: ${devices[0].label}. Vì chỉ có 1 thiết bị nên chỉ có thể bật 1 ô (Chế độ 1 Camera dự phòng), không thể bật đồng thời cả 2 ô.`
      );
    } else {
      const names = devices.map((d) => d.label).join(", ");
      showBanner(
        dom.cameraAlertBox,
        "success",
        `Tìm thấy ${devices.length} thiết bị: ${names}. Hãy chọn thiết bị cho Cam 1 / Cam 2 và bấm "Kết nối" hoặc "Bật cả 2".`
      );
    }
  } catch (err) {
    showBanner(dom.cameraAlertBox, "error", err.message);
  } finally {
    if (dom.btnScanCamera) dom.btnScanCamera.disabled = false;
    renderDeviceSelects();
    refreshCamControlButtons();
  }
}

export async function startBothCamsUI() {
  if (state.camBusy[1] || state.camBusy[2] || state.isStartingCamera) return;
  const dom = getDom();
  if (dom.btnStartCamera) dom.btnStartCamera.disabled = true;
  try {
    if (state.browserCamDevices.length === 0) {
      await discoverCameraDevices({
        requestPermission: true,
        isInitialAssign: true,
      });
    }
    if (state.browserCamDevices.length < 2) {
      const msg =
        state.browserCamDevices.length === 1
          ? `Chỉ tìm thấy 1 thiết bị (${state.browserCamDevices[0].label}). Để dùng "Bật cả 2", máy cần kết nối ít nhất 2 thiết bị camera khác nhau (hoặc bấm "Kết nối" ở 1 ô để dùng chế độ 1 Camera dự phòng).`
          : "Không tìm thấy đủ 2 thiết bị camera để bật đồng thời cả 2 ô.";
      showBanner(dom.cameraAlertBox, "error", msg);
      return;
    }

    const dev1 = state.camStreaming[1]
      ? state.activeCamDeviceIds[1]
      : (dom.cam1DeviceSelect && dom.cam1DeviceSelect.value) ||
        state.selectedCamDeviceIds[1] ||
        "";
    const dev2 = state.camStreaming[2]
      ? state.activeCamDeviceIds[2]
      : (dom.cam2DeviceSelect && dom.cam2DeviceSelect.value) ||
        state.selectedCamDeviceIds[2] ||
        "";

    if (!dev1 || !dev2) {
      showBanner(
        dom.cameraAlertBox,
        "error",
        'Vui lòng chọn đủ 2 thiết bị camera cho Cam 1 và Cam 2 trước khi bấm "Bật cả 2".'
      );
      return;
    }
    if (dev1 === dev2) {
      showBanner(
        dom.cameraAlertBox,
        "error",
        "Cam 1 và Cam 2 không được chọn cùng một thiết bị camera. Vui lòng chọn 2 thiết bị khác nhau."
      );
      return;
    }

    const wasStreaming1 = Boolean(state.camStreaming[1]);
    const wasStreaming2 = Boolean(state.camStreaming[2]);
    const ok1 = wasStreaming1
      ? true
      : await startSingleCamUI(1, { silentSuccessBanner: true });
    const ok2 = wasStreaming2
      ? true
      : await startSingleCamUI(2, { silentSuccessBanner: true });

    if (ok1 && ok2) {
      showBanner(
        dom.cameraAlertBox,
        "success",
        `Đã kết nối cả 2 Camera: Cam 1 (${state.activeCamDeviceLabels[1]}) & Cam 2 (${state.activeCamDeviceLabels[2]}).`,
        1200
      );
    } else if (ok1 && !ok2) {
      showBanner(
        dom.cameraAlertBox,
        "error",
        `Cam 1 (${state.activeCamDeviceLabels[1]}) đang hoạt động, nhưng Cam 2 kết nối thất bại: ${state.lastCamError[2] || "Không mở được thiết bị."}`
      );
    } else if (!ok1 && ok2) {
      showBanner(
        dom.cameraAlertBox,
        "error",
        `Cam 2 (${state.activeCamDeviceLabels[2]}) đang hoạt động, nhưng Cam 1 kết nối thất bại: ${state.lastCamError[1] || "Không mở được thiết bị."}`
      );
    } else {
      showBanner(
        dom.cameraAlertBox,
        "error",
        `Không thể kết nối cả 2 Camera. Cam 1: ${state.lastCamError[1] || "Lỗi"} | Cam 2: ${state.lastCamError[2] || "Lỗi"}`
      );
    }
  } catch (err) {
    showBanner(dom.cameraAlertBox, "error", err.message);
  } finally {
    renderDeviceSelects();
    refreshCamControlButtons();
  }
}

export async function stopAllCamsUI() {
  if (state.camBusy[1] || state.camBusy[2]) return;
  const dom = getDom();
  if (dom.btnStopCamera) dom.btnStopCamera.disabled = true;
  state.isStartingCamera = true;
  stopBrowserWebRTC();
  hideCamStreamUI(1);
  hideCamStreamUI(2);
  setPlaceholderText(1, "Chưa kết nối Cam 1");
  setPlaceholderText(2, "Chưa kết nối Cam 2");
  updateIdleBadgeForCam(1);
  updateIdleBadgeForCam(2);
  renderDeviceSelects();
  refreshCamControlButtons();
  try {
    await stopAllCameras();
  } catch (err) {
    showBanner(dom.cameraAlertBox, "error", err.message);
  } finally {
    state.isStartingCamera = false;
    renderDeviceSelects();
    refreshCamControlButtons();
  }
  await pollCameraStatusOnce();
}
