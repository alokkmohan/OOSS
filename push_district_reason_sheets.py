"""
Build two report tabs in the Google Sheet from the classified data:

1. "District-wise Breakup" (overwritten in the new layout: Sr No, District
   Name, Total Entries, Known - Studying, Known - Not Studying / Dropout,
   Unclear, Death Cases, % Studying, % Not Studying, % Unclear, Data
   Received? (Y/N)) — covers all 75 master-list districts, not just the
   ones that have reported, so the non-reporting ones are visible too.

2. "Reason-wise Analysis" (new tab: Reason Category, Applies To, No. of
   Students, % of All Not-Studying + Unclear Cases, plus a TOTAL row).

Reuses fetch_dashboard_data.py's tab-reading/willingness-matching/district
normalization — no classification is re-derived. The reason patterns here
are intentionally NOT merged the way the web dashboard's chart categories
are (e.g. "Wrong / Invalid Number" and "Switched Off / Not Reachable" stay
separate, and the two "Other" rows are disambiguated by the Applies To
column) — a table doesn't have the two-identical-bars-with-no-context
problem a chart does.

SETUP: same as push_dashboard_to_sheet.py — needs the service account to
have Editor access to the Sheet.

USAGE
-----
    python push_district_reason_sheets.py
"""
import argparse
import re
import unicodedata
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fetch_dashboard_data import (
    DEFAULT_CREDS_FILE,
    DEFAULT_SHEET_ID,
    MASTER_DISTRICTS,
    load_rows,
    normalize_district,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DISTRICT_BREAKUP_TAB = "District-wise Breakup"
REASON_ANALYSIS_TAB = "Reason-wise Analysis"

NOT_STUDYING_REASON_PATTERNS = [
    ("Refused to Continue Studies",
     r"not\s*intere?st|not\s*want\s*to\s*stud|unwilling|refused|नहीं\s*पढ़ना|"
     r"guardian\s*not\s*inter|parents?\s*not\s*inter|अभिभावक"),
    ("Financial Problem", r"poor\s*econ|economic|financial"),
    ("Migrated for Labour/Work", r"labour|labor|labure|मजदूरी|working|\bjob\b|naukri|migrat"),
    ("Marriage", r"marri|शादी|ससुराल"),
    ("Admission Not Taken / TC Issue", r"tc\s*issu|no\s*admi|not\s*admi|admisson"),
    ("Household / Domestic Responsibility", r"घरेलू|कृषि|किसानी|दुकान|home\s*work|household"),
    ("Health / Medical Reason", r"sick|health|ill\b|disab"),
]

UNCLEAR_REASON_PATTERNS = [
    ("Call Not Received", r"not\s*receiv|no\s*answer|not\s*answer|call\s*not|no\s*respond|not\s*respond"),
    ("Wrong / Invalid Number", r"wrong\s*no|wrong\s*number|wrong\s*phone|invalid\s*number|incorrect\s*phone"),
    ("Switched Off / Not Reachable", r"switch\s*off|switched\s*off|swich\s*off|swtich\s*off"),
    ("No Information Available", r"no\s*info|data\s*not|active\s*for\s*import|status\s*not\s*known|no\s*data"),
    ("Refused to Share Information", r"refused\s*to\s*share|not\s*share"),
]

REASON_ROWS_SPEC = (
    [(name, "Not Studying / Dropout") for name, _ in NOT_STUDYING_REASON_PATTERNS]
    + [("Death (Student/Family Member)", "Not Studying / Dropout"), ("Other", "Not Studying / Dropout")]
    + [(name, "Unclear / Not Reachable") for name, _ in UNCLEAR_REASON_PATTERNS]
    + [("Yet to be Contacted", "Unclear / Not Reachable"), ("Other", "Unclear / Not Reachable")]
)


def detect_reason_detailed(bucket: str, current_status: str, remark: str) -> str:
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


def build_district_breakup_rows(rows: list[dict]) -> list[list]:
    stats = {d: {"total": 0, "studying": 0, "not_studying": 0, "unclear": 0, "deceased": 0}
              for d in MASTER_DISTRICTS}
    for r in rows:
        d = normalize_district(r.get("District Name"))
        if d not in stats:
            stats[d] = {"total": 0, "studying": 0, "not_studying": 0, "unclear": 0, "deceased": 0}
        s = stats[d]
        s["total"] += 1
        key = {"Studying": "studying", "Not Studying": "not_studying",
               "Unclear": "unclear", "Deceased": "deceased"}[r["_bucket"]]
        s[key] += 1

    headers = ["Sr No", "District Name", "Total Entries", "Known - Studying",
               "Known - Not Studying / Dropout", "Unclear", "Death Cases",
               "% Studying", "% Not Studying", "% Unclear", "Data Received? (Y/N)"]
    out = [headers]
    for i, d in enumerate(sorted(stats.keys()), start=1):
        s = stats[d]
        total = s["total"]
        pct = lambda n: round(n / total * 100, 1) if total else 0.0
        out.append([
            i, d, total, s["studying"], s["not_studying"], s["unclear"], s["deceased"],
            pct(s["studying"]), pct(s["not_studying"]), pct(s["unclear"]),
            "Y" if total > 0 else "N",
        ])
    return out


def build_reason_analysis_rows(rows: list[dict]) -> list[list]:
    counts = {(name, applies): 0 for name, applies in REASON_ROWS_SPEC}
    denom = sum(1 for r in rows if r["_bucket"] in ("Not Studying", "Unclear", "Deceased"))
    studying_count = sum(1 for r in rows if r["_bucket"] == "Studying")
    grand_total = denom + studying_count
    for r in rows:
        reason = detect_reason_detailed(r["_bucket"], str(r.get("current Status") or ""), str(r.get("Remark") or ""))
        if reason is None:
            continue
        applies = "Not Studying / Dropout" if r["_bucket"] in ("Not Studying", "Deceased") else "Unclear / Not Reachable"
        counts[(reason, applies)] = counts.get((reason, applies), 0) + 1

    headers = ["Reason Category", "Applies To", "No. of Students", "% of All Not-Studying + Unclear Cases"]
    out = [headers]
    total_count = 0
    for name, applies in REASON_ROWS_SPEC:
        n = counts[(name, applies)]
        total_count += n
        pct = round(n / denom * 100, 1) if denom else 0.0
        out.append([name, applies, n, f"{pct}%"])
    out.append(["TOTAL (Not Studying + Unclear)", "", total_count, f"{round(total_count / denom * 100, 1) if denom else 0.0}%"])
    # Reconciles the table to the full record count — Known - Studying rows
    # don't have a "reason" (nothing to explain), so they're outside the
    # Not-Studying+Unclear denominator above; this row accounts for them so
    # the sheet totals to all 40k+ records, not just the ones with a reason.
    out.append(["Known - Studying (no reason applicable)", "Studying", studying_count,
                f"{round(studying_count / grand_total * 100, 1) if grand_total else 0.0}% of all records"])
    out.append(["TOTAL (All Records)", "", grand_total, "100.0%"])
    return out


def get_or_replace_ws(sh, title, rows, cols, index=None):
    try:
        ws = sh.worksheet(title)
        ws.clear()
        return ws
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols, index=index)


def style_district_breakup(ws, n_rows):
    ws.format("A1:K1", {
        "backgroundColor": {"red": 0.11, "green": 0.22, "blue": 0.40},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    })
    ws.freeze(rows=1)


def style_reason_analysis(ws, not_studying_count, unclear_count):
    dark_navy = {"backgroundColor": {"red": 0.11, "green": 0.22, "blue": 0.40},
                 "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}
    ws.format("A1:D1", dark_navy)

    not_studying_start = 2
    not_studying_end = not_studying_start + not_studying_count - 1
    ws.format(f"A{not_studying_start}:D{not_studying_end}", {"backgroundColor": {"red": 0.99, "green": 0.90, "blue": 0.78}})

    unclear_start = not_studying_end + 1
    unclear_end = unclear_start + unclear_count - 1
    ws.format(f"A{unclear_start}:D{unclear_end}", {"backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.98}})

    subtotal_row = unclear_end + 1
    ws.format(f"A{subtotal_row}:D{subtotal_row}", dark_navy)

    studying_row = subtotal_row + 1
    ws.format(f"A{studying_row}:D{studying_row}", {"backgroundColor": {"red": 0.85, "green": 0.96, "blue": 0.85}})

    grand_total_row = studying_row + 1
    ws.format(f"A{grand_total_row}:D{grand_total_row}", dark_navy)

    ws.freeze(rows=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--creds", type=Path, default=DEFAULT_CREDS_FILE)
    args = parser.parse_args()

    if not args.creds.exists():
        raise SystemExit(f"Service account key not found at {args.creds}.")

    creds = Credentials.from_service_account_file(str(args.creds), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(args.sheet_id)

    print("Reading data tabs ...")
    rows = load_rows(args.sheet_id, args.creds)
    print(f"  {len(rows):,} total rows loaded.")

    print("Building District-wise Breakup ...")
    district_table = build_district_breakup_rows(rows)
    ws1 = get_or_replace_ws(sh, DISTRICT_BREAKUP_TAB, rows=len(district_table) + 5, cols=11)
    ws1.update(district_table, "A1")
    style_district_breakup(ws1, len(district_table))
    print(f"  {len(district_table) - 1} districts (all 75 master-list districts included).")

    print("Building Reason-wise Analysis ...")
    reason_table = build_reason_analysis_rows(rows)
    not_studying_count = len(NOT_STUDYING_REASON_PATTERNS) + 2  # + Death + Other
    unclear_count = len(UNCLEAR_REASON_PATTERNS) + 2  # + Yet to be Contacted + Other
    ws2 = get_or_replace_ws(sh, REASON_ANALYSIS_TAB, rows=len(reason_table) + 5, cols=4, index=1)
    ws2.update(reason_table, "A1")
    style_reason_analysis(ws2, not_studying_count, unclear_count)
    print(f"  {not_studying_count + unclear_count} reason categories + Studying reconciliation + TOTAL rows.")

    print("Done.")


if __name__ == "__main__":
    main()
