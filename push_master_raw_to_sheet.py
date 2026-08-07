"""
Build a "Master Raw" tab in the Google Sheet, consolidating every classified
row (Known - Studying / Known - Not Studying / Unclear / Death Cases) into
one flat table in the district-officer-facing layout:

    Sr No, District Name, Block Name, Student Name, Father Name, Gender,
    Social Category, Class, Dropout Year, Address, Mobile No.,
    Current Status (Study/Not), Status Category, Reason Category,
    Remark (Verbatim), Willing to Resume Studies, Referred to Open Schooling,
    Duplicate PEN/Record, Data Collected By, Collection Date,
    Interested in Studying via NIOS (Yes/No)

Reuses fetch_dashboard_data.py's tab-reading, willingness-matching, gender/
category normalization, and reason-detection logic — no classification is
re-derived here.

The last 4 columns (Referred to Open Schooling, Duplicate PEN/Record,
Data Collected By, Collection Date, Interested in Studying via NIOS) are
left BLANK for every row. Per README's "Known limitations": this data was
never collected in the current survey — filling it in would be fabricating
data, not reporting it. These columns exist so districts can fill them in
by hand in a future collection round.

SETUP: same as push_dashboard_to_sheet.py — needs the service account to
have Editor access to the Sheet.

USAGE
-----
    python push_master_raw_to_sheet.py
    python push_master_raw_to_sheet.py --sheet-id <id> --creds service_account.json
"""
import argparse
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fetch_dashboard_data import (
    DEFAULT_CREDS_FILE,
    DEFAULT_SHEET_ID,
    UNWILLING_VALUE,
    WILLING_VALUE,
    detect_reason,
    load_rows,
    normalize_category,
    normalize_gender,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MASTER_RAW_TAB = "Master Raw"

HEADERS = [
    "Sr No", "District Name", "Block Name", "Student Name", "Father Name",
    "Gender", "Social Category", "Class", "Dropout Year", "Address",
    "Mobile No.", "Current Status (Study/Not)", "Status Category",
    "Reason Category", "Remark (Verbatim)", "Willing to Resume Studies",
    "Referred to Open Schooling", "Duplicate PEN/Record", "Data Collected By",
    "Collection Date", "Interested in Studying via NIOS (Yes/No)",
]

BUCKET_TO_STATUS_CATEGORY = {
    "Studying": "Known - Studying",
    "Not Studying": "Known - Not Studying / Dropout",
    "Unclear": "Unclear",
    "Deceased": "Deceased",
}


def willing_to_resume(bucket: str, willingness: str) -> str:
    if bucket == "Not Studying":
        return "Yes" if willingness == WILLING_VALUE else "No" if willingness == UNWILLING_VALUE else ""
    if bucket == "Unclear":
        return "Not Asked"
    if bucket in ("Studying", "Deceased"):
        return "Not Applicable"
    return ""


def build_master_raw_rows(rows: list[dict]) -> list[list]:
    out = [HEADERS]
    for i, r in enumerate(rows, start=1):
        bucket = r["_bucket"]
        current_status = str(r.get("current Status") or "").strip()
        remark = str(r.get("Remark") or "").strip()
        gender_raw = str(r.get("Gender") or "").strip()
        category_raw = str(r.get("Category") or "").strip()
        gender_norm = normalize_gender(gender_raw)
        category_norm = normalize_category(category_raw)
        out.append([
            i,
            str(r.get("District Name") or "").strip(),
            str(r.get("Block Name") or "").strip(),
            str(r.get("Student Name") or "").strip(),
            str(r.get("Father Name") or "").strip(),
            gender_raw if gender_norm == "Unspecified" else gender_norm,
            category_raw if category_norm == "Unspecified" else category_norm,
            str(r.get("Class") or "").strip(),
            str(r.get("Droupout Year") or "").strip(),
            str(r.get("Address") or "").strip(),
            str(r.get("Mobile No.") or "").strip(),
            current_status,
            BUCKET_TO_STATUS_CATEGORY[bucket],
            detect_reason(bucket, current_status, remark) or "",
            remark,
            willing_to_resume(bucket, r["_willingness"]),
            "",  # Referred to Open Schooling — not in source data
            "",  # Duplicate PEN/Record — not in source data
            "",  # Data Collected By — not in source data
            "",  # Collection Date — not in source data
            "",  # Interested in Studying via NIOS (Yes/No) — not in source data
        ])
    return out


def get_or_create_master_raw_ws(sh):
    try:
        ws = sh.worksheet(MASTER_RAW_TAB)
        ws.clear()
        return ws
    except gspread.exceptions.WorksheetNotFound:
        pass
    # Place right after the Dashboard tab if present, else at index 1.
    index = 1
    return sh.add_worksheet(title=MASTER_RAW_TAB, rows=1000, cols=len(HEADERS), index=index)


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

    print("Building Master Raw rows ...")
    table = build_master_raw_rows(rows)

    print("Writing Master Raw tab ...")
    ws = get_or_create_master_raw_ws(sh)
    ws.update(table, "A1")
    ws.format("A1:U1", {
        "backgroundColor": {"red": 0.11, "green": 0.22, "blue": 0.40},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    })
    ws.freeze(rows=1)

    print(f"Done. Master Raw tab has {len(table) - 1:,} student rows.")


if __name__ == "__main__":
    main()
