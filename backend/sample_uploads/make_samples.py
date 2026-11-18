"""Creates fictional demonstration files for Method B (file-based ingestion). Run: python3 make_samples.py"""
import json, io
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

here = Path(__file__).parent

# 1) CSV – patient demographics. Covers: matched by ID (adds info), new patient, uncertain (name only), ID/name mismatch, in-file duplicate, invalid row.
(here / 'patients_import.csv').write_text("""record_type,patient_id,first_name,last_name,dob,gender,mobile,email,department,primary_condition,allergies,medications,care_plan
patient,PT-1005,Olivia,Green,,Female,07700 900555,,General Medicine,Asthma,Aspirin,Montelukast 10 mg nightly,Annual asthma review and inhaler technique check
patient,PT-2001,Fiona,Walker,1984-03-12,Female,07700 900611,fiona.walker@example.com,Cardiology,Hypertension,Penicillin,Ramipril 2.5 mg daily,Blood pressure monitoring and 6-monthly review
patient,,Emma,Parker,,Female,07700 900622,,General Medicine,Type 2 diabetes mellitus,,,
patient,PT-1003,Michael,Smith,1971-05-02,Male,,,Cardiology,Atrial fibrillation,,,
patient,PT-2001,Fiona,Walker,1984-03-12,Female,07700 900611,fiona.walker@example.com,Cardiology,Hypertension,Penicillin,Ramipril 2.5 mg daily,
patient,,Tariq,,1990-02-30,Male,,,Neurology,Migraine,,,
""")

# 2) JSON – clinical records for existing patients (consultation, diagnostic report, appointment, referral, task, history) and a new patient + their consultation.
json.dump({
  "consultations": [
    {"patient_id": "PT-1002", "date": "2026-11-10", "doctor": "u-d1", "notes": "Review of glycaemic control. Patient reports improved adherence to diet plan. No hypoglycaemic episodes.", "diagnosis": "Type 2 diabetes mellitus", "plan": "Repeat HbA1c in 3 months; continue metformin", "follow_up": "2027-02-10"},
    {"patient_id": "PT-2001", "date": "2026-11-12", "doctor": "u-d1", "notes": "Initial cardiology assessment for hypertension. Home BP diary requested."}
  ],
  "diagnostic_reports": [
    {"patient_id": "PT-1007", "test_name": "Lipid Profile", "date": "2026-11-09", "summary": "Total cholesterol 5.1 mmol/L; LDL 3.1 mmol/L; HDL 1.4 mmol/L (synthetic imported report)."}
  ],
  "appointments": [
    {"patient_id": "PT-1006", "date": "2027-02-02", "time": "10:30", "type": "Follow-up review", "status": "Scheduled"}
  ],
  "referrals": [
    {"patient_id": "PT-1008", "referred_to": "Renal clinic", "reason": "CKD stage 3 – annual specialist review", "status": "Pending"}
  ],
  "tasks": [
    {"patient_id": "PT-1013", "title": "Confirm repeat prescription collection", "due": "2026-12-01"}
  ],
  "medical_history": [
    {"patient_id": "PT-1009", "date": "2026-10-20", "type": "Hospital Visit", "title": "Emergency department attendance – severe migraine", "detail": "Discharged same day (synthetic)."}
  ],
  "patients": [
    {"patient_id": "PT-2001", "first_name": "Fiona", "last_name": "Walker", "dob": "1984-03-12", "gender": "Female", "department": "Cardiology",
     "primary_condition": "Hypertension", "allergies": "Penicillin", "medications": "Ramipril 2.5 mg daily", "mobile": "07700 900611"}
  ]
}, open(here / 'clinical_records.json', 'w'), indent=2)

# 3) PDF with a text layer – diagnostic report for an existing patient (matched by ID, name consistent)
def report_pdf(path, lines):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont('Helvetica-Bold', 16); c.drawString(60, y, lines[0]); y -= 34
    c.setFont('Helvetica', 11)
    for l in lines[1:]:
        c.drawString(60, y, l); y -= 18
    c.save()

report_pdf(here / 'PT-1002_HbA1c_report.pdf', [
 'Fictional Diagnostics Laboratory – Demonstration Report',
 'Patient ID: PT-1002',
 'Patient Name: Emma Parker',
 'Report Type: HbA1c',
 'Report Date: 12/11/2026',
 'Requested by: Dr. Sarah Wilson',
 '',
 'Findings:',
 'HbA1c 48 mmol/mol (reference 20-42). Fasting glucose 6.4 mmol/L.',
 'Synthetic demonstration report - not real patient data.',
 '',
 'Allergies: None recorded',
 'Medications: Metformin 500 mg twice daily',
])
# 4) PDF without patient ID – name only → uncertain match, manual review required
report_pdf(here / 'unmatched_ECG_report.pdf', [
 'Fictional Cardiology Unit – Demonstration Report',
 'Patient Name: Michael Reed',
 'Report Type: ECG',
 'Report Date: 2026-11-11',
 '',
 'Findings:',
 'Regular rhythm, rate 74 bpm. No acute change described (synthetic).',
])
# 5) Scanned-style PDF (image only, no text layer) → OCR path
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (1240, 700), 'white')
    dr = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 34)
    except Exception:
        f = ImageFont.load_default()
    txt = ['Patient ID: PT-1010', 'Patient Name: Grace Ellis', 'Report Type: MRI', 'Report Date: 2026-11-13', 'Findings:', 'No acute findings described (synthetic scan).']
    for i, t in enumerate(txt):
        dr.text((60, 50 + i * 70), t, fill='black', font=f)
    img.save(here / 'scanned_MRI_report.pdf', 'PDF', resolution=150)
except Exception as e:
    print('skipped scanned sample:', e)
print('samples written')
