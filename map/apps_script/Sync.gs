/**
 * Sync verified students from the field-collection sheet into this Sheet.
 *
 * Source (READ-ONLY — never written to): "Field Data Collection" tab of the
 * collect sheet. A student belongs in the lists only if they are really not
 * studying: Current Status = "Not Studying", not a death, and no remark saying
 * they study elsewhere, have passed class 12, or are a duplicate/wrong entry.
 *
 * Each run:
 *   - students no longer valid are moved from "All Student Data" and
 *     "MAP Data 213 centre" to "Excluded Students" (with the reason);
 *   - new valid students are appended with a NIOS centre assigned
 *     (own school → same block → same district; gender and seats checked);
 *   - a line is added to "Sync Log".
 * Run setupSync() once from the editor to install the hourly trigger.
 */

const FIELD_SHEET_ID = '1WWifakyqkBoA922wu16bCYBZTjK2NyrxkVC_6eLBIV0'; // collect sheet (read-only here)
const FIELD_TAB = 'Field Data Collection';
const EXCLUDED_TAB = 'Excluded Students';
const LOG_TAB = 'Sync Log';
// written as plain text so IDs keep their leading zeros
const TEXT_COLS = ['Student PEN', 'Last UDISE Code', 'Mobile No', 'Academic Year', 'Centre UDISE Code', 'Centre Pin', 'Centre Mobile No.'];

// ---- remark rules (Hindi / English / Hinglish) ----
const DEV = 'ऀ-ॿ';
// negates, stops, or only intends studying — such a remark never counts as "studying"
const NEG_RX = /नहीं|नही|नहि|\bna\b|\bnahi|nahin|\bnhi\b|\bnot\b|\bno\b|didn'?t|don'?t|\bdont\b|never|kabhi|stop|chhod|\bchod|छोड़|छोड|\bband\b|बंद|बन्द|\bleft\b|drop|discontinu|could\s*not|unable|chah|चाह|want|\bwill\b|\blene\b|lenge|\blega\b|\blegi\b|लेना|लेंगे|लेगा|लेगी|पढ़ेंगे|पढ़ेगा|पढ़ेगी/i;
const PARENT_RX = /पिता|माता|मां|माँ|पापा|father|mother|papa|parent|abba|ammi|भाई|\bbhai\b|brother|sister|बहन|दादा|दादी|grand|\bnana\b|\bnani\b/i;
const DEATH_RX = new RegExp('death|\\bdead\\b|expired|\\bdied\\b|मृत्यु|मृत्यू|मृत(?![' + DEV + '])|देहांत|देहान्त|स्वर्गवास|निधन|nidhan|डेथ', 'i');
const DUP_RX = /duplicat|dublicat|डुप्लीकेट|wrong\s*entry|गलत\s*(entry|प्रविष्टि)|\bdouble\b|dob+u?le\s*pen|dusra\s*(hai|pen)|पेन\s*(गलत|दूसरा)/i;
const DONE12_RX = new RegExp(
  '\\b12\\s*(th)?\\s*(class)?\\s*(pass|paas|passed|paased|पास)|\\bxii\\s*(th)?\\s*pass|class\\s*(12|xii)\\s*(th)?\\s*pass|pass\\s*out\\s*class\\s*(12|xii)|' +
  'कक्षा\\s*-?\\s*12\\s*(वीं)?\\s*(पास|उत्तीर्ण)|12\\s*(वीं|वी)?\\s*(पास|उत्तीर्ण)|after\\s*12\\s*(th)?|inter[a-z]*\\s*pass|इंटर[' + DEV + ']*\\s*पास|' +
  'completed\\s*(class\\s*)?12|graduat|स्नातक|\\bb\\.\\s?a\\b|\\bba\\s*(1st|2nd|3rd|first|second|third|part)|\\bb\\.?\\s?sc\\b|\\bb\\.?\\s?com\\b|degree\\s*college', 'i');
const OTHER = '(an?\\s*other|other|othar|oter|othr|different|anya|dusr[a-z]*|doosr[a-z]*|kisi\\s*aur|kahi\\s*aur|kahin\\s*aur|अन्य|अन्यत्र|दूसर[' + DEV + ']*|दुसर[' + DEV + ']*|किसी\\s*(और|अन्य)|कहीं\\s*और|कही\\s*और)';
const SCHOOL = '(school|vidyal[a-z]*|college|collage|institute|विद्यालय|विधालय|स्कूल|कॉलेज|कालेज|महाविद्यालय|संस्थान|inter\\s*college)';
const STUDY_ANY = '(stud[a-z]*|read[a-z]*|padh[a-z]*|pad\\s*(raha|rahi|rahe|rha|rhi)|\\bpd\\s*(rha|raha|rhi|rahi)|पढ़[' + DEV + ']*|पढ[' + DEV + ']*|' +
  'अध्[' + DEV + ']*यन|admi[a-z]*|addmi[a-z]*|प्रवेश|एडमिशन|नामांकन|दाखिला|पंजीकृत|enrol[a-z]*|transfer[a-z]*|moved|shift[a-z]*|' +
  'chala\\s*gaya|chali\\s*gayi|चला\\s*गया|चली\\s*गई|\\bgo\\b|gone|active)';
// clearly says the student studies somewhere (ignored when the remark negates it)
const STUDYING_RX = [
  new RegExp(OTHER + '\\s*' + SCHOOL + '[\\s\\S]{0,40}' + STUDY_ANY + '|' + STUDY_ANY + '[\\s\\S]{0,40}' + OTHER + '\\s*' + SCHOOL, 'i'),
  /अन्यत्र\s*प्रवेश|further\s*education|\biti\b\s*(karta|kar\s*raha|me\s*padh)|admission\s*in\s*iti|polytec[a-z]*/i,
  new RegExp('(padh|pad)\\s*(raha|rahi|rahe|rha|rhi)|\\bpd\\s*(rha|raha|rhi|rahi)|पढ़\\s*(रहा|रही|रहे)|पढ\\s*(रहा|रही|रहे)|अध्[' + DEV + ']*यन\\s*कर\\s*(रहा|रही|रहे)|' +
    'reading\\s*in|studying\\s*in|study\\s*in\\s+[a-z]|(प्रवेश|एडमिशन)\\s*(ले\\s*लिया|लिया)|admission\\s*(le\\s*liya|liya|ho\\s*gaya|in\\s+[a-z])|' +
    '(school|college|vidyalay[a-z]*|विद्यालय|कॉलेज)\\s*(me|में|mein|mai)\\s*active|(क्लास|कक्षा|class)\\s*\\d+\\s*(का|की|ka|ki)\\s*(छात्र|छात्रा|student|chhatra)\\s*(है|हैं|hai|h)|' +
    '(विद्यालय|स्कूल|कक्षा|कॉलेज|\\d+\\s*(वीं|वी|th))[\\s\\S]{0,25}पड़\\s*(रहा|रही|रहे)|(school|college)\\s*(admission|addmis[a-z]*)', 'i'),
  new RegExp(OTHER + '\\s*' + SCHOOL, 'i'), // "Other school" — studies in another school
];
// says they left for studies elsewhere, even if the remark also has a "not"
const STUDYING_ALWAYS_RX = /(टी\.?\s*सी|\btc\b|t\.c).{0,40}(आगे\s*की|अग्रिम)\s*पढ़ाई|(आगे\s*की|अग्रिम)\s*पढ़ाई\s*(हेतु|के\s*लिए).{0,30}(चला|चली|टी\.?\s*सी|\btc\b|स्थानांतरण)|transfer[a-z]*\s*(with\s*tc\s*)?to\s*(current|another|other|new)\s*school|already\s*(an\s*)?(another|other)\s*school/i;

/** Why a field row is excluded, or '' if the student is really not studying. */
function exclusionReason_(status, reason, remark) {
  const t = String(remark || '').trim();
  if (status !== 'Not Studying') return 'Studying (field status)';
  if ((reason === 'Death' && !PARENT_RX.test(t)) || (DEATH_RX.test(t) && !PARENT_RX.test(t))) return 'Death';
  if (DUP_RX.test(t)) return 'Duplicate / wrong entry';
  if (DONE12_RX.test(t)) return 'Class 12 passed / higher studies';
  if (STUDYING_ALWAYS_RX.test(t)) return 'Studying elsewhere (remark)';
  if (!NEG_RX.test(t) && STUDYING_RX.some(rx => rx.test(t))) return 'Studying elsewhere (remark)';
  return '';
}

// ---- entry points ----
function setupSync() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'syncFromField')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('syncFromField').timeBased().everyHours(1).create();
  Logger.log(JSON.stringify(sync_(false)));
}

function syncFromField() { sync_(false); }

function sync_(dryRun) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return { ok: false, error: 'another sync is running' };
  try { return runSync_(dryRun); } finally { lock.releaseLock(); }
}

function runSync_(dryRun) {
  const t0 = Date.now();
  const ss = SpreadsheetApp.openById(SHEET_ID);

  // 1. field rows, one per PEN (read-only); the collect app upserts by PEN, so a later row wins
  const fv = SpreadsheetApp.openById(FIELD_SHEET_ID).getSheetByName(FIELD_TAB).getDataRange().getDisplayValues();
  const fh = fv[0], fc = n => fh.indexOf(n);
  const field = new Map();
  for (let r = 1; r < fv.length; r++) {
    const pen = String(fv[r][fc('Student PEN')]).trim();
    if (pen) field.set(pen, fv[r]);
  }
  const verdict = new Map(); // pen -> exclusion reason ('' = valid)
  field.forEach((row, pen) => verdict.set(pen, exclusionReason_(row[fc('Current Status')], row[fc('Reason')], row[fc('Remarks')])));
  const samples = {}; // dry run only: which remarks each rule caught (text and counts, no names)
  if (dryRun) field.forEach((row, pen) => {
    const why = verdict.get(pen);
    if (!why || why === 'Studying (field status)') return;
    const k = String(row[fc('Remarks')] || '').trim().slice(0, 120) || '(remark blank; Reason: ' + row[fc('Reason')] + ')';
    const o = samples[why] || (samples[why] = {});
    o[k] = (o[k] || 0) + 1;
  });

  // 2. current lists
  const allT = readTab_(ss.getSheetByName(DATA_TABS.survey));
  const finT = readTab_(ss.getSheetByName(DATA_TABS.final));
  const H = allT.headers, hc = n => H.indexOf(n);

  // 3. rows to drop (field says no longer valid); students missing from the field tab are left alone
  const dropReason = pen => (verdict.has(pen) ? verdict.get(pen) : '');
  const excluded = [];
  const keepAll = allT.rows.filter(r => {
    const why = dropReason(String(r[hc('Student PEN')]).trim());
    if (why) excluded.push([why, r]);
    return !why;
  });
  const keepFin = finT.rows.filter(r => !dropReason(String(r[finT.headers.indexOf('Student PEN')]).trim()));

  // 4. new valid students, with a centre
  const have = new Set(allT.rows.map(r => String(r[hc('Student PEN')]).trim()));
  const centres = centreTable_(ss, keepAll, H);
  const added = [];
  field.forEach((row, pen) => {
    if (have.has(pen) || verdict.get(pen)) return;
    added.push(newStudentRow_(row, fc, H, centres));
  });
  const addedFin = added.filter(r => AI_CODES[code_(r[hc('Centre UDISE Code')])]);

  const byReason = {}, basis = {};
  excluded.forEach(([why]) => { byReason[why] = (byReason[why] || 0) + 1; });
  added.forEach(r => { const b = r[hc('Admission Basis')]; basis[b] = (basis[b] || 0) + 1; });
  const stats = {
    ok: true, dryRun: dryRun, fieldStudents: field.size,
    allBefore: allT.rows.length, allAfter: keepAll.length + added.length,
    finalBefore: finT.rows.length, finalAfter: keepFin.length + addedFin.length,
    removedAll: excluded.length, removedFinal: finT.rows.length - keepFin.length,
    removedByReason: byReason, added: added.length, addedFinal: addedFin.length, addedBasis: basis,
  };
  if (dryRun) {
    stats.samples = samples;
  }

  if (!dryRun) {
    if (excluded.length) appendExcluded_(ss, H, excluded);
    writeTab_(allT, keepAll.concat(added));
    writeTab_(finT, keepFin.concat(addedFin.map(r => finT.headers.map(h => r[hc(h)]))));
    const cache = CacheService.getScriptCache();
    cache.removeAll(['idx:final', 'idx:survey', 'sum:final', 'sum:survey', 'sum:centres', 'centres']);
    if (excluded.length || added.length) log_(ss, stats);
  }
  stats.seconds = Math.round((Date.now() - t0) / 1000);
  return stats;
}

// ---- helpers ----
function readTab_(sh) {
  const h = headerRow_(sh, UDISE_COL);
  const headers = h.headers.filter(String);
  const n = Math.max(sh.getLastRow() - h.row, 0);
  const rows = n ? sh.getRange(h.row + 1, 1, n, headers.length).getValues() : [];
  const filled = rows.filter(r => String(r[0]).trim() !== '');
  return { sh: sh, headerRow: h.row, headers: headers, rows: filled, oldCount: n, hadBlanks: filled.length !== rows.length };
}

// Rewrites the data block from the first changed row; IDs are kept as text.
function writeTab_(t, rows) {
  const width = t.headers.length, first = t.headerRow + 1;
  let start = 0;
  while (!t.hadBlanks && start < rows.length && start < t.rows.length && rows[start] === t.rows[start]) start++;
  const tail = rows.slice(start);
  if (tail.length) {
    TEXT_COLS.forEach(name => {
      const c = t.headers.indexOf(name);
      if (c >= 0) t.sh.getRange(first + start, c + 1, tail.length, 1).setNumberFormat('@');
    });
    const out = tail.map(r => r.map((v, c) => t.headers[c] === UDISE_COL ? code_(v) : TEXT_COLS.indexOf(t.headers[c]) >= 0 ? String(v) : v));
    for (let i = 0; i < out.length; i += 5000) { // chunked: one 36k-row write can time out
      const part = out.slice(i, i + 5000);
      t.sh.getRange(first + start + i, 1, part.length, width).setValues(part);
    }
  }
  const extra = t.oldCount - rows.length;
  if (extra > 0) t.sh.getRange(first + rows.length, 1, extra, width).clearContent();
}

// Centre list with details copied from an existing student row, and live seat counts.
function centreTable_(ss, rows, H) {
  const hc = n => H.indexOf(n);
  const sh = ss.getSheetByName(CENTRES_TAB);
  const h = headerRow_(sh, 'Centre UDISE');
  const v = sh.getRange(h.row + 1, 1, sh.getLastRow() - h.row, h.headers.length).getDisplayValues();
  const col = n => h.headers.indexOf(n);
  const byCode = new Map();
  v.forEach(r => {
    const u = code_(r[col('Centre UDISE')]);
    if (!u) return;
    byCode.set(u, { udise: u, name: r[col('Centre Name')], district: key_(r[col('District')]), block: key_(r[col('Block')]), blockName: r[col('Block')], districtName: r[col('District')],
                    gender: r[col('Gender')], type: r[col('Type')], seats: Number(r[col('Seats')]) || 0, used: 0, template: null });
  });
  rows.forEach(r => {
    const c = byCode.get(code_(r[hc('Centre UDISE Code')]));
    if (!c) return;
    c.used++;
    if (!c.template) c.template = r;
  });
  return byCode;
}

const norm_ = s => String(s || '').trim().toUpperCase();
const key_ = s => norm_(s).replace(/[^A-Z0-9]/g, '');

// 1 - edit distance / longer length; "MAHARAJGANJ" vs "MAHARJGANJ" = 0.91
function similar_(a, b) {
  if (a === b) return 1;
  const m = a.length, n = b.length;
  if (!m || !n) return 0;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prev = cur;
  }
  return 1 - prev[n] / Math.max(m, n);
}
const genderOk_ = (centreGender, sex) => centreGender === 'Both' || (centreGender === 'Girls' && sex === 'FEMALE') || (centreGender === 'Boys' && sex === 'MALE');

function pickCentre_(centres, district, block, sex, ownUdise) {
  const own = centres.get(code_(ownUdise));
  if (own) return [own, 'Own school is a NIOS centre'];
  const inDist = [...centres.values()].filter(c => c.district === district);
  const free = c => c.seats - c.used > 0;
  const best = list => list.sort((a, b) => (b.seats - b.used) - (a.seats - a.used))[0];
  let sameBlock = inDist.filter(c => c.block === block);
  if (!sameBlock.length && block) { // spelling differences, e.g. "PURE DALAI" / "PUREDALAI"
    const near = inDist.map(c => [similar_(c.block, block), c]).filter(x => x[0] >= 0.8).sort((a, b) => b[0] - a[0])[0];
    if (near) sameBlock = inDist.filter(c => c.block === near[1].block);
  }
  let c = best(sameBlock.filter(c => genderOk_(c.gender, sex) && free(c)));
  if (c) return [c, 'Centre in same block'];
  c = best(inDist.filter(c => genderOk_(c.gender, sex) && free(c)));
  if (c) return [c, 'Centre in same district (other block)'];
  c = best(inDist.filter(free));
  if (c) return [c, 'Exception: gender not matching - verify'];
  c = best(inDist.filter(c => genderOk_(c.gender, sex)));
  if (c) return [c, 'Exception: seats exceeded - verify'];
  c = best(inDist);
  if (c) return [c, 'Exception: gender + seats - verify'];
  return [null, 'No NIOS centre in district - verify'];
}

function newStudentRow_(f, fc, H, centres) {
  const sex = norm_(f[fc('Sex')]);
  const [c, basis] = pickCentre_(centres, key_(f[fc('District Name')]), key_(f[fc('Block Name')]), sex, f[fc('Last UDISE Code')]);
  if (c) c.used++;
  const eligible = String(f[fc('Last Class')] || '').trim(); // All Student Data keeps the last class here
  const studentCols = ['Student PEN', 'District Name', 'Block Name', 'Last UDISE Code', 'Last School Name', 'Student Name', 'Sex',
                       'Mobile No', 'Mother Name', 'Father Name', 'Academic Year'];
  return H.map((name, i) => {
    if (studentCols.indexOf(name) >= 0) return String(f[fc(name)] || '').trim();
    if (name === 'Eligible Class to Import') return eligible !== '' && !isNaN(eligible) ? Number(eligible) : eligible;
    if (name === 'Current Status') return 'Not Studying';
    if (name === 'Admission Basis') return basis;
    if (!c) return '';
    if (c.template) return c.template[i];
    return { 'Centre UDISE Code': c.udise, 'Centre Name': c.name, 'Centre Block': c.blockName, 'Centre District': c.districtName,
             'Centre Gender': c.gender, 'Centre Type': c.type, 'Centre Seats': c.seats }[name] || '';
  });
}

function appendExcluded_(ss, H, excluded) {
  let sh = ss.getSheetByName(EXCLUDED_TAB);
  const head = H.concat(['Excluded Reason', 'Excluded On']);
  if (!sh) {
    sh = ss.insertSheet(EXCLUDED_TAB);
    sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  const when = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'dd-MM-yyyy HH:mm');
  const rows = excluded.map(([why, r]) => r.map((v, c) => TEXT_COLS.indexOf(H[c]) >= 0 ? String(v) : v).concat([why, when]));
  const start = sh.getLastRow() + 1;
  TEXT_COLS.forEach(name => { const c = H.indexOf(name); if (c >= 0) sh.getRange(start, c + 1, rows.length, 1).setNumberFormat('@'); });
  sh.getRange(start, 1, rows.length, head.length).setValues(rows);
}

function log_(ss, s) {
  let sh = ss.getSheetByName(LOG_TAB);
  if (!sh) {
    sh = ss.insertSheet(LOG_TAB);
    sh.appendRow(['Time', 'Field students', 'Added (All)', 'Added (213)', 'Removed (All)', 'Removed (213)', 'All Student Data', 'MAP Data 213 centre', 'Removed by reason']);
    sh.setFrozenRows(1);
  }
  sh.appendRow([Utilities.formatDate(new Date(), 'Asia/Kolkata', 'dd-MM-yyyy HH:mm'), s.fieldStudents, s.added, s.addedFinal,
                s.removedAll, s.removedFinal, s.allAfter, s.finalAfter, JSON.stringify(s.removedByReason)]);
}
