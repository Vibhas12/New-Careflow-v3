"""Builds the one-click demo datasets shown on the Data Import screen (fictional data only).

Run:  python backend/demo_datasets/make_demo_datasets.py

Each dataset is a CSV *template*. Dates are written relative to the day the dataset is loaded:
  {T}    = today      {T+7} = 7 days from today      {T-8} = 8 days ago
so the care-gap rules (missed appointments, overdue tasks, pending referrals ...) behave the same on any demo day.
Dates of birth stay absolute.

The four datasets describe the SAME patients (PT-3001 … PT-3010) at different points in time, so loading them
in order shows each patient's priority moving: 1 Baseline → 2 Escalation → 3 Recovery. Dataset 4 exercises the
review safeguards (uncertain matches, invalid rows, duplicates).

record_type=priority rows change a patient's priority. They need `priority` (High / Medium / Low) and a mandatory
`reason`. They are shown as "current → new" in the review step and are written to the immutable priority history
only when the Care Coordinator confirms the import.
"""
import csv, io, json
from pathlib import Path

HERE = Path(__file__).parent

COLS = ['record_type', 'patient_id', 'first_name', 'last_name', 'dob', 'gender', 'mobile', 'email', 'address', 'emergency_contact_name',
        'emergency_contact_number', 'department', 'primary_condition', 'secondary_conditions', 'allergies', 'medications', 'care_plan', 'doctor',
        'date', 'time', 'type', 'status', 'notes', 'diagnosis', 'plan', 'follow_up', 'test_name', 'summary', 'abnormal', 'referred_to', 'reason',
        'title', 'priority']


def P(pid, fn, ln, dob, gender, mobile, email, address, ecn, ecp, dept, cond, sec, alg, meds, plan, doc):
    return dict(record_type='patient', patient_id=pid, first_name=fn, last_name=ln, dob=dob, gender=gender, mobile=mobile, email=email, address=address,
                emergency_contact_name=ecn, emergency_contact_number=ecp, department=dept, primary_condition=cond, secondary_conditions=sec,
                allergies=alg, medications=meds, care_plan=plan, doctor=doc)


def appt(pid, doc, date, time, typ, status, notes=''):
    return dict(record_type='appointment', patient_id=pid, doctor=doc, date=date, time=time, type=typ, status=status, notes=notes)


def consult(pid, doc, date, notes, diagnosis='', plan='', follow_up=''):
    return dict(record_type='consultation', patient_id=pid, doctor=doc, date=date, notes=notes, diagnosis=diagnosis, plan=plan, follow_up=follow_up)


def test(pid, doc, date, name, summary, abnormal):
    return dict(record_type='test', patient_id=pid, doctor=doc, date=date, test_name=name, summary=summary, abnormal=abnormal)


def referral(pid, doc, date, to, reason, status='Pending'):
    return dict(record_type='referral', patient_id=pid, doctor=doc, date=date, status=status, referred_to=to, reason=reason)


def hist(pid, date, typ, title):
    return dict(record_type='history', patient_id=pid, date=date, type=typ, title=title)


def task(pid, date, title):
    return dict(record_type='task', patient_id=pid, date=date, title=title)


def med(pid, meds):
    return dict(record_type='medication', patient_id=pid, medications=meds)


def pri(pid, level, reason):
    return dict(record_type='priority', patient_id=pid, priority=level, reason=reason)


PATIENTS = [
    P('PT-3001', 'Aarav', 'Sharma', '1968-03-14', 'Male', '+91 98200 11001', 'aarav.sharma@example.com', '12 MG Road, Pune', 'Meera Sharma', '+91 98200 11002',
      'Cardiology', 'Hypertension', 'Type 2 diabetes mellitus', 'Penicillin', 'Amlodipine 5 mg daily; Metformin 500 mg twice daily', 'BP monitoring and 3-monthly cardiology review', 'u-d1'),
    P('PT-3002', 'Priyanka', 'Iyer', '1985-07-22', 'Female', '+91 98450 22001', 'priyanka.iyer@example.com', '45 Anna Salai, Chennai', 'Raghav Iyer', '+91 98450 22002',
      'General Medicine', 'Hypothyroidism', '', 'None known', 'Levothyroxine 50 mcg daily', 'Thyroid function test every 6 months', 'u-d1'),
    P('PT-3003', 'Rohan', 'Mehta', '1979-11-05', 'Male', '+91 99300 33001', 'rohan.mehta@example.com', '8 Linking Road, Mumbai', 'Kavita Mehta', '+91 99300 33002',
      'Neurology', 'Migraine with aura', '', 'Ibuprofen', 'Propranolol 40 mg twice daily', 'Headache diary and neurology follow-up', 'u-d2'),
    P('PT-3004', 'Ananya', 'Reddy', '1962-01-30', 'Female', '+91 98480 44001', 'ananya.reddy@example.com', '221 Banjara Hills, Hyderabad', 'Vikram Reddy', '+91 98480 44002',
      'Oncology', 'Breast cancer - on adjuvant therapy', 'Osteopenia', 'Sulfa drugs', 'Tamoxifen 20 mg daily', 'Oncology review every 3 months with imaging', 'u-d3'),
    P('PT-3005', 'Vikram', 'Singh', '1955-09-12', 'Male', '+91 98110 55001', 'vikram.singh@example.com', '17 Sector 15, Chandigarh', 'Harpreet Kaur', '+91 98110 55002',
      'Orthopedics', 'Osteoarthritis of right knee', 'Hypertension', 'None known', 'Paracetamol 1 g as required', 'Physiotherapy and review for knee replacement', 'u-d4'),
    P('PT-3006', 'Kavya', 'Nair', '1992-04-18', 'Female', '+91 94470 66001', 'kavya.nair@example.com', '3 MG Road, Kochi', 'Suresh Nair', '+91 94470 66002',
      'Mental Health', 'Generalised anxiety disorder', '', 'None known', 'Sertraline 50 mg daily', 'CBT sessions and 6-weekly psychiatric review', 'u-d5'),
    P('PT-3007', 'Arjun', 'Gupta', '1975-12-02', 'Male', '+91 98100 77001', 'arjun.gupta@example.com', '56 Lajpat Nagar, New Delhi', 'Neha Gupta', '+91 98100 77002',
      'Cardiology', 'Coronary artery disease - post angioplasty', 'Hyperlipidaemia', 'Aspirin (gastric intolerance)', 'Clopidogrel 75 mg daily; Atorvastatin 40 mg nightly',
      'Cardiac rehab and lipid monitoring', 'u-d1'),
    P('PT-3008', 'Sneha', 'Patil', '1988-06-25', 'Female', '+91 98220 88001', 'sneha.patil@example.com', '9 FC Road, Pune', 'Amol Patil', '+91 98220 88002',
      'General Medicine', 'Iron-deficiency anaemia', '', 'None known', 'Ferrous sulfate 200 mg daily', 'Repeat haemoglobin in 6 weeks', 'u-d1'),
    P('PT-3009', 'Rajesh', 'Kumar', '1958-08-08', 'Male', '+91 94430 99001', 'rajesh.kumar@example.com', '14 Gandhi Nagar, Coimbatore', 'Lakshmi Kumar', '+91 94430 99002',
      'Neurology', 'Parkinson disease', '', 'Codeine', 'Levodopa/carbidopa 100/25 mg three times daily', 'Movement-disorder clinic review every 4 months', 'u-d2'),
    P('PT-3010', 'Diya', 'Banerjee', '1996-02-14', 'Female', '+91 98300 10101', 'diya.banerjee@example.com', '27 Park Street, Kolkata', 'Sourav Banerjee', '+91 98300 10102',
      'General Medicine', 'Asthma', 'Allergic rhinitis', 'Dust mites; Pollen', 'Salbutamol inhaler as required; Budesonide inhaler twice daily',
      'Annual asthma review and inhaler technique check', 'u-d1'),
]

# 1 ── Baseline: the supplied sample (dates made relative) + an initial priority for each patient
BASELINE = PATIENTS + [
    appt('PT-3001', 'u-d1', '{T+7}', '10:30', 'Follow-up review', 'Scheduled', 'BP review'),
    appt('PT-3003', 'u-d2', '{T+9}', '11:00', 'Follow-up review', 'Confirmed'),
    appt('PT-3005', 'u-d4', '{T-8}', '09:30', 'Initial assessment', 'Missed', 'Patient did not attend'),
    appt('PT-3006', 'u-d5', '{T+14}', '15:00', 'Follow-up review', 'Scheduled'),
    consult('PT-3001', 'u-d1', '{T-13}', 'BP 152/94 at clinic. Reports occasional headaches. Good adherence to amlodipine.',
            'Hypertension - suboptimally controlled', 'Increase amlodipine to 10 mg; home BP diary', '{T+17}'),
    consult('PT-3007', 'u-d1', '{T-21}', 'Six weeks post angioplasty. No chest pain on exertion. Attending cardiac rehab.',
            'Coronary artery disease - stable', 'Continue dual therapy; repeat lipid profile', '{T+71}'),
    test('PT-3002', 'u-d1', '{T-10}', 'Thyroid Function Test', 'TSH 6.8 mIU/L (raised); Free T4 11 pmol/L (synthetic result)', 'yes'),
    test('PT-3008', 'u-d1', '{T-6}', 'Full Blood Count', 'Haemoglobin 9.6 g/dL (low); MCV 72 fL (synthetic result)', 'yes'),
    test('PT-3004', 'u-d3', '{T-15}', 'Mammogram', 'No new suspicious lesions (synthetic result)', 'no'),
    referral('PT-3005', 'u-d4', '{T-29}', 'Physiotherapy', 'Knee osteoarthritis - strengthening programme'),
    referral('PT-3009', 'u-d2', '{T-17}', 'Speech and language therapy', 'Mild dysarthria'),
    hist('PT-3007', '{T-64}', 'Surgery', 'Coronary angioplasty with stent (LAD)'),
    hist('PT-3010', '{T-108}', 'Hospital Visit', 'Emergency visit - acute asthma attack'),
    task('PT-3005', '{T+2}', 'Call patient to rebook missed orthopaedic appointment'),
    task('PT-3010', '{T+6}', 'Confirm inhaler refill collection'),
    # initial priorities (new patients start at Medium; only differing values are listed)
    pri('PT-3002', 'High', 'Raised TSH on latest thyroid test - dose review needed'),
    pri('PT-3005', 'High', 'Missed orthopaedic assessment and physiotherapy referral still pending'),
    pri('PT-3008', 'High', 'Low haemoglobin (9.6 g/dL) - response to iron therapy must be checked'),
    pri('PT-3009', 'High', 'Speech and language therapy referral outstanding for over two weeks'),
    pri('PT-3003', 'Low', 'Stable on propranolol - routine neurology follow-up only'),
    pri('PT-3006', 'Low', 'Stable on sertraline - routine review booked'),
    pri('PT-3007', 'Low', 'Stable after angioplasty - attending cardiac rehab'),
    pri('PT-3010', 'Low', 'Asthma controlled - annual review only'),
]

# 2 ── Escalation: new results and events for the same patients push priority UP
ESCALATION = [
    consult('PT-3001', 'u-d1', '{T-1}', 'Home BP diary averaging 168/102 despite amlodipine 10 mg. New ankle swelling.',
            'Hypertension - uncontrolled', 'Add telmisartan 40 mg; renal function and urine ACR', '{T+7}'),
    test('PT-3001', 'u-d1', '{T-1}', 'Renal Function', 'eGFR 52 mL/min (reduced); creatinine 128 umol/L (synthetic result)', 'yes'),
    med('PT-3001', 'Telmisartan 40 mg daily'),
    pri('PT-3001', 'High', 'Uncontrolled blood pressure with reduced kidney function on new results'),

    test('PT-3003', 'u-d2', '{T-2}', 'MRI Brain', 'New T2 hyperintensity in left parietal lobe - correlate clinically (synthetic result)', 'yes'),
    pri('PT-3003', 'High', 'New lesion on MRI - urgent neurology review'),

    test('PT-3004', 'u-d3', '{T-3}', 'CT Chest', 'Two new sub-centimetre pulmonary nodules (synthetic result)', 'yes'),
    pri('PT-3004', 'High', 'New pulmonary nodules on CT during adjuvant therapy'),

    hist('PT-3006', '{T-5}', 'Hospital Visit', 'Emergency visit - panic attack with chest pain (cardiac cause excluded)'),
    referral('PT-3006', 'u-d5', '{T-10}', 'Community crisis team', 'Escalating anxiety symptoms after emergency attendance'),
    task('PT-3006', '{T-2}', 'Safety-plan check-in call'),
    pri('PT-3006', 'High', 'Emergency attendance and crisis-team referral not yet picked up'),

    consult('PT-3007', 'u-d1', '{T-2}', 'One week of exertional chest tightness relieved by rest. Adherent to clopidogrel and atorvastatin.',
            'Coronary artery disease - possible recurrent angina', 'Urgent exercise ECG; GTN spray as required', '{T+5}'),
    test('PT-3007', 'u-d1', '{T-1}', 'Lipid Profile', 'LDL 4.2 mmol/L (raised) on atorvastatin 40 mg (synthetic result)', 'yes'),
    pri('PT-3007', 'High', 'New exertional chest pain and raised LDL after angioplasty'),

    hist('PT-3010', '{T-4}', 'Hospital Visit', 'Emergency visit - moderate asthma exacerbation'),
    med('PT-3010', 'Prednisolone 40 mg daily for 5 days'),
    appt('PT-3010', 'u-d1', '{T+1}', '16:00', 'Asthma review', 'Scheduled', 'Post-exacerbation review'),
    pri('PT-3010', 'Medium', 'Second asthma exacerbation this year - review needed this week'),

    # already High after the baseline → shown as "no change" and skipped
    pri('PT-3005', 'High', 'Still awaiting physiotherapy and rebooked assessment'),
]

# 3 ── Recovery: follow-ups completed and results back in range bring priority DOWN
RECOVERY = [
    appt('PT-3001', 'u-d1', '{T}', '10:30', 'Follow-up review', 'Completed', 'BP 132/84 on telmisartan + amlodipine'),
    test('PT-3001', 'u-d1', '{T}', 'Renal Function', 'eGFR 61 mL/min (stable); creatinine 104 umol/L (synthetic result)', 'no'),
    pri('PT-3001', 'Medium', 'BP now controlled and kidney function stable - keep monitoring'),

    test('PT-3002', 'u-d1', '{T-1}', 'Thyroid Function Test', 'TSH 2.4 mIU/L (within range) after dose increase (synthetic result)', 'no'),
    med('PT-3002', 'Levothyroxine 75 mcg daily'),
    pri('PT-3002', 'Low', 'TSH back in range after dose adjustment'),

    test('PT-3003', 'u-d2', '{T}', 'MRI Brain', 'Repeat scan: lesion unchanged, appearance consistent with migraine-related change (synthetic result)', 'no'),
    pri('PT-3003', 'Medium', 'Repeat MRI stable - routine neurology follow-up'),

    appt('PT-3005', 'u-d4', '{T-1}', '10:00', 'Initial assessment', 'Completed', 'Rebooked assessment attended'),
    pri('PT-3005', 'Medium', 'Missed assessment now completed; physiotherapy referral still awaited'),

    appt('PT-3006', 'u-d5', '{T-1}', '12:00', 'Crisis team assessment', 'Completed', 'Safety plan agreed'),
    pri('PT-3006', 'Medium', 'Seen by crisis team, safety plan in place'),

    test('PT-3007', 'u-d1', '{T-1}', 'Exercise ECG', 'No inducible ischaemia at 10 METs (synthetic result)', 'no'),
    pri('PT-3007', 'Low', 'Exercise ECG normal and symptoms settled'),

    test('PT-3008', 'u-d1', '{T-1}', 'Full Blood Count', 'Haemoglobin 11.9 g/dL (improving); MCV 80 fL (synthetic result)', 'no'),
    pri('PT-3008', 'Medium', 'Haemoglobin improving on oral iron'),

    appt('PT-3010', 'u-d1', '{T}', '11:00', 'Asthma review', 'Completed', 'Peak flow back to 90% of best'),
    pri('PT-3010', 'Low', 'Exacerbation resolved; inhaler technique checked'),
]

# 4 ── Data-quality checks: every row exercises a review safeguard
EDGE = [
    P('PT-3011', 'Ishaan', 'Verma', '1990-05-20', 'Male', '+91 98710 11011', 'ishaan.verma@example.com', '4 Civil Lines, Jaipur', 'Pooja Verma', '+91 98710 11012',
      'General Medicine', 'Type 1 diabetes mellitus', '', 'None known', 'Insulin glargine 18 units nightly; Insulin aspart with meals',
      'Diabetes nurse review in 2 weeks; HbA1c in 3 months', 'u-d1'),
    hist('PT-3011', '{T-9}', 'Hospital Visit', 'Admission - diabetic ketoacidosis at diagnosis'),
    pri('PT-3011', 'High', 'Newly diagnosed after DKA admission - close follow-up needed'),          # new patient + priority in one file
    P('PT-3002', 'Priyanka', 'Iyer', '1985-07-23', 'Female', '', '', '', '', '', 'General Medicine', '', 'Vitamin D deficiency', '', '', '', ''),  # DOB differs → needs review
    dict(consult('', 'u-d2', '{T-1}', 'Telephone review: aura episodes reduced to one per month.', 'Migraine with aura', 'Continue propranolol'),
         first_name='Rohan', last_name='Mehta', dob='1979-11-05'),                                  # no ID, name + DOB only → needs review
    pri('PT-3004', 'Urgent', 'Oncologist asked for faster review'),                                 # invalid value
    pri('PT-3009', 'Low', ''),                                                                       # reason missing
    pri('PT-9999', 'High', 'Unknown patient reference'),                                             # patient not found
    pri('PT-3008', 'High', 'Fatigue worsening'),
    pri('PT-3008', 'Low', 'Second row for the same patient in this file'),                           # only one change per patient per file
    test('PT-3001', 'u-d1', '31/02/2026', 'HbA1c', 'HbA1c 58 mmol/mol (synthetic result)', 'yes'),   # impossible date
    appt('PT-3009', 'u-d2', '{T+2}', '14:00', 'Movement-disorder clinic', 'Scheduled'),             # unconfirmed within 3 days → care gap
]

DATASETS = [
    dict(id='baseline', file='01_baseline.csv', title='1 · Baseline – 10 new patients',
         summary='Creates PT-3001 … PT-3010 with appointments, notes, results, referrals and tasks, and sets an initial priority for each patient.',
         effect='4 patients High, 2 Medium, 4 Low', rows=BASELINE),
    dict(id='escalation', file='02_escalation.csv', title='2 · Escalation – condition worsens',
         summary='Abnormal results, emergency visits and new referrals for the same patients. Raises priority for 6 patients.',
         effect='PT-3001, 3003, 3004, 3006, 3007 → High · PT-3010 → Medium', rows=ESCALATION),
    dict(id='recovery', file='03_recovery.csv', title='3 · Recovery – patients improving',
         summary='Completed follow-ups and results back in range for the same patients. Lowers priority for 8 patients.',
         effect='PT-3002, 3007, 3010 → Low · PT-3001, 3003, 3005, 3006, 3008 → Medium', rows=RECOVERY),
    dict(id='edge', file='04_edge_cases.csv', title='4 · Data-quality checks',
         summary='A new patient with a priority, ID/DOB mismatch, a record with no ID, invalid priority values, a missing reason, an unknown patient, a duplicate row and an impossible date.',
         effect='Shows review decisions, invalid and duplicate handling', rows=EDGE),
]


def write_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, lineterminator='\n')
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, '') for c in COLS})
    return buf.getvalue()


def main():
    manifest = []
    for ds in DATASETS:
        (HERE / ds['file']).write_text(write_csv(ds['rows']), encoding='utf-8')
        manifest.append({k: ds[k] for k in ('id', 'file', 'title', 'summary', 'effect')} | {'records': len(ds['rows'])})
    (HERE / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('\n'.join(f"{m['file']}: {m['records']} rows" for m in manifest))


if __name__ == '__main__':
    main()
