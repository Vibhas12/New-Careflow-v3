"""Reference lists shared by the API and validation (same values as the V2 prototype)."""
from typing import Literal

DEPARTMENTS = ['Cardiology', 'Neurology', 'Oncology', 'Orthopedics', 'General Medicine', 'Mental Health']
APPT_TYPES = ['Initial assessment', 'Consultation', 'Follow-up review', 'Diagnostic review', 'Telehealth review', 'Medication review']
TEST_TYPES = ['Blood Test', 'HbA1c', 'Lipid Profile', 'Thyroid Function', 'ECG', 'X-Ray', 'MRI', 'EEG']
SLOTS = [f'{h:02d}:{m}' for h in range(8, 18) for m in ('00', '30')]          # 08:00 … 17:30
ACTIVE_APPT = ('Scheduled', 'Confirmed')

TaskStatus = Literal['New', 'In Progress', 'Waiting for Patient', 'Completed']
TaskKind = Literal['followup', 'contact', 'test', 'review', 'medication', 'referral', 'admin']
ReferralStatus = Literal['Pending', 'Booked', 'Completed', 'Cancelled']
TestPriority = Literal['Routine', 'Urgent']


def _v(name, values, unit, lo, hi, abnormal):
    x = values[1] if abnormal else values[0]
    return {'analyte': name, 'value': str(x), 'unit': unit, 'ref_range': f'{lo}–{hi}', 'flag': 'L' if x < lo else 'H' if x > hi else None}


def simulated_result(test_name: str, abnormal: bool) -> dict:
    """Deterministic synthetic report used by the demo 'result feed' – never a real clinical result."""
    a = abnormal
    lib = {
        'Blood Test': ('Full blood count (synthetic report).', [_v('Haemoglobin', (138, 108), 'g/L', 130, 170, a), _v('White cell count', (6.2, 13.4), '×10⁹/L', 4, 11, a), _v('Platelets', (245, 480), '×10⁹/L', 150, 400, a)]),
        'HbA1c': ('Glycaemic markers (synthetic report).', [_v('HbA1c', (41, 62), 'mmol/mol', 20, 42, a), _v('Fasting glucose', (5.1, 9.1), 'mmol/L', 3.9, 5.5, a)]),
        'Lipid Profile': ('Lipid panel (synthetic report).', [_v('Total cholesterol', (4.6, 6.8), 'mmol/L', 0, 5, a), _v('LDL cholesterol', (2.4, 4.4), 'mmol/L', 0, 3, a), _v('HDL cholesterol', (1.5, 0.8), 'mmol/L', 1, 3, a)]),
        'Thyroid Function': ('Thyroid panel (synthetic report).', [_v('TSH', (2.1, 8.4), 'mIU/L', 0.4, 4, a), _v('Free T4', (15, 9), 'pmol/L', 10, 22, a)]),
        'ECG': ('Synthetic report: rhythm irregularity noted – for clinical interpretation.' if a else 'Synthetic report: regular rhythm, no acute change noted.',
                [_v('Heart rate', (72, 118), 'bpm', 50, 100, a), _v('QTc', (420, 486), 'ms', 350, 460, a)]),
        'X-Ray': ('Synthetic report: possible cortical irregularity – for clinical review.' if a else 'Synthetic report: alignment satisfactory, no acute abnormality described.', []),
        'MRI': ('Synthetic report: signal change described – for specialist review.' if a else 'Synthetic report: no acute findings described.', []),
        'EEG': ('Synthetic report: epileptiform activity described – for specialist review.' if a else 'Synthetic report: background activity within normal limits.', []),
    }
    summary, values = lib.get(test_name, lib['Blood Test'])
    return {'summary': summary, 'values': values, 'source': 'Synthetic diagnostic report – demonstration data (simulated feed)'}
