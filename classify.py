"""
Out-of-School Student Status Classifier
=========================================
Reads a district-wise "out of school students" Excel/CSV export (columns:
District Name, Block Name, Student Name, Father Name, Gender, Category, Class,
Droupout Year, Address, Mobile No., current Status, Remark) and classifies
each record into:

    Known - Studying
    Known - Not Studying / Dropout   (further split into Willing / Unwilling)
    Garbage / Unclear                (no usable status obtained)

Also flags Death cases separately, and produces a multi-sheet Excel report.

USAGE
-----
    python classify.py INPUT_FILE.xlsx [-o OUTPUT_FILE.xlsx]

    python classify.py data/latest_district_report.xlsx -o outputs/classified.xlsx

See README.md for the full methodology writeup.
"""
import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIRMED_PHRASES_FILE = SCRIPT_DIR / "data" / "confirmed_studying_phrases.txt"


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------
# These were built iteratively against real district survey text (English,
# Hindi, and Hinglish, with heavy typos). Add new patterns here as new
# districts/phrasings show up — see README.md "Extending the patterns".

GARBAGE_PATTERNS = [
    r'^nan$', r'^-+$', r'^_+$', r'^&+$', r'^\.+$', r'^nil$', r'^null$', r'^none$', r'^no$',
    r'not\s*contact', r'no\s*contact', r'not\s*incoming', r'no\s*incoming', r'not\s*receiv',
    r'no\s*call\s*rec', r'not\s*respond', r'no\s*respond', r'not\s*answer', r'no\s*answer',
    r'wrong\s*no', r'wrong\s*number', r'wrong\s*phone', r'invalid\s*number', r'number\s*not',
    r'not\s*available', r'incorrect\s*phone', r'number\s*is\s*not', r'phone\s*number\s*not',
    r'switch\s*off', r'switched\s*off', r'swich\s*off', r'swtich\s*off', r'phone\s*swich',
    r'data\s*not', r'no\s*information', r'no\s*info\b', r'information\s*not', r'not\s*found',
    r'no\s*data', r'active\s*for\s*import', r'status\s*not\s*known', r'un-?tagged',
    r'duplicate', r'not\s*tracable', r'not\s*traceable', r'not\s*in\s*contact',
    r'recharge\s*nahi', r'नम्बर\s*(गलत|अमान्य)', r'सम्पर्क\s*नहीं', r'संपर्क\s*नह',
    r'रॉंग\s*नंबर', r'no\s*call\s*recev', r'not\s*reved\s*phone', r'unavilable\s*to\s*contact',
    r'unavailability', r'call\s*not\s*receiv', r'not\s*recieved', r'no\s*incomming',
    r'incomming\s*not', r'not\s*trac', r'no\s*contect', r'ragistration\s*is', r'unkown\s*reason',
    r'जानकारी\s*उपलब्ध\s*नहीं', r'service\s*closed', r't\.?c[\s-]*no[\s-]*genrate',
]
GARBAGE_EXACT = [r'^mid\s*session$', r'^end\s*session$', r'^inactive$', r'^not\s*active$']

STUDYING_PATTERNS = [
    r'studying', r'stdying', r'study\s*in\b', r'studies\s*in\b', r'studynig',
    r'admission\s*(in|other)', r'take\s*admission', r'admitted',
    r'transfer\s*to\s*other\s*school', r'same\s*school', r'studied\s*in\s*other',
    r'pass\s*out', r'passout', r'pass[\s-]*out', r'\bpassed\b', r'\bpass\b', r'12th\s*pass', r'10th\s*pass',
    r'अध्ययनरत', r'नामांकित', r'पढाई\s*जारी', r'active\s*in\s*1[0-2]', r'^active$', r'उत्तीर्ण',
    r'class\s*1[0-2]\s*read', r'reading', r'b\.?a\b', r'\bb\s*a\b', r'\bm\s*a\b', r'read for', r'^study$',
    r'college', r'class\s*-?\s*\d+\s*pass', r'^class\s*-?\s*\d+$', r'at\s*the\s*school',
    r'stud(y|ing)', r'near\s*by', r'pass\s*from', r'continue\s*stud', r'will\s*continue',
    r'पढ़?\s*रह', r'अध्ययन\s*कर\s*रह', r'अध्यनरत', r'admi[s]{1,2}io?n', r're\s*admi',
    r'12th\s*paas', r'paas\s*out', r'\bi\s*t\s*i\b', r'ongoing\s*stud',
    r'already\s*in\s*class', r'with\s*pen\s*no', r'completed\s*inter', r'open\s*school',
    r'open\s*board', r'open\s*से', r'from\s*open',
]

NEG_PATTERNS = r'not|no\s|nahi|नहीं|nat\s'

NOT_STUDYING_PATTERNS = [
    r'drop\s*out', r'dropout', r'drpout', r'drop\s*box', r'nso\b',
    r'left\s*(the\s*)?school', r'left\s*stud', r'leave\s*stud', r'leave\s*school',
    r'not\s*stud', r'no\s*stud', r'stopped\s*stud', r'stud.*stopped', r'padhai',
    r'padai', r'nahi\s*padh', r'नहीं\s*पढ़', r'नही\s*पढ़', r'पढ़ाई\s*छोड़', r'पढाई\s*छोड',
    r'not\s*intere?st', r'guardian\s*not\s*inter', r'parents?\s*not\s*inter',
    r'no\s*admi[sd]{1,2}ion', r'not\s*admi', r'admisson',
    r'migrat', r'marri', r'शादी', r'ससुराल', r'labour', r'मजदूरी', r'working',
    r'\bjob\b', r'naukri', r'death', r'मृत्यु', r'out\s*of\s*stat', r'other\s*stat',
    r'family\s*reloc', r'family\s*problem', r'घरेलू', r'कृषि', r'किसानी', r'दुकान',
    r'फर्नीचर', r'refused', r'unwilling', r'not\s*intrest', r'quit\s*stud',
    r'due\s*to\s*(unknow|job|marriage)', r'fail', r'home\s*work', r'at\s*home',
    r'^home$', r'live\s*at\s*home', r'घर\s*पर', r'ghar\s*p', r'not\s*related\s*to\s*this',
    r'tc\s*issu', r't\.?c\.?\s*lekar', r'without\s*tc', r'name\s*struck',
    r'सिलाई', r'ब्यूटीपार्लर', r'जीविकोपार्जन', r'बाहर\s*रह', r'delete\s*from\s*dropout',
    r'not\s*upathithi', r'absent', r'खारिज', r'not\s*s[yt]?udying', r'not\s*std', r'stdying',
    r'out\s*of\s*school', r'out\s*of\s*distr', r'छोड़', r'chor\s*di', r'chhod\s*di',
    r'not\s*intra?sted', r'not\s*want\s*to\s*stud', r'the\s*student\s*was\s*to\s*put\s*work',
    r'study\s*closed', r'prayas\s*karne\s*bad', r't\s*c\s*lekar\s*chala\s*gaya',
    r'प्रवेश\s*नहीं', r'नहीं\s*लिया', r'n\.s\.o', r'दिल्ली', r'गाजियाबाद', r'नोयडा',
    r'dropped\s*out', r'अभिभावक', r'left\s*with\s*tc', r'left\s*without', r'tc\s*genrate',
    r'निर्गत', r'पढना\s*है', r'पढ़ना\s*है', r'not\s*present\s*in\s*school', r'poor\s*economic',
    r'home\s*maker', r'left\s*state', r'labure', r'labor', r'guardian\s*concert',
    r'not\s*read\s*for\s*sick', r'deleted', r'ड्रॉपआउट', r'kharij', r'अध्ययनरत\s*नहीं',
    r'marked\s*dropout', r'\bnso\b', r'not\s*of\s*stat',
]

CONTACT_FAIL_PATTERN = (
    r'contact|no.?info|not receiv|no response|not respond|no answer|not in touch|'
    r'unreachable|not reachable|switch\s*off|संपर्क|सम्पर्क|number|नंबर|नम्बर'
)

DEATH_PATTERN = r'death|मृत्यु|मृत\b|deaqth|expired|dead\b'

UNWILLING_PATTERNS = [
    r'not\s*intere?st', r'not\s*intrest', r'not\s*intra?sted', r'guardian\s*not\s*inter',
    r'parents?\s*not\s*inter', r'unwilling', r'refused', r'not\s*want\s*to\s*stud',
    r'does\s*not\s*want', r'नहीं\s*पढ़ना\s*चाहती', r'पढ़ना\s*नहीं\s*चाहती', r'चाहती\s*नहीं',
    r'सहमती\s*से\s*नहीं\s*पढ़ना', r'parental\s*wish', r'parental\s*consent', r'parents?\s*wish',
    r'guardian\s*dicision', r'guardian\s*decision', r'guardian\s*concert',
    r'अभिभावक.*(इच्छा|अनुसार)', r'पिता.*(अनुसार|इच्छा)', r'नहीं\s*पढ़ना\s*है', r'पढ़ना\s*नहीं\s*है',
    r'not\s*studying\s*with\s*gaurdian', r'nahin\s*padhna\s*hai', r'padhne\s*ka\s*ichuk\s*nahi',
    r'पढने\s*का\s*इच्छुक\s*नहीं', r'पढने\s*से\s*इनकार', r'kisi\s*bhi\s*school\s*me\s*nhi\s*padhna',
    r'student\s*choice', r'not\s*interested\s*in\s*stud',
    # NOTE: death/मृत्यु deliberately excluded — death cases are tracked separately
    # and should not count toward "unwilling to study" (see README "Death handling").
]

UNABLE_PATTERNS = [
    r'labour', r'labor', r'labure', r'मजदूरी', r'working', r'\bjob\b', r'naukri',
    r'poor\s*econ', r'economic', r'migrat', r'family\s*reloc', r'out\s*of\s*stat',
    r'out\s*of\s*distr', r'married', r'marri', r'शादी', r'ससुराल', r'tc\s*issu',
    r'no\s*admi', r'not\s*admi', r'admisson', r'sick', r'health', r'family\s*problem',
    r'कृषि', r'किसानी', r'दुकान', r'घरेलू', r'death', r'मृत्यु', r'फर्नीचर',
    r'private\s*job', r'home\s*work', r'due\s*to\s*job', r'due\s*to\s*marriage',
    r'transportation', r'सिलाई', r'ब्यूटीपार्लर', r'जीविकोपार्जन', r'work\s*at\s*shop',
    r'self\s*employ', r'नौकरी', r'ill\b', r'disab',
]

REASON_PATTERNS_ORDERED = [
    ('Marriage (शादी/ससुराल)', r'marri|शादी|ससुराल'),
    ('Death (मृत्यु)', r'death|मृत्यु'),
    ('Guardian/Parent not interested',
     r'guardian\s*not\s*inter|parents?\s*not\s*inter|guardian\s*wish|guardian\s*decision|'
     r'guardian\s*consent|अभिभावक'),
    ('Student personally not interested / refused',
     r'not\s*intere?st|not\s*want\s*to\s*stud|unwilling|refused|नहीं\s*पढ़ना|चाहती\s*नहीं'),
]


def load_confirmed_phrases():
    """Exact-match phrases previously verified by hand (see data/confirmed_studying_phrases.txt).
    These override the regex patterns above and are checked against BOTH the
    'current Status' and 'Remark' columns."""
    if not CONFIRMED_PHRASES_FILE.exists():
        return set()
    with open(CONFIRMED_PHRASES_FILE, encoding="utf-8") as f:
        labels = [line.rstrip("\n") for line in f if line.strip()]
    nfc = {unicodedata.normalize("NFC", x.strip()) for x in labels}
    # bare numbers are handled by a dedicated rule, not the exact-match list
    return {v for v in nfc if not re.match(r"^\d+$", v)}


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Take a raw dataframe with the expected columns and return it with
    Status_Category, Willingness_Category, and Death_Flag columns added."""

    df = df.copy()
    s = df["current Status"].astype(str).str.strip().apply(
        lambda x: unicodedata.normalize("NFC", str(x))
    )
    s_low = s.str.lower()

    def has(pattern, series=s_low):
        return series.str.contains(unicodedata.normalize("NFC", pattern), regex=True, na=False)

    # --- garbage / no real info ---
    is_garbage = pd.Series(False, index=df.index)
    for p in GARBAGE_PATTERNS:
        is_garbage |= has(p)
    for p in GARBAGE_EXACT:
        is_garbage |= s_low.str.match(unicodedata.normalize("NFC", p), na=False)
    is_garbage |= s.isna() | (s_low == "nan") | (s.str.strip() == "")

    # --- studying ---
    is_studying_raw = pd.Series(False, index=df.index)
    for p in STUDYING_PATTERNS:
        is_studying_raw |= has(p)
    is_negated = has(NEG_PATTERNS)
    # "PEN No" / "did not take TC" false-trigger the negation check (No = number, not "not")
    is_studying = (is_studying_raw & ~is_negated) | has(r"already\s*in\s*class") | has(r"did\s*not\s*take\s*t\.?c")

    # --- not studying ---
    is_not_studying_raw = pd.Series(False, index=df.index)
    for p in NOT_STUDYING_PATTERNS:
        is_not_studying_raw |= has(p)
    is_not_studying = is_not_studying_raw & ~is_studying
    is_garbage = is_garbage & ~is_studying & ~is_not_studying

    cat = pd.Series("Unclear/Other (needs manual review)", index=df.index)
    cat[is_garbage] = "Garbage / No Info (khanapurti)"
    cat[is_not_studying] = "Known - Not Studying / Dropout"
    cat[is_studying] = "Known - Studying"

    # Contact-failure text that happened to also match a dropout keyword should
    # NOT count as a known outcome — move it back to Unclear.
    is_contact_fail = has(CONTACT_FAIL_PATTERN)
    move_to_unclear = (cat == "Known - Not Studying / Dropout") & is_contact_fail
    cat[move_to_unclear] = "Unclear/Other (needs manual review)"

    df["Status_Category"] = cat

    # --- hand-verified exact-match overrides (current Status OR Remark) ---
    confirmed = load_confirmed_phrases()
    if confirmed:
        remark_exact = df["Remark"].astype(str).str.strip().apply(
            lambda x: unicodedata.normalize("NFC", str(x))
        )
        override_mask = s.isin(confirmed) | remark_exact.isin(confirmed)
        df.loc[override_mask, "Status_Category"] = "Known - Studying"

    # --- death flag (independent of status category) ---
    death_mask = (
        df["current Status"].astype(str).str.contains(DEATH_PATTERN, case=False, na=False, regex=True)
        | df["Remark"].astype(str).str.contains(DEATH_PATTERN, case=False, na=False, regex=True)
    )
    df["Death_Flag"] = ""
    df.loc[death_mask, "Death_Flag"] = "Death Reported"

    # --- bare 1-2 digit "status" (e.g. "10", "12") -> Not Studying ---
    bare_number_mask = s.str.match(r"^\d{1,2}$", na=False) & (
        df["Status_Category"] == "Unclear/Other (needs manual review)"
    )
    df.loc[bare_number_mask, "Status_Category"] = "Known - Not Studying / Dropout"

    # --- long numeric "status" (duplicated mobile number) -> fall back to Remark ---
    remark_s = (
        df["Remark"].astype(str).str.strip().apply(lambda x: unicodedata.normalize("NFC", str(x))).str.lower()
    )

    def has_remark(pattern):
        return remark_s.str.contains(unicodedata.normalize("NFC", pattern), regex=True, na=False)

    long_numeric_mask = s.str.match(r"^\d{3,}$", na=False) & (
        df["Status_Category"] == "Unclear/Other (needs manual review)"
    )
    remark_studying = pd.Series(False, index=df.index)
    remark_not_studying = pd.Series(False, index=df.index)
    for p in STUDYING_PATTERNS:
        remark_studying |= has_remark(p)
    for p in NOT_STUDYING_PATTERNS:
        remark_not_studying |= has_remark(p)
    remark_studying = remark_studying & ~has_remark(NEG_PATTERNS)

    df.loc[long_numeric_mask & remark_studying, "Status_Category"] = "Known - Studying"
    df.loc[
        long_numeric_mask & remark_not_studying & ~remark_studying, "Status_Category"
    ] = "Known - Not Studying / Dropout"

    # --- willingness sub-classification (within Not Studying only) ---
    ns_mask = df["Status_Category"] == "Known - Not Studying / Dropout"
    is_unwilling = pd.Series(False, index=df.index)
    for p in UNWILLING_PATTERNS:
        is_unwilling |= has(p)
    is_unable = pd.Series(False, index=df.index)
    for p in UNABLE_PATTERNS:
        is_unable |= has(p)

    will_cat = pd.Series("Willing (economic/external reason or unspecified)", index=df.index)
    will_cat[ns_mask & is_unwilling] = "Unwilling - Does Not Want to Study"
    df.loc[ns_mask, "Willingness_Category"] = will_cat[ns_mask]

    return df


def detect_reason(row):
    text = f"{row['current Status']} {row['Remark']}"
    for name, pat in REASON_PATTERNS_ORDERED:
        if re.search(pat, str(text), re.IGNORECASE):
            return name
    return "Reason unclear (matched general unwilling keyword)"


def build_report(df: pd.DataFrame, output_path: Path, master_total: int | None = None):
    out_cols = [
        "District Name", "Block Name", "Student Name", "Father Name", "Gender", "Category",
        "Class", "Droupout Year", "Address", "Mobile No.", "current Status", "Remark",
        "Status_Category", "Willingness_Category", "Death_Flag",
    ]
    out_cols = [c for c in out_cols if c in df.columns]

    known_studying = df.loc[df["Status_Category"] == "Known - Studying", out_cols].reset_index(drop=True)
    known_not_studying = df.loc[df["Status_Category"] == "Known - Not Studying / Dropout", out_cols].reset_index(drop=True)
    garbage_unclear = df.loc[
        df["Status_Category"].isin(["Garbage / No Info (khanapurti)", "Unclear/Other (needs manual review)"]),
        out_cols,
    ].reset_index(drop=True)
    death_cases = df.loc[df["Death_Flag"] == "Death Reported", out_cols].reset_index(drop=True)

    unwilling_df = known_not_studying[
        known_not_studying["Willingness_Category"] == "Unwilling - Does Not Want to Study"
    ].reset_index(drop=True)
    willing_df = known_not_studying[
        known_not_studying["Willingness_Category"] == "Willing (economic/external reason or unspecified)"
    ].reset_index(drop=True)
    if len(unwilling_df):
        unwilling_df["Detected Reason"] = unwilling_df.apply(detect_reason, axis=1)

    total = len(df)
    studying_n = len(known_studying)
    ns_total = len(known_not_studying)
    verified_n = studying_n + ns_total

    summary_rows = [
        {"Status_Category": "Known - Studying", "Count": studying_n, "Percent (of Total)": round(studying_n / total * 100, 1)},
        {"Status_Category": "Known - Not Studying / Dropout", "Count": ns_total, "Percent (of Total)": round(ns_total / total * 100, 1)},
        {"Status_Category": "    > Willing", "Count": len(willing_df), "Percent (of Total)": ""},
        {"Status_Category": "    > Unwilling", "Count": len(unwilling_df), "Percent (of Total)": ""},
        {"Status_Category": "Garbage / Unclear", "Count": len(garbage_unclear), "Percent (of Total)": round(len(garbage_unclear) / total * 100, 1)},
        {"Status_Category": "TOTAL (this file)", "Count": total, "Percent (of Total)": 100.0},
    ]
    if master_total:
        summary_rows += [
            {"Status_Category": "", "Count": "", "Percent (of Total)": ""},
            {"Status_Category": "Total records sent to districts (master list)", "Count": master_total, "Percent (of Total)": 100.0},
            {"Status_Category": "  > Verified (this file)", "Count": verified_n, "Percent (of Total)": round(verified_n / master_total * 100, 1)},
            {"Status_Category": "      > Studying", "Count": studying_n, "Percent (of Total)": round(studying_n / master_total * 100, 1)},
            {"Status_Category": "      > Not Studying", "Count": ns_total, "Percent (of Total)": round(ns_total / master_total * 100, 1)},
        ]
    summary = pd.DataFrame(summary_rows)

    district_cat = df["Status_Category"].replace({
        "Garbage / No Info (khanapurti)": "Unclear",
        "Unclear/Other (needs manual review)": "Unclear",
        "Known - Not Studying / Dropout": "Known - Not Studying",
    })
    district_summary = df.groupby(df["District Name"])[district_cat.name].value_counts() \
        if False else None  # placeholder to avoid confusion; computed below properly
    district_summary = pd.concat([df["District Name"], district_cat.rename("cat")], axis=1) \
        .groupby("District Name")["cat"].value_counts().unstack(fill_value=0)
    for col in ["Known - Studying", "Known - Not Studying", "Unclear"]:
        if col not in district_summary.columns:
            district_summary[col] = 0
    district_summary = district_summary[["Known - Studying", "Known - Not Studying", "Unclear"]]
    district_summary.insert(0, "Total Entries", district_summary.sum(axis=1))
    district_summary = district_summary.sort_values("Total Entries", ascending=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        district_summary.to_excel(writer, sheet_name="District-wise Breakup")
        known_studying.to_excel(writer, sheet_name="Known - Studying", index=False)
        known_not_studying.to_excel(writer, sheet_name="Known - Not Studying", index=False)
        unwilling_df.to_excel(writer, sheet_name="Unwilling (with reason)", index=False)
        death_cases.to_excel(writer, sheet_name="Death Cases", index=False)
        garbage_unclear.to_excel(writer, sheet_name="Garbage_Unclear", index=False)

    print(f"Saved: {output_path}")
    print(f"  Known - Studying:      {studying_n}")
    print(f"  Known - Not Studying:  {ns_total}  (Willing: {len(willing_df)}, Unwilling: {len(unwilling_df)})")
    print(f"  Garbage/Unclear:       {len(garbage_unclear)}")
    print(f"  Death cases flagged:   {len(death_cases)}")


def main():
    parser = argparse.ArgumentParser(description="Classify out-of-school student status records.")
    parser.add_argument("input_file", type=Path, help="Input .xlsx or .csv file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .xlsx path")
    parser.add_argument(
        "--master-total", type=int, default=None,
        help="Total records in the full master list sent to all districts (for coverage %% rows)",
    )
    args = parser.parse_args()

    if args.input_file.suffix.lower() == ".csv":
        df = pd.read_csv(args.input_file)
    else:
        df = pd.read_excel(args.input_file)

    df = classify(df)

    output = args.output or args.input_file.with_name(args.input_file.stem + "_classified.xlsx")
    build_report(df, output, master_total=args.master_total)

    # also drop a pickle next to the output for downstream scripts (e.g. map_to_dashboard.py)
    df.to_pickle(output.with_suffix(".pkl"))


if __name__ == "__main__":
    main()
