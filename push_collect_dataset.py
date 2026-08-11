"""
Generate collect/students.json — a static snapshot of the full field-
collection target list (all 75 districts, ~90k students) plus current
Field Data Collection status, for the /collect/ page to load directly
from GitHub Pages instead of paginating through the Apps Script API
(which is far slower for a bulk read of this size).

NOTE: unlike every other JSON this project publishes, this one is NOT
scrubbed of PII (student/parent names, mobile numbers) — that's a
deliberate, informed call the project owner made for this specific file,
not the default policy. Re-confirm before reusing this pattern elsewhere.

Submissions still go live through the Apps Script API (POST), which
writes straight into the Sheet — this script only refreshes the READ-side
snapshot. Re-run it periodically (or whenever the target list changes) and
commit+push to update the published file.

USAGE
-----
    python push_collect_dataset.py
"""
import argparse
import json
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fetch_dashboard_data import DEFAULT_CREDS_FILE

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
TARGET_SHEET_ID = "1WWifakyqkBoA922wu16bCYBZTjK2NyrxkVC_6eLBIV0"
TARGET_LIST_TAB = "Out of School Student Status - Raw data"
COLLECTION_TAB = "Field Data Collection"
OUTPUT_PATH = Path(__file__).resolve().parent / "collect" / "students.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet-id", default=TARGET_SHEET_ID)
    parser.add_argument("--creds", type=Path, default=DEFAULT_CREDS_FILE)
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    if not args.creds.exists():
        raise SystemExit(f"Service account key not found at {args.creds}.")

    creds = Credentials.from_service_account_file(str(args.creds), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(args.sheet_id)

    print(f"Reading '{TARGET_LIST_TAB}' ...")
    target_rows = sh.worksheet(TARGET_LIST_TAB).get_all_records()
    print(f"  {len(target_rows):,} rows.")

    status_by_pen = {}
    try:
        print(f"Reading '{COLLECTION_TAB}' ...")
        collection_rows = sh.worksheet(COLLECTION_TAB).get_all_records()
        for r in collection_rows:
            pen = str(r.get("Student PEN") or "").strip()
            if pen:
                status_by_pen[pen] = r
        print(f"  {len(status_by_pen):,} recorded statuses.")
    except gspread.exceptions.WorksheetNotFound:
        print("  (tab doesn't exist yet — no submissions recorded so far)")

    print("Building students.json ...")
    students = []
    for r in target_rows:
        pen = str(r.get("Student PEN") or "").strip()
        existing = status_by_pen.get(pen, {})
        students.append({
            "district": str(r.get("District Name") or "").strip(),
            "block": str(r.get("Block Name") or "").strip(),
            "udise": str(r.get("Last UDISE Code") or "").strip(),
            "school": str(r.get("Last School Name") or "").strip(),
            "pen": pen,
            "name": str(r.get("Student Name") or "").strip(),
            "sex": str(r.get("Sex") or "").strip(),
            "mobile": str(r.get("Mobile No") or "").strip(),
            "mother": str(r.get("Mother Name") or "").strip(),
            "father": str(r.get("Father Name") or "").strip(),
            "subStatus": str(r.get("Student Sub Status") or "").strip(),
            "studentClass": str(r.get("Last Class") or "").strip(),
            "eligibleClass": str(r.get("Eligible Class to Import") or "").strip(),
            "academicYear": str(r.get("Academic Year") or "").strip(),
            "currentStatus": str(existing.get("Current Status") or "").strip(),
            "willing": str(existing.get("Willing to Resume Studies") or "").strip(),
            "mode": str(existing.get("Mode (Regular/NIOS)") or "").strip(),
            "reason": str(existing.get("Reason") or "").strip(),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(students, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output} ({len(students):,} students, "
          f"{args.output.stat().st_size / 1024 / 1024:.1f} MB).")


if __name__ == "__main__":
    main()
