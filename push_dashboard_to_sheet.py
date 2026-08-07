"""
Push a computed dashboard into the Google Sheet itself, as a "Dashboard" tab
(placed first) with summary numbers, breakdown tables, and native Sheets
charts — built from the same aggregation logic as fetch_dashboard_data.py,
so the two stay consistent. Does not re-derive classification; reads
Status_Category / Willingness_Category as already recorded across the
Known - Studying / Known - Not Studying / Unwilling / Unclear / Death Cases
tabs (see fetch_dashboard_data.py's module docstring for how those combine).

Values are written as plain numbers (not live formulas) — the multi-column
row-matching needed to fold Willingness/Death Cases back onto the main
Not-Studying rows (see match_key() in fetch_dashboard_data.py) isn't
practical to express as a Sheets formula, so this script recomputes and
overwrites the Dashboard tab each time you run it. Charts are deleted and
re-added on every run so they never go stale or duplicate.

SETUP (in addition to fetch_dashboard_data.py's setup)
--------------------------------------------------------
The service account needs WRITE access for this script — Viewer is not
enough. In the Sheet's Share dialog, change its role from Viewer to Editor.

USAGE
-----
    python push_dashboard_to_sheet.py
    python push_dashboard_to_sheet.py --sheet-id <id> --creds service_account.json
"""
import argparse
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from fetch_dashboard_data import (
    DEFAULT_CREDS_FILE,
    DEFAULT_SHEET_ID,
    build_dashboard_data,
    load_rows,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DASHBOARD_TAB = "Dashboard"
DISTRICT_TARGET = 75  # master list target, per README

KPI_CARDS = [
    # (label, header_bg, value_fg)
    ("Total Records Traced", {"red": 0.11, "green": 0.22, "blue": 0.40}, {"red": 0.11, "green": 0.22, "blue": 0.40}),
    ("Currently Studying", {"red": 0.13, "green": 0.42, "blue": 0.20}, {"red": 0.13, "green": 0.42, "blue": 0.20}),
    ("Confirmed Not Studying", {"red": 0.55, "green": 0.11, "blue": 0.11}, {"red": 0.55, "green": 0.11, "blue": 0.11}),
    ("Unclear / Not Reached", {"red": 0.72, "green": 0.48, "blue": 0.02}, {"red": 0.72, "green": 0.48, "blue": 0.02}),
    ("Districts Reporting", {"red": 0.10, "green": 0.28, "blue": 0.47}, {"red": 0.10, "green": 0.28, "blue": 0.47}),
]


def get_or_create_dashboard_ws(sh):
    try:
        ws = sh.worksheet(DASHBOARD_TAB)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=DASHBOARD_TAB, rows=200, cols=20, index=0)
    if sh.worksheets()[0].id != ws.id:
        ordered = [ws] + [w for w in sh.worksheets() if w.id != ws.id]
        sh.reorder_worksheets(ordered)
    return ws


def delete_existing_charts(sh, ws):
    meta = sh.fetch_sheet_metadata()
    requests = []
    for sheet in meta["sheets"]:
        if sheet["properties"]["sheetId"] != ws.id:
            continue
        for chart in sheet.get("charts", []):
            requests.append({"deleteEmbeddedObject": {"objectId": chart["chartId"]}})
    if requests:
        sh.batch_update({"requests": requests})


DATA_COL_OFFSET = 13  # hidden helper data starts at column N (0-indexed 13)
DATA_COL_LETTER = "N"


def write_tables(ws, data):
    # --- Visible part: title + KPI banner only (columns A-E), matching the
    # web dashboard's look. Everything charts need is written to a hidden
    # column block instead of as visible tables (see build_chart_requests /
    # hide_data_columns) — this tab should read as charts-only, like
    # https://ooss.dataimpact.in/, not a data dump.
    visible_rows = []

    def vrow(*vals):
        visible_rows.append(list(vals))

    vrow("Out-of-School Student Status Dashboard")
    vrow(f"Last updated: {data['generated_at']}")
    vrow()

    s = data["summary"]

    kpi_header_row = len(visible_rows) + 1
    vrow(*(label for label, _, _ in KPI_CARDS))
    kpi_value_row = len(visible_rows) + 1
    vrow(s["total"], s["studying"], s["not_studying"], s["unclear"],
         f"{len(data['districts'])}/{DISTRICT_TARGET}")

    ws.update(visible_rows, "A1")
    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A2", {"textFormat": {"italic": True}})

    # --- Hidden part: the small per-chart source tables ------------------
    data_rows = []

    def row(*vals):
        data_rows.append(list(vals))

    summary_header_row = len(data_rows) + 2  # 1-indexed row of the header line below
    row("SUMMARY")
    row("Total", "Studying", "Not Studying", "Unclear", "Deceased")
    row(s["total"], s["studying"], s["not_studying"], s["unclear"], s["deceased"])
    row("100%", f"{s['studying_pct']}%", f"{s['not_studying_pct']}%",
        f"{s['unclear_pct']}%", f"{s['deceased_pct']}%")
    row()

    w = data["willingness"]
    willing_header_row = len(data_rows) + 2
    row("WILLING / UNWILLING / UNCLEAR")
    row("Willing (Economic/External/Unspecified)", "Unwilling", "Unclear")
    row(w["willing"], w["unwilling"], s["unclear"])
    row()

    reason_header_row = len(data_rows) + 2
    row("REASON-WISE BREAKUP — NOT STUDYING & UNCLEAR CASES")
    row("Reason", "No. of Students")
    reason_items = data["reason_breakdown"]
    for item in reason_items:
        row(item["label"], item["count"])
    row()

    gender_header_row = len(data_rows) + 2
    row("GENDER x STATUS")
    row("Gender", "Studying", "Not Studying", "Unclear", "Deceased")
    gender_items = sorted(data["gender_breakdown"].items())
    for g, counts in gender_items:
        row(g, counts["Studying"], counts["Not Studying"], counts["Unclear"], counts["Deceased"])
    row()

    category_header_row = len(data_rows) + 2
    row("SOCIAL CATEGORY x STATUS")
    row("Category", "Studying", "Not Studying", "Unclear", "Deceased")
    category_items = sorted(data["category_breakdown"].items())
    for c, counts in category_items:
        row(c, counts["Studying"], counts["Not Studying"], counts["Unclear"], counts["Deceased"])
    row()

    ws.update(data_rows, f"{DATA_COL_LETTER}1")

    formats = []
    for i, (label, header_bg, value_fg) in enumerate(KPI_CARDS):
        col = chr(ord("A") + i)
        formats.append({
            "range": f"{col}{kpi_header_row}",
            "format": {
                "backgroundColor": header_bg,
                "textFormat": {"bold": True, "fontSize": 10,
                                "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            },
        })
        formats.append({
            "range": f"{col}{kpi_value_row}",
            "format": {
                "backgroundColor": {"red": 0.91, "green": 0.91, "blue": 0.91},
                "textFormat": {"bold": True, "fontSize": 18, "foregroundColor": value_fg},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        })
    ws.batch_format(formats)
    ws.spreadsheet.batch_update({"requests": [{
        "updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                       "startIndex": kpi_header_row - 1, "endIndex": kpi_value_row},
            "properties": {"pixelSize": 36},
            "fields": "pixelSize",
        }
    }]})
    ws.columns_auto_resize(0, 8)

    # Hide the helper data block (columns N onward) — charts still read from
    # it, but it shouldn't show up as a visible table on the tab.
    ws.spreadsheet.batch_update({"requests": [{
        "updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                       "startIndex": DATA_COL_OFFSET, "endIndex": DATA_COL_OFFSET + 8},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }
    }]})

    return {
        "kpi_header_row": kpi_header_row,
        "kpi_value_row": kpi_value_row,
        "summary_header_row": summary_header_row,
        "willing_header_row": willing_header_row,
        "reason_header_row": reason_header_row,
        "reason_row_count": len(reason_items),
        "gender_header_row": gender_header_row,
        "gender_row_count": len(gender_items),
        "category_header_row": category_header_row,
        "category_row_count": len(category_items),
    }


def chart_position(anchor_row, anchor_col, width_px=480, height_px=300):
    return {
        "overlayPosition": {
            "anchorCell": {"sheetId": None, "rowIndex": anchor_row, "columnIndex": anchor_col},
            "widthPixels": width_px,
            "heightPixels": height_px,
        }
    }


def build_chart_requests(sheet_id, layout):
    requests = []
    anchor_col = 9  # column J

    def pos(row_0indexed, height_px=300):
        p = chart_position(row_0indexed, anchor_col, height_px=height_px)
        p["overlayPosition"]["anchorCell"]["sheetId"] = sheet_id
        return p

    def domain(row, start_col, end_col):
        return {"domain": {"sourceRange": {"sources": [{
            "sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
            "startColumnIndex": DATA_COL_OFFSET + start_col, "endColumnIndex": DATA_COL_OFFSET + end_col}]}}}

    def series(row, start_col, end_col):
        return {"series": {"sourceRange": {"sources": [{
            "sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
            "startColumnIndex": DATA_COL_OFFSET + start_col, "endColumnIndex": DATA_COL_OFFSET + end_col}]}},
            "targetAxis": "LEFT_AXIS"}

    # --- Status breakdown pie chart -----------------------------------
    hdr = layout["summary_header_row"] + 1
    val = hdr + 1
    requests.append({"addChart": {"chart": {
        "spec": {
            "title": "Status Breakdown",
            "hiddenDimensionStrategy": "SHOW_ALL",
            "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                # columns 1-4 = Studying/Not Studying/Unclear/Deceased; column 0
                # (Total) is deliberately excluded, it's the sum of the rest.
                "domain": {"sourceRange": {"sources": [{
                    "sheetId": sheet_id, "startRowIndex": hdr - 1, "endRowIndex": hdr,
                    "startColumnIndex": DATA_COL_OFFSET + 1, "endColumnIndex": DATA_COL_OFFSET + 5}]}},
                "series": {"sourceRange": {"sources": [{
                    "sheetId": sheet_id, "startRowIndex": val - 1, "endRowIndex": val,
                    "startColumnIndex": DATA_COL_OFFSET + 1, "endColumnIndex": DATA_COL_OFFSET + 5}]}},
            },
        },
        "position": pos(hdr - 2),
    }}})

    # --- Willingness pie chart -----------------------------------------
    whdr = layout["willing_header_row"] + 1
    wval = whdr + 1
    requests.append({"addChart": {"chart": {
        "spec": {
            "title": "Willing / Unwilling / Unclear",
            "hiddenDimensionStrategy": "SHOW_ALL",
            "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                "domain": {"sourceRange": {"sources": [{
                    "sheetId": sheet_id, "startRowIndex": whdr - 1, "endRowIndex": whdr,
                    "startColumnIndex": DATA_COL_OFFSET, "endColumnIndex": DATA_COL_OFFSET + 3}]}},
                "series": {"sourceRange": {"sources": [{
                    "sheetId": sheet_id, "startRowIndex": wval - 1, "endRowIndex": wval,
                    "startColumnIndex": DATA_COL_OFFSET, "endColumnIndex": DATA_COL_OFFSET + 3}]}},
            },
        },
        "position": pos(whdr + 17),
    }}})

    # --- Reason-wise breakup horizontal bar chart -------------------------
    rhdr = layout["reason_header_row"] + 1
    rrows = layout["reason_row_count"]
    if rrows:
        requests.append({"addChart": {"chart": {
            "spec": {
                "title": "Reason-wise Breakup — Not Studying & Unclear Cases",
                "hiddenDimensionStrategy": "SHOW_ALL",
                "basicChart": {
                    "chartType": "BAR",
                    "legendPosition": "NO_LEGEND",
                    "domains": [{"domain": {"sourceRange": {"sources": [{
                        "sheetId": sheet_id, "startRowIndex": rhdr - 1,
                        "endRowIndex": rhdr + rrows,
                        "startColumnIndex": DATA_COL_OFFSET, "endColumnIndex": DATA_COL_OFFSET + 1}]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [{
                        "sheetId": sheet_id, "startRowIndex": rhdr - 1,
                        "endRowIndex": rhdr + rrows,
                        "startColumnIndex": DATA_COL_OFFSET + 1, "endColumnIndex": DATA_COL_OFFSET + 2}]}},
                        "targetAxis": "BOTTOM_AXIS"}],
                    "headerCount": 1,
                },
            },
            "position": pos(whdr + 38, height_px=420),
        }}})

    # --- Gender x status stacked column chart ---------------------------
    ghdr = layout["gender_header_row"] + 1
    grows = layout["gender_row_count"]
    if grows:
        requests.append({"addChart": {"chart": {
            "spec": {
                "title": "Status by Gender",
                "hiddenDimensionStrategy": "SHOW_ALL",
                "basicChart": {
                    "chartType": "COLUMN",
                    "stackedType": "STACKED",
                    "legendPosition": "BOTTOM_LEGEND",
                    "domains": [domain(ghdr, 0, 1)],
                    "series": [series(ghdr, c, c + 1) for c in (1, 2, 3, 4)],
                    "headerCount": 1,
                },
            },
            "position": pos(whdr + 60),
        }}})

    # --- Category x status stacked column chart --------------------------
    chdr = layout["category_header_row"] + 1
    crows = layout["category_row_count"]
    if crows:
        requests.append({"addChart": {"chart": {
            "spec": {
                "title": "Status by Social Category",
                "hiddenDimensionStrategy": "SHOW_ALL",
                "basicChart": {
                    "chartType": "COLUMN",
                    "stackedType": "STACKED",
                    "legendPosition": "BOTTOM_LEGEND",
                    "domains": [{"domain": {"sourceRange": {"sources": [{
                        "sheetId": sheet_id, "startRowIndex": chdr - 1,
                        "endRowIndex": chdr + crows,
                        "startColumnIndex": DATA_COL_OFFSET, "endColumnIndex": DATA_COL_OFFSET + 1}]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [{
                        "sheetId": sheet_id, "startRowIndex": chdr - 1,
                        "endRowIndex": chdr + crows,
                        "startColumnIndex": DATA_COL_OFFSET + c, "endColumnIndex": DATA_COL_OFFSET + c + 1}]}},
                        "targetAxis": "LEFT_AXIS"} for c in (1, 2, 3, 4)],
                    "headerCount": 1,
                },
            },
            "position": pos(whdr + 81),
        }}})

    return requests


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

    print("Computing aggregates ...")
    data = build_dashboard_data(rows)

    print("Writing Dashboard tab ...")
    ws = get_or_create_dashboard_ws(sh)
    layout = write_tables(ws, data)

    print("Refreshing charts ...")
    delete_existing_charts(sh, ws)
    requests = build_chart_requests(ws.id, layout)
    sh.batch_update({"requests": requests})

    print(f"Done. Dashboard tab updated with {len(data['districts'])} districts, "
          f"{data['summary']['total']:,} total records.")


if __name__ == "__main__":
    main()
