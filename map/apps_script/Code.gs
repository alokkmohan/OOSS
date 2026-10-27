/**
 * NIOS Centre Map — login API for ooss.dataimpact.in/map
 *
 * Reads the "NIOS All Centre Mapping - Out of School Students" Google Sheet.
 * A centre logs in with its UDISE (User ID and Password are both the UDISE)
 * and gets back only its own students. No student data lives in the GitHub repo.
 *
 * Tabs read (kept up to date by Sync.js):
 *   Centre List                 - centre master (every centre can log in)
 *   Centre-wise Count           - per-centre counts
 *   All Student Data            - student list ("MAP Data" format)
 *   NIOS Format All student     - the same students in the NIOS admission format
 *
 * Deploy: Deploy → New deployment → Web app, Execute as: Me,
 * Who has access: Anyone. Put the /exec URL in map/index.html (API_URL).
 */

const SHEET_ID = '1_O6YJji1mC3-8n4uhz1IBZnY-4CDXDPM8jBt-tgRcMI'; // "NIOS All Centre Mapping - Out of School Students"
const CENTRES_TAB = 'Centre-wise Count';
const DATA_TABS = { final: 'MAP Data 213 centre', survey: 'All Student Data' };
const UDISE_COL = 'Centre UDISE Code';
const CENTRE_LIST_TAB = 'Centre List';
const NIOS_TABS = { final: 'NIOS Format 213 centre', survey: 'NIOS Format All student' };
const NIOS_CODE_COL = 'Study Centre Code';
const CENTRE_SEES_AADHAAR = false; // centre downloads leave the Aadhaar column blank unless this is true

// NIOS AI Codes — NIOS notification 20/2026 dated 07-08-2026, Annexure-I (used only until the Centre List tab exists)
const AI_CODES = {
  '09151714173':'G21001', '09151711940':'G21002', '09121108012':'G21003', '09730208001':'G21004', '09732502201':'G21005',
  '09731703504':'G21006', '09732701209':'G21007', '09471205909':'G21008', '09612301305':'G21009', '09611604608':'G21010',
  '09191603004':'G21011', '09190800117':'G21012', '09192100333':'G21013', '09192100288':'G21014', '09500203010':'G21015',
  '09500703604':'G21016', '09501301105':'G21017', '09400102522':'G21018', '09400902302':'G21019', '09400900404':'G21020',
  '09460403405':'G21021', '09461621202':'G21022', '09460805708':'G21023', '09460106303':'G21024', '09460609416':'G21025',
  '09461110119':'G21026', '09461621201':'G21027', '09201300412':'G21028', '09200700205':'G21029', '09201910704':'G21030',
  '09550314108':'G21031', '09710221518':'G21032', '09030806511':'G21033', '09030501608':'G21034', '09030102505':'G21035',
  '09030208202':'G21036', '09031203905':'G21037', '09660700806':'G21038', '09660907306':'G21039', '09410304106':'G21040',
  '09410403909':'G21041', '09601502903':'G21042', '09601502902':'G21043', '09310907904':'G21044', '09290703803':'G21045',
  '09290209907':'G21046', '09420400103':'G21047', '09421401917':'G21048', '09421402518':'G21049', '09160311004':'G21050',
  '09160202503':'G21051', '09531101002':'G21052', '09531100605':'G21053', '09580203302':'G21054', '09580702902':'G21055',
  '09580213902':'G21056', '09380802001':'G21057', '09380108620':'G21058', '09380707109':'G21059', '09380400112':'G21060',
  '09250904203':'G21061', '09251802705':'G21062', '09350315603':'G21063', '09360413201':'G21064', '09360306909':'G21065',
  '09360714414':'G21066', '09360307009':'G21067', '09360106216':'G21068', '09231008402':'G21069', '09330210405':'G21070',
  '09340907956':'G21071', '09721901301':'G21072', '09370500119':'G21073', '09370107806':'G21074', '09370400110':'G21075',
  '09370700109':'G21076', '09270404806':'G21077', '09270700612':'G21078', '09390108523':'G21079', '09390500939':'G21080',
  '09390108524':'G21081', '09390500965':'G21082', '09181002917':'G21083', '09180811515':'G21084', '09180115230':'G21085',
  '09140200114':'G21086', '09691304906':'G21087', '09210904268':'G21088', '09210904267':'G21089', '09210708942':'G21090',
  '09210204408':'G21091', '09210707902':'G21092', '09430402706':'G21093', '09430401003':'G21094', '09451606902':'G21095',
  '09452211107':'G21096', '09451806805':'G21097', '09452200605':'G21098', '09450609903':'G21099', '09451605402':'G21100',
  '09282208604':'G21101', '09280403609':'G21102', '09282306503':'G21103', '09282208603':'G21104', '09050315823':'G21105',
  '09050619004':'G21106', '09050705613':'G21107', '09050211713':'G21108', '09050514917':'G21109', '09050701903':'G21110',
  '09681300307':'G21111', '09561500506':'G21112', '09221507402':'G21113', '09221501009':'G21114', '09241300117':'G21115',
  '09241605008':'G21116', '09241910803':'G21117', '09241010002':'G21118', '09242000315':'G21119', '09241505705':'G21120',
  '09242301416':'G21121', '09700300714':'G21122', '09700112318':'G21123', '09700400308':'G21124', '09700106103':'G21125',
  '09700700704':'G21126', '09700208504':'G21127', '09700100503':'G21128', '09700807506':'G21129', '09700208505':'G21130',
  '09490403121':'G21131', '09492300512':'G21132', '09492300510':'G21133', '09261702951':'G21134', '09260805106':'G21135',
  '09261702950':'G21136', '09671000103':'G21137', '09670900603':'G21138', '09670509206':'G21139', '09670900605':'G21140',
  '09670514201':'G21141', '09671001402':'G21142', '09062202551':'G21143', '09062500230':'G21144', '09110803903':'G21145',
  '09071207718':'G21146', '09071300179':'G21147', '09071100118':'G21148', '09071304120':'G21149', '09041402835':'G21150',
  '09040306005':'G21151', '09040908605':'G21152', '09040800132':'G21153', '09021500266':'G21154', '09020603506':'G21155',
  '09020404852':'G21156', '09011400504':'G21157', '09090404624':'G21158', '09090900315':'G21159', '09100101804':'G21160',
  '09470103101':'G21161', '09470103603':'G21162', '09470109407':'G21163', '09471300102':'G21164', '09471501703':'G21165',
  '09471502405':'G21166', '09470200402':'G21167', '09470205405':'G21168', '09470401503':'G21169', '09470607608':'G21170',
  '09470609301':'G21171', '09470706504':'G21172', '09470711203':'G21173', '09470713301':'G21174', '09471400204':'G21175',
  '09471201503':'G21176', '09471202303':'G21177', '09471207202':'G21178', '09470803105':'G21179', '09470810609':'G21180',
  '09470902310':'G21181', '09470907604':'G21182', '09470910903':'G21183', '09472302403':'G21184', '09471003511':'G21185',
  '09471004907':'G21186', '09510100116':'G21187', '09510103104':'G21188', '09510106412':'G21189', '09510109605':'G21190',
  '09510209816':'G21191', '09510208003':'G21192', '09510208303':'G21193', '09510206205':'G21194', '09510216503':'G21195',
  '09510209503':'G21196', '09510207403':'G21197', '09510300131':'G21198', '09510302403':'G21199', '09510311401':'G21200',
  '09510305104':'G21201', '09510303105':'G21202', '09510407103':'G21203', '09510409004':'G21204', '09510404906':'G21205',
  '09510401103':'G21206', '09510611204':'G21207', '09510607704':'G21208', '09510601103':'G21209', '09510603503':'G21210',
  '09510604803':'G21211', '09510610003':'G21212', '09510603804':'G21213'
};

function json_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

// Run once from the editor (Run → authorize) to grant the Sheet permission.
function authorize() {
  Logger.log(SpreadsheetApp.openById(SHEET_ID).getName());
}

// GET ?action=summary — public, no student-level data: the centre list (with
// AI codes) and per-centre counts for the Centre-wise table and Centre Code tab.
function doGet(e) {
  try {
    if (e && e.parameter && e.parameter.action === 'summary') return json_(summary_());
    return json_({ ok: true, service: 'nios-centre-map' });
  } catch (err) {
    return json_({ ok: false, error: 'Server error: ' + err.message });
  }
}

// Accredited centres: UDISE -> NIOS AI Code, from the Centre List tab.
function aiCodes_() {
  return cached_('ai', function () {
    const sh = SpreadsheetApp.openById(SHEET_ID).getSheetByName(CENTRE_LIST_TAB);
    if (!sh) return AI_CODES;
    const v = sh.getDataRange().getDisplayValues(), h = v[0];
    const cu = h.indexOf('UDISE Code'), ca = h.findIndex(x => String(x).indexOf('NIOS AI Code') === 0);
    const out = {};
    for (let r = 1; r < v.length; r++) {
      const u = code_(v[r][cu]), a = String(v[r][ca] || '').trim();
      if (u && a) out[u] = a;
    }
    return out;
  });
}

function summary_() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  const ai = aiCodes_();
  // [udise, name, district, block, gender, type, seats, aiCode]
  const centres = cached_('sum:centres', function () {
    const sh = ss.getSheetByName(CENTRES_TAB);
    const h = headerRow_(sh, 'Centre UDISE');
    const values = sh.getRange(h.row + 1, 1, sh.getLastRow() - h.row, h.headers.length).getDisplayValues();
    const col = name => h.headers.indexOf(name);
    return values.filter(r => r[col('Centre UDISE')]).map(function (r) {
      const u = code_(r[col('Centre UDISE')]);
      return [u, r[col('Centre Name')], r[col('District')], r[col('Block')], r[col('Gender')],
              r[col('Type')], Number(r[col('Seats')]) || 0, ai[u] || ''];
    });
  });
  const out = { ok: true, centres: centres };
  Object.keys(DATA_TABS).forEach(function (key) {
    // { udise: [students, male] }
    out[key] = cached_('sum:' + key, function () {
      const sh = ss.getSheetByName(DATA_TABS[key]);
      const h = sh && headerRow_(sh, UDISE_COL);
      const counts = {};
      if (!h || sh.getLastRow() <= h.row) return counts;
      const n = sh.getLastRow() - h.row;
      const codes = sh.getRange(h.row + 1, h.headers.indexOf(UDISE_COL) + 1, n, 1).getValues();
      const sex = sh.getRange(h.row + 1, h.headers.indexOf('Sex') + 1, n, 1).getValues();
      codes.forEach(function (c, i) {
        const u = code_(c[0]);
        if (!u) return;
        const e = counts[u] || (counts[u] = [0, 0]);
        e[0]++;
        if (String(sex[i][0]).toUpperCase() === 'MALE') e[1]++;
      });
      return counts;
    });
  });
  return out;
}

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const udise = String(body.udise || '').trim();
    const password = String(body.password || '').trim();
    if (!udise || !password) return json_({ ok: false, error: 'User ID और Password दोनों भरें।' });
    if (udise.toLowerCase() === 'admin') return json_(admin_(password, body.key, body));

    if (password !== udise) return json_({ ok: false, error: 'User ID या Password गलत है।' });
    const ai = aiCodes_();
    const ss = SpreadsheetApp.openById(SHEET_ID);
    if (body.action === 'nios') return json_(niosFor_(ss, [udise], 'survey', CENTRE_SEES_AADHAAR));
    const centre = findCentre_(ss, udise);
    if (!centre) return json_({ ok: false, error: 'User ID या Password गलत है।' });
    centre['AI Code'] = ai[udise] || '';

    const list = studentsFor_(ss, 'survey', udise);
    return json_({ ok: true, centre: centre, survey: list, final: list }); // 'final' kept for older page versions
  } catch (err) {
    return json_({ ok: false, error: 'Server error: ' + err.message });
  }
}

// Admin sees every student of one data tab. The password lives in Script
// Properties (ADMIN_PASSWORD), never in this file — the repo is public.
// Columns are dictionary-encoded ({dict, idx}) to keep the 36k-row reply small.
function admin_(password, key, body) {
  const expected = String(PropertiesService.getScriptProperties().getProperty('ADMIN_PASSWORD') || '').trim();
  if (!expected) return { ok: false, error: 'Admin login अभी चालू नहीं है (ADMIN_PASSWORD set नहीं)।' };
  if (password !== expected) return { ok: false, error: 'User ID या Password गलत है।' };
  if (key === 'syncdry') return sync_({ dryRun: true });
  if (key === 'syncnow') return sync_({ tabs: body.tabs });
  if (key === 'nios') return niosFor_(SpreadsheetApp.openById(SHEET_ID), body.centres || [], body.tab, true);
  if (!DATA_TABS[key]) return { ok: true, admin: true };
  const sh = SpreadsheetApp.openById(SHEET_ID).getSheetByName(DATA_TABS[key]);
  const h = headerRow_(sh, UDISE_COL);
  const headers = h.headers.filter(String);
  const n = sh.getLastRow() - h.row;
  const values = n > 0 ? sh.getRange(h.row + 1, 1, n, headers.length).getDisplayValues() : [];
  const cols = headers.map(function (name, c) {
    const lookup = {}, dict = [], idx = new Array(values.length);
    for (let r = 0; r < values.length; r++) {
      const v = name === UDISE_COL ? code_(values[r][c]) : values[r][c];
      let i = lookup[v];
      if (i === undefined) { i = lookup[v] = dict.length; dict.push(v); }
      idx[r] = i;
    }
    return { name: name, dict: dict, idx: idx };
  });
  return { ok: true, admin: true, key: key, students: values.length, cols: cols };
}

// Lookups (which rows belong to which centre) are cached for 30 minutes so a
// login reads only that centre's rows. A stale lookup is detected on read and
// rebuilt, so edits to the Sheet still show up.
const CACHE_SECONDS = 1800;

function cached_(key, build, force) {
  const cache = CacheService.getScriptCache();
  if (!force) {
    const hit = cache.get(key);
    if (hit) return JSON.parse(hit);
  }
  const value = build();
  try { cache.put(key, JSON.stringify(value), CACHE_SECONDS); } catch (e) { /* too large to cache */ }
  return value;
}

const code_ = v => { const s = String(v).trim(); return /^\d{10}$/.test(s) ? '0' + s : s; };

// Header row is row 1 or 2 (some tabs have a title row above it).
function headerRow_(sh, name) {
  const top = sh.getRange(1, 1, 3, sh.getLastColumn()).getDisplayValues();
  for (let r = 0; r < top.length; r++) if (top[r].indexOf(name) >= 0) return { row: r + 1, headers: top[r] };
  return null;
}

// Details of every centre, from the Centre-wise Count tab.
function findCentre_(ss, udise) {
  const all = cached_('centres', function () {
    const sh = ss.getSheetByName(CENTRES_TAB);
    const h = headerRow_(sh, 'Centre UDISE');
    if (!h) return {};
    const values = sh.getRange(h.row + 1, 1, sh.getLastRow() - h.row, h.headers.length).getDisplayValues();
    const col = name => h.headers.indexOf(name);
    const out = {};
    values.forEach(function (r) {
      const u = code_(r[col('Centre UDISE')]);
      if (u) out[u] = { UDISE: u, 'Centre Name': r[col('Centre Name')], District: r[col('District')],
                                  Block: r[col('Block')], Gender: r[col('Gender')], Seats: r[col('Seats')] };
    });
    return out;
  });
  return all[udise] || null;
}

// { headerRow, headers, runs: { udise: [[firstRow, count], ...] } } for one data tab.
function index_(sh, key, force) { return codeIndex_(sh, key, UDISE_COL, force); }

function codeIndex_(sh, key, colName, force) {
  return cached_('idx:' + key, function () {
    const h = headerRow_(sh, colName);
    if (!h) return { headerRow: 0, headers: [], runs: {} };
    const headers = h.headers.filter(String);
    const n = sh.getLastRow() - h.row, runs = {};
    if (n > 0) {
      const codes = sh.getRange(h.row + 1, headers.indexOf(colName) + 1, n, 1).getValues();
      let prev = null;
      codes.forEach(function (c, i) {
        const u = code_(c[0]);
        if (u === prev) runs[u][runs[u].length - 1][1]++;
        else (runs[u] = runs[u] || []).push([h.row + 1 + i, 1]);
        prev = u;
      });
    }
    return { headerRow: h.row, headers: headers, runs: runs, lastRow: sh.getLastRow() };
  }, force);
}

function studentsFor_(ss, key, udise, force) {
  const sh = ss.getSheetByName(DATA_TABS[key]);
  if (!sh) return { headers: [], rows: [] };
  const idx = index_(sh, key, force);
  if (!force && idx.lastRow !== sh.getLastRow()) return studentsFor_(ss, key, udise, true);
  const col = idx.headers.indexOf(UDISE_COL), rows = [];
  let stale = false;
  (idx.runs[udise] || []).forEach(function (run) {
    sh.getRange(run[0], 1, run[1], idx.headers.length).getDisplayValues().forEach(function (r) {
      if (code_(r[col]) === udise) rows.push(r); else stale = true;
    });
  });
  if (stale && !force) return studentsFor_(ss, key, udise, true);
  return { headers: idx.headers, rows: rows };
}

// NIOS admission-format rows (63 columns) for the given centres; all rows when none are given.
function niosFor_(ss, codes, tab, withAadhaar) {
  const key = NIOS_TABS[tab] ? tab : 'survey';
  const sh = ss.getSheetByName(NIOS_TABS[key]);
  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getDisplayValues()[0].filter(String);
  const col = headers.indexOf(NIOS_CODE_COL), aad = headers.findIndex(h => /aadh?a?a?r/i.test(h));
  const n = sh.getLastRow() - 1, want = new Set(codes.map(code_));
  let rows = [];
  if (n > 0 && (!want.size || want.size > 40)) {      // many centres: read the tab once
    rows = sh.getRange(2, 1, n, headers.length).getDisplayValues().filter(r => !want.size || want.has(code_(r[col])));
  } else if (n > 0) {                                  // a few centres: read only their rows
    let idx = codeIndex_(sh, 'nios:' + key, NIOS_CODE_COL);
    if (idx.lastRow !== sh.getLastRow()) idx = codeIndex_(sh, 'nios:' + key, NIOS_CODE_COL, true);
    want.forEach(u => (idx.runs[u] || []).forEach(run => sh.getRange(run[0], 1, run[1], headers.length).getDisplayValues()
      .forEach(r => { if (code_(r[col]) === u) rows.push(r); })));
  }
  if (!withAadhaar && aad >= 0) rows.forEach(r => { r[aad] = ''; });
  if (rows.length <= 3000) return { ok: true, headers: headers, rows: rows };
  // large replies are dictionary-encoded per column, like the admin student dump
  const cols = headers.map((_, c) => {
    const lookup = {}, dict = [], idx = new Array(rows.length);
    rows.forEach((r, i) => { const v = r[c]; let k = lookup[v]; if (k === undefined) { k = lookup[v] = dict.length; dict.push(v); } idx[i] = k; });
    return { dict: dict, idx: idx };
  });
  return { ok: true, headers: headers, n: rows.length, cols: cols };
}
