/* ==========================================================================
   Shared DOM, Formatting, SVG Fallback & Pagination Utilities
   ========================================================================== */

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function formatVnd(amount) {
  const val = Math.max(0, Number(amount) || 0);
  return `${val.toLocaleString("de-DE")} đ`;
}

export function formatCurrentTimestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function showBanner(box, type, message, durationMs = 0) {
  if (!box) return;
  const isTopupToast =
    box.id === "gate-topup-box" ||
    (box.classList && box.classList.contains("topup-toast"));
  const baseClass = isTopupToast ? "topup-toast" : "notice-banner";
  if (box._hideTimer) {
    clearTimeout(box._hideTimer);
    box._hideTimer = null;
  }
  if (!message) {
    box.className = `${baseClass} hidden`;
    box.textContent = "";
    return;
  }
  box.className = type ? `${baseClass} notice-${type}` : baseClass;
  box.textContent = message;
  if (durationMs > 0) {
    box._hideTimer = setTimeout(() => {
      box.className = `${baseClass} hidden`;
      box.textContent = "";
      box._hideTimer = null;
    }, durationMs);
  }
}

export function makeFallbackPlateSvg(plateText) {
  const raw = String(plateText || "59A1-12345").trim();
  const parts = raw.split("-");
  const topLine = escapeHtml(parts[0] || raw);
  const botLine = escapeHtml(parts[1] || "");
  const svg = botLine
    ? `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="96" viewBox="0 0 200 96">
        <rect x="3" y="3" width="194" height="90" rx="8" fill="#f8fafc" stroke="#1e293b" stroke-width="4"/>
        <rect x="7" y="7" width="186" height="82" rx="5" fill="none" stroke="#0f172a" stroke-width="1.5"/>
        <text x="100" y="42" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="800" font-size="28" fill="#0f172a">${topLine}</text>
        <text x="100" y="78" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="800" font-size="28" fill="#0f172a">${botLine}</text>
      </svg>`
    : `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="96" viewBox="0 0 200 96">
        <rect x="3" y="3" width="194" height="90" rx="8" fill="#f8fafc" stroke="#1e293b" stroke-width="4"/>
        <text x="100" y="58" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="800" font-size="24" fill="#0f172a">${topLine}</text>
      </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function makeFallbackFaceSvg(plateText, faceLabel) {
  const seed = Array.from(String(plateText || "X")).reduce(
    (s, c) => s + c.charCodeAt(0),
    0
  );
  const hues = [200, 265, 150, 32, 330, 185];
  const hue = hues[seed % hues.length];
  const conf = escapeHtml(String(faceLabel || "").replace(/[^0-9%]/g, "") || "-");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
    <rect width="160" height="160" rx="16" fill="hsl(${hue}, 35%, 16%)"/>
    <circle cx="80" cy="58" r="28" fill="hsl(${hue}, 70%, 65%)"/>
    <path d="M32 138 C32 102, 128 102, 128 138" fill="hsl(${hue}, 70%, 65%)"/>
    <rect x="14" y="14" width="132" height="132" rx="10" fill="none" stroke="#d946ef" stroke-width="3" stroke-dasharray="10 6"/>
    <rect x="86" y="118" width="56" height="24" rx="5" fill="rgba(6,7,9,0.82)"/>
    <text x="114" y="135" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="700" font-size="13" fill="#f0abfc">${conf}</text>
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function getRowSnapshots(row) {
  if (!row) {
    return {
      plateImg: "",
      faceImg: "",
      hasRealPlate: false,
      hasRealFace: false,
    };
  }
  const hasRealPlate = Boolean(row.plate_image);
  const hasRealFace = Boolean(row.face_image);
  const plateImg = row.plate_image || makeFallbackPlateSvg(row["Biển số"]);
  const faceImg =
    row.face_image || makeFallbackFaceSvg(row["Biển số"], row["Khuôn mặt"]);
  return {
    plateImg,
    faceImg,
    realPlateImg: row.plate_image || "",
    realFaceImg: row.face_image || "",
    hasRealPlate,
    hasRealFace,
  };
}

export function buildPageNumbers(totalPages, current) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const pages = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(totalPages - 1, current + 1);
  if (start > 2) pages.push("...");
  for (let p = start; p <= end; p += 1) {
    pages.push(p);
  }
  if (end < totalPages - 1) pages.push("...");
  pages.push(totalPages);
  return pages;
}

export function renderDirectionPill(row, faceMatchThreshold = 0.65) {
  const str = String(
    (row && typeof row === "object" ? row["Luồng"] : row) || "Vào bãi"
  );
  if (str.includes("Ra")) {
    const matchLabel =
      row && typeof row === "object" ? String(row["Đối chiếu"] || "") : "";
    const isMismatch =
      matchLabel.includes("Lệch") ||
      (row &&
        typeof row === "object" &&
        typeof row.face_match_score === "number" &&
        row.face_match_score < faceMatchThreshold);
    const pillClass = isMismatch ? "pill neg" : "pill warn";
    return `<span class="${pillClass}">${escapeHtml(str)}</span>`;
  }
  return `<span class="pill pos">${escapeHtml(str)}</span>`;
}

export function applyImageOrEmptyHint(imgEl, emptyEl, srcUrl, emptyText) {
  if (srcUrl) {
    if (imgEl) {
      imgEl.src = srcUrl;
      imgEl.classList.remove("hidden");
    }
    if (emptyEl) {
      emptyEl.classList.add("hidden");
    }
  } else {
    if (imgEl) {
      imgEl.src = "";
      imgEl.classList.add("hidden");
    }
    if (emptyEl) {
      emptyEl.textContent = emptyText;
      emptyEl.classList.remove("hidden");
    }
  }
}
