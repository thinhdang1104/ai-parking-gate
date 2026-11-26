/* ==========================================================================
   A4 Printable PDF Report Exporter (History / Revenue / Lost Vehicle Case)
   ========================================================================== */

import { getManagementOverview } from "./api.js";
import { getDom, state } from "./state.js";
import {
  escapeHtml,
  formatCurrentTimestamp,
  formatVnd,
  getRowSnapshots,
} from "./utils.js";

export function openPrintablePdfDocument(docTitle, bodyHtml) {
  const fullHtml = `<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <title>${escapeHtml(docTitle)}</title>
  <style>
    @page { size: A4; margin: 14mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif;
      color: #0f172a;
      background: #ffffff;
      font-size: 12.5px;
      line-height: 1.45;
    }
    .report-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 2px solid #0f172a;
      padding-bottom: 10px;
      margin-bottom: 14px;
    }
    .report-title {
      margin: 0 0 4px 0;
      font-size: 18px;
      font-weight: 700;
      text-transform: uppercase;
      color: #0f172a;
    }
    .report-subtitle {
      margin: 0;
      font-size: 12px;
      color: #475569;
    }
    .report-meta {
      text-align: right;
      font-size: 11.5px;
      color: #334155;
    }
    .kpi-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .kpi-box {
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      padding: 8px 12px;
      background: #f8fafc;
    }
    .kpi-box-label {
      font-size: 11px;
      color: #64748b;
      display: block;
      margin-bottom: 2px;
    }
    .kpi-box-val {
      font-size: 16px;
      font-weight: 700;
      color: #0f172a;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
    }
    th, td {
      border: 1px solid #cbd5e1;
      padding: 6px 8px;
      text-align: left;
      vertical-align: middle;
      font-size: 12px;
    }
    th {
      background: #f1f5f9;
      font-weight: 700;
      color: #1e293b;
    }
    td.n, th.n {
      text-align: right;
    }
    .thumb-pair {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .thumb-plate {
      width: 58px;
      height: 28px;
      object-fit: cover;
      border: 1px solid #94a3b8;
      border-radius: 3px;
    }
    .thumb-face {
      width: 28px;
      height: 28px;
      object-fit: cover;
      border: 1px solid #94a3b8;
      border-radius: 50%;
    }
    .verdict-box {
      border: 1px solid #94a3b8;
      background: #f8fafc;
      border-radius: 6px;
      padding: 10px 12px;
      font-weight: 600;
      margin-bottom: 14px;
    }
    .case-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 12px;
    }
    .case-col {
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      padding: 10px;
    }
    .case-col h4 {
      margin: 0 0 8px 0;
      font-size: 13px;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 5px;
    }
    .case-img-box {
      margin-top: 8px;
      text-align: center;
    }
    .case-img-box img {
      max-width: 100%;
      height: 110px;
      object-fit: contain;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      background: #0f172a;
    }
  </style>
</head>
<body>
  ${bodyHtml}
</body>
</html>`;

  const printWin =
    typeof window.open === "function"
      ? window.open("", "_blank", "width=980,height=740")
      : null;
  if (printWin && printWin.document) {
    printWin.document.open();
    printWin.document.write(fullHtml);
    printWin.document.close();
    setTimeout(() => {
      try {
        printWin.focus();
        printWin.print();
      } catch (_) {}
    }, 280);
    return { mode: "popup", html: fullHtml };
  }

  // Fallback khi trình duyệt chặn Popup: tạo <iframe> ẩn và gọi contentWindow.print() trên đúng mẫu A4 nền trắng
  if (
    document &&
    typeof document.createElement === "function" &&
    document.body
  ) {
    const iframe = document.createElement("iframe");
    iframe.style.cssText =
      "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden;";
    document.body.appendChild(iframe);
    const idoc =
      iframe.contentDocument ||
      (iframe.contentWindow && iframe.contentWindow.document);
    if (idoc) {
      idoc.open();
      idoc.write(fullHtml);
      idoc.close();
    }
    const cleanupIframe = () => {
      try {
        iframe.remove();
      } catch (_) {}
    };
    if (iframe.contentWindow) {
      iframe.contentWindow.onafterprint = cleanupIframe;
    }
    setTimeout(() => {
      try {
        if (iframe.contentWindow) {
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
        }
      } catch (_) {}
      setTimeout(cleanupIframe, 60000);
    }, 280);
    return { mode: "iframe", html: fullHtml };
  }

  if (typeof window.print === "function") {
    window.print();
  }
  return { mode: "fallback", html: fullHtml };
}

export async function exportHistoryPdfReport() {
  const dom = getDom();
  if (dom.btnExportHistoryPdf && dom.btnExportHistoryPdf.disabled) return null;
  if (dom.btnExportHistoryPdf) dom.btnExportHistoryPdf.disabled = true;

  try {
    const filterNameMap = {
      all: "Tất cả bản ghi",
      in_parking: "Đang gửi trong bãi",
      direction_in: "Lượt vào bãi",
      direction_out: "Lượt ra bãi",
    };
    const filterLabel =
      filterNameMap[state.activeStatusFilter] || "Tất cả bản ghi";
    const searchQuery = (
      (dom.searchPlateInput && dom.searchPlateInput.value) ||
      ""
    ).trim();
    const inParkingVal =
      (dom.statInParking && dom.statInParking.textContent) || "0";
    const todayVal =
      (dom.statTodayRecords && dom.statTodayRecords.textContent) || "0";
    const totalVal =
      (dom.statTotalRecords && dom.statTotalRecords.textContent) || "0";

    let recordsForPdf = state.cachedHistoryRecords;
    let totalMatchedForPdf =
      state.cachedMatchedCount || state.cachedHistoryRecords.length;
    try {
      const data = await getManagementOverview({
        q: searchQuery || undefined,
        status: state.activeStatusFilter,
        sort:
          state.activeStatusFilter === "direction_out" &&
          state.activeDirectionSort
            ? state.activeDirectionSort
            : undefined,
        limit: 200,
      });
      if (data && Array.isArray(data.records)) {
        recordsForPdf = data.records;
        totalMatchedForPdf =
          typeof data.matched === "number" ? data.matched : data.records.length;
      }
    } catch (_) {}

    const rowsHtml =
      recordsForPdf.length === 0
        ? `<tr><td colspan="6">Không có bản ghi nào khớp điều kiện lọc.</td></tr>`
        : recordsForPdf
            .map((row) => {
              const snap = getRowSnapshots(row);
              const imgHtml =
                snap.hasRealPlate || snap.hasRealFace
                  ? `<span class="thumb-pair">
                      ${snap.hasRealPlate ? `<img class="thumb-plate" src="${snap.realPlateImg}" alt="Biển số" />` : `<span>Không có ảnh biển</span>`}
                      ${snap.hasRealFace ? `<img class="thumb-face" src="${snap.realFaceImg}" alt="Khuôn mặt" />` : `<span>Không có ảnh mặt</span>`}
                    </span>`
                  : "Không có ảnh lưu trữ";
              return `
                <tr>
                  <td><strong>${escapeHtml(row["Biển số"])}</strong></td>
                  <td>${imgHtml}</td>
                  <td>${escapeHtml(row["Luồng"])}</td>
                  <td>${escapeHtml(row["Đối chiếu"] || "-")}</td>
                  <td class="n">${escapeHtml(row["Thời gian nhận diện"])}</td>
                  <td class="n">#${escapeHtml(row["ID"])}</td>
                </tr>
              `;
            })
            .join("");

    const limitNote =
      totalMatchedForPdf > recordsForPdf.length
        ? ` (hiển thị ${recordsForPdf.length}/${totalMatchedForPdf} bản ghi mới nhất)`
        : "";

    const bodyHtml = `
      <header class="report-header">
        <div>
          <h1 class="report-title">BÁO CÁO LỊCH SỬ &amp; QUẢN LÝ RA VÀO BÃI XE</h1>
          <p class="report-subtitle">Hệ thống Quản lý Bãi giữ xe Trường học AI Nhận diện Biển số &amp; Khuôn mặt</p>
        </div>
        <div class="report-meta">
          <div>Ngày xuất: <strong>${escapeHtml(formatCurrentTimestamp())}</strong></div>
          <div>Bộ lọc: <strong>${escapeHtml(filterLabel)}</strong>${
      searchQuery ? ` · Tìm biển số: <strong>${escapeHtml(searchQuery)}</strong>` : ""
    }</div>
        </div>
      </header>

      <div class="kpi-strip">
        <div class="kpi-box">
          <span class="kpi-box-label">Đang gửi trong bãi</span>
          <strong class="kpi-box-val">${escapeHtml(inParkingVal)}</strong>
        </div>
        <div class="kpi-box">
          <span class="kpi-box-label">Lượt vào / ra hôm nay</span>
          <strong class="kpi-box-val">${escapeHtml(todayVal)}</strong>
        </div>
        <div class="kpi-box">
          <span class="kpi-box-label">Tổng lượt lưu trữ</span>
          <strong class="kpi-box-val">${escapeHtml(totalVal)}</strong>
        </div>
        <div class="kpi-box">
          <span class="kpi-box-label">Số bản ghi trong báo cáo</span>
          <strong class="kpi-box-val">${escapeHtml(recordsForPdf.length)}${escapeHtml(limitNote)}</strong>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Biển số xe</th>
            <th>Ảnh cắt (Biển &amp; Mặt)</th>
            <th>Luồng</th>
            <th>Đối chiếu FaceNet</th>
            <th class="n">Thời gian</th>
            <th class="n">Mã ghi</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    `;

    return openPrintablePdfDocument("Bao_Cao_Lich_Su_Bai_Xe", bodyHtml);
  } finally {
    if (dom.btnExportHistoryPdf) dom.btnExportHistoryPdf.disabled = false;
  }
}

export function exportRevenuePdfReport() {
  const periodLabelMap = {
    daily: "Theo ngày (DD/MM/YYYY)",
    monthly: "Theo tháng (MM/YYYY)",
    yearly: "Theo năm (YYYY)",
  };
  const periodTitle =
    periodLabelMap[state.activeRevenuePeriod] || "Kỳ thống kê";
  const rev = state.cachedRevenueData || {};
  const unitFee = rev.unit_price || 2000;
  const unitFeeText = formatVnd(unitFee);
  const today = rev.today || { tickets: 0, revenue: 0 };
  const month = rev.month || { tickets: 0, revenue: 0 };
  const year = rev.year || { tickets: 0, revenue: 0 };
  const total = rev.total || { tickets: 0, revenue: 0 };
  const rows = rev[state.activeRevenuePeriod] || [];

  const rowsHtml =
    rows.length === 0
      ? `<tr><td colspan="4">Chưa có dữ liệu doanh thu trong kỳ này.</td></tr>`
      : rows
          .map(
            (item) => `
              <tr>
                <td><strong>${escapeHtml(item.period)}</strong></td>
                <td class="n">${escapeHtml(item.tickets)} lượt</td>
                <td class="n">${escapeHtml(unitFeeText)}</td>
                <td class="n"><strong>${escapeHtml(formatVnd(item.revenue))}</strong></td>
              </tr>
            `
          )
          .join("");

  const bodyHtml = `
    <header class="report-header">
      <div>
        <h1 class="report-title">BÁO CÁO QUẢN LÝ DOANH THU GIỮ XE</h1>
        <p class="report-subtitle">Đơn giá áp dụng: ${escapeHtml(unitFeeText)} / lượt gửi · Chu kỳ bảng: ${escapeHtml(periodTitle)}</p>
      </div>
      <div class="report-meta">
        <div>Ngày xuất: <strong>${escapeHtml(formatCurrentTimestamp())}</strong></div>
      </div>
    </header>

    <div class="kpi-strip">
      <div class="kpi-box">
        <span class="kpi-box-label">Doanh thu hôm nay (${escapeHtml(today.tickets ?? 0)} lượt)</span>
        <strong class="kpi-box-val">${escapeHtml(formatVnd(today.revenue))}</strong>
      </div>
      <div class="kpi-box">
        <span class="kpi-box-label">Doanh thu tháng này (${escapeHtml(month.tickets ?? 0)} lượt)</span>
        <strong class="kpi-box-val">${escapeHtml(formatVnd(month.revenue))}</strong>
      </div>
      <div class="kpi-box">
        <span class="kpi-box-label">Doanh thu năm nay (${escapeHtml(year.tickets ?? 0)} lượt)</span>
        <strong class="kpi-box-val">${escapeHtml(formatVnd(year.revenue))}</strong>
      </div>
      <div class="kpi-box">
        <span class="kpi-box-label">Tổng doanh thu tích lũy (${escapeHtml(total.tickets ?? 0)} lượt)</span>
        <strong class="kpi-box-val">${escapeHtml(formatVnd(total.revenue))}</strong>
      </div>
    </div>

    <table>
      <thead>
        <tr>
          <th>${escapeHtml(periodTitle)}</th>
          <th class="n">Số lượt gửi xe</th>
          <th class="n">Đơn giá / lượt</th>
          <th class="n">Tổng doanh thu</th>
        </tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  `;

  return openPrintablePdfDocument("Bao_Cao_Doanh_Thu_Bai_Xe", bodyHtml);
}

export function exportLostCasePdfReport() {
  if (!state.activeLostCase) return null;
  const c = state.activeLostCase;
  const bodyHtml = `
    <header class="report-header">
      <div>
        <h1 class="report-title">BIÊN BẢN TRA CỨU &amp; XỬ LÝ TÌNH HUỐNG MẤT XE</h1>
        <p class="report-subtitle">Biển số tra cứu: <strong>${escapeHtml(c.plateNumber)}</strong></p>
      </div>
      <div class="report-meta">
        <div>Ngày xuất: <strong>${escapeHtml(formatCurrentTimestamp())}</strong></div>
      </div>
    </header>

    <div class="verdict-box">${escapeHtml(c.verdictText)}</div>

    <div class="case-grid">
      <div class="case-col">
        <h4>1. CHECK IN (LÚC GỬI XE)</h4>
        <div>Mã bản ghi: <strong>${c.checkinRow ? `#${escapeHtml(c.checkinRow["ID"])}` : "-"}</strong></div>
        <div>Thời gian vào: <strong>${escapeHtml(c.checkinRow ? c.checkinRow["Thời gian nhận diện"] : "-")}</strong></div>
        <div>Biển số: <strong>${escapeHtml(c.plateNumber)}</strong></div>
        <div class="case-img-box">
          <div>Ảnh biển số Check-in</div>
          ${c.checkinSnap.realPlateImg ? `<img src="${c.checkinSnap.realPlateImg}" alt="Biển số lúc vào" />` : `<p>Không có ảnh lưu trữ</p>`}
        </div>
        <div class="case-img-box">
          <div>Ảnh khuôn mặt Người gửi xe</div>
          ${c.checkinSnap.realFaceImg ? `<img src="${c.checkinSnap.realFaceImg}" alt="Người gửi xe" />` : `<p>Không có ảnh lưu trữ</p>`}
        </div>
      </div>

      <div class="case-col">
        <h4>2. CHECK OUT (LÚC LẤY XE)</h4>
        <div>Mã bản ghi: <strong>${c.checkoutRow ? `#${escapeHtml(c.checkoutRow["ID"])}` : c.sessionClosedMissingExit ? "Phiên đã đóng, thiếu thông tin lượt ra" : "Chưa có lượt ra"}</strong></div>
        <div>Thời gian ra: <strong>${escapeHtml(c.checkoutRow ? c.checkoutRow["Thời gian nhận diện"] : c.sessionClosedMissingExit ? "Phiên đã đóng, thiếu thông tin lượt ra" : "Chưa có lượt ra")}</strong></div>
        <div>Đối chiếu FaceNet: <strong>${escapeHtml(c.matchLabel)}</strong></div>
        ${
          c.checkoutSnap
            ? `<div class="case-img-box">
                <div>Ảnh biển số Check-out</div>
                ${c.checkoutSnap.realPlateImg ? `<img src="${c.checkoutSnap.realPlateImg}" alt="Biển số lúc ra" />` : `<p>Không có ảnh lưu trữ</p>`}
              </div>`
            : `<p>${c.sessionClosedMissingExit ? "Phiên đã đóng, thiếu thông tin lượt ra." : "Chưa ghi nhận lượt Check-out qua cổng."}</p>`
        }
      </div>

      <div class="case-col">
        <h4>3. NGƯỜI LẤY XE</h4>
        <div>Kết quả đối chiếu: <strong>${escapeHtml(c.matchLabel)}</strong></div>
        ${
          c.checkoutSnap
            ? `<div class="case-img-box">
                <div>Ảnh khuôn mặt Người lấy xe</div>
                ${c.checkoutSnap.realFaceImg ? `<img src="${c.checkoutSnap.realFaceImg}" alt="Người lấy xe" />` : `<p>Không có ảnh lưu trữ</p>`}
              </div>`
            : `<p>Chưa có ảnh Người lấy xe.</p>`
        }
        <p>${escapeHtml(c.takerNote)}</p>
      </div>
    </div>
  `;
  return openPrintablePdfDocument(`Bien_Ban_Mat_Xe_${c.plateNumber}`, bodyHtml);
}
