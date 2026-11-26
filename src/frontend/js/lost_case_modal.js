/* ==========================================================================
   Snapshot Inspection & 3-Block Lost Vehicle Case Modal Controller
   ========================================================================== */

import { getSessionCase } from "./api.js";
import { getDom, state } from "./state.js";
import { applyImageOrEmptyHint, getRowSnapshots } from "./utils.js";

export function computeLostCaseDetails(
  checkinRow,
  checkoutRow,
  fallbackPlate = "-"
) {
  const plateNumber =
    (checkinRow && checkinRow["Biển số"]) ||
    (checkoutRow && checkoutRow["Biển số"]) ||
    fallbackPlate ||
    "-";

  const checkinSnap = checkinRow
    ? getRowSnapshots(checkinRow)
    : {
        plateImg: "",
        faceImg: "",
        realPlateImg: "",
        realFaceImg: "",
        hasRealPlate: false,
        hasRealFace: false,
      };
  const checkoutSnap = checkoutRow ? getRowSnapshots(checkoutRow) : null;

  const inStatusCode = checkinRow
    ? String(checkinRow.parking_status_code || "").toUpperCase()
    : "";
  const inStatusText = checkinRow
    ? String(checkinRow["Trạng thái bãi"] || "")
    : "";
  const sessionClosedMissingExit = Boolean(
    checkinRow &&
      !checkoutRow &&
      ((inStatusCode && inStatusCode !== "IN_PARKING") ||
        (inStatusText && !inStatusText.includes("Đang gửi")))
  );

  const matchLabel = checkoutRow
    ? String(checkoutRow["Đối chiếu"] || "-")
    : sessionClosedMissingExit
    ? "Phiên đã đóng, thiếu thông tin lượt ra"
    : "Chưa có lượt ra";

  const isMismatch =
    Boolean(checkoutRow) &&
    (matchLabel.includes("Lệch") ||
      (typeof checkoutRow.face_match_score === "number" &&
        checkoutRow.face_match_score < state.faceMatchThreshold));

  let verdictType = "warn";
  let verdictText = "";
  let takerNote = "";

  if (checkoutRow) {
    if (isMismatch) {
      verdictType = "alert";
      verdictText =
        `CẢNH BÁO NGHI VẤN MẤT XE: Xe ${plateNumber} đã Check-out lúc ${checkoutRow["Thời gian nhận diện"]} ` +
        `với khuôn mặt Người lấy xe LỆCH so với người gửi lúc Check-in (${matchLabel} — Duyệt ngoại lệ).`;
      takerNote =
        "Khuôn mặt Người lấy xe KHÔNG KHỚP với người gửi xe lúc Check-in. Đề nghị trích xuất ảnh này làm bằng chứng xác minh.";
    } else {
      verdictType = "ok";
      verdictText =
        `ĐÃ LẤY XE RA BÃI: Xe ${plateNumber} Check-in lúc ${checkinRow ? checkinRow["Thời gian nhận diện"] : "-"} ` +
        `và đã Check-out lúc ${checkoutRow["Thời gian nhận diện"]} (${matchLabel}).`;
      takerNote =
        "Ảnh khuôn mặt Người lấy xe được camera cổng ra ghi nhận tại thời điểm Check-out.";
    }
  } else if (sessionClosedMissingExit) {
    verdictType = "warn";
    verdictText =
      `Phiên đã đóng, thiếu thông tin lượt ra: Xe ${plateNumber} (Check-in lúc ${checkinRow ? checkinRow["Thời gian nhận diện"] : "-"}) ` +
      `đã được đánh dấu đóng phiên (${checkinRow["Trạng thái bãi"] || inStatusCode}), nhưng không tìm thấy bản ghi lượt ra liên kết.`;
    takerNote = "Phiên đã đóng, thiếu thông tin lượt ra.";
  } else {
    verdictType = "warn";
    verdictText =
      `CHƯA CÓ LƯỢT CHECK-OUT: Xe ${plateNumber} đã Check-in lúc ${checkinRow ? checkinRow["Thời gian nhận diện"] : "-"} ` +
      `và hiện vẫn đang ở trạng thái Đang gửi trong bãi (chưa ghi nhận lượt lấy xe qua cổng).`;
    takerNote =
      "Chưa có ảnh Người lấy xe vì biển số này chưa thực hiện Check-out qua cổng camera.";
  }

  return {
    plateNumber,
    checkinRow,
    checkoutRow,
    checkinSnap,
    checkoutSnap,
    sessionClosedMissingExit,
    matchLabel,
    isMismatch,
    verdictType,
    verdictText,
    takerNote,
  };
}

export function setModalPrimaryLabels(
  isSingleMode,
  isOutRow = false,
  isMismatch = false
) {
  const dom = getDom();
  if (dom.snapshotModalCard) {
    dom.snapshotModalCard.classList.toggle(
      "single-snapshot-mode",
      Boolean(isSingleMode)
    );
  }
  if (isSingleMode && isOutRow) {
    if (dom.checkinBadgePill) {
      dom.checkinBadgePill.className = isMismatch ? "pill neg" : "pill warn";
      dom.checkinBadgePill.textContent = "CHECK OUT (LÚC LẤY XE)";
    }
    if (dom.checkinTimeLabel) dom.checkinTimeLabel.textContent = "Thời gian ra:";
    if (dom.checkinPlateLabel) dom.checkinPlateLabel.textContent = "Biển số lúc ra:";
    if (dom.checkinFaceLabel) dom.checkinFaceLabel.textContent = "Đối chiếu FaceNet:";
    if (dom.checkinPlateImgLabel) {
      dom.checkinPlateImgLabel.textContent = "Biển số Check-out";
    }
    if (dom.checkinFaceImgLabel) {
      dom.checkinFaceImgLabel.textContent = "Người lấy xe (Check-out)";
    }
    return;
  }
  if (dom.checkinBadgePill) {
    dom.checkinBadgePill.className = "pill pos";
    dom.checkinBadgePill.textContent = isSingleMode
      ? "CHECK IN (LÚC GỬI XE)"
      : "1. CHECK IN (LÚC GỬI XE)";
  }
  if (dom.checkinTimeLabel) dom.checkinTimeLabel.textContent = "Thời gian vào:";
  if (dom.checkinPlateLabel) dom.checkinPlateLabel.textContent = "Biển số lúc vào:";
  if (dom.checkinFaceLabel) dom.checkinFaceLabel.textContent = "Nhận diện mặt:";
  if (dom.checkinPlateImgLabel) {
    dom.checkinPlateImgLabel.textContent = "Biển số Check-in";
  }
  if (dom.checkinFaceImgLabel) {
    dom.checkinFaceImgLabel.textContent = "Người gửi xe (Check-in)";
  }
}

export function openSingleSnapshotModalByRow(row) {
  const dom = getDom();
  if (!dom.snapshotModal || !row) return;
  state.lostCaseReqSeq += 1;
  state.isLostModalOpen = true;
  state.activeLostCase = null;
  if (dom.btnExportLostCasePdf) {
    dom.btnExportLostCasePdf.disabled = true;
  }

  const plateNumber = row["Biển số"] || "-";
  const isOut =
    String(row.direction_code || "").toUpperCase() === "OUT" ||
    String(row["Luồng"] || "").includes("Ra");
  const matchLabel = String(row["Đối chiếu"] || "-");
  const isMismatch =
    isOut &&
    (matchLabel.includes("Lệch") ||
      (typeof row.face_match_score === "number" &&
        row.face_match_score < state.faceMatchThreshold));
  const snap = getRowSnapshots(row);

  setModalPrimaryLabels(true, isOut, isMismatch);
  if (dom.snapshotModalTitle) {
    dom.snapshotModalTitle.textContent = `Biển số ${plateNumber}`;
  }
  if (dom.checkinRecordId) dom.checkinRecordId.textContent = `#${row["ID"]}`;
  if (dom.checkinTime) {
    dom.checkinTime.textContent = row["Thời gian nhận diện"] || "-";
  }
  if (dom.checkinPlate) dom.checkinPlate.textContent = plateNumber;
  if (dom.checkinFaceStatus) {
    dom.checkinFaceStatus.textContent = isOut
      ? matchLabel
      : row["Khuôn mặt"] || "Đã lưu mẫu mặt";
  }
  applyImageOrEmptyHint(
    dom.modalPlateImg,
    dom.checkinPlateEmpty,
    snap.realPlateImg,
    "Không có ảnh lưu trữ"
  );
  applyImageOrEmptyHint(
    dom.modalFaceImg,
    dom.checkinFaceEmpty,
    snap.realFaceImg,
    "Không có ảnh lưu trữ"
  );

  dom.snapshotModal.classList.remove("hidden");
}

export function renderLostVehicleModalCase(caseData) {
  const dom = getDom();
  if (!dom.snapshotModal || !caseData) return;
  setModalPrimaryLabels(false, false, false);
  state.activeLostCase = caseData;
  if (dom.btnExportLostCasePdf) {
    dom.btnExportLostCasePdf.disabled = false;
  }

  if (dom.snapshotModalTitle) {
    dom.snapshotModalTitle.textContent = `Biển số ${caseData.plateNumber}`;
  }
  if (dom.lostCaseVerdictBanner) {
    dom.lostCaseVerdictBanner.className = `lost-case-verdict verdict-${caseData.verdictType}`;
    dom.lostCaseVerdictBanner.textContent = caseData.verdictText;
  }

  // 1. Check-in
  if (dom.checkinRecordId) {
    dom.checkinRecordId.textContent = caseData.checkinRow
      ? `#${caseData.checkinRow["ID"]}`
      : "Chưa rõ";
  }
  if (dom.checkinTime) {
    dom.checkinTime.textContent = caseData.checkinRow
      ? caseData.checkinRow["Thời gian nhận diện"]
      : "Không tìm thấy bản ghi vào";
  }
  if (dom.checkinPlate) {
    dom.checkinPlate.textContent = caseData.plateNumber;
  }
  if (dom.checkinFaceStatus) {
    dom.checkinFaceStatus.textContent = caseData.checkinRow
      ? caseData.checkinRow["Khuôn mặt"] || "Đã lưu mẫu mặt"
      : "-";
  }
  applyImageOrEmptyHint(
    dom.modalPlateImg,
    dom.checkinPlateEmpty,
    caseData.checkinSnap.realPlateImg,
    "Không có ảnh lưu trữ"
  );
  applyImageOrEmptyHint(
    dom.modalFaceImg,
    dom.checkinFaceEmpty,
    caseData.checkinSnap.realFaceImg,
    "Không có ảnh lưu trữ"
  );

  // 2. Check-out & 3. Người lấy xe
  if (caseData.checkoutRow && caseData.checkoutSnap) {
    if (dom.checkoutBadgePill) {
      dom.checkoutBadgePill.className = caseData.isMismatch
        ? "pill neg"
        : "pill pos";
      dom.checkoutBadgePill.textContent = "2. CHECK OUT (ĐÃ RA BÃI)";
    }
    if (dom.checkoutRecordId) {
      dom.checkoutRecordId.textContent = `#${caseData.checkoutRow["ID"]}`;
    }
    if (dom.checkoutTime) {
      dom.checkoutTime.textContent = caseData.checkoutRow["Thời gian nhận diện"];
    }
    if (dom.checkoutParkingStatus) {
      dom.checkoutParkingStatus.textContent = "Đã lấy xe ra khỏi bãi";
    }
    if (dom.checkoutMatchStatus) {
      dom.checkoutMatchStatus.textContent = caseData.matchLabel;
    }
    applyImageOrEmptyHint(
      dom.modalCheckoutPlateImg,
      dom.checkoutPlateEmpty,
      caseData.checkoutSnap.realPlateImg,
      "Không có ảnh lưu trữ"
    );

    if (dom.takerMatchPill) {
      dom.takerMatchPill.className = caseData.isMismatch
        ? "pill neg mono-num num"
        : "pill pos mono-num num";
      dom.takerMatchPill.textContent = caseData.matchLabel;
    }
    applyImageOrEmptyHint(
      dom.modalTakerFaceImg,
      dom.takerFaceEmpty,
      caseData.checkoutSnap.realFaceImg,
      "Không có ảnh lưu trữ"
    );
  } else if (caseData.sessionClosedMissingExit) {
    if (dom.checkoutBadgePill) {
      dom.checkoutBadgePill.className = "pill warn";
      dom.checkoutBadgePill.textContent = "2. CHECK OUT (THIẾU BẢN GHI RA)";
    }
    if (dom.checkoutRecordId) dom.checkoutRecordId.textContent = "#-";
    if (dom.checkoutTime) {
      dom.checkoutTime.textContent = "Phiên đã đóng, thiếu thông tin lượt ra";
    }
    if (dom.checkoutParkingStatus) {
      dom.checkoutParkingStatus.textContent =
        "Phiên đã đóng, thiếu thông tin lượt ra";
    }
    if (dom.checkoutMatchStatus) {
      dom.checkoutMatchStatus.textContent = "Không có dữ liệu lượt ra";
    }

    applyImageOrEmptyHint(
      dom.modalCheckoutPlateImg,
      dom.checkoutPlateEmpty,
      "",
      "Phiên đã đóng, thiếu thông tin lượt ra"
    );

    if (dom.takerMatchPill) {
      dom.takerMatchPill.className = "pill warn mono-num num";
      dom.takerMatchPill.textContent = "Thiếu lượt ra";
    }
    applyImageOrEmptyHint(
      dom.modalTakerFaceImg,
      dom.takerFaceEmpty,
      "",
      "Phiên đã đóng, thiếu thông tin lượt ra"
    );
  } else {
    if (dom.checkoutBadgePill) {
      dom.checkoutBadgePill.className = "pill warn";
      dom.checkoutBadgePill.textContent = "2. CHECK OUT (CHƯA RA)";
    }
    if (dom.checkoutRecordId) dom.checkoutRecordId.textContent = "#-";
    if (dom.checkoutTime) dom.checkoutTime.textContent = "Chưa có lượt ra";
    if (dom.checkoutParkingStatus) {
      dom.checkoutParkingStatus.textContent = "Đang gửi trong bãi";
    }
    if (dom.checkoutMatchStatus) {
      dom.checkoutMatchStatus.textContent = "Chưa đối chiếu";
    }

    applyImageOrEmptyHint(
      dom.modalCheckoutPlateImg,
      dom.checkoutPlateEmpty,
      "",
      "Chưa có lượt Check-out qua cổng"
    );

    if (dom.takerMatchPill) {
      dom.takerMatchPill.className = "pill warn mono-num num";
      dom.takerMatchPill.textContent = "Chưa xác định";
    }
    applyImageOrEmptyHint(
      dom.modalTakerFaceImg,
      dom.takerFaceEmpty,
      "",
      "Xe chưa ghi nhận lượt lấy ra qua cổng"
    );
  }

  if (dom.takerNoteText) {
    dom.takerNoteText.textContent = caseData.takerNote;
  }

  dom.snapshotModal.classList.remove("hidden");
}

export function renderLostModalLoadingState(row) {
  const dom = getDom();
  if (!dom.snapshotModal) return;
  setModalPrimaryLabels(false, false, false);
  state.activeLostCase = null;
  if (dom.btnExportLostCasePdf) {
    dom.btnExportLostCasePdf.disabled = true;
  }

  const plateNumber = (row && row["Biển số"]) || "-";
  const isOut =
    Boolean(row) &&
    (String(row.direction_code || "").toUpperCase() === "OUT" ||
      String(row["Luồng"] || "").includes("Ra"));
  const rowSnap = row ? getRowSnapshots(row) : null;

  if (dom.snapshotModalTitle) {
    dom.snapshotModalTitle.textContent = `Biển số ${plateNumber}`;
  }
  if (dom.lostCaseVerdictBanner) {
    dom.lostCaseVerdictBanner.className = "lost-case-verdict";
    dom.lostCaseVerdictBanner.textContent = isOut
      ? "Đang đối chiếu bản ghi Check-in từ cơ sở dữ liệu..."
      : "Đang đối chiếu bản ghi Check-out từ cơ sở dữ liệu...";
  }

  if (row && !isOut && rowSnap) {
    // Hiển thị ngay toàn bộ thông tin & ảnh Check-in sẵn có của dòng đang chọn
    if (dom.checkinRecordId) dom.checkinRecordId.textContent = `#${row["ID"]}`;
    if (dom.checkinTime) {
      dom.checkinTime.textContent = row["Thời gian nhận diện"] || "-";
    }
    if (dom.checkinPlate) dom.checkinPlate.textContent = plateNumber;
    if (dom.checkinFaceStatus) {
      dom.checkinFaceStatus.textContent = row["Khuôn mặt"] || "Đã lưu mẫu mặt";
    }
    applyImageOrEmptyHint(
      dom.modalPlateImg,
      dom.checkinPlateEmpty,
      rowSnap.realPlateImg,
      "Không có ảnh lưu trữ"
    );
    applyImageOrEmptyHint(
      dom.modalFaceImg,
      dom.checkinFaceEmpty,
      rowSnap.realFaceImg,
      "Không có ảnh lưu trữ"
    );
  } else {
    if (dom.checkinRecordId) dom.checkinRecordId.textContent = "#-";
    if (dom.checkinTime) dom.checkinTime.textContent = "Đang đối chiếu...";
    if (dom.checkinPlate) dom.checkinPlate.textContent = plateNumber;
    if (dom.checkinFaceStatus) dom.checkinFaceStatus.textContent = "-";
    applyImageOrEmptyHint(
      dom.modalPlateImg,
      dom.checkinPlateEmpty,
      "",
      "Đang đối chiếu..."
    );
    applyImageOrEmptyHint(
      dom.modalFaceImg,
      dom.checkinFaceEmpty,
      "",
      "Đang đối chiếu..."
    );
  }

  if (row && isOut && rowSnap) {
    // Hiển thị ngay thông tin & ảnh Check-out / Người lấy xe sẵn có của dòng đang chọn
    const matchLabel = String(row["Đối chiếu"] || "-");
    const isMismatch =
      matchLabel.includes("Lệch") ||
      (typeof row.face_match_score === "number" &&
        row.face_match_score < state.faceMatchThreshold);
    if (dom.checkoutBadgePill) {
      dom.checkoutBadgePill.className = isMismatch ? "pill neg" : "pill pos";
      dom.checkoutBadgePill.textContent = "2. CHECK OUT (ĐÃ RA BÃI)";
    }
    if (dom.checkoutRecordId) {
      dom.checkoutRecordId.textContent = `#${row["ID"]}`;
    }
    if (dom.checkoutTime) {
      dom.checkoutTime.textContent = row["Thời gian nhận diện"] || "-";
    }
    if (dom.checkoutParkingStatus) {
      dom.checkoutParkingStatus.textContent = "Đã lấy xe ra khỏi bãi";
    }
    if (dom.checkoutMatchStatus) {
      dom.checkoutMatchStatus.textContent = matchLabel;
    }
    applyImageOrEmptyHint(
      dom.modalCheckoutPlateImg,
      dom.checkoutPlateEmpty,
      rowSnap.realPlateImg,
      "Không có ảnh lưu trữ"
    );
    if (dom.takerMatchPill) {
      dom.takerMatchPill.className = isMismatch
        ? "pill neg mono-num num"
        : "pill pos mono-num num";
      dom.takerMatchPill.textContent = matchLabel;
    }
    applyImageOrEmptyHint(
      dom.modalTakerFaceImg,
      dom.takerFaceEmpty,
      rowSnap.realFaceImg,
      "Không có ảnh lưu trữ"
    );
    if (dom.takerNoteText) dom.takerNoteText.textContent = "";
  } else {
    if (dom.checkoutBadgePill) {
      dom.checkoutBadgePill.className = "pill warn";
      dom.checkoutBadgePill.textContent = "2. CHECK OUT (ĐANG ĐỐI CHIẾU...)";
    }
    if (dom.checkoutRecordId) dom.checkoutRecordId.textContent = "#-";
    if (dom.checkoutTime) dom.checkoutTime.textContent = "Đang đối chiếu...";
    if (dom.checkoutParkingStatus) dom.checkoutParkingStatus.textContent = "-";
    if (dom.checkoutMatchStatus) dom.checkoutMatchStatus.textContent = "-";
    applyImageOrEmptyHint(
      dom.modalCheckoutPlateImg,
      dom.checkoutPlateEmpty,
      "",
      "Đang đối chiếu..."
    );
    if (dom.takerMatchPill) {
      dom.takerMatchPill.className = "pill mono-num num";
      dom.takerMatchPill.textContent = "-";
    }
    applyImageOrEmptyHint(
      dom.modalTakerFaceImg,
      dom.takerFaceEmpty,
      "",
      "Đang đối chiếu..."
    );
    if (dom.takerNoteText) dom.takerNoteText.textContent = "";
  }

  dom.snapshotModal.classList.remove("hidden");
}

export async function openLostVehicleModalByRow(row) {
  const dom = getDom();
  if (!dom.snapshotModal || !row) return;
  const recId = Number(row["ID"]);
  const reqId = ++state.lostCaseReqSeq;
  state.isLostModalOpen = true;
  const verSnapshot = state.lastRecordsVersion;
  const cacheKey = `${verSnapshot}:${recId}`;

  if (verSnapshot >= 0 && state.lostCaseClientCache.has(cacheKey)) {
    renderLostVehicleModalCase(state.lostCaseClientCache.get(cacheKey));
    return;
  }

  const dirCode = String(row.direction_code || "").toUpperCase();
  const statusCode = String(row.parking_status_code || "").toUpperCase();

  // Dòng IN đang gửi trong bãi (IN_PARKING) chắc chắn chưa có lượt OUT -> hiển thị đầy đủ tức thì 0 ms
  if (verSnapshot >= 0 && dirCode === "IN" && statusCode === "IN_PARKING") {
    const instantCase = computeLostCaseDetails(row, null, row["Biển số"]);
    state.lostCaseClientCache.set(cacheKey, instantCase);
    renderLostVehicleModalCase(instantCase);
    return;
  }

  // Nếu dòng IN đã lấy xe có sẵn dòng OUT liên kết ngay trong trang hiện tại -> ghép cặp tức thì 0 ms
  if (verSnapshot >= 0 && dirCode === "IN" && recId > 0) {
    const linkedCheckout = state.cachedHistoryRecords.find(
      (r) =>
        String(r.direction_code || "").toUpperCase() === "OUT" &&
        Number(r.entry_record_id) === recId
    );
    if (linkedCheckout) {
      const instantInCase = computeLostCaseDetails(
        row,
        linkedCheckout,
        row["Biển số"]
      );
      state.lostCaseClientCache.set(cacheKey, instantInCase);
      renderLostVehicleModalCase(instantInCase);
      return;
    }
  }

  // Nếu dòng OUT có sẵn entry_record_id đang nằm ngay trong trang hiện tại -> ghép cặp tức thì 0 ms
  if (verSnapshot >= 0 && dirCode === "OUT" && row.entry_record_id) {
    const linkedCheckin = state.cachedHistoryRecords.find(
      (r) => Number(r["ID"]) === Number(row.entry_record_id)
    );
    if (linkedCheckin) {
      const instantLinkedCase = computeLostCaseDetails(
        linkedCheckin,
        row,
        row["Biển số"]
      );
      state.lostCaseClientCache.set(cacheKey, instantLinkedCase);
      renderLostVehicleModalCase(instantLinkedCase);
      return;
    }
  }

  renderLostModalLoadingState(row);

  if (!Number.isNaN(recId) && recId > 0) {
    try {
      const payload = await getSessionCase(recId);
      if (reqId !== state.lostCaseReqSeq || !state.isLostModalOpen) return;
      if (payload && ("checkin_row" in payload || "checkout_row" in payload)) {
        const authoritativeCase = computeLostCaseDetails(
          payload.checkin_row || null,
          payload.checkout_row || null,
          payload.plate_number || row["Biển số"]
        );
        if (verSnapshot >= 0 && verSnapshot === state.lastRecordsVersion) {
          state.lostCaseClientCache.set(cacheKey, authoritativeCase);
        }
        renderLostVehicleModalCase(authoritativeCase);
        return;
      }
    } catch (_) {
      if (reqId !== state.lostCaseReqSeq || !state.isLostModalOpen) return;
    }
  }

  if (reqId === state.lostCaseReqSeq && state.isLostModalOpen) {
    const isOut =
      dirCode === "OUT" || String(row["Luồng"] || "").includes("Ra");
    const fallbackCase = computeLostCaseDetails(
      isOut ? null : row,
      isOut ? row : null,
      row["Biển số"]
    );
    renderLostVehicleModalCase(fallbackCase);
  }
}

export function closeSnapshotModal() {
  const dom = getDom();
  state.isLostModalOpen = false;
  state.lostCaseReqSeq += 1;
  if (!dom.snapshotModal) return;
  dom.snapshotModal.classList.add("hidden");
}
