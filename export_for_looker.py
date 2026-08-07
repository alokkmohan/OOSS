"""
Export Out-of-School Student Tracking data for Looker / Looker Studio.
========================================================================

Reads classified student data (from classify.py output .pkl or .xlsx)
and exports two optimized datasets for Looker / Looker Studio:

1. fact_student_status.csv / .parquet (Row-Level Fact Dataset)
2. agg_district_summary.csv (District Aggregated Summary Dataset)

USAGE
-----
    python export_for_looker.py INPUT_CLASSIFIED.pkl -o outputs/

    or

    python export_for_looker.py input_district_data.xlsx -o outputs/
"""
import argparse
import re
from pathlib import Path
import pandas as pd
import numpy as np

# Import classification logic if raw file provided
from classify import classify

DISTRICT_ALIAS = {
    "GB NAGAR": "Gautam Buddha Nagar",
    "HAMIRPUR (U.P.)": "Hamirpur",
    "KHERI": "Lakhimpur Kheri",
    "LAKHIMPUR KHERI": "Lakhimpur Kheri",
    "SHRAWASTI": "Shravasti",
    "BHADOI": "Bhadohi",
}

NOT_STUDYING_REASON_PATTERNS = [
    ("Marriage", r"marri|शादी|ससुराल"),
    ("Migrated for Labour/Work", r"labour|labor|labure|मजदूरी|working|\bjob\b|naukri|migrat"),
    ("Admission Not Taken / TC Issue", r"tc\s*issu|no\s*admi|not\s*admi|admisson"),
    ("Household / Domestic Responsibility", r"घरेलू|कृषि|किसानी|दुकान|home\s*work|household"),
    ("Health / Medical Reason", r"sick|health|ill\b|disab"),
    ("Financial Problem", r"poor\s*econ|economic|financial"),
    ("Refused to Continue Studies",
     r"not\s*intere?st|not\s*want\s*to\s*stud|unwilling|refused|नहीं\s*पढ़ना|"
     r"guardian\s*not\s*inter|parents?\s*not\s*inter|अभिभावक"),
]

UNCLEAR_REASON_PATTERNS = [
    ("Wrong / Invalid Number", r"wrong\s*no|wrong\s*number|wrong\s*phone|invalid\s*number|incorrect\s*phone"),
    ("Switched Off / Not Reachable", r"switch\s*off|switched\s*off|swich\s*off|swtich\s*off"),
    ("Call Not Received", r"not\s*receiv|no\s*answer|not\s*answer|call\s*not|no\s*respond|not\s*respond"),
    ("No Information Available", r"no\s*info|data\s*not|active\s*for\s*import|status\s*not\s*known|no\s*data"),
    ("Refused to Share Information", r"refused\s*to\s*share|not\s*share"),
]


def norm_district(d):
    du = str(d).strip().upper()
    if du in DISTRICT_ALIAS:
        return DISTRICT_ALIAS[du]
    return str(d).strip().title()


def map_status_category(row):
    if row.get("Death_Flag") == "Death Reported":
        return "Death Case"
    sc = row.get("Status_Category", "Unclear/Other (needs manual review)")
    if sc == "Known - Studying":
        return "Known - Studying"
    if sc == "Known - Not Studying / Dropout":
        return "Known - Not Studying / Dropout"
    return "Unclear"


def map_current_status_simple(scd):
    return {
        "Death Case": "Deceased",
        "Known - Studying": "Studying",
        "Known - Not Studying / Dropout": "Not Studying",
    }.get(scd, "Unclear")


def detect_reason(row):
    scd = row["status_category_dash"]
    text = f"{row.get('current Status', '')} {row.get('Remark', '')}"
    if scd == "Death Case":
        return "Death (Student/Family Member)"
    if scd == "Known - Not Studying / Dropout":
        for name, pat in NOT_STUDYING_REASON_PATTERNS:
            if re.search(pat, str(text), re.IGNORECASE):
                return name
        return "Other Reason"
    if scd == "Unclear":
        for name, pat in UNCLEAR_REASON_PATTERNS:
            if re.search(pat, str(text), re.IGNORECASE):
                return name
        if str(row.get("current Status", "")).strip() in ("", "nan", "None") and str(row.get("Remark", "")).strip() in ("", "nan", "None"):
            return "Yet to be Contacted"
        return "Unclear Reason"
    return "N/A"


def map_willing(row):
    if row["status_category_dash"] != "Known - Not Studying / Dropout":
        return "N/A"
    return "No" if row.get("Willingness_Category") == "Unwilling - Does Not Want to Study" else "Yes"


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names across varying district export formats."""
    col_map = {
        "Student Sub Status": "current Status",
        "Current Status": "current Status",
        "Current Status (Study/Not Study)": "current Status",
        "Remarks": "Remark",
        "Remark (Verbatim)": "Remark",
        "Last Class": "Class",
        "Social Category": "Category",
        "Willing to Resume Studies": "Willingness_Category",
        "Status Category": "Status_Category",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    return df


def prepare_fact_dataset(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = normalize_column_names(df)

    # Ensure current Status and Remark columns exist
    if "current Status" not in df.columns:
        df["current Status"] = ""
    if "Remark" not in df.columns:
        df["Remark"] = ""

    # Ensure required columns are present
    if "Status_Category" not in df.columns or df["Status_Category"].isna().all():
        print("Status_Category missing. Running classification logic...")
        df = classify(df)

    df["district_name"] = df["District Name"].apply(norm_district)
    df["block_name"] = df.get("Block Name", pd.Series("Unknown", index=df.index)).fillna("Unknown Block").astype(str).str.title().str.strip()
    df["gender"] = df.get("Gender", pd.Series("Unknown", index=df.index)).fillna("Unknown").astype(str).str.title().str.strip()
    df["category"] = df.get("Category", pd.Series("General", index=df.index)).fillna("General").astype(str).str.upper().str.strip()
    df["class_name"] = df.get("Class", pd.Series("Unknown Class", index=df.index)).fillna("Unknown Class").astype(str).str.strip()
    df["dropout_year"] = df.get("Droupout Year", pd.Series("Unknown", index=df.index)).fillna("Unknown").astype(str).str.strip()
    
    df["status_category_dash"] = df.apply(map_status_category, axis=1)
    df["current_status_simple"] = df["status_category_dash"].apply(map_current_status_simple)
    df["reason_category"] = df.apply(detect_reason, axis=1)
    df["willing_to_resume"] = df.apply(map_willing, axis=1)
    df["death_flag"] = df.get("Death_Flag", pd.Series("", index=df.index)).fillna("")

    # Binary Indicator Metrics for fast Looker aggregations
    df["is_verified"] = df["current_status_simple"].isin(["Studying", "Not Studying"]).astype(int)
    df["is_studying"] = (df["current_status_simple"] == "Studying").astype(int)
    df["is_not_studying"] = (df["current_status_simple"] == "Not Studying").astype(int)
    df["is_unclear"] = (df["current_status_simple"] == "Unclear").astype(int)
    df["is_deceased"] = (df["current_status_simple"] == "Deceased").astype(int)

    fact_cols = [
        "district_name",
        "block_name",
        "Student Name",
        "Father Name",
        "gender",
        "category",
        "class_name",
        "dropout_year",
        "current_status_simple",
        "status_category_dash",
        "reason_category",
        "willing_to_resume",
        "death_flag",
        "is_verified",
        "is_studying",
        "is_not_studying",
        "is_unclear",
        "is_deceased",
    ]
    
    # Rename student and father name columns for cleaner SQL/BI naming
    rename_dict = {
        "Student Name": "student_name",
        "Father Name": "father_name",
        "status_category_dash": "status_category_full",
    }
    
    fact_df = df[[c for c in fact_cols if c in df.columns]].rename(columns=rename_dict)
    return fact_df


def prepare_aggregated_summary(fact_df: pd.DataFrame) -> pd.DataFrame:
    agg_df = fact_df.groupby("district_name").agg(
        total_students=("student_name", "count"),
        total_verified=("is_verified", "sum"),
        total_studying=("is_studying", "sum"),
        total_not_studying=("is_not_studying", "sum"),
        total_unclear=("is_unclear", "sum"),
        total_deceased=("is_deceased", "sum"),
    ).reset_index()

    agg_df["verification_rate_pct"] = (agg_df["total_verified"] / agg_df["total_students"] * 100).round(1)
    agg_df["studying_rate_of_verified_pct"] = np.where(
        agg_df["total_verified"] > 0,
        (agg_df["total_studying"] / agg_df["total_verified"] * 100).round(1),
        0.0
    )
    agg_df["dropout_rate_of_verified_pct"] = np.where(
        agg_df["total_verified"] > 0,
        (agg_df["total_not_studying"] / agg_df["total_verified"] * 100).round(1),
        0.0
    )

    agg_df = agg_df.sort_values("total_students", ascending=False)
    return agg_df


def main():
    parser = argparse.ArgumentParser(description="Export Out-of-School Student data for Looker / Looker Studio.")
    parser.add_argument("input_file", type=Path, help="Input classified .pkl, .xlsx, or .csv file")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("outputs"), help="Output directory path")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    file_suffix = args.input_file.suffix.lower()

    print(f"Loading input file: {args.input_file}")
    if file_suffix == ".pkl":
        df = pd.read_pickle(args.input_file)
    elif file_suffix == ".csv":
        df = pd.read_csv(args.input_file)
    else:
        xls = pd.ExcelFile(args.input_file)
        # Check if this is a classified report workbook with multiple data sheets
        classified_sheets = [s for s in ["Known - Studying", "Known - Not Studying", "Garbage_Unclear", "Death Cases"] if s in xls.sheet_names]
        if classified_sheets:
            print(f"Found classified data sheets: {classified_sheets}. Concatenating...")
            dfs = [pd.read_excel(xls, sheet_name=s) for s in classified_sheets]
            df = pd.concat(dfs, ignore_index=True)
        else:
            sheet_to_read = "Master Raw Data" if "Master Raw Data" in xls.sheet_names else 0
            df = pd.read_excel(xls, sheet_name=sheet_to_read)

    print("Building Fact Dataset for Looker...")
    fact_df = prepare_fact_dataset(df)

    print("Building Aggregated District Summary Dataset...")
    agg_df = prepare_aggregated_summary(fact_df)

    fact_csv_path = args.output_dir / "fact_student_status.csv"
    agg_csv_path = args.output_dir / "agg_district_summary.csv"

    fact_df.to_csv(fact_csv_path, index=False, encoding="utf-8")
    agg_df.to_csv(agg_csv_path, index=False, encoding="utf-8")

    print(f"\nSuccessfully generated Looker export files:")
    print(f"  1. Fact Dataset: {fact_csv_path} ({len(fact_df):,} rows)")
    print(f"  2. Aggregated Summary: {agg_csv_path} ({len(agg_df):,} districts)")

if __name__ == "__main__":
    main()
