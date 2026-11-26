/* ==========================================================================
   History Ledger, Client Page Cache, Prefetch, Sort & Management Controller
   ========================================================================== */

import { getManagementOverview, reconnectDatabase } from "./api.js";
import {
  openLostVehicleModalByRow,
  openSingleSnapshotModalByRow,
} from "./lost_case_modal.js";
import { renderRevenueSection } from "./revenue.js";
import {
  clearClientManagementCaches,
  getDom,
  makeOverviewCacheKey,
  setOverviewClientCache,
  state,
} from "./state.js";
import {
  buildPageNumbers,
  escapeHtml,
  getRowSnapshots,
  renderDirectionPill,
  showBanner,
} from "./utils.js";

function renderSnapshotCell(row) {
  const { plateImg, faceImg } = getRowSnapshots(row);
  const plate = escapeHtml(row["Biển số"]);
  const recId = escapeHtml(row["ID"]);
  return `
    <div class="snapshot-cell">
      <button type="button" class="snap-thumb-btn" data-record-id="${recId}" title="Bấm để xem ảnh cắt biển số và khuôn mặt của lượt này">
        <img class="snap-plate-img" src="${plateImg}" alt="Biển số ${plate}" loading="lazy" />
        <img class="snap-face-img" src="${faceImg}" alt="Khuôn mặt ${plate}" loading="lazy" />
      </button>
    </div>
  `;
}

export function renderPaginationControls(totalItems, totalPages) {
  const dom = getDom();
  if (!dom.paginationControls) return;

  if (totalItems === 0) {
    if (dom.paginationRangeText) {
      dom.paginationRangeText.textContent = "Hiển thị 0–0";
    }
    dom.paginationControls.innerHTML = "";
    return;
  }

  const startIdx = (state.currentPage - 1) * state.pageSize + 1;
  const endIdx = Math.min(totalItems, state.currentPage * state.pageSize);
  if (dom.paginationRangeText) {
    dom.paginationRangeText.textContent = `Hiển thị ${startIdx}–${endIdx}`;
  }

  const pageItems = buildPageNumbers(totalPages, state.currentPage);
  const buttonsHtml = [];

  buttonsHtml.push(
    `<button type="button" class="page-btn" data-page="${state.currentPage - 1}" ${
      state.currentPage <= 1 ? "disabled" : ""
    } title="Trang trước">‹ Trước</button>`
  );

  pageItems.forEach((item) => {
    if (item === "...") {
      buttonsHtml.push(`<span class="page-ellipsis">…</span>`);
    } else {
      const activeClass = item === state.currentPage ? " active" : "";
      buttonsHtml.push(
        `<button type="button" class="page-btn${activeClass}" data-page="${item}">${item}</button>`
      );
    }
  });

  buttonsHtml.push(
    `<button type="button" class="page-btn" data-page="${state.currentPage + 1}" ${
      state.currentPage >= totalPages ? "disabled" : ""
    } title="Trang sau">Sau ›</button>`
  );

  dom.paginationControls.innerHTML = buttonsHtml.join("");
}

export function renderHistoryTable(records, matchedCount, totalRecords) {
  const dom = getDom();
  state.cachedHistoryRecords = Array.isArray(records) ? records : [];
  state.cachedMatchedCount =
    typeof matchedCount === "number"
      ? matchedCount
      : state.cachedHistoryRecords.length;
  state.cachedTotalRecords =
    typeof totalRecords === "number"
      ? totalRecords
      : state.cachedHistoryRecords.length;

  if (dom.ledgerCountText) {
    dom.ledgerCountText.textContent = `${state.cachedMatchedCount} / ${state.cachedTotalRecords}`;
  }

  const totalItems = state.cachedMatchedCount;
  const totalPages = Math.max(1, Math.ceil(totalItems / state.pageSize));
  if (state.currentPage > totalPages) {
    state.currentPage = totalPages;
  }
  if (state.currentPage < 1) {
    state.currentPage = 1;
  }

  if (!dom.historyTableBody) return;

  if (totalItems === 0 || state.cachedHistoryRecords.length === 0) {
    dom.historyTableBody.innerHTML = `
      <tr>
        <td colspan="6">Không có bản ghi nào khớp điều kiện lọc.</td>
      </tr>
    `;
    renderPaginationControls(0, 1);
    return;
  }

  // Hỗ trợ cả hai chế độ: server đã cắt đúng trang (<= pageSize) hoặc mảng nhiều trang
  const pageSlice =
    state.cachedHistoryRecords.length > state.pageSize
      ? state.cachedHistoryRecords.slice(
          (state.currentPage - 1) * state.pageSize,
          (state.currentPage - 1) * state.pageSize + state.pageSize
        )
      : state.cachedHistoryRecords;

  dom.historyTableBody.innerHTML = pageSlice
    .map(
      (row) => `
        <tr>
          <td><span class="plate-cell-main mono-num num">${escapeHtml(row["Biển số"])}</span></td>
          <td>${renderSnapshotCell(row)}</td>
          <td>${renderDirectionPill(row, state.faceMatchThreshold)}</td>
          <td class="n mono-num num">${escapeHtml(row["Thời gian nhận diện"])}</td>
          <td class="n mono-num num">#${escapeHtml(row["ID"])}</td>
          <td class="n">
            <button type="button" class="btn btn-sm btn-lost-case" data-record-id="${escapeHtml(row["ID"])}">
              Tra cứu mất xe
            </button>
          </td>
        </tr>
      `
    )
    .join("");

  renderPaginationControls(totalItems, totalPages);
}

export function setHistoryTableLoading(isLoading) {
  const dom = getDom();
  if (!dom.historyTableBody) return;
  dom.historyTableBody.classList.toggle("table-loading", Boolean(isLoading));
}

export function applyManagementData(data, includeRecords = true) {
  const dom = getDom();
  const records = data.records || [];
  if (data.stats) {
    state.cachedStatsData = data.stats;
  }
  const stats = data.stats || state.cachedStatsData || {
    total_records: records.length,
    today_records: 0,
    in_parking: 0,
    total_in: 0,
    total_out: 0,
  };

  if (dom.statInParking) {
    dom.statInParking.textContent = String(stats.in_parking ?? 0);
  }
  if (dom.statTodayRecords) {
    dom.statTodayRecords.textContent = String(stats.today_records ?? 0);
  }
  if (dom.statTotalRecords) {
    dom.statTotalRecords.textContent = String(stats.total_records ?? 0);
  }

  if (dom.tabCountAll) {
    dom.tabCountAll.textContent = String(stats.total_records ?? 0);
  }
  if (dom.tabCountParking) {
    dom.tabCountParking.textContent = String(stats.in_parking ?? 0);
  }
  if (dom.tabCountIn) {
    dom.tabCountIn.textContent = String(stats.total_in ?? 0);
  }
  if (dom.tabCountOut) {
    dom.tabCountOut.textContent = String(stats.total_out ?? 0);
  }

  if (data.revenue) {
    renderRevenueSection(data.revenue);
  }

  if (data.database_error) {
    showBanner(
      dom.managementAlertBox,
      "error",
      `Chưa kết nối được MySQL: ${data.database_error}`
    );
  } else {
    showBanner(dom.managementAlertBox, "", "");
  }

  if (includeRecords) {
    setHistoryTableLoading(false);
    if (typeof data.page === "number" && data.page >= 1) {
      state.currentPage = data.page;
    }
    const matched =
      typeof data.matched === "number" ? data.matched : records.length;
    renderHistoryTable(records, matched, stats.total_records ?? 0);
  }
}

export function prefetchNextOverviewPage(
  ver,
  query,
  statusFilter,
  page,
  size,
  totalItems,
  sortBy = ""
) {
  if (typeof ver !== "number" || ver < 0) return;
  const totalPages = Math.max(1, Math.ceil((Number(totalItems) || 0) / size));
  const nextPage = page + 1;
  if (nextPage > totalPages) return;

  const nextKey = makeOverviewCacheKey(
    ver,
    query,
    statusFilter,
    nextPage,
    size,
    sortBy
  );
  if (
    state.overviewPageCache.has(nextKey) ||
    state.overviewPrefetchInFlight.has(nextKey)
  ) {
    return;
  }

  state.overviewPrefetchInFlight.add(nextKey);
  getManagementOverview({
    q: query || undefined,
    status: statusFilter,
    sort: sortBy || undefined,
    page: nextPage,
    pageSize: size,
    includeRevenue: false,
  })
    .then((data) => {
      if (!data || data.database_error) return;
      const dataVer =
        typeof data.records_version === "number" ? data.records_version : ver;
      if (dataVer === state.lastRecordsVersion) {
        setOverviewClientCache(nextKey, data);
      }
    })
    .catch(() => {})
    .finally(() => {
      state.overviewPrefetchInFlight.delete(nextKey);
    });
}

export function updateDirectionSortHeaderUI() {
  const dom = getDom();
  if (!dom.thDirectionSort || !dom.directionSortIndicator) return;
  const isOutTab = state.activeStatusFilter === "direction_out";
  dom.thDirectionSort.classList.toggle("sortable-th", isOutTab);
  if (!isOutTab) {
    dom.thDirectionSort.removeAttribute("title");
    dom.directionSortIndicator.textContent = "";
    return;
  }
  dom.thDirectionSort.title =
    "Bấm để sắp xếp Ra bãi lệch mặt / không lệch mặt";
  if (state.activeDirectionSort === "mismatch_first") {
    dom.directionSortIndicator.textContent = "▾";
  } else if (state.activeDirectionSort === "matched_first") {
    dom.directionSortIndicator.textContent = "▴";
  } else {
    dom.directionSortIndicator.textContent = "⇅";
  }
}

export async function fetchManagementOverview(options = {}) {
  const dom = getDom();
  const forceNetwork = Boolean(options && options.forceNetwork);
  const reqSeq = ++state.overviewReqSeq;

  const isRevenueOnly = state.activeViewId === "view-revenue";
  const query = ((dom.searchPlateInput && dom.searchPlateInput.value) || "").trim();
  const statusFilter = state.activeStatusFilter || "all";
  const sortBy =
    statusFilter === "direction_out" ? state.activeDirectionSort : "";
  const requestedPage = state.currentPage;
  const requestedSize = state.pageSize;

  // Trả ngay 0 ms từ RAM nếu trang đã có trong cache hoặc vừa được prefetch
  if (!forceNetwork && !isRevenueOnly && state.lastRecordsVersion >= 0) {
    const hitKey = makeOverviewCacheKey(
      state.lastRecordsVersion,
      query,
      statusFilter,
      requestedPage,
      requestedSize,
      sortBy
    );
    if (state.overviewPageCache.has(hitKey)) {
      const cachedPayload = state.overviewPageCache.get(hitKey);
      applyManagementData(cachedPayload, true);
      prefetchNextOverviewPage(
        state.lastRecordsVersion,
        query,
        statusFilter,
        state.currentPage,
        requestedSize,
        cachedPayload.matched,
        sortBy
      );
      return;
    }
  }
  if (
    !forceNetwork &&
    isRevenueOnly &&
    state.lastRecordsVersion >= 0 &&
    state.cachedRevenueData
  ) {
    if (state.cachedStatsData) {
      applyManagementData(
        {
          stats: state.cachedStatsData,
          revenue: state.cachedRevenueData,
          database_error: null,
        },
        false
      );
    } else {
      renderRevenueSection(state.cachedRevenueData);
    }
    return;
  }

  const reqParams = isRevenueOnly
    ? { includeRecords: false, includeRevenue: true }
    : {
        q: query || undefined,
        status: statusFilter,
        sort: sortBy || undefined,
        page: requestedPage,
        pageSize: requestedSize,
        includeRevenue: false,
      };

  if (!isRevenueOnly) {
    setHistoryTableLoading(true);
  }

  state.overviewInFlight = true;
  try {
    const data = await getManagementOverview(reqParams);
    if (reqSeq !== state.overviewReqSeq) return;
    if (typeof data.records_version === "number") {
      if (data.records_version !== state.lastRecordsVersion) {
        clearClientManagementCaches();
      }
      state.lastRecordsVersion = data.records_version;
    }
    applyManagementData(data, !isRevenueOnly);
    if (
      !isRevenueOnly &&
      !data.database_error &&
      state.lastRecordsVersion >= 0
    ) {
      const resolvedPage =
        typeof data.page === "number" && data.page >= 1
          ? data.page
          : requestedPage;
      const storeKey = makeOverviewCacheKey(
        state.lastRecordsVersion,
        query,
        statusFilter,
        resolvedPage,
        requestedSize,
        sortBy
      );
      setOverviewClientCache(storeKey, data);
      prefetchNextOverviewPage(
        state.lastRecordsVersion,
        query,
        statusFilter,
        resolvedPage,
        requestedSize,
        data.matched,
        sortBy
      );
    }
  } catch (_) {
    if (reqSeq !== state.overviewReqSeq) return;
    setHistoryTableLoading(false);
    showBanner(
      dom.managementAlertBox,
      "error",
      "Không kết nối được tới máy chủ FastAPI."
    );
  } finally {
    if (reqSeq === state.overviewReqSeq) {
      state.overviewInFlight = false;
    }
  }
}

export async function handleRefreshManagement() {
  const dom = getDom();
  if (dom.btnRefreshManagement) dom.btnRefreshManagement.disabled = true;
  clearClientManagementCaches();
  state.cachedRevenueData = null;
  try {
    await reconnectDatabase();
    await fetchManagementOverview({ forceNetwork: true });
    showBanner(dom.managementAlertBox, "success", "Đã làm mới dữ liệu từ MySQL.");
  } catch (err) {
    await fetchManagementOverview({ forceNetwork: true });
    const msg =
      err && err.data && err.data.detail
        ? err.data.detail
        : err && err.status
        ? "Chưa kết nối được MySQL."
        : (err && err.message) || "Chưa kết nối được MySQL.";
    showBanner(dom.managementAlertBox, "error", msg);
  } finally {
    if (dom.btnRefreshManagement) dom.btnRefreshManagement.disabled = false;
  }
}

export function activateView(targetId) {
  const dom = getDom();
  state.activeViewId = targetId;
  dom.navItems.forEach((btn) => {
    if (!btn) return;
    const isMatch = btn.getAttribute("data-target") === targetId;
    if (isMatch) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
  });

  dom.views.forEach((section) => {
    section.classList.toggle("active", section.id === targetId);
  });

  if (targetId === "view-management" || targetId === "view-revenue") {
    fetchManagementOverview();
  }
}

export function bindHistoryRowActions() {
  const dom = getDom();
  const targetContainer = dom.historyTableBody || document;
  targetContainer.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-record-id]");
    if (!btn) return;
    const recId = Number(btn.getAttribute("data-record-id"));
    const row = state.cachedHistoryRecords.find((r) => Number(r["ID"]) === recId);
    if (!row) return;
    if (btn.classList.contains("snap-thumb-btn")) {
      openSingleSnapshotModalByRow(row);
    } else {
      openLostVehicleModalByRow(row);
    }
  });
}
