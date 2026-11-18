"""Request / response models. JSON uses camelCase; Python uses snake_case."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Priority = Literal['high', 'med', 'low']


class Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---------------------------------------------------------------- auth / users
class LoginIn(Schema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(Schema):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class UserOut(Schema):
    id: str
    name: str
    role: str
    title: str | None
    email: str
    departments: list[str] = []
    must_change_password: bool = False


class UserBrief(Schema):
    id: str
    name: str
    role: str
    title: str | None
    departments: list[str] = []


class DemoAccount(Schema):
    name: str
    role: str
    title: str | None
    email: str


# ---------------------------------------------------------------- patients
class PatientListItem(Schema):
    id: str
    first_name: str
    last_name: str
    dob: date | None
    gender: str | None
    department: str | None
    primary_condition: str | None
    doctor_id: str | None
    doctor_name: str | None = None
    coord_id: str | None
    priority: Priority
    suggested_priority: Priority | None = None     # advisory, from open care-gap alerts – never applied automatically
    review_due: date | None
    discharged: bool
    mobile: str | None = None
    last_visit: date | None = None
    next_appt: 'NextAppt | None' = None
    status: str = 'Active'                          # Active · Under follow-up · Awaiting results · Discharged
    follow_up_status: str | None = None
    attention: str | None = None                    # first open care gap, shown on dashboard cards
    attention_kind: str | None = None


class NextAppt(Schema):
    date: date
    time: str
    id: str


class PatientPage(Schema):
    items: list[PatientListItem]
    total: int
    page: int
    page_size: int


class CarePlanOut(Schema):
    plan_text: str | None
    start_date: date | None


class AppointmentOut(Schema):
    id: str
    doctor_id: str | None
    dept: str | None
    appt_date: date
    appt_time: str | None
    type: str | None
    status: str
    notes: str | None


class TestValueOut(Schema):
    analyte: str | None
    value: str | None
    unit: str | None
    ref_range: str | None
    flag: str | None


class TestOut(Schema):
    id: str
    name: str
    ordered_by: str | None
    ordered_on: date | None
    scheduled_date: date | None
    status: str
    result_on: date | None
    reviewed_on: date | None
    review_note: str | None
    abnormal: bool
    result_summary: str | None
    values: list[TestValueOut] = []


class ReferralOut(Schema):
    id: str
    referred_to: str | None
    reason: str | None
    status: str
    created_on: date | None


class PrescriptionOut(Schema):
    id: str
    drug: str | None
    rx_date: date | None
    refill_due: date | None
    status: str | None


class ConsultationOut(Schema):
    id: str
    doctor_id: str | None
    consult_date: date | None
    notes: str | None
    diagnosis: str | None
    plan: str | None
    follow_up: date | None


class HistoryOut(Schema):
    id: str
    event_date: date | None
    type: str | None
    title: str | None
    detail: str | None


class PatientDetail(PatientListItem):
    email: str | None
    mobile: str | None
    address: str | None
    ec_name: str | None
    ec_phone: str | None
    secondary_conditions: str | None
    previous_surgeries: str | None
    family_history: str | None
    ins_provider: str | None
    policy: str | None
    coverage: str | None
    registered_on: date | None
    priority_updated_at: datetime | None
    coordinator_name: str | None = None
    allergies: list[str] = []
    medications: list[str] = []
    diagnoses: list[str] = []
    care_plan: CarePlanOut | None = None
    appointments: list[AppointmentOut] = []
    tests: list[TestOut] = []
    referrals: list[ReferralOut] = []
    prescriptions: list[PrescriptionOut] = []
    consultations: list[ConsultationOut] = []
    history: list[HistoryOut] = []
    tasks: list['TaskOut'] = []
    care_gaps: list['AlertOut'] = []
    activity: list['ActivityOut'] = []
    documents: list['DocumentOut'] = []
    can_change_priority: bool = False


class ActivityOut(Schema):
    ts: datetime
    user_name: str | None
    action: str
    detail: str | None


class DocumentOut(Schema):
    id: str
    filename: str
    file_type: str | None
    doc_type: str | None
    extraction_method: str | None
    batch_id: str | None
    uploaded_at: datetime


# ---------------------------------------------------------------- priority
class PriorityChangeIn(Schema):
    new_priority: Priority
    comment: str = Field(min_length=5, max_length=1000)


class PriorityEntryOut(Schema):
    id: int
    patient_id: str
    previous_priority: Priority | None
    new_priority: Priority
    comment: str
    user_id: str | None
    user_name: str
    user_role: str
    changed_at: datetime


# ---------------------------------------------------------------- phase 2: workflows
TaskStatus = Literal['New', 'In Progress', 'Waiting for Patient', 'Completed']
TaskKind = Literal['followup', 'contact', 'test', 'review', 'medication', 'referral', 'admin']
Hhmm = Annotated[str, Field(pattern=r'^\d{2}:\d{2}$')]


class Catalog(Schema):
    departments: list[str]
    appointment_types: list[str]
    test_types: list[str]
    slots: list[str]
    task_statuses: list[str]


class AppointmentItem(AppointmentOut):
    patient_id: str
    patient_name: str = ''
    doctor_name: str | None = None


class AppointmentPage(Schema):
    items: list[AppointmentItem]
    total: int


class BookAppointmentIn(Schema):
    patient_id: str
    doctor_id: str
    date: date
    time: Hhmm
    type: str
    notes: str | None = Field(None, max_length=1000)


class RescheduleIn(Schema):
    date: date
    time: Hhmm
    reason: str | None = Field(None, max_length=500)


class ReasonIn(Schema):
    reason: str = Field(min_length=3, max_length=500)


class Slots(Schema):
    doctor_id: str
    date: date
    slots: list[str]


class TestItem(TestOut):
    patient_id: str
    patient_name: str = ''
    department: str | None = None
    ordered_by_name: str | None = None
    priority: str | None
    notes: str | None
    completed_on: date | None


class RequestTestIn(Schema):
    patient_id: str
    name: str
    priority: Literal['Routine', 'Urgent'] = 'Routine'
    notes: str | None = Field(None, max_length=1000)


class ScheduleTestIn(Schema):
    date: date


class ResultIn(Schema):
    abnormal: bool = False


class ReviewIn(Schema):
    note: str | None = Field(None, max_length=1000)


class TaskEventOut(Schema):
    ts: datetime | None
    by_name: str | None
    text: str | None


class TaskOut(Schema):
    id: str
    title: str
    patient_id: str | None
    patient_name: str | None = None
    priority: Priority | None
    assignee: str | None
    assignee_name: str | None = None
    created: date | None
    due: date | None
    status: str
    kind: str | None
    source: str | None
    description: str | None
    completed_on: date | None
    test_id: str | None
    events: list[TaskEventOut] = []


class TaskCreateIn(Schema):
    title: str = Field(min_length=3, max_length=300)
    patient_id: str | None = None
    assignee: str
    due: date
    priority: Priority = 'med'
    kind: TaskKind = 'followup'
    description: str | None = Field(None, max_length=2000)


class TaskUpdateIn(Schema):
    status: TaskStatus | None = None
    assignee: str | None = None
    due: date | None = None
    priority: Priority | None = None
    note: str | None = Field(None, max_length=1000)


class ReferralCreateIn(Schema):
    referred_to: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=3, max_length=1000)


class ReferralStatusIn(Schema):
    status: Literal['Booked', 'Completed', 'Cancelled']


class ConsultationIn(Schema):
    date: date
    notes: str = Field(min_length=5, max_length=5000)
    diagnosis: str | None = Field(None, max_length=500)
    prescription: str | None = Field(None, max_length=500)
    plan: str | None = Field(None, max_length=2000)
    follow_up: date | None = None
    instructions: str | None = Field(None, max_length=2000)
    create_follow_up_task: bool = True


class NotificationOut(Schema):
    id: str
    ts: datetime | None
    title: str | None
    text: str | None
    route: str | None
    patient_id: str | None
    is_read: bool
    level: str | None


class NotificationList(Schema):
    items: list[NotificationOut]
    unread: int


# ---------------------------------------------------------------- phase 3: import, care gaps, jobs
class IngestRecordOut(Schema):
    id: int
    row: int | None
    kind: str
    mapped: dict
    status: str
    patient_id: str | None
    candidates: list[dict]
    issues: list[dict]
    decision: str
    result: str | None
    message: str | None
    saved: str | None


class BatchOut(Schema):
    id: str
    filename: str
    type: str | None
    size: int | None
    sha256: str | None
    status: str
    message: str | None
    uploaded_by: str | None
    uploaded_at: datetime
    confirmed_at: datetime | None
    method: str | None
    records: int
    imported: int
    skipped: int
    failed: int


class BatchDetail(BatchOut):
    record_list: list[IngestRecordOut] = []
    document: dict | None = None
    pending: int = 0


class RecordReviewIn(Schema):
    fields: dict[str, str | None] | None = None
    patient_id: str | None = None             # an existing patient ID, or "NEW" to create one (patient rows only)
    decision: Literal['import', 'skip'] | None = None


class ConfirmOut(Schema):
    result: dict
    batch: BatchDetail


class DemoDataset(Schema):
    id: str
    file: str
    title: str
    summary: str
    effect: str
    records: int


class AlertOut(Schema):
    id: str
    rule: str
    category: str
    rule_name: str
    patient_id: str
    patient_name: str = ''
    entity: str
    priority: Priority
    reason: str
    evidence: list[dict]
    action: dict
    assignee: str | None
    assignee_name: str | None = None
    status: str
    first_seen: datetime
    last_seen: datetime
    resolved_at: datetime | None
    actioned_at: datetime | None
    task_id: str | None
    dismiss_reason: str | None
    ai_text: str | None = None
    ai_rationale: str | None = None
    ai_task_title: str | None = None
    ai_model: str | None = None
    ai_generated_at: datetime | None = None
    ai_status: Literal['ready', 'none', 'stale', 'withheld', 'error', 'off'] = 'off'
    ai_error: str | None = None


class AlertApproveIn(Schema):
    title: str | None = Field(None, min_length=3, max_length=300)
    text: str | None = Field(None, max_length=2000)
    assignee: str | None = None
    due: date | None = None
    priority: Priority | None = None


class AlertSummary(Schema):
    categories: list[dict]                    # [{rule, category, open, high}]
    total_open: int
    by_status: dict[str, int]


class Health(Schema):
    ok: bool
    database: str
    migration: str | None
    patients: int


for _m in (PatientListItem, PatientDetail, PatientPage):     # resolve forward references (NextAppt, TaskOut, AlertOut, …)
    _m.model_rebuild()
