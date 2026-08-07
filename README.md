# Out-of-School Student Status Classifier — UP Education Dept.

Classifies district-collected "out of school student" survey data into
**Studying / Not Studying (Willing / Unwilling) / Unclear**, based on free-text
`current Status` and `Remark` fields that districts fill in inconsistently
(mixed English/Hindi, heavy typos, no fixed vocabulary).

## Why this exists

75 districts across UP were sent a master dropout list (Class 9/10/11,
~90,000 students) to verify: is this student studying somewhere, or genuinely
out of school? Districts phone the families and write back whatever they
want in a free-text `current Status` / `Remark` column — no standard format.
This project turns that free text into a clean, reportable classification.

As of the last run: **46 of 75 districts** have responded (40,068 of 90,048
records). Of those, only ~19,000 have a clear studying/not-studying outcome —
the rest is either genuinely unclear (couldn't reach the family) or just
badly filled in ("khanapurti").

## Project layout

```
classify.py                          # main classification engine + CLI
map_to_dashboard.py                  # populates the statewide dashboard template
data/
  confirmed_studying_phrases.txt     # hand-verified exact-match overrides (578 phrases)
outputs/                             # your generated reports land here (gitignored)
```

## Quick start

```bash
pip install pandas openpyxl

# Classify one district file
python classify.py path/to/district_report.xlsx -o outputs/classified.xlsx

# Same, but also show what % of the full master list this represents
python classify.py path/to/district_report.xlsx -o outputs/classified.xlsx --master-total 90048

# Push the classified data into the statewide dashboard template
python map_to_dashboard.py outputs/classified.pkl path/to/OOS_Dashboard_75Districts.xlsx -o outputs/dashboard_populated.xlsx

# Dashboard has live Excel formulas — force them to recalculate without
# opening Excel by hand (needs LibreOffice installed):
soffice --headless --convert-to xlsx --outdir outputs/ outputs/dashboard_populated.xlsx
```

### Expected input columns

`District Name, Block Name, Student Name, Father Name, Gender, Category,
Class, Droupout Year, Address, Mobile No., current Status, Remark`

(Column names are matched exactly, including the "Droupout" typo — that's
what's in the source files.)

## How classification works

`classify.py` runs the free text through several layers, **in this priority
order** (later layers can override earlier ones):

1. **Garbage patterns** — blank, `-`, `&`, "Active for Import/Status Not
   Known", "wrong number", "switched off", "call not received", etc. (English
   + Hindi). Anything matching this and nothing more informative → *no real
   status obtained*.
2. **Studying patterns** — "studying", "admission", institution names +
   class numbers, "pass out", Hindi "अध्ययनरत"/"नामांकित"/"पढ़ रहा", etc.
3. **Not-studying patterns** — "dropout", "left school", "not interested",
   "married"/"शादी", "labour"/"मजदूरी", "TC issued", etc.
4. **Priority resolution** — if a string matches both a studying and a
   not-studying pattern, studying/not-studying (info-bearing) wins over
   garbage; a few explicit overrides exist for known false-positives (see
   "Gotchas" below).
5. **Contact-failure override** — if a row landed in "Not Studying" only
   because a dropout keyword happened to co-occur with "no contact"/"wrong
   number" text, it's pulled back to Unclear — a phone failure is not a
   verified outcome.
6. **Exact-match overrides** (`data/confirmed_studying_phrases.txt`) — ~580
   phrases that were manually reviewed and confirmed to mean "studying"
   (mostly institution names and Hindi sentences the regex patterns
   couldn't reliably catch). Checked against **both** `current Status` and
   `Remark`, since many districts put the real answer in Remark and leave
   Status blank or just paste the mobile number into it.
7. **Bare-number rule** — if `current Status` is just "9", "10", "12" (a
   stray class number, not an answer) → Not Studying.
8. **Long-numeric fallback** — if `current Status` is a duplicated mobile
   number, fall back to classifying the `Remark` column instead.
9. **Willingness sub-split** (within Not Studying only) — "Willing" (economic/
   external reason, e.g. labour, marriage, TC issue, or reason simply not
   given) vs. "Unwilling" (explicit "not interested", guardian refusal,
   student refused). **Death cases are excluded from Unwilling** — they're
   tracked via a separate `Death_Flag` column and don't reflect a choice.

### Output workbook sheets

- **Summary** — headline counts, optionally with % against a master-list total
- **District-wise Breakup** — Total / Studying / Not Studying / Unclear per district
- **Known - Studying**, **Known - Not Studying**, **Garbage_Unclear**, **Death Cases**
- **Unwilling (with reason)** — the Unwilling subset with a `Detected Reason`
  column (Marriage / Death / Guardian not interested / Student not interested)

## Known limitations — read before promising numbers

- **NIOS/Open School interest, vocational-education interest, and
  formal-vs-open-school preference are NOT captured anywhere in the source
  data.** Districts were never asked these questions in the current survey
  format. Don't try to derive them from `current Status` text — there's
  nothing there. (There's a proper structured tracking template — see
  "Related files" below — that has dedicated columns for this; it should be
  used for the *next* round of data collection if this is needed.)
- The classifier is pattern-based, not ML. New phrasing that doesn't match
  any pattern falls into "Unclear/Other (needs manual review)" — inspect
  that sheet after every new district batch and feed genuinely-studying
  entries into `data/confirmed_studying_phrases.txt` (one phrase per line).
- District name spelling varies a lot across files (`GB NAGAR` / `Gautam
  Buddha Nagar` / `GAUTAM BUDDHA NAGAR`, `Saharanpur` / `Saharanpur ` with a
  trailing space, casing differences, etc.). `map_to_dashboard.py` has a
  `DISTRICT_ALIAS` dict for the mismatches found so far — extend it if a new
  file introduces a new variant.
- The dashboard template's formulas are hardcoded to scan rows up to 30,000.
  `map_to_dashboard.py` automatically widens this to 50,000, but if a future
  combined file exceeds ~49,997 rows, bump `new_bound` in
  `widen_formula_ranges()`.

## Gotchas worth knowing about (learned the hard way)

- **"PEN No" false-triggers the negation check.** The generic negation
  filter treats any "No" as "not" (to catch "not interested" etc.), which
  wrongly excluded strings like "Already in class XII **with PEN No**:
  ...". There's an explicit override for `already\s*in\s*class` and
  `did\s*not\s*take\s*t\.?c` — if you add new patterns and see similar
  false-negation bugs, add an override rather than loosening the negation
  regex globally.
- **Hindi text needs NFC normalization before regex matching.** The same
  Devanagari string can be byte-different depending on how the source file
  encoded combining marks (composed vs. decomposed). Every string comparison
  in this codebase goes through `unicodedata.normalize("NFC", ...)` — don't
  skip this if you add new matching code, or Hindi patterns will silently
  fail to match despite looking identical on screen.
- **"Other" reason double-counts in the dashboard template if you're not
  careful.** The original template used a plain `COUNTIF` on the Reason
  Category column for "Other", which doesn't distinguish "Other (Not
  Studying)" from "Other (Unclear)" — both showed the same inflated number.
  `map_to_dashboard.py` writes distinct Reason Category values per group, but
  if you regenerate the dashboard template from scratch, use `COUNTIFS`
  (Reason Category AND Status Category) not `COUNTIF`.

## Live dashboard, in-Sheet (primary)

```bash
python push_dashboard_to_sheet.py
```

Reads the classified data tabs (`Known - Studying`, `Known - Not Studying`,
`Unwilling - Does Not Want to Study`, `Unclear`, `Death Cases`), recomputes
every aggregate, and writes a **`Dashboard`** tab as the first tab in the
Sheet — summary KPIs, willingness split, gender/category breakdowns, a
district-wise table sorted by highest Unclear % first, and 5 native Sheets
charts. Safe to re-run any time new district data lands; it clears and
rewrites the tab (and deletes+recreates the charts) each time rather than
appending, so there's no drift or duplication.

Needs the service account to have **Editor** access to the Sheet (Viewer is
enough for `fetch_dashboard_data.py` below, but not for writing).

## Live dashboard (Google Sheets → static site)

`index.html` / `app.js` / `styles.css` is a lightweight static dashboard
(Chart.js, no build step) driven entirely by `dashboard_data.json`. It reads
row-level data from the `fact_student_status` tab of a Google Sheet — it does
**not** re-run classification; `Status_Category`, `Willingness_Category`, and
`Death_Flag` are expected to already be populated in that sheet.

### One-time setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create/reuse
   a project and enable the **Google Sheets API**.
2. Create a **Service Account**, then a JSON key for it. Save the key as
   `service_account.json` in the project root (already gitignored).
3. Open the Google Sheet → Share → add the service account's email
   (`...@...iam.gserviceaccount.com`, in the JSON key file) as **Viewer**.
4. `pip install -r requirements.txt`

### Refreshing the dashboard

```bash
python fetch_dashboard_data.py
```

This pulls `fact_student_status`, recomputes all aggregates (district
breakdown, willingness split, gender/category crosstabs, status summary),
and overwrites `dashboard_data.json`. Nothing is hardcoded to a row count or
district count, so re-running this as more districts report in is safe —
just open `index.html` afterward (or refresh it) to see the update.

Run `python fetch_dashboard_data.py --sheet-id <id>` to point at a different
sheet, or `--creds <path>` for a different service account key.

**Note:** the row-level `records` export used for the searchable student
table deliberately excludes Address and Mobile No. to limit how much PII
ends up sitting in a plain JSON file on disk — add them into
`fetch_dashboard_data.py`'s `records` list if the table view needs them.

## Related files (not in this repo, but referenced)

- `Out_of_School_Student_Tracking_Template.xlsx` — a per-student structured
  intake form (dropdowns for Reason for Dropout, Current Activity, Mode of
  Study, NIOS interest, etc.) intended for the *next* round of district data
  collection, so these gaps don't recur.
- `OOS_Dashboard_75Districts.xlsx` — the statewide dashboard template that
  `map_to_dashboard.py` populates.
- The original ~90,048-record master list sent to districts (used for the
  `--master-total` coverage percentages).

## Extending the patterns

If a new district batch has a lot of "Unclear" results with an obvious
common phrase:

1. Search the Garbage_Unclear sheet for the phrase.
2. Decide: is it a *pattern* (generalizes well, e.g. a typo variant of an
   existing keyword) or a *specific phrase* (institution name, one-off
   sentence)?
   - Pattern → add a regex to the relevant list in `classify.py`
     (`STUDYING_PATTERNS`, `NOT_STUDYING_PATTERNS`, etc.)
   - Specific phrase → append it as a new line to
     `data/confirmed_studying_phrases.txt` (only add phrases you're
     confident mean "studying" — this list is an exact-match override with
     no ambiguity handling)
3. Re-run `classify.py` and check the Unclear count dropped as expected.
