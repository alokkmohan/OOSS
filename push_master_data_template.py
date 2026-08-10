"""
Build a "Master Data (Tracking Template)" tab in the Google Sheet, using the
exact 33-column layout from Out_of_School_Student_Tracking_Template_-_1.xlsx
(the structured intake form meant for the *next* round of district data
collection — see README's "Known limitations" and "Related files").

Reads from the "Master Raw" tab (via push_master_raw_to_sheet.py) rather
than recomputing from the source tabs independently — this is the single
source of truth for per-row classification, so the two tabs stay
consistent by construction, and any manual corrections made directly in
Master Raw (e.g. fixing a misclassified row) carry through here too.
Run push_master_raw_to_sheet.py first if Master Raw itself needs refreshing
from the source tabs.

Columns this survey never collected — Student ID, UDISE Code, CWSN,
Alternate Mobile, the call-attempt/verification trail, Follow-up Required,
and Interested in Studying via NIOS — are left BLANK: don't fabricate data
that was never collected, leave it for districts to fill in when they do
this round of verification. Data Collected By / Collection Date (if ever
filled in on Master Raw) are carried into Verified By / Verification Date,
the closest equivalent fields in the template.

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

from fetch_dashboard_data import DEFAULT_CREDS_FILE, DEFAULT_SHEET_ID
from push_master_raw_to_sheet import MASTER_RAW_TAB

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

STATUS_CATEGORY_TO_CURRENT_STATUS = {
    "Known - Studying": "Studying",
    "Known - Not Studying / Dropout": "Not Studying",
    "Unclear": "Unclear",
    "Deceased": "Deceased",
}

# Our reason-detection categories (see detect_reason in fetch_dashboard_data.py,
# same values Master Raw's "Reason Category" column holds) mapped onto the
# template's fixed "Reason for Dropout" dropdown list. Only meaningful for
# Not Studying / Deceased rows in the template's own design.
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


def read_master_raw(sh):
    ws = sh.worksheet(MASTER_RAW_TAB)
    return ws.get_all_records()


def build_template_rows(master_raw_rows: list[dict]) -> list[list]:
    out = [HEADERS]
    for row in master_raw_rows:
        status_category = str(row.get("Status Category") or "").strip()
        current_status = STATUS_CATEGORY_TO_CURRENT_STATUS.get(status_category, "")
        reason_key = str(row.get("Reason Category") or "").strip() or None
        gender = str(row.get("Gender") or "").strip()
        category = str(row.get("Social Category") or "").strip()

        out.append([
            row.get("Sr No", ""),
            "",  # Student ID — not in source data
            row.get("District Name", ""),
            row.get("Block Name", ""),
            "",  # Village / Gram Panchayat — not captured separately from Address
            row.get("Student Name", ""),
            row.get("Father Name", ""),
            GENDER_TO_TEMPLATE.get(gender, ""),
            CATEGORY_TO_TEMPLATE.get(category, ""),
            "",  # CWSN — not in source data
            "",  # School Last Attended — not in source data
            "",  # UDISE Code — not in source data
            row.get("Class", ""),
            row.get("Dropout Year", ""),
            row.get("Address", ""),
            row.get("Mobile No.", ""),
            "",  # Alternate Mobile No. — not in source data
            current_status,
            REASON_TO_TEMPLATE.get(reason_key, "") if reason_key else "",
            "",  # If Studying: Current School/Institution — not in source data
            "",  # If Studying: Mode — not in source data
            "",  # If Studying: Current Class — not distinguished from Class Last Attended
            REASON_TO_ACTIVITY.get(reason_key, "") if current_status == "Not Studying" else "",
            "",  # If Migrated: Current Location — no Migrated bucket in source data
            "",  # No. of Call Attempts — not in source data
            "",  # Last Attempt Date — not in source data
            "",  # Last Attempt Result — not in source data
            row.get("Data Collected By", ""),  # closest equivalent field
            row.get("Collection Date", ""),  # closest equivalent field
            "",  # Follow-up Required (Y/N) — not in source data
            row.get("Remark (Verbatim)", ""),  # carried forward as the verbatim field note
            status_category,
            row.get("Interested in Studying via NIOS (Yes/No)", ""),
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

    print(f"Reading '{MASTER_RAW_TAB}' tab ...")
    master_raw_rows = read_master_raw(sh)
    print(f"  {len(master_raw_rows):,} rows loaded.")

    print("Building Master Data (Tracking Template) rows ...")
    table = build_template_rows(master_raw_rows)

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
