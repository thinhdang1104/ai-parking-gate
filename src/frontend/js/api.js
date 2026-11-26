/* ==========================================================================
   Centralized REST API client for DATN2 FastAPI backend
   ========================================================================== */

/**
 * Execute a fetch request and parse JSON response with normalized error handling.
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
async function requestJson(url, options = {}) {
  const res = await fetch(url, options);
  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    data = null;
  }
  if (!res.ok) {
    const detail =
      data && typeof data.detail === "string" && data.detail.trim()
        ? data.detail.trim()
        : "";
    const err = new Error(detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export async function getCameraStatus() {
  return requestJson("/api/camera/status");
}

export async function startCamera(camId) {
  return requestJson(`/api/camera/${camId}/start`, { method: "POST" });
}

export async function stopCamera(camId) {
  return requestJson(`/api/camera/${camId}/stop`, { method: "POST" });
}

export async function stopAllCameras() {
  return requestJson("/api/camera/stop", { method: "POST" });
}

export async function sendBrowserFrame(cam1Image, cam2Image) {
  return requestJson("/api/camera/browser-frame", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cam1_image: cam1Image ?? null,
      cam2_image: cam2Image ?? null,
    }),
  });
}

export async function cancelLatch() {
  return requestJson("/api/camera/cancel-latch", { method: "POST" });
}

export async function resolveAlert(action) {
  return requestJson("/api/camera/resolve-alert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}

/**
 * Fetch management overview (stats, optional revenue report, and filtered history).
 * @param {Object} [params]
 * @returns {Promise<any>}
 */
export async function getManagementOverview(params = {}) {
  const qs = new URLSearchParams();
  if (params.q) {
    qs.set("q", String(params.q));
  }
  if (params.status && params.status !== "all") {
    qs.set("status", String(params.status));
  }
  if (params.sort) {
    qs.set("sort", String(params.sort));
  }
  if (params.limit !== undefined && params.limit !== null) {
    qs.set("limit", String(params.limit));
  }
  if (params.page !== undefined && params.page !== null) {
    qs.set("page", String(params.page));
  }
  const pageSize =
    params.pageSize !== undefined && params.pageSize !== null
      ? params.pageSize
      : params.page_size;
  if (pageSize !== undefined && pageSize !== null) {
    qs.set("page_size", String(pageSize));
  }
  const includeRecords =
    params.includeRecords !== undefined
      ? params.includeRecords
      : params.include_records;
  if (includeRecords !== undefined && includeRecords !== null) {
    qs.set("include_records", String(Boolean(includeRecords)));
  }
  const includeRevenue =
    params.includeRevenue !== undefined
      ? params.includeRevenue
      : params.include_revenue;
  if (includeRevenue !== undefined && includeRevenue !== null) {
    qs.set("include_revenue", String(Boolean(includeRevenue)));
  }

  const queryStr = qs.toString();
  const url = queryStr
    ? `/api/management/overview?${queryStr}`
    : "/api/management/overview";
  return requestJson(url);
}

export async function getSessionCase(recordId) {
  return requestJson(`/api/management/session-case/${recordId}`);
}

export async function reconnectDatabase() {
  return requestJson("/api/management/reconnect", { method: "POST" });
}
