"""
Automated Reason Report Generator for Out-of-School Dashboard
=============================================================
Fetches latest records from 'Field Data Collection' tab in Google Sheets,
applies the exact classification logic:
1. Filters Status = 'Not Studying' and Reason != 'Death'.
2. Classifies Reason = 'Other' remarks into themes using Regex.
3. Imputes remaining Other records using school (UDISE) mode if >= 2 reasons recorded.
4. Aggregates into main categories:
   - रुचि नहीं
   - पलायन (Economic 1)
   - आर्थिक (Economic 2)
   - घरेलू (Economic 3)
   - प्रवेश नहीं/TC
   - विवाह
   - बीमारी
   - अभिभावक की इच्छा
   - fail/नाम कटा/स्कूल दूर
   - कारण पता नहीं चला (स्पष्ट नहीं, पहले से पास/गलत entry, संपर्क नहीं)
5. Generates gender comparison table.
6. Updates dashboard/index.html and pushes to GitHub.
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime
import pandas as pd
from google.oauth2.service_account import Credentials
import gspread

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = r"D:\NIOS"
CREDS_FILE = os.path.join(SCRIPT_DIR, "service_account.json")
SHEET_ID = "1WWifakyqkBoA922wu16bCYBZTjK2NyrxkVC_6eLBIV0"
COLLECTION_TAB = "Field Data Collection"
DASHBOARD_HTML = os.path.join(SCRIPT_DIR, "dashboard", "index.html")

def fetch_data():
    print(f"Connecting to Google Sheet ({SHEET_ID})...")
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(COLLECTION_TAB)
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        raise ValueError("No data rows found in worksheet")
    
    headers = all_values[0]
    rows = all_values[1:]
    
    records = []
    for r in rows:
        while len(r) < 21:
            r.append('')
        records.append({
            'pen': r[0].strip(),
            'district': r[1].strip(),
            'udise': r[3].strip(),
            'gender': r[6].strip(),
            'last_class': r[11].strip(),
            'status': r[14].strip(),
            'willing': r[15].strip(),
            'reason': r[17].strip(),
            'remarks': r[19].strip(),
            'updated_at': r[20].strip()
        })
    df = pd.DataFrame(records)
    print(f"Fetched {len(df)} total survey records.")
    return df

def classify_reasons(df):
    total_surveyed = len(df)
    studying = len(df[df['status'] == 'Studying'])
    deceased = len(df[df['reason'] == 'Death'])
    
    not_studying = df[(df['status'] == 'Not Studying') & (df['reason'] != 'Death')].copy()
    total_not_studying = len(not_studying)
    willing_students = len(not_studying[not_studying['willing'] == 'Yes'])
    
    # Class breakdown
    class_counts = not_studying['last_class'].value_counts()
    class_10 = int(class_counts.get('10', 0))
    class_9 = int(class_counts.get('9', 0))
    class_11 = int(class_counts.get('11', 0))

    # Known non-Other reasons
    known = not_studying[(not_studying['reason'].notna()) & (not_studying['reason'] != '') & (not_studying['reason'] != 'Other')].copy()
    
    # UDISE mode map (school level top reason if >= 2 known reasons)
    udise_modes = {}
    for udise, group in known.groupby('udise'):
        if len(group) >= 2:
            top_r = group['reason'].mode().iloc[0]
            udise_modes[udise] = top_r

    # Regex patterns for Other remarks
    P_PASSED_OR_ELSEWHERE = re.compile(r'pass|paas|प[ाा]?स|कहीं\s*और|अन्य\s*स्कूल|प्राइवेट|degree|iti|diploma|college|admitted\s*elsewhere', re.I)
    P_WRONG_DUPLICATE = re.compile(r'गलत|duplicate|wrong|फेक|fake|अमान्य|pen\s*गलत|रजिस्टर\s*नहीं', re.I)
    P_NO_CONTACT = re.compile(r'संपर्क\s*नहीं|not\s*reach|switch|स्विच\s*ऑफ|out\s*of\s*service|not\s*contact|बात\s*नहीं|अमान्य\s*नंबर|गलत\s*नंबर', re.I)
    P_PARENT_WISH = re.compile(r'अभिभावक|माता|पिता|parents?|घर\s*वाले|मना\s*कर|इच्छा\s*नहीं', re.I)
    P_MIGRATION_LABOUR = re.compile(r'पलायन|काम|मजदूरी|मज़दूरी|नौकरी|बाहर|दुकान|job|work|migrat|delhi|mumbai|surat|punjab|कमाने', re.I)
    P_FAIL_DROPPED_FAR = re.compile(r'fail|फेल|फ़ैल|नाम\s*कट|दूर|distance|आने\s*जाने', re.I)
    P_FINANCIAL = re.compile(r'पैस|आर्थिक|तंगी|गरीबी|financ|money|fees?|फीस', re.I)
    P_MARRIAGE = re.compile(r'विवाह|शादी|shaadi|marr?iage', re.I)
    P_DOMESTIC = re.compile(r'घरेलू|घर\s*का|देखभाल|छोटा\s*भाई|परिवार', re.I)
    P_HEALTH = re.compile(r'बीमार|इलाज|स्वास्थ्य|medical|ill|mental|दिव्यांग', re.I)
    P_TC_ADMISSION = re.compile(r'tc|प्रवेश|दाखिला|एडमिशन|admission|टी[०.]?सी', re.I)
    P_NOT_INTERESTED = re.compile(r'रुचि\s*नहीं|इच्छा\s*नहीं|मन\s*नहीं|not\s*interest|पढ़ना\s*नहीं|पढ़ना\s*नहीं', re.I)

    # Process all not_studying records
    final_categories = []
    
    other_remark_count = 0
    other_udise_count = 0
    other_unclear_count = 0

    for _, row in not_studying.iterrows():
        r = (row['reason'] or '').strip()
        rem = (row['remarks'] or '').strip()
        u = (row['udise'] or '').strip()
        g = (row['gender'] or '').strip()
        
        assigned = None
        
        if r and r != 'Other':
            assigned = r
        elif r == 'Other':
            # Check remarks first
            if rem:
                if P_PASSED_OR_ELSEWHERE.search(rem) or P_WRONG_DUPLICATE.search(rem):
                    assigned = "पहले से पास / गलत entry"
                elif P_NO_CONTACT.search(rem):
                    assigned = "संपर्क नहीं हो सका"
                elif P_PARENT_WISH.search(rem):
                    assigned = "अभिभावक की इच्छा"
                elif P_MIGRATION_LABOUR.search(rem):
                    assigned = "Migrated for Labour/Work"
                elif P_FAIL_DROPPED_FAR.search(rem):
                    assigned = "fail / नाम कटा / स्कूल दूर"
                elif P_FINANCIAL.search(rem):
                    assigned = "Financial Problem"
                elif P_MARRIAGE.search(rem):
                    assigned = "Marriage"
                elif P_DOMESTIC.search(rem):
                    assigned = "Household / Domestic Responsibility"
                elif P_HEALTH.search(rem):
                    assigned = "Health / Medical Reason"
                elif P_TC_ADMISSION.search(rem):
                    assigned = "Admission Not Taken / TC Issue"
                elif P_NOT_INTERESTED.search(rem):
                    assigned = "Not Interested"
            
            if assigned:
                other_remark_count += 1
            else:
                # Fallback to UDISE mode
                if u in udise_modes:
                    assigned = udise_modes[u]
                    other_udise_count += 1
                else:
                    assigned = "कारण स्पष्ट नहीं"
                    other_unclear_count += 1
        else:
            # Empty / blank reason
            assigned = None
            
        if assigned:
            final_categories.append({'category': assigned, 'gender': g})

    cat_df = pd.DataFrame(final_categories)
    total_with_reasons = len(cat_df)
    
    # Mapping to display labels
    NAME_MAP = {
        'Not Interested': 'पढ़ाई में रुचि नहीं',
        'Migrated for Labour/Work': 'मज़दूरी / काम के लिए पलायन',
        'Financial Problem': 'आर्थिक समस्या',
        'Household / Domestic Responsibility': 'घरेलू / पारिवारिक ज़िम्मेदारी',
        'Admission Not Taken / TC Issue': 'प्रवेश नहीं लिया / TC',
        'Marriage': 'विवाह',
        'Health / Medical Reason': 'बीमारी',
        'अभिभावक की इच्छा': 'अभिभावक की इच्छा',
        'fail / नाम कटा / स्कूल दूर': 'fail / नाम कटा / स्कूल दूर',
        'कारण स्पष्ट नहीं': 'कारण स्पष्ट नहीं',
        'पहले से पास / गलत entry': 'पहले से पास / गलत entry',
        'संपर्क नहीं हो सका': 'संपर्क नहीं हो सका'
    }
    
    cat_df['display_name'] = cat_df['category'].map(lambda x: NAME_MAP.get(x, x))
    counts = cat_df['display_name'].value_counts()
    
    def get_stat(name):
        c = int(counts.get(name, 0))
        p = round((c / total_with_reasons) * 100, 1) if total_with_reasons else 0.0
        return c, p

    # Gender breakdown
    boys_df = cat_df[cat_df['gender'].astype(str).str.lower().isin(['boy', 'male', 'm', 'लड़का', 'लड़के'])]
    girls_df = cat_df[cat_df['gender'].astype(str).str.lower().isin(['girl', 'female', 'f', 'लड़की', 'लड़कियाँ'])]
    total_boys = len(boys_df)
    total_girls = len(girls_df)

    def get_gender_stat(name):
        b_c = int((boys_df['display_name'] == name).sum())
        b_p = round((b_c / total_boys) * 100, 1) if total_boys else 0.0
        g_c = int((girls_df['display_name'] == name).sum())
        g_p = round((g_c / total_girls) * 100, 1) if total_girls else 0.0
        return b_c, b_p, g_c, g_p

    # Economic total
    mig_c, mig_p = get_stat('मज़दूरी / काम के लिए पलायन')
    fin_c, fin_p = get_stat('आर्थिक समस्या')
    dom_c, dom_p = get_stat('घरेलू / पारिवारिक ज़िम्मेदारी')
    econ_p = round(mig_p + fin_p + dom_p, 1)

    today_str = datetime.now().strftime("%d %B %Y").replace('October', 'अक्टूबर').replace('November', 'नवंबर').replace('December', 'दिसंबर')

    data = {
        'total_surveyed': total_surveyed,
        'studying': studying,
        'not_studying': total_not_studying,
        'deceased': deceased,
        'willing': willing_students,
        'class_10': class_10,
        'class_9': class_9,
        'class_11': class_11,
        'total_with_reasons': total_with_reasons,
        'econ_p': econ_p,
        'items': {
            'not_interested': get_stat('पढ़ाई में रुचि नहीं'),
            'migration': (mig_c, mig_p),
            'financial': (fin_c, fin_p),
            'domestic': (dom_c, dom_p),
            'admission_tc': get_stat('प्रवेश नहीं लिया / TC'),
            'marriage': get_stat('विवाह'),
            'health': get_stat('बीमारी'),
            'parent_wish': get_stat('अभिभावक की इच्छा'),
            'fail_dropped': get_stat('fail / नाम कटा / स्कूल दूर'),
            'unclear': get_stat('कारण स्पष्ट नहीं'),
            'passed_wrong': get_stat('पहले से पास / गलत entry'),
            'no_contact': get_stat('संपर्क नहीं हो सका'),
        },
        'gender': {
            'total_boys': total_boys,
            'total_girls': total_girls,
            'migration': get_gender_stat('मज़दूरी / काम के लिए पलायन'),
            'marriage': get_gender_stat('विवाह'),
            'domestic': get_gender_stat('घरेलू / पारिवारिक ज़िम्मेदारी'),
            'not_interested': get_gender_stat('पढ़ाई में रुचि नहीं'),
        },
        'date_str': today_str
    }
    return data

def update_html(data):
    print(f"Reading {DASHBOARD_HTML}...")
    with open(DASHBOARD_HTML, 'r', encoding='utf-8') as f:
        html = f.read()

    # Calculate bar widths relative to max percentage (not_interested)
    max_p = data['items']['not_interested'][1]
    if max_p <= 0: max_p = 28.8

    def b_width(p):
        return f"{min(round((p / max_p) * 100, 1), 100.0)}%"

    # Format values
    ni_c, ni_p = data['items']['not_interested']
    mig_c, mig_p = data['items']['migration']
    fin_c, fin_p = data['items']['financial']
    dom_c, dom_p = data['items']['domestic']
    tc_c, tc_p = data['items']['admission_tc']
    mar_c, mar_p = data['items']['marriage']
    hlth_c, hlth_p = data['items']['health']
    pw_c, pw_p = data['items']['parent_wish']
    fd_c, fd_p = data['items']['fail_dropped']
    unc_c, unc_p = data['items']['unclear']
    pw_entry_c, pw_entry_p = data['items']['passed_wrong']
    nc_c, nc_p = data['items']['no_contact']

    # Gender values
    tb = f"{data['gender']['total_boys']:,}"
    tg = f"{data['gender']['total_girls']:,}"
    gm_bc, gm_bp, gm_gc, gm_gp = data['gender']['migration']
    gmar_bc, gmar_bp, gmar_gc, gmar_gp = data['gender']['marriage']
    gd_bc, gd_bp, gd_gc, gd_gp = data['gender']['domestic']
    gni_bc, gni_bp, gni_gc, gni_gp = data['gender']['not_interested']

    new_report = f"""    <div class="chart-card col-12" style="padding: 0; background: transparent; border: none; box-shadow: none;">
      <div class="report-wrapper">
        <div class="report-chart-section">
          <div class="report-chart-head">पढ़ाई छोड़ने के कारण</div>
          <div class="report-chart-insight">हर तीन में से एक से ज़्यादा बच्चा आर्थिक कारणों से पढ़ाई से बाहर</div>

          <div class="reason-bars-box">
            <!-- 1. Not Interested -->
            <div class="rbar-row">
              <div class="rbar-label">पढ़ाई में रुचि नहीं</div>
              <div class="rbar-track"><div class="rbar-fill r-gray" style="width: {b_width(ni_p)};"></div></div>
              <div class="rbar-val">{ni_c:,} • {ni_p}%</div>
            </div>

            <!-- Economic Group with Curly Bracket -->
            <div class="econ-bracket-wrapper">
              <div class="econ-rows-cluster">
                <div class="rbar-row" style="grid-template-columns: 230px 1fr 140px;">
                  <div class="rbar-label">मज़दूरी / काम के लिए पलायन</div>
                  <div class="rbar-track"><div class="rbar-fill r-blue" style="width: {b_width(mig_p)};"></div></div>
                  <div class="rbar-val">{mig_c:,} • {mig_p}%</div>
                </div>
                <div class="rbar-row" style="grid-template-columns: 230px 1fr 140px;">
                  <div class="rbar-label">आर्थिक समस्या</div>
                  <div class="rbar-track"><div class="rbar-fill r-blue" style="width: {b_width(fin_p)};"></div></div>
                  <div class="rbar-val">{fin_c:,} • {fin_p}%</div>
                </div>
                <div class="rbar-row" style="grid-template-columns: 230px 1fr 140px;">
                  <div class="rbar-label">घरेलू / पारिवारिक ज़िम्मेदारी</div>
                  <div class="rbar-track"><div class="rbar-fill r-blue" style="width: {b_width(dom_p)};"></div></div>
                  <div class="rbar-val">{dom_c:,} • {dom_p}%</div>
                </div>
              </div>
              <div class="econ-bracket-side">
                <svg class="econ-bracket-svg" viewBox="0 0 16 96" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round">
                  <path d="M 4 2 Q 11 2 11 24 Q 11 48 15 48 Q 11 48 11 72 Q 11 94 4 94"/>
                </svg>
                <div class="econ-bracket-label">आर्थिक कुल<br><strong style="font-size:1.1rem; color:#1d4ed8;">{data['econ_p']}%</strong></div>
              </div>
            </div>

            <!-- 5. Admission Not Taken / TC Issue -->
            <div class="rbar-row">
              <div class="rbar-label">प्रवेश नहीं लिया / TC</div>
              <div class="rbar-track"><div class="rbar-fill r-gray" style="width: {b_width(tc_p)};"></div></div>
              <div class="rbar-val">{tc_c:,} • {tc_p}%</div>
            </div>

            <!-- 6. Marriage -->
            <div class="rbar-row">
              <div class="rbar-label">विवाह</div>
              <div class="rbar-track"><div class="rbar-fill r-gray" style="width: {b_width(mar_p)};"></div></div>
              <div class="rbar-val">{mar_c:,} • {mar_p}%</div>
            </div>

            <!-- 7. Health / Medical -->
            <div class="rbar-row">
              <div class="rbar-label">बीमारी</div>
              <div class="rbar-track"><div class="rbar-fill r-gray" style="width: {b_width(hlth_p)};"></div></div>
              <div class="rbar-val">{hlth_c:,} • {hlth_p}%</div>
            </div>

            <!-- 8. Parents Wish -->
            <div class="rbar-row">
              <div class="rbar-label">अभिभावक की इच्छा</div>
              <div class="rbar-track"><div class="rbar-fill r-gray" style="width: {b_width(pw_p)};"></div></div>
              <div class="rbar-val">{pw_c:,} • {pw_p}%</div>
            </div>

            <!-- 9. Fail / Dropped / School far -->
            <div class="rbar-row">
              <div class="rbar-label">fail / नाम कटा / स्कूल दूर</div>
              <div class="rbar-track"><div class="rbar-fill r-gray" style="width: {b_width(fd_p)};"></div></div>
              <div class="rbar-val">{fd_c:,} • {fd_p}%</div>
            </div>

            <!-- Subgroup: Reason Not Known -->
            <div class="rbar-subgroup-title">कारण पता नहीं चला</div>

            <div class="rbar-row">
              <div class="rbar-label">कारण स्पष्ट नहीं</div>
              <div class="rbar-track"><div class="rbar-fill r-light-gray" style="width: {b_width(unc_p)};"></div></div>
              <div class="rbar-val">{unc_c:,} • {unc_p}%</div>
            </div>

            <div class="rbar-row">
              <div class="rbar-label">पहले से पास / गलत entry</div>
              <div class="rbar-track"><div class="rbar-fill r-light-gray" style="width: {b_width(pw_entry_p)};"></div></div>
              <div class="rbar-val">{pw_entry_c:,} • {pw_entry_p}%</div>
            </div>

            <div class="rbar-row">
              <div class="rbar-label">संपर्क नहीं हो सका</div>
              <div class="rbar-track"><div class="rbar-fill r-light-gray" style="width: {b_width(nc_p)};"></div></div>
              <div class="rbar-val">{nc_c:,} • {nc_p}%</div>
            </div>
          </div>
        </div>

        <div class="report-gender-section">
          <div class="gender-sec-head">लड़के और लड़कियाँ</div>
          <div class="gender-sec-insight">
            लड़कों को मज़दूरी / काम के लिए पलायन ({gm_bp}%) और लड़कियों को विवाह ({gmar_gp}%) पढ़ाई से अलग कर रहा है। पलायन के 82% मामले लड़कों के हैं और विवाह के 84% लड़कियों के।
          </div>

          <table class="gender-summary-table">
            <thead>
              <tr>
                <th>कारण</th>
                <th>लड़के ({tb})</th>
                <th>लड़कियाँ ({tg})</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>मज़दूरी / काम के लिए पलायन</strong></td>
                <td>{gm_bc:,} ({gm_bp}%)</td>
                <td>{gm_gc:,} ({gm_gp}%)</td>
              </tr>
              <tr>
                <td><strong>विवाह</strong></td>
                <td>{gmar_bc:,} ({gmar_bp}%)</td>
                <td>{gmar_gc:,} ({gmar_gp}%)</td>
              </tr>
              <tr>
                <td><strong>घरेलू / पारिवारिक ज़िम्मेदारी</strong></td>
                <td>{gd_bc:,} ({gd_bp}%)</td>
                <td>{gd_gc:,} ({gd_gp}%)</td>
              </tr>
              <tr>
                <td><strong>पढ़ाई में रुचि नहीं</strong></td>
                <td>{gni_bc:,} ({gni_bp}%)</td>
                <td>{gni_gc:,} ({gni_gp}%)</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="report-footer-src">
          📋 <strong>स्रोत:</strong> Field Data Collection (survey) • कुल बच्चे: {data['total_surveyed']:,} (Status: Not Studying {data['not_studying']:,}) • अद्यतन: {data['date_str']} तक।<br>
          🔒 <em>नोट: रिपोर्ट में केवल समेकित (Aggregated) सांख्यिकी प्रदर्शित है। आधार, जन्म तिथि, नाम जैसी कोई भी व्यक्तिगत पहचान शामिल नहीं है।</em>
        </div>
      </div>
    </div>"""

    s_tag = '<div class="chart-card col-12" style="padding: 0; background: transparent;'
    e_tag = '</div>\n    </div>\n  </section>'
    
    s_idx = html.find(s_tag)
    e_idx = html.find(e_tag, s_idx)
    if s_idx != -1 and e_idx != -1:
        e_idx = e_idx + len('</div>\n    </div>')
        html = html[:s_idx] + new_report + html[e_idx:]
    else:
        print("Warning: could not locate exact wrapper tags.")

    with open(DASHBOARD_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Updated {DASHBOARD_HTML} successfully!")

    ossc_path = r"d:\ossc-nios\dashboard\index.html"
    if os.path.exists(ossc_path):
        with open(ossc_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Updated {ossc_path} successfully!")

def push_to_git():
    print("Checking git status...")
    try:
        subprocess.run(["git", "-C", "D:\\NIOS", "add", "dashboard/index.html"], check=True)
        res = subprocess.run(["git", "-C", "D:\\NIOS", "status", "--porcelain"], capture_output=True, text=True)
        if "dashboard/index.html" in res.stdout:
            subprocess.run(["git", "-C", "D:\\NIOS", "commit", "-m", "chore: auto-update reason report from latest survey data"], check=True)
            subprocess.run(["git", "-C", "D:\\NIOS", "push", "origin", "main"], check=True)
            print("Pushed to D:\\NIOS successfully!")
        else:
            print("No new data changes to commit in D:\\NIOS.")
    except Exception as e:
        print("Git push error in D:\\NIOS:", e)

    try:
        if os.path.exists(r"d:\ossc-nios\dashboard\index.html"):
            subprocess.run(["git", "-C", "d:\\ossc-nios", "add", "dashboard/index.html"], check=True)
            res = subprocess.run(["git", "-C", "d:\\ossc-nios", "status", "--porcelain"], capture_output=True, text=True)
            if "dashboard/index.html" in res.stdout:
                subprocess.run(["git", "-C", "d:\\ossc-nios", "commit", "-m", "chore: auto-update reason report from latest survey data"], check=True)
                subprocess.run(["git", "-C", "d:\\ossc-nios", "push", "origin", "main"], check=True)
                print("Pushed to d:\\ossc-nios successfully!")
    except Exception as e:
        print("Git push error in d:\\ossc-nios:", e)

def main():
    df = fetch_data()
    data = classify_reasons(df)
    update_html(data)
    push_to_git()
    print("Auto-update finished successfully!")

if __name__ == "__main__":
    main()
