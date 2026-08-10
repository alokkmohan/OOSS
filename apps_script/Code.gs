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

// 1-indexed column positions in the target list tab (from the source CSV).
const COL = {
  DISTRICT: 1, BLOCK: 2, UDISE: 3, SCHOOL_CATEGORY: 4, SCHOOL: 5,
  PEN: 6, STATE_CODE: 7, STUDENT: 8, GENDER: 9, MOBILE: 10,
  MOTHER: 11, FATHER: 12, SUB_STATUS: 13, CLASS: 14, ELIGIBLE_CLASS: 15,
  ACADEMIC_YEAR: 16,
};

const COLLECTION_HEADERS = [
  'Student PEN', 'District Name', 'Block Name', 'School Name',
  'Student Name', 'Father Name', 'Mobile No.', 'Class',
  'Current Status', 'Willing to Resume Studies', 'Mode (Regular/NIOS)',
  'Reason', 'Collected By', 'Remarks', 'Last Updated',
];
// Column indices (1-indexed) within COLLECTION_HEADERS, for readability.
const CCOL = { PEN: 1, STATUS: 9, WILLING: 10, MODE: 11, REASON: 12, UPDATED: 15 };

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('Out-of-School Student — Field Data Collection')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
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
  const values = sh.getRange(2, 1, lastRow - 1, COL.SCHOOL).getValues();
  const seen = new Map(); // key: school||block -> {school, block}
  values.forEach(r => {
    if (String(r[COL.DISTRICT - 1] || '').trim() !== district) return;
    const school = String(r[COL.SCHOOL - 1] || '').trim();
    const block = String(r[COL.BLOCK - 1] || '').trim();
    if (!school) return;
    const key = school + '||' + block;
    if (!seen.has(key)) seen.set(key, { school, block });
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
 * district: required. school: optional ('' = all schools in district).
 * search: optional, matches Student Name or Father Name (case-insensitive).
 */
function getStudents(district, school, search) {
  const sh = targetSheet_();
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return [];
  const width = COL.ACADEMIC_YEAR;
  const values = sh.getRange(2, 1, lastRow - 1, width).getValues();
  const statusMap = collectionStatusByPen_();
  const needle = (search || '').trim().toLowerCase();

  const out = [];
  values.forEach(r => {
    if (String(r[COL.DISTRICT - 1] || '').trim() !== district) return;
    if (school && String(r[COL.SCHOOL - 1] || '').trim() !== school) return;
    const name = String(r[COL.STUDENT - 1] || '').trim();
    const father = String(r[COL.FATHER - 1] || '').trim();
    if (needle && !(name.toLowerCase().includes(needle) || father.toLowerCase().includes(needle))) return;

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
