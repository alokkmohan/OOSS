"""
Fetch Out-of-School Student Tracking data from Google Sheets and build
dashboard_data.json for the static dashboard (index.html / app.js).
=====================================================================

Does NOT re-derive classification. The source Sheet is a classify.py-style
multi-sheet report (one tab per bucket), NOT a single fact table:

    Known - Studying                     (Status_Category)
    Known - Not Studying                 (Status_Category; Willingness_Category
                                           is NOT included here)
    Unwilling - Does Not Want to Study   (subset of the above, with
                                           Willingness_Category filled in —
                                           rows in "Known - Not Studying" that
                                           don't appear here are Willing)
    Unclear                              (garbage + unclear combined already)
    Death Cases                          (subset of Known - Not Studying,
                                           overlaid as Deceased)

This script reads all five tabs, tags each row with a status bucket, and
aggregates. It does not touch Summary / District-wise Breakup (those have
hardcoded formula ranges per README) or re-run classify.py.

SETUP (one-time)
-----------------
1. In Google Cloud Console, create/reuse a project and enable the
   "Google Sheets API".
2. Create a Service Account, then a JSON key for it. Save the key file as
   `service_account.json` in this project's root (it's gitignored).
3. Open the Google Sheet, click Share, and add the service account's
   email address (looks like xxx@xxx.iam.gserviceaccount.com, found in the
   JSON key file) as a Viewer.
4. pip install -r requirements.txt

USAGE
-----
    python fetch_dashboard_data.py
    python fetch_dashboard_data.py --sheet-id 1zKcBA-sKDzJAW8Gq1ajuk51SsT5XscUNGND3At2Aro4
    python fetch_dashboard_data.py -o dashboard_data.json
"""
import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SHEET_ID = "1zKcBA-sKDzJAW8Gq1ajuk51SsT5XscUNGND3At2Aro4"
DEFAULT_CREDS_FILE = SCRIPT_DIR / "service_account.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

TAB_STUDYING = "Known - Studying"
TAB_NOT_STUDYING = "Known - Not Studying"
TAB_UNWILLING = "Unwilling - Does Not Want to Study"
TAB_UNCLEAR = "Unclear"
TAB_DEATH = "Death Cases"

# Columns shared by every tab; used as a match key to figure out which
# Known-Not-Studying rows are also in the Unwilling / Death Cases subsets
# (those tabs carry no student ID column, just the same row duplicated).
MATCH_COLS = [
    "District Name", "Block Name", "Student Name", "Father Name", "Gender",
    "Category", "Class", "Droupout Year", "Address", "Mobile No.",
    "current Status", "Remark",
]

WILLING_VALUE = "Willing (Economic/External reason or unspecified)"
UNWILLING_VALUE = "Unwilling - Does Not Want to Study"

# The Category column is free-text and riddled with typos/case variants,
# and some rows have education-level text ("7 - Upper Pr. and Secondary")
# instead of a social category, or a mix of caste + religion ("OBC, Minority
# ority"). Normalize to exactly one of the 5 canonical values below, checked
# in this priority order — official caste category (SC/ST/OBC/General) wins
# over a co-mentioned "Minority" religious tag, and anything that doesn't
# clearly say one of these five is left as "Unspecified" rather than guessed.
_CATEGORY_RULES = [
    ("SC", re.compile(r"\bsc\b|s\.c\.?|jatav", re.IGNORECASE)),
    ("ST", re.compile(r"\bst\b|3-st", re.IGNORECASE)),
    ("OBC", re.compile(r"\bobc\b|o\.b\.c|oibc|\bob\b|\bbc\b|4-obc", re.IGNORECASE)),
    ("General", re.compile(r"\bgen\b|general|genral|gernal|\bur\b|1-general", re.IGNORECASE)),
    ("Minority", re.compile(r"muslim|minorit|minrity|\bmin\b|\bminor\b", re.IGNORECASE)),
]


def normalize_category(raw: str) -> str:
    s = (raw or "").strip()
    for canonical, pattern in _CATEGORY_RULES:
        if pattern.search(s):
            return canonical
    return "Unspecified"


# Gender has the same case/typo problem ("MALE" vs "Male", "FEMALE" vs
# "female" vs stray-prefix typos "RFEMALE"/"NFEMALE") which without
# normalization shows up as duplicate bars for the same gender.
_GENDER_RULES = [
    ("Transgender", re.compile(r"transgender", re.IGNORECASE)),
    ("Female", re.compile(r"female", re.IGNORECASE)),
    ("Male", re.compile(r"\bmale\b", re.IGNORECASE)),
]


def normalize_gender(raw: str) -> str:
    s = (raw or "").strip()
    for canonical, pattern in _GENDER_RULES:
        if pattern.search(s):
            return canonical
    return "Unspecified"


# Reason-wise breakup, applied to current Status + Remark text. Same intent
# as export_for_looker.py's NOT_STUDYING_REASON_PATTERNS / UNCLEAR_REASON_
# PATTERNS, kept in a fixed display order (Not-Studying-side categories,
# then Unclear-side categories) matching the reference dashboard layout.
NOT_STUDYING_REASON_PATTERNS = [
    ("Financial Problem", r"poor\s*econ|economic|financial"),
    ("Migrated for Labour/Work", r"labour|labor|labure|मजदूरी|working|\bjob\b|naukri|migrat"),
    ("Marriage", r"marri|शादी|ससुराल"),
    ("Admission Not Taken / TC Issue", r"tc\s*issu|no\s*admi|not\s*admi|admisson"),
    ("Household / Domestic Responsibility", r"घरेलू|कृषि|किसानी|दुकान|home\s*work|household"),
    ("Health / Medical Reason", r"sick|health|ill\b|disab"),
]

UNCLEAR_REASON_PATTERNS = [
    ("Call Not Received", r"not\s*receiv|no\s*answer|not\s*answer|call\s*not|no\s*respond|not\s*respond"),
    ("Wrong Number / Switched Off",
     r"wrong\s*no|wrong\s*number|wrong\s*phone|invalid\s*number|incorrect\s*phone|"
     r"switch\s*off|switched\s*off|swich\s*off|swtich\s*off"),
    ("No Information Available", r"no\s*info|data\s*not|active\s*for\s*import|status\s*not\s*known|no\s*data"),
    ("Refused to Share Information", r"refused\s*to\s*share|not\s*share"),
]

# The Not-Studying-side and Unclear-side fallbacks ("no specific reason
# matched anything above") are merged into a single "Other" bar.
REASON_KEYS_ORDERED = (
    [name for name, _ in NOT_STUDYING_REASON_PATTERNS]
    + ["Death (Student/Family Member)"]
    + [name for name, _ in UNCLEAR_REASON_PATTERNS]
    + ["Yet to be Contacted", "Other"]
)
REASON_DISPLAY_LABEL = {}


def detect_reason(bucket: str, current_status: str, remark: str) -> str:
    text = unicodedata.normalize("NFC", f"{current_status} {remark}")
    if bucket == "Deceased":
        return "Death (Student/Family Member)"
    if bucket == "Not Studying":
        for name, pattern in NOT_STUDYING_REASON_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return name
        return "Other"
    if bucket == "Unclear":
        for name, pattern in UNCLEAR_REASON_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return name
        if not current_status.strip() and not remark.strip():
            return "Yet to be Contacted"
        return "Other"
    return None


def match_key(row):
    return tuple(str(row.get(c) or "").strip() for c in MATCH_COLS)


def get_client(creds_file: Path):
    creds = Credentials.from_service_account_file(str(creds_file), scopes=SCOPES)
    return gspread.authorize(creds)


def read_tab(sh, title):
    try:
        ws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        print(f"  (tab '{title}' not found, skipping)")
        return []
    return ws.get_all_records()


def load_rows(sheet_id: str, creds_file: Path) -> list[dict]:
    gc = get_client(creds_file)
    sh = gc.open_by_key(sheet_id)

    studying = read_tab(sh, TAB_STUDYING)
    not_studying = read_tab(sh, TAB_NOT_STUDYING)
    unwilling = read_tab(sh, TAB_UNWILLING)
    unclear = read_tab(sh, TAB_UNCLEAR)
    death = read_tab(sh, TAB_DEATH)

    print(f"  Known - Studying: {len(studying):,}")
    print(f"  Known - Not Studying: {len(not_studying):,}")
    print(f"  Unwilling (subset): {len(unwilling):,}")
    print(f"  Unclear: {len(unclear):,}")
    print(f"  Death Cases (subset): {len(death):,}")

    # Death Cases overlays onto rows from EITHER Known - Not Studying or
    # Unclear (a death can be reported alongside a garbage/no-info remark
    # too, not just a dropout reason) — so check both, not just Not Studying.
    unwilling_keys = Counter(match_key(r) for r in unwilling)
    death_keys = Counter(match_key(r) for r in death)

    rows = []
    for r in studying:
        r["_bucket"] = "Studying"
        r["_willingness"] = ""
        rows.append(r)

    for r in not_studying:
        key = match_key(r)
        if death_keys[key] > 0:
            r["_bucket"] = "Deceased"
            death_keys[key] -= 1
            r["_willingness"] = ""
        else:
            r["_bucket"] = "Not Studying"
            if unwilling_keys[key] > 0:
                r["_willingness"] = UNWILLING_VALUE
                unwilling_keys[key] -= 1
            else:
                r["_willingness"] = WILLING_VALUE
        rows.append(r)

    for r in unclear:
        key = match_key(r)
        if death_keys[key] > 0:
            r["_bucket"] = "Deceased"
            death_keys[key] -= 1
        else:
            r["_bucket"] = "Unclear"
        r["_willingness"] = ""
        rows.append(r)

    unmatched_deaths = sum(death_keys.values())
    if unmatched_deaths:
        print(f"  WARNING: {unmatched_deaths} Death Cases row(s) had no matching "
              f"row in Known - Not Studying or Unclear (data may have changed "
              f"between reads) — they are excluded from the dataset entirely.")

    return rows


def build_dashboard_data(rows: list[dict], include_records: bool = True) -> dict:
    total = len(rows)
    n_studying = sum(1 for r in rows if r["_bucket"] == "Studying")
    n_not_studying = sum(1 for r in rows if r["_bucket"] == "Not Studying")
    n_unclear = sum(1 for r in rows if r["_bucket"] == "Unclear")
    n_deceased = sum(1 for r in rows if r["_bucket"] == "Deceased")

    def pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    summary = {
        "total": total,
        "studying": n_studying,
        "not_studying": n_not_studying,
        "unclear": n_unclear,
        "deceased": n_deceased,
        "studying_pct": pct(n_studying, total),
        "not_studying_pct": pct(n_not_studying, total),
        "unclear_pct": pct(n_unclear, total),
        "deceased_pct": pct(n_deceased, total),
    }

    # --- Reason-wise breakup (Not Studying + Death + Unclear) ------------
    reason_counts = Counter()
    for r in rows:
        reason_key = detect_reason(r["_bucket"], str(r.get("current Status") or ""), str(r.get("Remark") or ""))
        if reason_key:
            reason_counts[reason_key] += 1
    reason_breakdown = [
        {"label": REASON_DISPLAY_LABEL.get(key, key), "count": reason_counts.get(key, 0)}
        for key in REASON_KEYS_ORDERED
    ]

    # --- District breakdown ---------------------------------------------
    districts: dict[str, dict] = {}
    for r in rows:
        d = str(r.get("District Name") or "Unknown").strip()
        entry = districts.setdefault(d, {
            "district_name": d, "total": 0, "studying": 0,
            "not_studying": 0, "unclear": 0, "deceased": 0,
        })
        entry["total"] += 1
        key = {"Studying": "studying", "Not Studying": "not_studying",
               "Unclear": "unclear", "Deceased": "deceased"}[r["_bucket"]]
        entry[key] += 1

    district_list = list(districts.values())
    for d in district_list:
        verified = d["studying"] + d["not_studying"]
        d["unclear_pct"] = pct(d["unclear"], d["total"])
        d["verification_rate_pct"] = pct(verified, d["total"])
    district_list.sort(key=lambda d: d["unclear_pct"], reverse=True)

    # --- Willingness (Not Studying only, deceased excluded already) ------
    willing = sum(1 for r in rows if r["_willingness"] == WILLING_VALUE)
    unwilling = sum(1 for r in rows if r["_willingness"] == UNWILLING_VALUE)
    willingness = {"willing": willing, "unwilling": unwilling}

    # --- Gender / Category x status --------------------------------------
    def crosstab(field_name, default="Unknown", value_fn=None, skip_values=()):
        out: dict[str, dict] = {}
        for r in rows:
            raw = str(r.get(field_name) or default).strip() or default
            key = value_fn(raw) if value_fn else raw
            if key in skip_values:
                continue
            bucket = out.setdefault(key, {"Studying": 0, "Not Studying": 0,
                                           "Unclear": 0, "Deceased": 0})
            bucket[r["_bucket"]] += 1
        return out

    gender_breakdown = crosstab("Gender", value_fn=normalize_gender, skip_values=("Unspecified",))
    # Only the 5 canonical social categories are shown — rows whose Category
    # text doesn't clearly map to one of them (typos aside, some rows have
    # education-level text like "7 - Upper Pr. and Secondary" instead of an
    # actual category, or are blank) are dropped rather than shown as a
    # misleading 6th "Unspecified" bucket.
    category_breakdown = crosstab("Category", value_fn=normalize_category, skip_values=("Unspecified",))

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "districts": district_list,
        "willingness": willingness,
        "gender_breakdown": gender_breakdown,
        "category_breakdown": category_breakdown,
        "reason_breakdown": reason_breakdown,
    }

    if include_records:
        # Row-level records for the searchable table. Address / Mobile No.
        # are deliberately left out even here to limit PII exposure; this
        # whole block is skipped entirely for --public output (see main()) —
        # student/father names have no business in a public repo.
        def s(r, col):
            return str(r.get(col) or "").strip()

        result["records"] = [{
            "district": s(r, "District Name"),
            "block": s(r, "Block Name"),
            "student_name": s(r, "Student Name"),
            "father_name": s(r, "Father Name"),
            "gender": s(r, "Gender"),
            "category": s(r, "Category"),
            "class": s(r, "Class"),
            "dropout_year": s(r, "Droupout Year"),
            "current_status": s(r, "current Status"),
            "remark": s(r, "Remark"),
            "status": r["_bucket"],
            "willingness": r["_willingness"],
        } for r in rows]

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID, help="Google Sheet ID (from the URL)")
    parser.add_argument("--creds", type=Path, default=DEFAULT_CREDS_FILE, help="Path to service account JSON key")
    parser.add_argument("-o", "--output", type=Path, default=SCRIPT_DIR / "dashboard_data.json")
    parser.add_argument("--public", action="store_true",
                         help="Omit row-level student/father names entirely — use this for "
                              "the file you intend to commit/publish (e.g. GitHub Pages). "
                              "The default (no flag) includes names, for local-only viewing; "
                              "that file must stay gitignored.")
    args = parser.parse_args()

    if not args.creds.exists():
        raise SystemExit(
            f"Service account key not found at {args.creds}.\n"
            "See the SETUP section at the top of this script."
        )

    print(f"Reading data tabs from sheet {args.sheet_id} ...")
    rows = load_rows(args.sheet_id, args.creds)
    print(f"  {len(rows):,} total rows loaded.")

    print("Building dashboard data ...")
    data = build_dashboard_data(rows, include_records=not args.public)

    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    mode = "public (no student/father names)" if args.public else "local (includes names)"
    print(f"Wrote {args.output} [{mode}] ({len(rows):,} rows, {len(data['districts'])} districts).")


if __name__ == "__main__":
    main()
