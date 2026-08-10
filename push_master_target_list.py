"""
Upload the full master target list (every district's dropout list, as sent
out for verification — not the classified responses) into a "Master Target
List" tab in the Google Sheet. Source: "Out of School Student Status - Raw
data.csv" (90,053 rows, all 75 districts, includes Student PEN and School
Name — data the classified response tabs don't carry).

This tab is the lookup source for the field data-collection Web App's
District -> School -> Student cascading dropdowns (see apps_script/), since
it covers every target student, not just the ~46 districts that have
responded so far.

Written in chunks (Sheets API has practical request-size limits around
~2M cells / request) rather than one giant update() call.

USAGE
-----
    python push_master_target_list.py
    python push_master_target_list.py --csv "Out of School Student Status - Raw data.csv"
"""
import argparse
import csv
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fetch_dashboard_data import DEFAULT_CREDS_FILE, DEFAULT_SHEET_ID

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TARGET_LIST_TAB = "Master Target List"
DEFAULT_CSV = Path(__file__).resolve().parent / "Out of School Student Status - Raw data.csv"
CHUNK_ROWS = 10000


def read_csv_rows(csv_path: Path) -> list[list]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return list(reader)


def get_or_replace_ws(sh, title, rows, cols):
    try:
        ws = sh.worksheet(title)
        ws.clear()
        if ws.row_count < rows or ws.col_count < cols:
            ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols))
        return ws
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--creds", type=Path, default=DEFAULT_CREDS_FILE)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    if not args.creds.exists():
        raise SystemExit(f"Service account key not found at {args.creds}.")
    if not args.csv.exists():
        raise SystemExit(f"CSV not found at {args.csv}.")

    print(f"Reading {args.csv} ...")
    table = read_csv_rows(args.csv)
    print(f"  {len(table) - 1:,} rows (+ header).")

    creds = Credentials.from_service_account_file(str(args.creds), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(args.sheet_id)

    print("Writing Master Target List tab ...")
    ws = get_or_replace_ws(sh, TARGET_LIST_TAB, rows=len(table) + 5, cols=len(table[0]))

    for start in range(0, len(table), CHUNK_ROWS):
        chunk = table[start:start + CHUNK_ROWS]
        ws.update(chunk, f"A{start + 1}")
        print(f"  wrote rows {start + 1}-{start + len(chunk)}")

    last_col_a1 = gspread.utils.rowcol_to_a1(1, len(table[0]))
    ws.format(f"A1:{last_col_a1}", {
        "backgroundColor": {"red": 0.11, "green": 0.22, "blue": 0.40},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    })
    ws.freeze(rows=1)

    print(f"Done. {len(table) - 1:,} rows written to '{TARGET_LIST_TAB}'.")


if __name__ == "__main__":
    main()
