/* ==========================================================================
   Frontend Mutable State Store, Lazy DOM Cache & Client Management Caches
   ========================================================================== */

export const OVERVIEW_CLIENT_CACHE_MAX = 30;

export const state = {
  activeViewId: "view-recognition",
  activeStatusFilter: "all",
  activeDirectionSort: "",
  activeRevenuePeriod: "daily",
  revCurrentPage: 1,
  revPageSize: 10,
  cachedRevenueData: null,
  cachedHistoryRecords: [],
  cachedMatchedCount: 0,
  cachedTotalRecords: 0,
  activeLostCase: null,
  isLostModalOpen: false,
  lostCaseReqSeq: 0,
  overviewReqSeq: 0,
  overviewInFlight: false,
  currentPage: 1,
  pageSize: 10,
  isCameraStreaming: false,
  camStreaming: { 1: false, 2: false },
  selectedCamDeviceIds: { 1: "", 2: "" },
  activeCamDeviceIds: { 1: null, 2: null },
  activeCamDeviceLabels: { 1: null, 2: null },
  lastDeviceSelectSig: { 1: "", 2: "" },
  camBusy: { 1: false, 2: false },
  manualStoppingCam: { 1: false, 2: false },
  trackEndedHandlers: { 1: null, 2: null },
  lastCamError: { 1: "", 2: "" },
  lastBackendError: "",
  faceMatchThreshold: 0.65,
  modelsReady: true,
  hasDiscoveredOnce: false,
  cameraPermissionGranted: false,
  deviceChangeBound: false,
  lastRecordsVersion: -1,
  lastFeedbackSeq: -1,
  hasActiveSecurityAlert: false,
  activeSecurityAlertPlate: "",
  resolvingAlertInFlight: false,
  searchDebounceTimer: null,
  overviewPageCache: new Map(),
  overviewPrefetchInFlight: new Set(),
  lostCaseClientCache: new Map(),
  cachedStatsData: null,

  // Runtime WebRTC & polling handles
  browserWebRTCActive: false,
  isStartingCamera: false,
  browserCamDevices: [],
  browserStreams: [null, null],
  browserVideos: [null, null],
  browserCanvas: null,
  browserFrameTimer: null,
  browserInFlight: false,
  commitPollTimer: null,
  commitPollInFlight: false,
};

let cachedDom = null;

/**
 * Lazily resolve and cache all DOM elements referenced across frontend modules.
 * @returns {Record<string, any>}
 */
export function getDom() {
  if (cachedDom) return cachedDom;

  const navRecognition = document.getElementById("nav-recognition");
  const navManagement = document.getElementById("nav-management");
  const navRevenue = document.getElementById("nav-revenue");

  cachedDom = {
    // Navigation & Topbar elements
    navRecognition,
    navManagement,
    navRevenue,
    navItems: [navRecognition, navManagement, navRevenue],
    views: document.querySelectorAll(".screen-view"),
    streamLiveDot: document.getElementById("stream-live-dot"),

    // Screen 1: Full-width Dual Camera (Cam 1 + Cam 2) elements
    cameraAlertBox: document.getElementById("camera-alert-box"),
    cam1DeviceSelect: document.getElementById("cam1-device-select"),
    cam2DeviceSelect: document.getElementById("cam2-device-select"),
    btnScanCamera: document.getElementById("btn-scan-camera"),
    btnStartCamera: document.getElementById("btn-start-camera"),
    btnStopCamera: document.getElementById("btn-stop-camera"),
    btnCam1Start: document.getElementById("btn-cam1-start"),
    btnCam1Stop: document.getElementById("btn-cam1-stop"),
    btnCam2Start: document.getElementById("btn-cam2-start"),
    btnCam2Stop: document.getElementById("btn-cam2-stop"),

    cam1VotePill: document.getElementById("cam1-vote-pill"),
    cam2VotePill: document.getElementById("cam2-vote-pill"),
    cam1PlateValue: document.getElementById("cam1-plate-value"),
    cam1FaceValue: document.getElementById("cam1-face-value"),
    cam2PlateValue: document.getElementById("cam2-plate-value"),
    cam2FaceValue: document.getElementById("cam2-face-value"),
    cam1LiveVideo: document.getElementById("cam1-live-video"),
    cam2LiveVideo: document.getElementById("cam2-live-video"),
    cam1OverlayCanvas: document.getElementById("cam1-overlay-canvas"),
    cam2OverlayCanvas: document.getElementById("cam2-overlay-canvas"),
    cam1Placeholder: document.getElementById("cam1-placeholder"),
    cam2Placeholder: document.getElementById("cam2-placeholder"),
    voteAmbiguousWarning: document.getElementById("vote-ambiguous-warning"),
    gateTopupBox: document.getElementById("gate-topup-box"),

    // Two-Phase Latch elements
    latchStatusBox: document.getElementById("latch-status-box"),
    latchDirectionBadge: document.getElementById("latch-direction-badge"),
    latchPlateText: document.getElementById("latch-plate-text"),
    latchStepText: document.getElementById("latch-step-text"),
    btnCancelLatch: document.getElementById("btn-cancel-latch"),

    // Security Alert elements
    securityAlertBox: document.getElementById("security-alert-box"),
    alertScorePill: document.getElementById("alert-score-pill"),
    alertDetailText: document.getElementById("alert-detail-text"),
    btnApproveExit: document.getElementById("btn-approve-exit"),
    btnRejectExit: document.getElementById("btn-reject-exit"),

    // Screen 2: Management & Ledger elements
    managementAlertBox: document.getElementById("management-alert-box"),
    statInParking: document.getElementById("stat-in-parking"),
    statTodayRecords: document.getElementById("stat-today-records"),
    statTotalRecords: document.getElementById("stat-total-records"),

    // Revenue Report elements
    revenueUnitPill: document.getElementById("revenue-unit-pill"),
    revTodayAmount: document.getElementById("rev-today-amount"),
    revTodayTickets: document.getElementById("rev-today-tickets"),
    revMonthAmount: document.getElementById("rev-month-amount"),
    revMonthTickets: document.getElementById("rev-month-tickets"),
    revYearAmount: document.getElementById("rev-year-amount"),
    revYearTickets: document.getElementById("rev-year-tickets"),
    revTotalAmount: document.getElementById("rev-total-amount"),
    revTotalTickets: document.getElementById("rev-total-tickets"),
    revPeriodBtns: document.querySelectorAll(".rev-period-btn[data-rev-period]"),
    revenuePeriodColTitle: document.getElementById("revenue-period-col-title"),
    revenueTableBody: document.getElementById("revenue-table-body"),
    revPaginationRangeText: document.getElementById("rev-pagination-range-text"),
    revPageSizeSelect: document.getElementById("rev-page-size-select"),
    revPaginationControls: document.getElementById("rev-pagination-controls"),

    // History Table & Filters
    tabLinks: document.querySelectorAll(".tab-link[data-status-filter]"),
    tabCountAll: document.getElementById("tab-count-all"),
    tabCountParking: document.getElementById("tab-count-parking"),
    tabCountIn: document.getElementById("tab-count-in"),
    tabCountOut: document.getElementById("tab-count-out"),
    searchPlateInput: document.getElementById("search-plate-input"),
    ledgerCountText: document.getElementById("ledger-count-text"),
    btnExportHistoryPdf: document.getElementById("btn-export-history-pdf"),
    btnRefreshManagement: document.getElementById("btn-refresh-management"),
    btnExportRevenuePdf: document.getElementById("btn-export-revenue-pdf"),
    thDirectionSort: document.getElementById("th-direction-sort"),
    directionSortIndicator: document.getElementById("direction-sort-indicator"),
    historyTableBody: document.getElementById("history-table-body"),
    paginationRangeText: document.getElementById("pagination-range-text"),
    pageSizeSelect: document.getElementById("page-size-select"),
    paginationControls: document.getElementById("pagination-controls"),

    // Snapshot & Lost Vehicle Case modal elements
    snapshotModal: document.getElementById("snapshot-modal"),
    snapshotModalCard: document.getElementById("snapshot-modal-card"),
    snapshotModalTitle: document.getElementById("snapshot-modal-title"),
    checkinBadgePill: document.getElementById("checkin-badge-pill"),
    checkinTimeLabel: document.getElementById("checkin-time-label"),
    checkinPlateLabel: document.getElementById("checkin-plate-label"),
    checkinFaceLabel: document.getElementById("checkin-face-label"),
    checkinPlateImgLabel: document.getElementById("checkin-plate-img-label"),
    checkinFaceImgLabel: document.getElementById("checkin-face-img-label"),
    modalPlateImg: document.getElementById("modal-plate-img"),
    modalFaceImg: document.getElementById("modal-face-img"),
    checkinPlateEmpty: document.getElementById("checkin-plate-empty"),
    checkinFaceEmpty: document.getElementById("checkin-face-empty"),
    btnCloseSnapshotModal: document.getElementById("btn-close-snapshot-modal"),
    btnExportLostCasePdf: document.getElementById("btn-export-lost-case-pdf"),
    lostCaseVerdictBanner: document.getElementById("lost-case-verdict-banner"),
    checkinRecordId: document.getElementById("checkin-record-id"),
    checkinTime: document.getElementById("checkin-time"),
    checkinPlate: document.getElementById("checkin-plate"),
    checkinFaceStatus: document.getElementById("checkin-face-status"),
    checkoutBadgePill: document.getElementById("checkout-badge-pill"),
    checkoutRecordId: document.getElementById("checkout-record-id"),
    checkoutTime: document.getElementById("checkout-time"),
    checkoutParkingStatus: document.getElementById("checkout-parking-status"),
    checkoutMatchStatus: document.getElementById("checkout-match-status"),
    modalCheckoutPlateImg: document.getElementById("modal-checkout-plate-img"),
    checkoutPlateEmpty: document.getElementById("checkout-plate-empty"),
    takerMatchPill: document.getElementById("taker-match-pill"),
    modalTakerFaceImg: document.getElementById("modal-taker-face-img"),
    takerFaceEmpty: document.getElementById("taker-face-empty"),
    takerNoteText: document.getElementById("taker-note-text"),
  };

  return cachedDom;
}

export function clearClientManagementCaches() {
  state.overviewPageCache.clear();
  state.overviewPrefetchInFlight.clear();
  state.lostCaseClientCache.clear();
}

export function makeOverviewCacheKey(
  ver,
  query,
  statusFilter,
  page,
  size,
  sortBy = ""
) {
  return `${ver}|${String(query || "").trim()}|${statusFilter || "all"}|${sortBy || ""}|${page}|${size}`;
}

export function setOverviewClientCache(key, payload) {
  if (state.overviewPageCache.has(key)) {
    state.overviewPageCache.delete(key);
  } else if (state.overviewPageCache.size >= OVERVIEW_CLIENT_CACHE_MAX) {
    const oldestKey = state.overviewPageCache.keys().next().value;
    if (oldestKey !== undefined) state.overviewPageCache.delete(oldestKey);
  }
  state.overviewPageCache.set(key, payload);
}
