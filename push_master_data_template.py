"""
Build a "Master Data (Tracking Template)" tab in the Google Sheet, using the
exact 33-column layout from Out_of_School_Student_Tracking_Template_-_1.xlsx
(the structured intake form meant for the *next* round of district data
collection — see README's "Known limitations" and "Related files").

Populates every column we actually have data for, mapped to the template's
own dropdown vocabulary (e.g. Gender -> MALE/FEMALE/OTHER, Category ->
SC/ST/OBC/GENERAL/MINORITY, Reason for Dropout -> the template's fixed
reason list). Columns this survey never collected — Student ID, UDISE Code,
CWSN, Alternate Mobile, the whole Verification Trail (call attempts,
verified by, dates), Follow-up Required, and Interested in Studying via
NIOS — are left BLANK, same policy as push_master_raw_to_sheet.py: don't
fabricate data that was never collected, leave it for districts to fill in
when they do this round of verification.

SETUP: same as push_dashboard_to_sheet.py — needs the service account to
have Editor access to the Sheet.

USAGE
-----
    python push_master_data_template.py
"""
import argparse
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fetch_dashboard_data import (
    DEFAULT_CREDS_FILE,
    DEFAULT_SHEET_ID,
    detect_reason,
    load_rows,
    normalize_category,
    normalize_class,
    normalize_gender,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TEMPLATE_TAB = "Master Data (Tracking Template)"

HEADERS = [
    "Sr. No", "Student ID", "District Name", "Block Name",
    "Village / Gram Panchayat", "Student Name", "Father / Guardian Name",
    "Gender", "Category", "CWSN (Divyang) Y/N", "School Last Attended",
    "UDISE Code", "Class Last Attended", "Academic Year of Dropout",
    "Address", "Mobile No.", "Alternate Mobile No.", "Current Status",
    "Reason for Dropout / Discontinuation",
    "If Studying: Current School / Institution", "If Studying: Mode",
    "If Studying: Current Class", "If Not Studying: Current Activity",
    "If Migrated: Current Location", "No. of Call Attempts",
    "Last Attempt Date", "Last Attempt Result",
    "Verified By (Name / Designation)", "Verification Date",
    "Follow-up Required (Y/N)", "Next Action / Remarks",
    "Status_Category (auto)", "Interested in Studying via NIOS (Yes/No)",
]

GENDER_TO_TEMPLATE = {"Male": "MALE", "Female": "FEMALE", "Transgender": "OTHER"}
CATEGORY_TO_TEMPLATE = {"SC": "SC", "ST": "ST", "OBC": "OBC", "General": "GENERAL", "Minority": "MINORITY"}

BUCKET_TO_CURRENT_STATUS = {
    "Studying": "Studying",
    "Not Studying": "Not Studying",
    "Unclear": "Unclear",
    "Deceased": "Deceased",
}
BUCKET_TO_STATUS_CATEGORY = {
    "Studying": "Known - Studying",
    "Not Studying": "Known - Not Studying / Dropout",
    "Unclear": "Unclear (no valid status)",
    "Deceased": "Deceased",
}

# Our reason-detection categories (see detect_reason in fetch_dashboard_data.py)
# mapped onto the template's fixed "Reason for Dropout" dropdown list. Only
# applied to Not Studying / Deceased rows — the field doesn't apply to
# Studying or Unclear rows in the template's own design.
REASON_TO_TEMPLATE = {
    "Financial Problem": "Financial constraints",
    "Migrated for Labour/Work": "Migration",
    "Marriage": "Marriage",
    "Admission Not Taken / TC Issue": "Other",
    "Household / Domestic Responsibility": "Domestic / Household work",
    "Health / Medical Reason": "Illness / Disability",
    "Death (Student/Family Member)": "Death in family",
    "Other": "Other",
}

# Same reason categories, mapped onto "If Not Studying: Current Activity"
# (a different dropdown, only meaningful for the Not Studying bucket).
REASON_TO_ACTIVITY = {
    "Migrated for Labour/Work": "Migrated for work",
    "Household / Domestic Responsibility": "Household work",
    "Marriage": "Married",
}


def build_template_rows(rows: list[dict]) -> list[list]:
    out = [HEADERS]
    for i, r in enumerate(rows, start=1):
        bucket = r["_bucket"]
        current_status_raw = str(r.get("current Status") or "").strip()
        remark = str(r.get("Remark") or "").strip()

        gender_norm = normalize_gender(str(r.get("Gender") or ""))
        category_norm = normalize_category(str(r.get("Category") or ""))
        class_norm = normalize_class(r.get("Class"))

        reason_key = None
        if bucket in ("Not Studying", "Deceased"):
            reason_key = detect_reason(bucket, current_status_raw, remark)

        out.append([
            i,
            "",  # Student ID — not in source data
            str(r.get("District Name") or "").strip(),
            str(r.get("Block Name") or "").strip(),
            "",  # Village / Gram Panchayat — not captured separately from Address
            str(r.get("Student Name") or "").strip(),
            str(r.get("Father Name") or "").strip(),
            GENDER_TO_TEMPLATE.get(gender_norm, ""),
            CATEGORY_TO_TEMPLATE.get(category_norm, ""),
            "",  # CWSN — not in source data
            "",  # School Last Attended — not in source data
            "",  # UDISE Code — not in source data
            class_norm if class_norm is not None else "",
            str(r.get("Droupout Year") or "").strip(),
            str(r.get("Address") or "").strip(),
            str(r.get("Mobile No.") or "").strip(),
            "",  # Alternate Mobile No. — not in source data
            BUCKET_TO_CURRENT_STATUS[bucket],
            REASON_TO_TEMPLATE.get(reason_key, "") if reason_key else "",
            "",  # If Studying: Current School/Institution — not in source data
            "",  # If Studying: Mode — not in source data
            "",  # If Studying: Current Class — not distinguished from Class Last Attended
            REASON_TO_ACTIVITY.get(reason_key, "") if bucket == "Not Studying" else "",
            "",  # If Migrated: Current Location — no Migrated bucket in source data
            "",  # No. of Call Attempts — not in source data
            "",  # Last Attempt Date — not in source data
            "",  # Last Attempt Result — not in source data
            "",  # Verified By — not in source data
            "",  # Verification Date — not in source data
            "",  # Follow-up Required (Y/N) — not in source data
            remark,  # carried forward as the verbatim field note
            BUCKET_TO_STATUS_CATEGORY[bucket],
            "",  # Interested in Studying via NIOS — not in source data (README limitation)
        ])
    return out


def get_or_replace_ws(sh, title, rows, cols, index=None):
    try:
        ws = sh.worksheet(title)
        ws.clear()
        if ws.row_count < rows or ws.col_count < cols:
            ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols))
        return ws
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols, index=index)


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

    print("Building Master Data (Tracking Template) rows ...")
    table = build_template_rows(rows)

    print("Writing tab ...")
    ws = get_or_replace_ws(sh, TEMPLATE_TAB, rows=len(table) + 5, cols=len(HEADERS))
    ws.update(table, "A1")
    last_col_a1 = gspread.utils.rowcol_to_a1(1, len(HEADERS))
    ws.format(f"A1:{last_col_a1}", {
        "backgroundColor": {"red": 0.11, "green": 0.22, "blue": 0.40},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "wrapStrategy": "WRAP",
    })
    ws.freeze(rows=1)

    print(f"Done. {len(table) - 1:,} student rows written to '{TEMPLATE_TAB}'.")


if __name__ == "__main__":
    main()
