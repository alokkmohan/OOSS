# Out-of-School Student — Field Data Collection: पूरा Flow

**Link:** https://ooss.dataimpact.in/collect/
**Data kaha jaata hai:** Google Sheet "Out of School Student Status - Raw data"
(1WWifakyqkBoA922wu16bCYBZTjK2NyrxkVC_6eLBIV0) → tab **"Field Data Collection"**

---

## Step 1 — Coordinator ka naam (optional)

"Your Name / Designation (Collected By)" field mein apna naam/designation likhna
(jaise "Ramesh Kumar, CRC Nakur") — yeh har submission ke saath save hota hai.

## Step 2 — District चुनें (Required)

Dropdown se District select karo. Poori list (~90,053 students, 75 districts)
load hone mein thoda time lagta hai (batches mein aata hai, progress dikhta hai).

## Step 3 — School चुनें (Optional)

District select karne ke baad "School" dropdown mein us District ke saare schools
(UDISE Code — School Name format mein) dikhte hain. Khali chhod sakte ho — tab
poore District ke students dikhenge.

## Step 4 — Student list (table)

Table mein District/School ke hisaab se filtered students dikhte hain, columns:

| Column | Matlab |
|---|---|
| Block Name | Block |
| UDISE Code | School ka UDISE code |
| School Name | School ka naam |
| Student PEN | Unique student ID |
| Student Name | Student ka naam |
| Sex | Gender |
| Mobile No | Contact number |
| Mother Name | Maa ka naam |
| Father Name | Pita ka naam |
| Class | Last class |
| → स्थिति | **Yahan status bharo/update karo** |

Agar student ka status pehle se bhara hai, badge dikhega (Studying / Not
Studying / Deceased). Nahi bhara to "Not recorded" dikhega.

## Step 5 — Status bharna (last column ka button "वर्तमान स्थिति")

Button click karne par ek popup khulta hai jisme decision-tree jaisa flow hai:

### Q1: क्या छात्र वर्तमान में पढ़ रहा है?

- **पढ़ रहा है (Studying)** → seedha Save kar sakte ho, koi aur sawaal nahi.
- **नहीं पढ़ रहा है (Not Studying)** → Q2 khulta hai.
- **मृत्यु हो गई (Deceased)** → seedha Save kar sakte ho.

### Q2 (sirf "Not Studying" par): क्या छात्र आगे पढ़ने के लिए इच्छुक है?

- **हाँ (Yes)** → Q3 (Mode) khulta hai.
- **नहीं (No)** → Q4 (Reason) khulta hai.

### Q3 (sirf "हाँ" par): अध्ययन का माध्यम

- **नियमित विद्यालय (Regular)**
- **NIOS (मुक्त विद्यालय)**

### Q4 (sirf "नहीं" par): न पढ़ने का कारण (dropdown)

- विवाह (Marriage)
- मजदूरी/काम के लिए पलायन (Migrated for Labour/Work)
- आर्थिक समस्या (Financial Problem)
- घरेलू जिम्मेदारी (Household / Domestic Responsibility)
- स्वास्थ्य/चिकित्सा कारण (Health / Medical Reason)
- प्रवेश नहीं लिया / टीसी समस्या (Admission Not Taken / TC Issue)
- रुचि नहीं है (Not Interested)
- अन्य (Other)

### टिप्पणी (Remarks) — Optional

Koi bhi extra note yahan likh sakte ho.

### Save

**"सहेजें" (Save)** dabane par entry "Field Data Collection" tab mein chali
jaati hai. **Same student ke liye dubara bharne par purana entry update ho
jaata hai** (naya duplicate row nahi banta) — matching Student PEN se hoti hai.

---

## Poora Flow Diagram (text form)

```
District (required)
  └─ School (optional filter)
       └─ Student table
            └─ "वर्तमान स्थिति" button click
                 └─ Q1: क्या छात्र वर्तमान में पढ़ रहा है?
                      ├─ पढ़ रहा है ────────────────────────► Save
                      ├─ मृत्यु हो गई ──────────────────────► Save
                      └─ नहीं पढ़ रहा है
                           └─ Q2: आगे पढ़ने के लिए इच्छुक?
                                ├─ हाँ
                                │   └─ Q3: माध्यम (Regular/NIOS) ► Save
                                └─ नहीं
                                    └─ Q4: कारण (dropdown) ──► Save
```

---

## Technical note (sirf reference ke liye)

- Frontend: `collect/index.html` (GitHub Pages, `ooss.dataimpact.in/collect/`)
- Backend: Google Apps Script (`apps_script/Code.gs`), JSON API
  (`?action=districts/schools/students/studentCount/allStudentsChunk/summary`,
  aur POST `submit`)
- Student list source: Sheet tab "Out of School Student Status - Raw data"
- Submissions destination: Sheet tab "Field Data Collection" (auto-banti
  hai pehli submission par), PEN se upsert (update-or-insert)
- Live dashboard (isi data se): `ooss.dataimpact.in/dashboard/`
