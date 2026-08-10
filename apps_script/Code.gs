/**
 * Field data-collection Web App for the Out-of-School Student Tracking
 * project. Coordinator picks a District (+ optional School / search),
 * sees a table of every target student in that district with their
 * current field-collection status (if any), and fills in / updates
 * status inline per row. Submissions upsert into "Field Data Collection"
 * by Student PEN — re-submitting for the same student updates the
 * existing row instead of creating a duplicate.
 *
 * Source of truth for the student list: "Out of School Student Status -
 * Raw data" tab (all 75 districts, ~90k students — the full target list).
 *
 * DEPLOYMENT: see README.md in this folder for step-by-step instructions.
 */

const SHEET_ID = '1WWifakyqkBoA922wu16bCYBZTjK2NyrxkVC_6eLBIV0'; // "Out of School Student Status - Raw data"
const TARGET_LIST_TAB = 'Out of School Student Status - Raw data';
const COLLECTION_TAB = 'Field Data Collection';

// 1-indexed column positions in the target list tab. This sheet's actual
// header row (District Name, Block Name, Last UDISE Code, Last School
// Name, Student PEN, Student Name, Sex, Mobile No, Mother Name, Father
// Name, Student Sub Status, Last Class, Eligible Class to Import, Academic
// Year) has no School Category / Student State Code columns and a
// different column order than the original source CSV — always verify
// against row 1 of the actual tab if this sheet gets rebuilt/replaced.
const COL = {
  DISTRICT: 1, BLOCK: 2, UDISE: 3, SCHOOL: 4, PEN: 5, STUDENT: 6,
  GENDER: 7, MOBILE: 8, MOTHER: 9, FATHER: 10, SUB_STATUS: 11,
  CLASS: 12, ELIGIBLE_CLASS: 13, ACADEMIC_YEAR: 14,
};

const COLLECTION_HEADERS = [
  'Student PEN', 'District Name', 'Block Name', 'School Name',
  'Student Name', 'Father Name', 'Mobile No.', 'Class',
  'Current Status', 'Willing to Resume Studies', 'Mode (Regular/NIOS)',
  'Reason', 'Collected By', 'Remarks', 'Last Updated',
];
// Column indices (1-indexed) within COLLECTION_HEADERS, for readability.
const CCOL = { PEN: 1, STATUS: 9, WILLING: 10, MODE: 11, REASON: 12, UPDATED: 15 };

/**
 * This is a pure JSON API — the actual form UI is hosted separately on
 * GitHub Pages (ooss.dataimpact.in/collect/), which calls this via fetch().
 * That way the public-facing URL field coordinators use stays stable even
 * if this Apps Script deployment URL ever changes (redeploys, project
 * moves, etc.) — only the API_URL constant in that page needs updating.
 *
 * GET  ?action=districts
 * GET  ?action=schools&district=...
 * GET  ?action=students&district=...&udise=...   (udise optional)
 * GET  ?action=summary                             (for the /dashboard/ page)
 * POST { action: 'submit', payload: {...} }        (body as text/plain JSON,
 *        see submitEntry() for payload shape — avoids a CORS preflight)
 */
function jsonOutput_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  try {
    const action = e && e.parameter && e.parameter.action;
    if (action === 'districts') return jsonOutput_({ ok: true, data: getDistricts() });
    if (action === 'schools') return jsonOutput_({ ok: true, data: getSchools(e.parameter.district) });
    if (action === 'students') return jsonOutput_({ ok: true, data: getStudents(e.parameter.district, e.parameter.udise || '') });
    if (action === 'summary') return jsonOutput_({ ok: true, data: getSummary() });
    return jsonOutput_({ ok: false, error: 'Unknown or missing action.' });
  } catch (err) {
    return jsonOutput_({ ok: false, error: err.message });
  }
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.action === 'submit') return jsonOutput_(submitEntry(body.payload));
    return jsonOutput_({ ok: false, error: 'Unknown or missing action.' });
  } catch (err) {
    return jsonOutput_({ ok: false, error: err.message });
  }
}

function spreadsheet_() {
  return SpreadsheetApp.openById(SHEET_ID);
}

function targetSheet_() {
  const sh = spreadsheet_().getSheetByName(TARGET_LIST_TAB);
  if (!sh) throw new Error(`Tab "${TARGET_LIST_TAB}" not found.`);
  return sh;
}

function getDistricts() {
  const sh = targetSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return [];
  const values = sh.getRange(2, COL.DISTRICT, lastRow - 1, 1).getValues();
  const set = new Set();
  values.forEach(r => { const v = String(r[0] || '').trim(); if (v) set.add(v); });
  return Array.from(set).sort();
}

function getSchools(district) {
  const sh = targetSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return [];
  const width = Math.max(COL.SCHOOL, COL.UDISE, COL.BLOCK);
  const values = sh.getRange(2, 1, lastRow - 1, width).getValues();
  const seen = new Map(); // key: udise||school -> {udise, school, block}
  values.forEach(r => {
    if (String(r[COL.DISTRICT - 1] || '').trim() !== district) return;
    const school = String(r[COL.SCHOOL - 1] || '').trim();
    const udise = String(r[COL.UDISE - 1] || '').trim();
    const block = String(r[COL.BLOCK - 1] || '').trim();
    if (!school) return;
    const key = udise + '||' + school;
    if (!seen.has(key)) seen.set(key, { udise, school, block });
  });
  return Array.from(seen.values()).sort((a, b) => a.school.localeCompare(b.school));
}

/** Map of PEN -> collection row data, for merging into the student list. */
function collectionStatusByPen_() {
  const sh = spreadsheet_().getSheetByName(COLLECTION_TAB);
  const map = {};
  if (!sh) return map;
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return map;
  const values = sh.getRange(2, 1, lastRow - 1, COLLECTION_HEADERS.length).getValues();
  values.forEach((r, idx) => {
    const pen = String(r[CCOL.PEN - 1] || '').trim();
    if (!pen) return;
    map[pen] = {
      rowIndex: idx + 2,
      currentStatus: r[CCOL.STATUS - 1] || '',
      willing: r[CCOL.WILLING - 1] || '',
      mode: r[CCOL.MODE - 1] || '',
      reason: r[CCOL.REASON - 1] || '',
    };
  });
  return map;
}

/**
 * district: required. udise: optional ('' = all schools in district) —
 * the school's UDISE code, matched exactly (more reliable than school
 * name, which can repeat).
 */
function getStudents(district, udise) {
  const sh = targetSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return [];
  const width = COL.ACADEMIC_YEAR;
  const values = sh.getRange(2, 1, lastRow - 1, width).getValues();
  const statusMap = collectionStatusByPen_();

  const out = [];
  values.forEach(r => {
    if (String(r[COL.DISTRICT - 1] || '').trim() !== district) return;
    if (udise && String(r[COL.UDISE - 1] || '').trim() !== udise) return;
    const name = String(r[COL.STUDENT - 1] || '').trim();
    const father = String(r[COL.FATHER - 1] || '').trim();

    const pen = String(r[COL.PEN - 1] || '').trim();
    const existing = statusMap[pen];
    out.push({
      pen: pen,
      name: name,
      father: father,
      mobile: String(r[COL.MOBILE - 1] || '').trim(),
      block: String(r[COL.BLOCK - 1] || '').trim(),
      school: String(r[COL.SCHOOL - 1] || '').trim(),
      studentClass: String(r[COL.CLASS - 1] || '').trim(),
      currentStatus: existing ? existing.currentStatus : '',
      willing: existing ? existing.willing : '',
      mode: existing ? existing.mode : '',
      reason: existing ? existing.reason : '',
    });
  });
  out.sort((a, b) => a.name.localeCompare(b.name));
  return out;
}

/**
 * Aggregate stats over the Field Data Collection tab, for the live
 * dashboard (ooss.dataimpact.in/dashboard/). Grows as coordinators submit
 * entries via the collect form — there's no separate "run a script"
 * refresh step, the dashboard just reads this on each page load.
 */
function getSummary() {
  const targetTotal = (function () {
    const sh = targetSheet_();
    return Math.max(sh.getLastRow() - 1, 0);
  })();

  const sh = spreadsheet_().getSheetByName(COLLECTION_TAB);
  const summary = {
    targetTotal: targetTotal,
    collected: 0,
    studying: 0,
    notStudying: 0,
    deceased: 0,
    willing: 0,
    unwilling: 0,
    modeRegular: 0,
    modeNios: 0,
    reasonBreakdown: {},
    districtBreakdown: {}, // district -> { collected, studying, notStudying, deceased }
    generatedAt: new Date().toISOString(),
  };
  if (!sh) return summary;
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return summary;

  const values = sh.getRange(2, 1, lastRow - 1, COLLECTION_HEADERS.length).getValues();
  values.forEach(r => {
    const pen = String(r[CCOL.PEN - 1] || '').trim();
    if (!pen) return;
    summary.collected++;

    const district = String(r[1] || '').trim() || 'Unknown';
    const status = String(r[CCOL.STATUS - 1] || '').trim();
    const willing = String(r[CCOL.WILLING - 1] || '').trim();
    const mode = String(r[CCOL.MODE - 1] || '').trim();
    const reason = String(r[CCOL.REASON - 1] || '').trim();

    const d = summary.districtBreakdown[district] ||
      (summary.districtBreakdown[district] = { collected: 0, studying: 0, notStudying: 0, deceased: 0 });
    d.collected++;

    if (status === 'Studying') { summary.studying++; d.studying++; }
    else if (status === 'Not Studying') {
      summary.notStudying++; d.notStudying++;
      if (willing === 'Yes') summary.willing++;
      else if (willing === 'No') summary.unwilling++;
      if (mode === 'Regular') summary.modeRegular++;
      else if (mode === 'NIOS') summary.modeNios++;
      if (reason) summary.reasonBreakdown[reason] = (summary.reasonBreakdown[reason] || 0) + 1;
    } else if (status === 'Deceased') { summary.deceased++; d.deceased++; }
  });

  return summary;
}

function collectionSheet_() {
  const ss = spreadsheet_();
  let sh = ss.getSheetByName(COLLECTION_TAB);
  if (!sh) {
    sh = ss.insertSheet(COLLECTION_TAB);
    sh.getRange(1, 1, 1, COLLECTION_HEADERS.length).setValues([COLLECTION_HEADERS]);
    sh.getRange(1, 1, 1, COLLECTION_HEADERS.length)
      .setBackground('#1c3866').setFontColor('#ffffff').setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function findRowByPen_(sh, pen) {
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return -1;
  const values = sh.getRange(2, CCOL.PEN, lastRow - 1, 1).getValues();
  for (let i = 0; i < values.length; i++) {
    if (String(values[i][0] || '').trim() === pen) return i + 2; // 1-indexed sheet row
  }
  return -1;
}

/**
 * payload: { district, block, school, pen, studentName, fatherName,
 *   mobile, studentClass, currentStatus, willing, mode, reason,
 *   collectedBy, remarks }
 * Upserts by PEN — re-submitting for the same student updates the
 * existing row instead of appending a duplicate.
 */
function submitEntry(payload) {
  if (!payload || !payload.district || !payload.school || !payload.studentName) {
    throw new Error('Missing required student selection.');
  }
  if (!payload.currentStatus) {
    throw new Error('Please answer whether the student is currently studying.');
  }
  if (!payload.pen) {
    throw new Error('This student has no PEN on record — cannot save without a unique ID.');
  }

  const sh = collectionSheet_();
  const rowValues = [
    payload.pen, payload.district || '', payload.block || '', payload.school || '',
    payload.studentName || '', payload.fatherName || '', payload.mobile || '',
    payload.studentClass || '', payload.currentStatus || '', payload.willing || '',
    payload.mode || '', payload.reason || '', payload.collectedBy || '',
    payload.remarks || '', new Date(),
  ];

  const existingRow = findRowByPen_(sh, payload.pen);
  if (existingRow > 0) {
    sh.getRange(existingRow, 1, 1, rowValues.length).setValues([rowValues]);
  } else {
    sh.appendRow(rowValues);
  }
  return { ok: true, updated: existingRow > 0 };
}
