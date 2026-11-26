/* ==========================================================================
   Frontend Bootstrap Entrypoint — Wires Views, Events & Initial Poll
   ========================================================================== */

import {
  attachDeviceChangeListenerOnce,
  ensureBrowserFrameLoop,
  hideCamStreamUI,
  refreshCamControlButtons,
  renderDeviceSelects,
  revealCamImagesIfReady,
  scanCameraDevicesUI,
  setPlaceholderText,
  startBothCamsUI,
  startSingleCamUI,
  stopAllCamsUI,
  stopBrowserWebRTC,
  stopBrowserWebRTCForCam,
  stopSingleCamUI,
} from "./camera.js";
import {
  cancelLatch,
  onRecordsVersionChanged,
  pollCameraStatusOnce,
  registerGateCameraCallbacks,
  resolveAlert,
  updateIdleBadgeForCam,
} from "./gate_ui.js";
import {
  activateView,
  bindHistoryRowActions,
  fetchManagementOverview,
  handleRefreshManagement,
  updateDirectionSortHeaderUI,
} from "./history.js";
import { closeSnapshotModal } from "./lost_case_modal.js";
import {
  exportHistoryPdfReport,
  exportLostCasePdfReport,
  exportRevenuePdfReport,
} from "./pdf_export.js";
import {
  setRevenuePage,
  setRevenuePageSize,
  setRevenuePeriod,
} from "./revenue.js";
import { getDom, state } from "./state.js";

function bootstrap() {
  const dom = getDom();

  // Wire gate_ui <-> camera & history callbacks without circular imports
  registerGateCameraCallbacks({
    renderDeviceSelects,
    refreshCamControlButtons,
    revealCamImagesIfReady,
    stopBrowserWebRTCForCam,
    hideCamStreamUI,
    setPlaceholderText,
    ensureBrowserFrameLoop,
  });

  onRecordsVersionChanged(({ wasUninitialized }) => {
    if (
      (state.activeViewId === "view-management" ||
        state.activeViewId === "view-revenue") &&
      !(wasUninitialized && state.overviewInFlight)
    ) {
      fetchManagementOverview();
    }
  });

  // View navigation
  dom.navItems.forEach((btn) => {
    if (!btn) return;
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-target");
      if (targetId) {
        activateView(targetId);
      }
    });
  });

  if (
    window.location.hash === "#management" ||
    new URLSearchParams(window.location.search).get("view") === "management"
  ) {
    activateView("view-management");
  }

  // Latch & Security Alert controls
  if (dom.btnCancelLatch) {
    dom.btnCancelLatch.addEventListener("click", () => cancelLatch());
  }
  if (dom.btnApproveExit) {
    dom.btnApproveExit.addEventListener("click", () => resolveAlert("approve"));
  }
  if (dom.btnRejectExit) {
    dom.btnRejectExit.addEventListener("click", () => resolveAlert("reject"));
  }

  // Camera device select & start/stop controls
  [1, 2].forEach((camId) => {
    const selectEl = camId === 1 ? dom.cam1DeviceSelect : dom.cam2DeviceSelect;
    if (!selectEl) return;
    selectEl.addEventListener("change", () => {
      if (state.camStreaming[camId] || state.camBusy[camId]) {
        selectEl.value =
          state.activeCamDeviceIds[camId] ||
          state.selectedCamDeviceIds[camId] ||
          "";
        return;
      }
      state.selectedCamDeviceIds[camId] = selectEl.value || "";
      updateIdleBadgeForCam(camId);
      refreshCamControlButtons();
    });
  });

  if (dom.btnCam1Start) {
    dom.btnCam1Start.addEventListener("click", () => startSingleCamUI(1));
  }
  if (dom.btnCam1Stop) {
    dom.btnCam1Stop.addEventListener("click", () => stopSingleCamUI(1));
  }
  if (dom.btnCam2Start) {
    dom.btnCam2Start.addEventListener("click", () => startSingleCamUI(2));
  }
  if (dom.btnCam2Stop) {
    dom.btnCam2Stop.addEventListener("click", () => stopSingleCamUI(2));
  }
  if (dom.btnScanCamera) {
    dom.btnScanCamera.addEventListener("click", () => scanCameraDevicesUI());
  }
  if (dom.btnStartCamera) {
    dom.btnStartCamera.addEventListener("click", () => startBothCamsUI());
  }
  if (dom.btnStopCamera) {
    dom.btnStopCamera.addEventListener("click", () => stopAllCamsUI());
  }

  // Management tabs, direction sort, search debounce, pagination & refresh
  dom.tabLinks.forEach((btn) => {
    btn.addEventListener("click", () => {
      dom.tabLinks.forEach((b) => b.setAttribute("aria-selected", "false"));
      btn.setAttribute("aria-selected", "true");
      state.activeStatusFilter =
        btn.getAttribute("data-status-filter") || "all";
      if (state.activeStatusFilter !== "direction_out") {
        state.activeDirectionSort = "";
      }
      updateDirectionSortHeaderUI();
      state.currentPage = 1;
      fetchManagementOverview();
    });
  });

  if (dom.thDirectionSort) {
    dom.thDirectionSort.addEventListener("click", () => {
      if (state.activeStatusFilter !== "direction_out") return;
      if (state.activeDirectionSort === "") {
        state.activeDirectionSort = "mismatch_first";
      } else if (state.activeDirectionSort === "mismatch_first") {
        state.activeDirectionSort = "matched_first";
      } else {
        state.activeDirectionSort = "";
      }
      updateDirectionSortHeaderUI();
      state.currentPage = 1;
      fetchManagementOverview();
    });
  }

  if (dom.searchPlateInput) {
    dom.searchPlateInput.addEventListener("input", () => {
      if (state.searchDebounceTimer) clearTimeout(state.searchDebounceTimer);
      state.searchDebounceTimer = setTimeout(() => {
        state.currentPage = 1;
        fetchManagementOverview();
      }, 200);
    });
  }

  if (dom.paginationControls) {
    dom.paginationControls.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-page]");
      if (!btn || btn.disabled) return;
      const targetPage = parseInt(btn.getAttribute("data-page") || "1", 10);
      if (!Number.isNaN(targetPage) && targetPage !== state.currentPage) {
        state.currentPage = targetPage;
        fetchManagementOverview();
      }
    });
  }

  if (dom.pageSizeSelect) {
    dom.pageSizeSelect.addEventListener("change", () => {
      const val = parseInt(dom.pageSizeSelect.value || "10", 10);
      state.pageSize = Number.isNaN(val) || val < 1 ? 10 : val;
      state.currentPage = 1;
      fetchManagementOverview();
    });
  }

  if (dom.btnRefreshManagement) {
    dom.btnRefreshManagement.addEventListener("click", () =>
      handleRefreshManagement()
    );
  }

  bindHistoryRowActions();

  // Revenue period cards & pagination
  dom.revPeriodBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      setRevenuePeriod(btn.getAttribute("data-rev-period") || "daily");
    });
  });

  if (dom.revPaginationControls) {
    dom.revPaginationControls.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-rev-page]");
      if (!btn || btn.disabled) return;
      setRevenuePage(btn.getAttribute("data-rev-page") || "1");
    });
  }

  if (dom.revPageSizeSelect) {
    dom.revPageSizeSelect.addEventListener("change", () => {
      setRevenuePageSize(dom.revPageSizeSelect.value || "10");
    });
  }

  // Modal close / backdrop / Escape key
  if (dom.btnCloseSnapshotModal) {
    dom.btnCloseSnapshotModal.addEventListener("click", closeSnapshotModal);
  }
  if (dom.snapshotModal) {
    dom.snapshotModal.addEventListener("click", (e) => {
      if (e.target === dom.snapshotModal) closeSnapshotModal();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.isLostModalOpen) {
      closeSnapshotModal();
    }
  });

  // PDF Export buttons
  if (dom.btnExportHistoryPdf) {
    dom.btnExportHistoryPdf.addEventListener("click", () =>
      exportHistoryPdfReport()
    );
  }
  if (dom.btnExportRevenuePdf) {
    dom.btnExportRevenuePdf.addEventListener("click", () =>
      exportRevenuePdfReport()
    );
  }
  if (dom.btnExportLostCasePdf) {
    dom.btnExportLostCasePdf.addEventListener("click", () =>
      exportLostCasePdfReport()
    );
  }

  // Cleanup active WebRTC streams on page unload
  window.addEventListener("beforeunload", () => {
    stopBrowserWebRTC();
  });

  // Initial camera setup & status sync
  attachDeviceChangeListenerOnce();
  setPlaceholderText(
    1,
    'Bấm "Tìm camera" để cấp quyền và chọn thiết bị cho Cam 1'
  );
  setPlaceholderText(
    2,
    'Bấm "Tìm camera" để cấp quyền và chọn thiết bị cho Cam 2'
  );
  renderDeviceSelects();
  refreshCamControlButtons();
  pollCameraStatusOnce();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
