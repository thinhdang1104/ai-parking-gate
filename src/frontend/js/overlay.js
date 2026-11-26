/* ==========================================================================
   Canvas Overlay Renderer for Plate & Face Bounding Boxes
   ========================================================================== */

export function clearOverlayCanvas(canvasEl) {
  if (!canvasEl) return;
  const ctx = canvasEl.getContext("2d");
  ctx.clearRect(0, 0, canvasEl.width || 640, canvasEl.height || 480);
}

export function drawOverlayBoxes(videoEl, canvasEl, boxData) {
  if (!canvasEl) return;
  const rect = canvasEl.getBoundingClientRect();
  const cw = Math.round(rect.width) || 640;
  const ch = Math.round(rect.height) || 480;
  if (canvasEl.width !== cw || canvasEl.height !== ch) {
    canvasEl.width = cw;
    canvasEl.height = ch;
  }
  const ctx = canvasEl.getContext("2d");
  ctx.clearRect(0, 0, cw, ch);
  if (!boxData || !videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return;

  const vw = videoEl.videoWidth;
  const vh = videoEl.videoHeight;
  const scale = Math.min(cw / vw, ch / vh);
  const drawW = vw * scale;
  const drawH = vh * scale;
  const offsetX = (cw - drawW) / 2;
  const offsetY = (ch - drawH) / 2;

  ctx.font = "600 13px 'JetBrains Mono', monospace";
  ctx.lineWidth = 2.5;

  (boxData.plates || []).forEach((b) => {
    const x = offsetX + b.x1 * drawW;
    const y = offsetY + b.y1 * drawH;
    const w = (b.x2 - b.x1) * drawW;
    const h = (b.y2 - b.y1) * drawH;
    const color = b.valid ? "#22c55e" : "#f59e0b";
    ctx.strokeStyle = color;
    ctx.strokeRect(x, y, w, h);
    if (b.label) {
      const tw = ctx.measureText(b.label).width + 12;
      const ly = Math.max(0, y - 24);
      ctx.fillStyle = "rgba(6, 7, 9, 0.85)";
      ctx.fillRect(x, ly, tw, 22);
      ctx.fillStyle = "#fde047";
      ctx.fillText(b.label, x + 6, ly + 15);
    }
  });

  (boxData.faces || []).forEach((f) => {
    const x = offsetX + f.x1 * drawW;
    const y = offsetY + f.y1 * drawH;
    const w = (f.x2 - f.x1) * drawW;
    const h = (f.y2 - f.y1) * drawH;
    ctx.strokeStyle = "#d946ef";
    ctx.strokeRect(x, y, w, h);
    if (f.label) {
      const tw = ctx.measureText(f.label).width + 12;
      const ly = Math.max(0, y - 24);
      ctx.fillStyle = "rgba(6, 7, 9, 0.85)";
      ctx.fillRect(x, ly, tw, 22);
      ctx.fillStyle = "#f0abfc";
      ctx.fillText(f.label, x + 6, ly + 15);
    }
  });
}
