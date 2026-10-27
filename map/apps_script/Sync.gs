/**
 * Hourly sync: students verified in the field → every tab of this Sheet.
 *
 * Source (READ-ONLY — never written to): "Field Data Collection" tab of the
 * collect sheet. Centre master: "Centre List" tab (all centres; the NIOS AI
 * Code column is for information).
 *
 * Rules (same as nios_centre_mapping.py):
 *  - students: Current Status "Not Studying"; Reason "Death" dropped; first
 *    row per PEN; remarks saying studying elsewhere / class 12 passed /
 *    duplicate or wrong entry dropped
 *  - districts and blocks come from UDISE codes (first 4 / 6 digits), never names
 *  - a centre fits when gender (a boy never goes to a girls-only centre),
 *    course (9-10 Secondary, 11-12 Sr. Secondary) and seats (hard cap) all
 *    fit; own school → same block → same district → "course not offered";
 *    lowest allotted/seats, then Type A > B > C, then PM Shri; a second pass
 *    places whoever is left as a labelled exception
 *  - INCREMENTAL: students already in All Student Data keep their centre
 *
 * Tabs kept up to date: All Student Data, NIOS Format All student,
 * Centre-wise Count (+ Excluded Students, Sync Log). Each tab is rewritten
 * only from its first changed row. The accredited-only tabs (MAP Data 213
 * centre, NIOS Format 213 centre) are paused: add 'map213' / 'nios213' to
 * SYNC_TABS to write them again.
 * Run setupSync() once from the editor to install the hourly trigger.
 */

const FIELD_SHEET_ID = '1WWifakyqkBoA922wu16bCYBZTjK2NyrxkVC_6eLBIV0'; // collect sheet (read-only here)
const FIELD_TAB = 'Field Data Collection';
const EXCLUDED_TAB = 'Excluded Students';
const LOG_TAB = 'Sync Log';
const TAB_ALL = 'All Student Data', TAB_MAP213 = 'MAP Data 213 centre';
const TAB_NIOS_ALL = 'NIOS Format All student', TAB_NIOS213 = 'NIOS Format 213 centre', TAB_COUNT = 'Centre-wise Count';
const SYNC_TABS = ['all', 'niosAll', 'count']; // all centres; 'map213' / 'nios213' paused
const MAP_TEXT = ['Student PEN', 'Last UDISE Code', 'Mobile No', 'Academic Year', 'Centre UDISE Code', 'Centre Pin', 'Centre Mobile No.'];
const NIOS_TEXT = [7, 11, 12, 39, 46, 48]; // mobile, DOB, Aadhaar, pincodes, study centre code
const CENTRE_COLS = {
  'Centre Name': 'name', 'Centre Address': 'address', 'Centre Block': 'block', 'Centre District': 'district',
  'Centre Pin': 'pin', 'Centre Mobile No.': 'mobile', 'Centre Email': 'email', 'Centre Principal / Coordinator': 'principal',
  'Centre Course': 'course', 'Centre With Science': 'science', 'Centre Medium': 'medium', 'Centre Gender': 'gender',
  'Centre Type': 'type', 'Centre Seats': 'seats', 'Centre PM Shri': 'pmshri',
};
const B_OWN = 'Own school is a NIOS centre', B_BLOCK = 'Centre in same block', B_DIST = 'Centre in same district (other block)';
const B_COURSE = 'Gender OK, but course not offered - verify';
const B_COURSE_OLD = 'Gender OK, but course (Sec/Sr.Sec) not offered - verify'; // same meaning, older wording
const X_GENDER = 'Exception: gender not matching - verify', X_SEATS = 'Exception: seats exceeded - verify';
const X_BOTH = 'Exception: gender + seats - verify', NO_CENTRE = 'No centre in district';

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

function remarkExclusion_(remark) {
  const t = String(remark || '').trim();
  if (!t) return '';
  if (DEATH_RX.test(t) && !PARENT_RX.test(t)) return 'Death';
  if (DUP_RX.test(t)) return 'Duplicate / wrong entry';
  if (DONE12_RX.test(t)) return 'Class 12 passed / higher studies';
  if (STUDYING_ALWAYS_RX.test(t) || (!NEG_RX.test(t) && STUDYING_RX.some(rx => rx.test(t)))) return 'Studying elsewhere (remark)';
  return '';
}

// ---- entry points ----
function setupSync() {
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'syncFromField')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('syncFromField').timeBased().everyHours(1).create();
  Logger.log(JSON.stringify(sync_({})));
}

function syncFromField() { sync_({}); }

/** opts: { dryRun, tabs: ['all','niosAll','count','map213','nios213'] (default SYNC_TABS) } */
function sync_(opts) {
  const o = typeof opts === 'object' && opts ? opts : { dryRun: !!opts };
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return { ok: false, error: 'another sync is running' };
  try { return runSync_(o); } finally { lock.releaseLock(); }
}

function runSync_(o) {
  const t0 = Date.now(), dry = !!o.dryRun;
  const want = k => (o.tabs || SYNC_TABS).indexOf(k) >= 0;
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const centres = centreList_(ss);

  // 1. field students (read-only): Not Studying, no Death, first row per PEN, remark rules
  const fv = SpreadsheetApp.openById(FIELD_SHEET_ID).getSheetByName(FIELD_TAB).getDataRange().getDisplayValues();
  const fh = fv[0], fc = n => fh.indexOf(n);
  const known = new Set(), seen = new Set(), valid = new Map(), why = new Map(), firstRow = new Map();
  for (let r = 1; r < fv.length; r++) {
    const row = fv[r], pen = String(row[fc('Student PEN')]).trim();
    if (!pen) continue;
    known.add(pen);
    if (!firstRow.has(pen)) firstRow.set(pen, row);
    if (String(row[fc('Current Status')]).trim() !== 'Not Studying') { if (!why.has(pen)) why.set(pen, 'Studying (field status)'); continue; }
    if (String(row[fc('Reason')]).trim() === 'Death') { why.set(pen, 'Death'); continue; }
    if (seen.has(pen)) continue;
    seen.add(pen);
    const ex = remarkExclusion_(row[fc('Remarks')]);
    if (ex) why.set(pen, ex); else valid.set(pen, row);
  }

  // 2. previous allotments: All Student Data rows stay unless the field now says otherwise
  const allT = readTab_(ss.getSheetByName(TAB_ALL), UDISE_COL);
  const H = allT.headers, hc = n => H.indexOf(n);
  const mapper = mapper_(centres);
  const kept = [], excluded = [], have = new Set();
  let relabelled = 0;
  allT.rows.forEach(r => {
    const pen = String(r[hc('Student PEN')]).trim();
    have.add(pen);
    if (known.has(pen) && !valid.has(pen)) { excluded.push([why.get(pen) || 'Not in field list', r]); return; }
    const row = r.slice();
    row[hc('Student PEN')] = pen;
    row[hc('Last UDISE Code')] = padUdise_(row[hc('Last UDISE Code')]);
    const u = padUdise_(row[hc('Centre UDISE Code')]);
    row[hc(UDISE_COL)] = u;
    if (row[hc('Admission Basis')] === B_COURSE_OLD) { row[hc('Admission Basis')] = B_COURSE; relabelled++; }
    const c = centres.get(u);
    if (c) Object.keys(CENTRE_COLS).forEach(h => { row[hc(h)] = c[CENTRE_COLS[h]]; });
    mapper.take(u);
    kept.push(row);
  });

  // 3. new students: first pass in field order, exceptions only after everyone else has a seat
  const fresh = [];
  valid.forEach((row, pen) => { if (!have.has(pen)) fresh.push(student_(row, fc, pen)); });
  const later = [];
  fresh.forEach(st => {
    const [u, basis] = mapper.firstPass(st);
    if (u) { mapper.take(u); st.u = u; st.basis = basis; } else later.push(st);
  });
  later.forEach(st => { const [u, basis] = mapper.secondPass(st); mapper.take(u); st.u = u; st.basis = basis; });
  const added = fresh.map(st => H.map(h => newCell_(h, st, centres)));

  // 4. every tab from the same final list
  const all = kept.concat(added);
  const isAcc = r => !!(centres.get(r[hc(UDISE_COL)]) || {}).ai;
  const map213 = all.filter(isAcc);
  const niosHead = headerOf_(ss.getSheetByName(TAB_NIOS_ALL));
  const nios = all.map(r => niosRow_(r, hc, niosHead.length, firstRow.get(String(r[hc('Student PEN')])), fc));
  const nios213 = nios.filter((_, i) => isAcc(all[i]));
  const count = centreCount_(centres, all, hc);

  const basis = {}, removed = {};
  fresh.forEach(st => { basis[st.basis] = (basis[st.basis] || 0) + 1; });
  excluded.forEach(([w]) => { removed[w] = (removed[w] || 0) + 1; });
  const stats = { ok: true, dryRun: dry, fieldRows: fv.length - 1, validStudents: valid.size,
    allBefore: allT.rows.length, allAfter: all.length, map213After: map213.length, kept: kept.length,
    removed: excluded.length, removedByReason: removed, added: added.length, addedBasis: basis,
    relabelled: relabelled, writes: {} };

  const plan = [
    ['all', TAB_ALL, all, H.length, MAP_TEXT.map(hc)],
    ['map213', TAB_MAP213, map213, H.length, MAP_TEXT.map(hc)],
    ['niosAll', TAB_NIOS_ALL, nios, niosHead.length, NIOS_TEXT],
    ['nios213', TAB_NIOS213, nios213, niosHead.length, NIOS_TEXT],
    ['count', TAB_COUNT, count, 12, [3]],
  ];
  plan.forEach(([key, name, rows, width, text]) => {
    if (!want(key)) return;
    stats.writes[key] = writeDiff_(ss.getSheetByName(name), rows, width, text, dry);
  });
  if (!dry) {
    if (want('all') && excluded.length) appendExcluded_(ss, H, excluded);
    CacheService.getScriptCache().removeAll(['idx:final', 'idx:survey', 'idx:nios:final', 'idx:nios:survey',
      'sum:final', 'sum:survey', 'sum:centres', 'centres', 'ai']);
    if (excluded.length || added.length || relabelled) log_(ss, stats);
  }
  stats.seconds = Math.round((Date.now() - t0) / 1000);
  return stats;
}

// ---- centres and placement ----
const padUdise_ = v => { const t = String(v === null || v === undefined ? '' : v).trim().replace(/\.0$/, ''); return /^\d{1,11}$/.test(t) ? t.padStart(11, '0') : t; };
const intOf_ = v => { const t = String(v === null || v === undefined ? '' : v).trim().replace(/\.0$/, ''); return /^\d+$/.test(t) ? Number(t) : null; };
const titleCase_ = t => String(t || '').trim().split(/\s+/).filter(String).map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');

function centreList_(ss) {
  const v = ss.getSheetByName(CENTRE_LIST_TAB).getDataRange().getDisplayValues();
  const h = v[0], c = n => h.indexOf(n);
  const ai = h.findIndex(x => String(x).indexOf('NIOS AI Code') === 0);
  const out = new Map();
  for (let r = 1; r < v.length; r++) {
    const row = v[r], u = padUdise_(row[c('UDISE Code')]);
    if (!u) continue;
    const type = String(row[c('Type')]).trim().toUpperCase();
    const g = String(row[c('Gender')]).trim();
    const dc = String(row[c('District Code')]).trim();
    out.set(u, {
      udise: u, dcode: dc ? dc.padStart(4, '0') : u.slice(0, 4), bcode: u.slice(0, 6),
      name: row[c('Centre Name')], address: row[c('Address')], block: row[c('Block')], district: row[c('District')],
      pin: row[c('Pin')], mobile: row[c('Mobile No.')], email: row[c('Email')], principal: row[c('Principal / Coordinator')],
      course: row[c('Course')] || 'Not specified', science: row[c('With Science')], medium: row[c('Medium')] || 'Hindi',
      gender: g === 'Girls' || g === 'Boys' ? g : 'Both', type: type,
      seats: Number(row[c('Seats')]) || { A: 500, B: 300, C: 150 }[type] || 0,
      pmshri: /^y/i.test(String(row[c('PM Shri')])) ? 'Yes' : '', ai: ai >= 0 ? String(row[ai]).trim() : '',
      typeRank: { A: 0, B: 1, C: 2 }[type] !== undefined ? { A: 0, B: 1, C: 2 }[type] : 3,
    });
  }
  return out;
}

function student_(row, fc, pen) {
  const udise = padUdise_(row[fc('Last UDISE Code')]);
  const ok = /^\d{11}$/.test(udise);
  const elig = intOf_(row[fc('Eligible Class to Import')]);
  const level = elig !== null ? elig : intOf_(row[fc('Last Class')]);
  return { pen: pen, row: row, fc: fc, udise: udise, dcode: ok ? udise.slice(0, 4) : '', bcode: ok ? udise.slice(0, 6) : '',
           sex: String(row[fc('Sex')]).trim().toUpperCase(), level: level,
           course: level === 9 || level === 10 ? 2 : level === 11 || level === 12 ? 3 : null };
}

const genderOk_ = (c, sex) => c.gender === 'Both' || (c.gender === 'Girls' && sex === 'FEMALE') || (c.gender === 'Boys' && sex === 'MALE');
const courseOk_ = (c, course) => course === null || [course === 2 ? 'Secondary' : 'Sr. Secondary', 'Both', 'Not specified'].indexOf(c.course) >= 0;

function mapper_(centres) {
  const allot = new Map(), byBlock = new Map(), byDist = new Map();
  const push = (m, k, u) => { if (!m.has(k)) m.set(k, []); m.get(k).push(u); };
  centres.forEach((c, u) => { push(byBlock, c.bcode, u); push(byDist, c.dcode, u); });
  const n = u => allot.get(u) || 0;
  const free = u => n(u) < centres.get(u).seats;
  const key = u => [n(u) / Math.max(centres.get(u).seats, 1), centres.get(u).typeRank, centres.get(u).pmshri ? 0 : 1];
  const best = us => {  // lowest allotted/seats, then Type A > B > C, then PM Shri first
    let b = null, bk = null;
    us.forEach(u => {
      const k = key(u);
      const less = !b || k[0] < bk[0] || (k[0] === bk[0] && (k[1] < bk[1] || (k[1] === bk[1] && (k[2] < bk[2] || (k[2] === bk[2] && u < b)))));
      if (less) { b = u; bk = k; }
    });
    return b;
  };
  const suitable = (u, st) => genderOk_(centres.get(u), st.sex) && courseOk_(centres.get(u), st.course) && free(u);
  const scopes = st => [byBlock.get(st.bcode) || [], byDist.get(st.dcode) || []];
  return {
    take: u => { if (u) allot.set(u, n(u) + 1); },
    firstPass: st => {
      if (centres.has(st.udise) && suitable(st.udise, st)) return [st.udise, B_OWN];
      const [blk, dist] = scopes(st);
      let u = best(blk.filter(x => suitable(x, st)));
      if (u) return [u, B_BLOCK];
      u = best(dist.filter(x => suitable(x, st)));
      if (u) return [u, B_DIST];
      for (const scope of [blk, dist]) {
        u = best(scope.filter(x => genderOk_(centres.get(x), st.sex) && free(x)));
        if (u) return [u, B_COURSE];
      }
      return [null, null];
    },
    secondPass: st => {
      for (const scope of scopes(st)) {
        if (!scope.length) continue;
        const fit = us => { const f = us.filter(x => courseOk_(centres.get(x), st.course)); return f.length ? f : us; };
        const groups = [scope.filter(x => genderOk_(centres.get(x), st.sex)), scope.filter(free), scope];
        for (const g of groups) {
          if (!g.length) continue;  // prefer a full centre of the right gender over a wrong-gender one
          const u = best(fit(g)), gOk = genderOk_(centres.get(u), st.sex), fOk = free(u);
          return [u, gOk ? X_SEATS : fOk ? X_GENDER : X_BOTH];
        }
      }
      return [null, NO_CENTRE];
    },
  };
}

function newCell_(h, st, centres) {
  const r = st.row, fc = st.fc, c = st.u ? centres.get(st.u) : null;
  switch (h) {
    case 'Student PEN': return st.pen;
    case 'Last UDISE Code': return st.udise;
    case 'Sex': return st.sex;
    case 'Eligible Class to Import': return st.level === null ? '' : st.level;
    case 'Current Status': return 'Not Studying';
    case 'Admission Basis': return st.basis;
    case UDISE_COL: return st.u || '';
  }
  if (CENTRE_COLS[h]) return c ? c[CENTRE_COLS[h]] : '';
  return fc(h) >= 0 ? String(r[fc(h)] || '').trim() : '';
}

// ---- NIOS admission format (63 columns; only the agreed cells filled) ----
function niosRow_(r, hc, width, f, fc) {
  const out = new Array(width).fill('');
  const get = h => String(r[hc(h)] === null || r[hc(h)] === undefined ? '' : r[hc(h)]).trim();
  const fget = h => (f && fc(h) >= 0 ? String(f[fc(h)] || '').trim() : '');
  const level = intOf_(get('Eligible Class to Import'));
  const lastClass = fget('Last Class') || get('Eligible Class to Import');
  const addr = 'Block ' + titleCase_(get('Block Name')) + ', District ' + titleCase_(get('District Name')) + ', Uttar Pradesh';
  const set = (i, v) => { if (i < width) out[i] = v === null || v === undefined ? '' : v; };
  if (get(UDISE_COL)) set(2, get('Centre Name') + ', ' + titleCase_(get('Centre Block')) + ', ' + titleCase_(get('Centre District')));
  set(3, level === 9 || level === 10 ? 2 : level === 11 || level === 12 ? 3 : '');
  set(4, 1); set(6, get('Centre Email')); set(7, get('Mobile No')); set(8, get('Student Name'));
  set(9, get('Father Name')); set(10, get('Mother Name')); set(11, dob_(fget('Date of Birth (DOB)')));
  set(12, aadhaar_(fget('Aadhaar Number'))); set(13, get('Sex').toLowerCase()); set(15, 'Hindi');
  set(32, lastClass ? 'Class ' + lastClass : ''); set(33, 'Failed'); set(34, addr); set(41, addr);
  set(37, 'Uttar Pradesh'); set(44, 'Uttar Pradesh'); set(38, get('District Name')); set(45, get('District Name'));
  set(39, get('Centre Pin')); set(46, get('Centre Pin')); set(48, get(UDISE_COL));
  return out;
}

function dob_(v) {
  const t = String(v || '').trim().slice(0, 10);
  let m = t.match(/^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})$/), y, mo, d;
  if (m) { y = +m[1]; mo = +m[2]; d = +m[3]; } else if ((m = t.match(/^(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{4})$/))) { d = +m[1]; mo = +m[2]; y = +m[3]; } else return '';
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return '';
  return String(d).padStart(2, '0') + '-' + String(mo).padStart(2, '0') + '-' + y;
}

function aadhaar_(v) {
  const d = String(v || '').replace(/\D/g, '');
  if (d.length !== 12 || /^(\d)\1+$/.test(d) || d === '123456789012' || d === '012345678901') return '';
  return d;
}

// ---- Centre-wise Count ----
function centreCount_(centres, rows, hc) {
  const n = {}, m = {};
  rows.forEach(r => {
    const u = r[hc(UDISE_COL)];
    n[u] = (n[u] || 0) + 1;
    if (String(r[hc('Sex')]).toUpperCase() === 'MALE') m[u] = (m[u] || 0) + 1;
  });
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const list = [...centres.values()].sort((a, b) => cmp(a.dcode, b.dcode) || cmp(a.block, b.block) || cmp(a.name, b.name) || cmp(a.udise, b.udise));
  const out = list.map((c, i) => [i + 1, c.district, c.block, c.udise, c.name, c.gender, c.type, c.seats,
                                   n[c.udise] || 0, m[c.udise] || 0, (n[c.udise] || 0) - (m[c.udise] || 0), c.seats - (n[c.udise] || 0)]);
  const sum = k => out.reduce((a, r) => a + r[k], 0);
  out.push(['', '', '', '', 'TOTAL', '', '', sum(7), sum(8), sum(9), sum(10), sum(11)]);
  return out;
}

// ---- sheet I/O ----
function headerOf_(sh) {
  return sh.getRange(1, 1, 1, sh.getLastColumn()).getDisplayValues()[0].filter(String);
}

function readTab_(sh, keyCol) {
  const h = headerRow_(sh, keyCol);
  const headers = h.headers.filter(String);
  const n = Math.max(sh.getLastRow() - h.row, 0);
  const rows = n ? sh.getRange(h.row + 1, 1, n, headers.length).getValues() : [];
  return { headerRow: h.row, headers: headers, rows: rows.filter(r => String(r[0]).trim() !== '') };
}

// Rewrites the tab from its first row that differs; IDs are written as text.
function writeDiff_(sh, rows, width, textCols, dry) {
  const top = sh.getRange(1, 1, Math.min(3, Math.max(sh.getLastRow(), 1)), width).getDisplayValues();
  let first = 2; // data starts under the header; tabs with a title row have the header in row 2
  for (let r = 0; r < top.length; r++) if (top[r].filter(String).length >= Math.min(5, width)) { first = r + 2; break; }
  const n = Math.max(sh.getLastRow() - first + 1, 0);
  const cur = n ? sh.getRange(first, 1, n, width).getValues() : [];
  const key = r => r.map(v => (v === null || v === undefined ? '' : String(v))).join('\u0001');
  let start = 0;
  const lim = Math.min(cur.length, rows.length);
  while (start < lim && key(cur[start]) === key(rows[start])) start++;
  const tail = rows.slice(start), cleared = Math.max(cur.length - rows.length, 0);
  if (!dry) {
    if (tail.length) {
      textCols.forEach(c => { if (c >= 0) sh.getRange(first + start, c + 1, tail.length, 1).setNumberFormat('@'); });
      const out = tail.map(r => r.map((v, c) => (textCols.indexOf(c) >= 0 && v !== '' ? String(v) : v)));
      for (let i = 0; i < out.length; i += 4000) { // chunked: one huge write can time out
        const part = out.slice(i, i + 4000);
        sh.getRange(first + start + i, 1, part.length, width).setValues(part);
      }
    }
    if (cleared) sh.getRange(first + rows.length, 1, cleared, width).clearContent();
  }
  return { fromRow: first + start, rowsWritten: tail.length, rowsCleared: cleared };
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
  const rows = excluded.map(([w, r]) => r.map((v, c) => MAP_TEXT.indexOf(H[c]) >= 0 ? String(v) : v).concat([w, when]));
  const start = sh.getLastRow() + 1;
  MAP_TEXT.forEach(name => { const c = H.indexOf(name); if (c >= 0) sh.getRange(start, c + 1, rows.length, 1).setNumberFormat('@'); });
  sh.getRange(start, 1, rows.length, head.length).setValues(rows);
}

function log_(ss, s) {
  const sh = ss.getSheetByName(LOG_TAB) || ss.insertSheet(LOG_TAB);
  const head = ['Time', 'Valid students (field)', 'Added', 'Added by basis', 'Removed', 'Relabelled', 'All Student Data', 'MAP Data 213 centre', 'Removed by reason'];
  sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.appendRow([Utilities.formatDate(new Date(), 'Asia/Kolkata', 'dd-MM-yyyy HH:mm'), s.validStudents, s.added, JSON.stringify(s.addedBasis),
                s.removed, s.relabelled, s.allAfter, s.map213After, JSON.stringify(s.removedByReason)]);
}
