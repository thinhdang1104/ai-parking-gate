/* ==========================================================================
   Revenue Report Summary Cards, Breakdown Table & Pagination
   ========================================================================== */

import { getDom, state } from "./state.js";
import { buildPageNumbers, escapeHtml, formatVnd } from "./utils.js";

export function renderRevenuePaginationControls(totalItems, totalPages) {
  const dom = getDom();
  if (!dom.revPaginationControls) return;

  if (totalItems === 0) {
    if (dom.revPaginationRangeText) {
      dom.revPaginationRangeText.textContent = "Hiển thị 0–0";
    }
    dom.revPaginationControls.innerHTML = "";
    return;
  }

  const startIdx = (state.revCurrentPage - 1) * state.revPageSize + 1;
  const endIdx = Math.min(totalItems, state.revCurrentPage * state.revPageSize);
  if (dom.revPaginationRangeText) {
    dom.revPaginationRangeText.textContent = `Hiển thị ${startIdx}–${endIdx}`;
  }

  const pageItems = buildPageNumbers(totalPages, state.revCurrentPage);
  const buttonsHtml = [];

  buttonsHtml.push(
    `<button type="button" class="page-btn" data-rev-page="${state.revCurrentPage - 1}" ${
      state.revCurrentPage <= 1 ? "disabled" : ""
    } title="Trang trước">‹ Trước</button>`
  );

  pageItems.forEach((item) => {
    if (item === "...") {
      buttonsHtml.push(`<span class="page-ellipsis">…</span>`);
    } else {
      const activeClass = item === state.revCurrentPage ? " active" : "";
      buttonsHtml.push(
        `<button type="button" class="page-btn${activeClass}" data-rev-page="${item}">${item}</button>`
      );
    }
  });

  buttonsHtml.push(
    `<button type="button" class="page-btn" data-rev-page="${state.revCurrentPage + 1}" ${
      state.revCurrentPage >= totalPages ? "disabled" : ""
    } title="Trang sau">Sau ›</button>`
  );

  dom.revPaginationControls.innerHTML = buttonsHtml.join("");
}

export function renderRevenueBreakdownTable() {
  const dom = getDom();
  if (!dom.revenueTableBody) return;

  const titleMap = {
    daily: "Ngày (DD/MM/YYYY)",
    monthly: "Tháng (MM/YYYY)",
    yearly: "Năm (YYYY)",
  };
  if (dom.revenuePeriodColTitle) {
    dom.revenuePeriodColTitle.textContent =
      titleMap[state.activeRevenuePeriod] || "Kỳ thống kê";
  }

  const unitFee =
    (state.cachedRevenueData && state.cachedRevenueData.unit_price) || 2000;
  const unitFeeText = formatVnd(unitFee);
  if (dom.revenueUnitPill) {
    dom.revenueUnitPill.textContent = `Đơn giá: ${unitFeeText} / lượt gửi`;
  }
  const rows =
    (state.cachedRevenueData &&
      state.cachedRevenueData[state.activeRevenuePeriod]) ||
    [];

  if (!rows || rows.length === 0) {
    dom.revenueTableBody.innerHTML = `
      <tr>
        <td colspan="4">Chưa có dữ liệu doanh thu trong kỳ này.</td>
      </tr>
    `;
    renderRevenuePaginationControls(0, 1);
    return;
  }

  const totalItems = rows.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / state.revPageSize));
  if (state.revCurrentPage > totalPages) state.revCurrentPage = totalPages;
  if (state.revCurrentPage < 1) state.revCurrentPage = 1;

  const startOffset = (state.revCurrentPage - 1) * state.revPageSize;
  const pageRows = rows.slice(startOffset, startOffset + state.revPageSize);

  dom.revenueTableBody.innerHTML = pageRows
    .map(
      (item) => `
        <tr>
          <td class="mono-num num"><strong>${escapeHtml(item.period)}</strong></td>
          <td class="n mono-num num">${escapeHtml(item.tickets)} lượt</td>
          <td class="n mono-num num">${escapeHtml(unitFeeText)}</td>
          <td class="n mono-num num"><span class="fee-cell-amount">${escapeHtml(formatVnd(item.revenue))}</span></td>
        </tr>
      `
    )
    .join("");

  renderRevenuePaginationControls(totalItems, totalPages);
}

export function renderRevenueSection(revenue) {
  const dom = getDom();
  state.cachedRevenueData = revenue || null;
  const today = (revenue && revenue.today) || { tickets: 0, revenue: 0 };
  const month = (revenue && revenue.month) || { tickets: 0, revenue: 0 };
  const year = (revenue && revenue.year) || { tickets: 0, revenue: 0 };
  const total = (revenue && revenue.total) || { tickets: 0, revenue: 0 };

  if (dom.revTodayAmount) dom.revTodayAmount.textContent = formatVnd(today.revenue);
  if (dom.revTodayTickets) {
    dom.revTodayTickets.textContent = `${today.tickets ?? 0} lượt gửi xe`;
  }

  if (dom.revMonthAmount) dom.revMonthAmount.textContent = formatVnd(month.revenue);
  if (dom.revMonthTickets) {
    dom.revMonthTickets.textContent = `${month.tickets ?? 0} lượt gửi xe`;
  }

  if (dom.revYearAmount) dom.revYearAmount.textContent = formatVnd(year.revenue);
  if (dom.revYearTickets) {
    dom.revYearTickets.textContent = `${year.tickets ?? 0} lượt gửi xe`;
  }

  if (dom.revTotalAmount) dom.revTotalAmount.textContent = formatVnd(total.revenue);
  if (dom.revTotalTickets) {
    dom.revTotalTickets.textContent = `${total.tickets ?? 0} lượt gửi xe`;
  }

  renderRevenueBreakdownTable();
}

export function setRevenuePeriod(period) {
  const dom = getDom();
  const nextPeriod = period || "daily";
  dom.revPeriodBtns.forEach((b) => {
    const isMatch = b.getAttribute("data-rev-period") === nextPeriod;
    b.setAttribute("aria-pressed", isMatch ? "true" : "false");
    b.classList.toggle("highlight-card", isMatch);
  });
  state.activeRevenuePeriod = nextPeriod;
  state.revCurrentPage = 1;
  renderRevenueBreakdownTable();
}

export function setRevenuePageSize(size) {
  const val = parseInt(String(size || "10"), 10);
  state.revPageSize = Number.isNaN(val) || val < 1 ? 10 : val;
  state.revCurrentPage = 1;
  renderRevenueBreakdownTable();
}

export function setRevenuePage(page) {
  const targetPage = parseInt(String(page || "1"), 10);
  if (!Number.isNaN(targetPage) && targetPage !== state.revCurrentPage) {
    state.revCurrentPage = targetPage;
    renderRevenueBreakdownTable();
  }
}
