"""AI Care Assistant – deterministic, template-based agents over the records the user may see. NO language model.

Agents (as in the V2 prototype):
  Context Agent          scopes the question to the user's authorised patients and retrieves their records
  Care-Gap Agent         reads the stored care-gap alerts produced by the deterministic rules
  Summary Agent          composes statements from recorded data only, each citing numbered source records
  Next-Best-Action Agent suggests actions or drafts proposals – nothing happens until a person approves

It never invents data, diagnoses or prescribes, and never changes a patient's priority.
"""
import re
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (Appointment, AssistantMessage, AssistantProposal, AuditLog, CareGapAlert, Consultation, DiagnosticTest, Document,
                        Patient, PriorityHistory, Referral, Task, User)
from app.services import messaging, patient_info
from app.services import tasks as task_svc
from app.services.access import get_visible_patient, scope_patients
from app.services.care_gaps import PRI_RANK, RULES, suggested_priorities
from app.services.common import audit, fail, fmt_d, next_id, today, utcnow

PRI = {'high': 'High', 'med': 'Medium', 'low': 'Low'}
ROLE = {'coordinator': 'Care Coordinator', 'doctor': 'Doctor', 'admin': 'Operations Manager', 'system': 'System'}
PROMPTS = ['Summarise {first} journey', 'Which patients have overdue follow-ups?', 'Which diagnostic tests are awaiting review?',
           'Show patients who missed appointments this week', 'What actions are pending for Dr. Wilson?', 'Summarise the latest patient activity',
           'Which referrals are still incomplete?', 'Create a reminder for {name}']


def _need(user: User):
    if user.role not in ('coordinator', 'doctor'):
        fail(403, 'The AI assistant is available to care coordinators and doctors')


def _pool(db: Session, user: User) -> list[Patient]:
    return list(db.execute(scope_patients(select(Patient), user).where(Patient.discharged.is_(False)).order_by(Patient.last_name)).scalars())


def _age(dob: date | None) -> str:
    if not dob:
        return 'age not recorded'
    t = today()
    return str(t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day)))


def prompts(db: Session, user: User) -> list[str]:
    pool = _pool(db, user)
    p = pool[0] if pool else None
    out = [x.format(first=f"{p.first_name} {p.last_name}’s patient" if p else 'a patient’s', name=f'{p.first_name} {p.last_name}' if p else 'a patient') for x in PROMPTS]
    if user.role == 'doctor':
        out[4] = 'What actions are pending for me?'
    return out


def find_patient(text: str, pool: list[Patient]) -> Patient | None:
    low = text.lower()
    for p in pool:
        if f'{p.first_name} {p.last_name}'.lower() in low or p.id.lower() in low:
            return p
    for attr in ('last_name', 'first_name'):
        hits = [p for p in pool if re.search(r'\b' + re.escape(getattr(p, attr).lower()) + r'\b', low)]
        if len(hits) == 1:
            return hits[0]
    return None


# ---------------------------------------------------------------- patient summary (Summary Agent)
def brief(db: Session, user: User, patient_id: str) -> dict:
    _need(user)
    p = get_visible_patient(db, user, patient_id)
    T, src = today(), []

    def S(ref, label, ts):
        for i, s in enumerate(src):
            if s['ref'] == ref:
                return i + 1
        src.append({'ref': ref, 'label': label, 'ts': ts.isoformat() if ts else None})
        return len(src)

    def F(text, sources=(), kind='fact', **kw):
        return {'text': text, 'kind': kind, 'sources': list(sources), **kw}
    names = dict(db.execute(select(User.id, User.name)).all())
    B = {'context': [], 'history': [], 'gaps': [], 'appointments': [], 'results': [], 'next': []}
    reg = S(p.id, 'Patient record', p.registered_on)
    sec = f'; also {p.secondary_conditions}' if p.secondary_conditions and p.secondary_conditions != 'None' else ''
    B['context'].append(F(f'{p.full_name}, {_age(p.dob)}, {p.gender}. Primary condition: {p.primary_condition}{sec}. Department: {p.department}.', [reg]))
    plan = p.care_plan.plan_text if p.care_plan and p.care_plan.plan_text else 'not recorded'
    B['context'].append(F(f"Assigned doctor: {names.get(p.doctor_id, 'not recorded')}. Registered {fmt_d(p.registered_on)}. Current treatment plan: {plan}.", [reg]))
    last = db.execute(select(PriorityHistory).where(PriorityHistory.patient_id == p.id).order_by(PriorityHistory.id.desc())).scalars().first()
    B['context'].append(F(f'Current priority: {PRI[p.priority]}' + (f' – set by {last.user_name} ({ROLE.get(last.user_role, last.user_role)}) on '
                                                                 f'{fmt_d(last.changed_at.date())}: “{last.comment}”.' if last else '.'),
                          [S(f'PRI-{last.id}' if last else p.id, 'Priority history', last.changed_at if last else p.registered_on)]))
    sug = suggested_priorities(db, [p.id])[p.id]
    if sug != p.priority:
        B['context'].append(F(f'Open care gaps would suggest {PRI[sug]} priority. This is advisory only – priority is changed solely by a Care Coordinator '
                              'or Doctor, with a comment.', [S('RULES', 'Care-gap rule engine', utcnow())], 'suggestion'))

    diag = ', '.join(d.description for d in p.diagnoses) or 'none recorded'
    B['history'].append(F(f'Previous diagnoses: {diag}. Previous surgeries: {p.previous_surgeries or "none recorded"}. '
                          f'Family history: {p.family_history or "none recorded"}.', [reg]))
    lc = db.execute(select(Consultation).where(Consultation.patient_id == p.id).order_by(Consultation.consult_date.desc())).scalars().first()
    if lc:
        B['history'].append(F(f'Latest consultation note ({fmt_d(lc.consult_date)}{", imported from file " + lc.source_batch_id if lc.source_batch_id else ""}): {lc.notes}',
                              [S(lc.id, 'Consultation', lc.created_on or lc.consult_date)]))
    for d in db.execute(select(Document).where(Document.patient_id == p.id).order_by(Document.uploaded_at)).scalars():
        extract = ' '.join((d.extracted_text or '').split())[:260]
        B['history'].append(F(f'Imported document “{d.filename}” ({d.doc_type}, imported {fmt_d(d.uploaded_at.date())}, extracted by {d.extraction_method}).'
                              + (f' Extract: {extract}…' if extract else ''), [S(d.id, 'Imported document', d.uploaded_at)]))
    allergies = [a.substance for a in p.allergies]
    B['history'].append(F(f'Recorded allergy: {"; ".join(allergies)}.', [reg]) if allergies else F('Allergy status is not recorded in the available data.', [], 'missing'))
    meds = [m.description for m in p.medications if m.status == 'Active']
    if meds:
        B['history'].append(F(f'Existing medication (as recorded): {"; ".join(meds)}.', [reg]))
    info = patient_info.compute(db, [p])[p.id]
    lv = info['last_visit']
    B['history'].append(F(f'Last completed visit: {fmt_d(lv)}.', [reg]) if lv else F('No completed visit is recorded.', [], 'missing'))
    if not p.email:
        B['history'].append(F('No email address is recorded for this patient.', [], 'missing'))

    alerts = sorted(db.execute(select(CareGapAlert).where(CareGapAlert.patient_id == p.id, CareGapAlert.status.in_(('Open', 'Actioned')))).scalars(),
                    key=lambda a: PRI_RANK[a.priority])
    if not alerts:
        B['gaps'].append(F('No outstanding care gaps are detected by the current rules.', [S('RULES', 'Care-gap rule engine', utcnow())]))
    for a in alerts:
        B['gaps'].append(F(f'[{a.category}] {a.reason}' + (' (action in progress)' if a.status == 'Actioned' else ''),
                           [S(e['ref'], 'Record', a.first_seen) for e in a.evidence]))
    up = list(db.execute(select(Appointment).where(Appointment.patient_id == p.id, Appointment.status.in_(('Scheduled', 'Confirmed')), Appointment.appt_date >= T)
                         .order_by(Appointment.appt_date, Appointment.appt_time)).scalars())
    for a in up:
        B['appointments'].append(F(f'Upcoming: {fmt_d(a.appt_date)} {a.appt_time} with {names.get(a.doctor_id, "—")} ({a.type}, {a.status}).',
                                   [S(a.id, 'Appointment', a.created_on or a.appt_date)]))
    if not up:
        B['appointments'].append(F('No upcoming appointment is recorded.', [S('APT', 'Appointment register', utcnow())], 'missing'))
    pend = list(db.execute(select(DiagnosticTest).where(DiagnosticTest.patient_id == p.id, DiagnosticTest.status != 'Reviewed')).scalars())
    if not pend:
        B['results'].append(F('No pending diagnostic results.'))
    for t in pend:
        tail = (' – values outside reference range, awaiting doctor review.' if t.abnormal else ' – awaiting doctor review.') if t.status == 'Result Available' else '.'
        B['results'].append(F(f'{t.name}{" (imported)" if t.source_batch_id else ""}: {t.status}{tail}', [S(t.id, 'Diagnostic test', t.result_on or t.ordered_on)]))
    for r in db.execute(select(Referral).where(Referral.patient_id == p.id, Referral.status.not_in(('Completed', 'Cancelled')))).scalars():
        B['results'].append(F(f'Referral to {r.referred_to}: {r.status} (created {fmt_d(r.created_on)}).', [S(r.id, 'Referral', r.created_on)]))

    for a in alerts:
        if a.status == 'Open':
            from app.services.recommendation_agent import is_current
            B['next'].append(F(f"{a.ai_text if is_current(a) else a.action['text']} ({a.category})", [S(e['ref'], 'Record', a.first_seen) for e in a.evidence], 'suggestion',
                               alertId=a.id, priority=a.priority))
    if not B['next']:
        B['next'].append(F('No coordination action is suggested at this time.', [], 'suggestion'))
    return {'patientId': p.id, 'patientName': p.full_name, 'generatedAt': utcnow().isoformat(), 'sections': B,
            'evidence': [{'n': i + 1, **s} for i, s in enumerate(src)]}


# ---------------------------------------------------------------- chat (all agents)
def _cell(t, pid=None):
    return {'t': t, 'pid': pid}


def answer(db: Session, user: User, text: str, context_pid: str | None = None) -> dict:
    _need(user)
    low, T, pool = text.lower().strip(), today(), _pool(db, user)
    ids = {p.id for p in pool}
    byid = {p.id: p for p in pool}
    label = lambda pid: f'{byid[pid].full_name} ({pid})' if pid in byid else pid
    names = dict(db.execute(select(User.id, User.name)).all())
    trace = [f'Context Agent: scoped to {len(pool)} authorised patient record(s) for {user.name}.']
    msg = {'intro': '', 'blocks': [], 'trace': trace, 'patientId': None}
    open_alerts = lambda rule=None: [a for a in db.execute(select(CareGapAlert).where(CareGapAlert.patient_id.in_(ids), CareGapAlert.status == 'Open')).scalars()
                                     if rule is None or a.rule == rule]
    p = find_patient(text, pool) or (byid.get(context_pid) if context_pid and re.search(r'\b(this|the) patient\b|\bthem\b|\bhim\b|\bher\b', low) else None)

    if re.search(r'(create|add|propose|raise|set up).*(task|reminder)', low):
        if not p:
            msg['intro'] = 'Tell me which patient the task or reminder is for (for example: “Create a reminder for Sarah Thompson”).'
            return msg
        rem = 'reminder' in low
        title = re.sub(r"^(please\s+)?(create|add|propose|raise|set up)\s+(a\s+)?(follow-?up\s+)?(task|reminder)\s*(for\s+[a-z .'-]+?)?\s*(to|:)?\s*", '', text, flags=re.I).strip()
        if rem:
            title = f'Reminder to {p.full_name}'
        elif len(title) < 4 or title.lower() in (p.full_name.lower(), p.first_name.lower(), p.last_name.lower()):
            title = f'Follow up with {p.full_name}'
        prop = AssistantProposal(id=next_id(db, 'PR', 100), created_by=user.id, created_at=utcnow(), patient_id=p.id, type='reminder' if rem else 'task',
                                 title=title[:1].upper() + title[1:], assignee=p.coord_id or user.id, due=T + timedelta(days=2), priority='med', channel='SMS',
                                 message='Reminder from your care team: please contact us to arrange your next appointment.', status='Proposed',
                                 rationale=f'Requested in chat by {user.name}.')
        db.add(prop)
        db.flush()
        msg.update(patientId=p.id, intro=f'I’ve drafted a proposed {prop.type} for {p.full_name}. Nothing happens until an authorised user approves it.')
        msg['blocks'].append({'type': 'proposals', 'proposalIds': [prop.id]})
        trace.append('Next-Best-Action Agent: drafted 1 proposal (status: Proposed – awaiting human approval).')
        return msg

    if p:
        b = brief(db, user, p.id)
        n_facts = sum(len(v) for k, v in b['sections'].items() if k != 'next')
        msg.update(patientId=p.id, intro=f'Here is a grounded summary for {p.full_name} ({p.id}). Recorded facts and AI suggestions are labelled separately.')
        msg['blocks'].append({'type': 'brief', 'brief': b})
        trace += [f'Context Agent: retrieved the patient record, appointments, tests, referrals, tasks and imported documents for {p.id}.',
                  f'Care-Gap Agent: {len(b["sections"]["gaps"])} care-gap statement(s) from the rule engine.',
                  f'Summary Agent: composed {n_facts} statements citing {len(b["evidence"])} sources (template-based; no LLM).',
                  f'Next-Best-Action Agent: {sum(1 for x in b["sections"]["next"] if x.get("alertId"))} suggested action(s), all pending approval.']
        return msg

    def gap_table(rule, intro, empty):
        g = open_alerts(rule)
        msg['intro'] = intro.format(n=len(g)) if g else empty
        if g:
            msg['blocks'].append({'type': 'table', 'head': ['Patient', 'Evidence', 'Priority', 'Source'],
                                  'rows': [[_cell(label(a.patient_id), a.patient_id), _cell(a.reason), _cell(PRI[a.priority]),
                                            _cell(f"{a.evidence[0]['ref']} · {fmt_d(a.first_seen.date())}")] for a in g]})
            msg['blocks'].append({'type': 'gapActions', 'alertIds': [a.id for a in g][:5]})
        trace.append(f'Care-Gap Agent: evaluated rule “{RULES[rule][1]}” → {len(g)} match(es).')
        return msg

    if re.search(r'overdue.*follow|follow.?up.*overdue', low):
        return gap_table('overdue_followup', '{n} patient(s) have an overdue follow-up (review date passed, no consultation or future appointment recorded):',
                         'No patients currently have an overdue follow-up under the active rule.')
    if re.search(r'(test|result|diagnostic)', low) and re.search(r'review', low):
        return gap_table('results_review', '{n} diagnostic result(s) are awaiting doctor review:', 'No diagnostic results are awaiting review.')
    if 'missed' in low:
        since = T - timedelta(days=7)
        m = list(db.execute(select(Appointment).where(Appointment.patient_id.in_(ids), Appointment.status == 'Missed', Appointment.appt_date >= since)
                            .order_by(Appointment.appt_date.desc())).scalars())
        later = {a.patient_id for a in db.execute(select(Appointment).where(Appointment.patient_id.in_(ids), Appointment.status.in_(('Scheduled', 'Confirmed', 'Completed')))).scalars()
                 if any(a.appt_date > x.appt_date for x in m if x.patient_id == a.patient_id)}
        trace.append(f'Care-Gap Agent: queried appointments with status Missed since {fmt_d(since)} → {len(m)}.')
        msg['intro'] = f'{len(m)} missed appointment(s) in the last 7 days:' if m else 'No missed appointments are recorded in the last 7 days.'
        if m:
            msg['blocks'].append({'type': 'table', 'head': ['Patient', 'Appointment', 'Doctor', 'Later appointment?'],
                                  'rows': [[_cell(label(a.patient_id), a.patient_id), _cell(f'{fmt_d(a.appt_date)} {a.appt_time} ({a.id})'),
                                            _cell(names.get(a.doctor_id, '—')), _cell('Yes – rebooked' if a.patient_id in later else 'No – needs rebooking')] for a in m]})
        g = open_alerts('missed_appt')
        if g:
            msg['blocks'].append({'type': 'gapActions', 'alertIds': [a.id for a in g][:5]})
        return msg
    if 'referral' in low:
        r = list(db.execute(select(Referral).where(Referral.patient_id.in_(ids), Referral.status.not_in(('Completed', 'Cancelled')))).scalars())
        trace.append(f'Context Agent: retrieved {len(r)} non-completed referral(s).')
        msg['intro'] = f'{len(r)} referral(s) are not yet completed:' if r else 'All referrals in your scope are completed.'
        if r:
            msg['blocks'].append({'type': 'table', 'head': ['Patient', 'Referral', 'Status', 'Age'],
                                  'rows': [[_cell(label(x.patient_id), x.patient_id), _cell(f'{x.referred_to} ({x.id})'), _cell(x.status),
                                            _cell(f'{(T - x.created_on).days} days' if x.created_on else '—')] for x in r]})
        g = open_alerts('referral')
        if g:
            msg['blocks'].append({'type': 'gapActions', 'alertIds': [a.id for a in g][:5]})
        return msg
    if re.search(r'(pending|actions).*(dr\.?|doctor|\bme\b)|(dr\.?|doctor)\s*\w+.*(pending|action)|pending for', low):
        doctors = list(db.execute(select(User).where(User.role == 'doctor', User.active.is_(True))).scalars())
        doc = next((d for d in doctors if d.name.split()[-1].lower() in low), None) or (user if user.role == 'doctor' else None)
        if not doc:
            msg['intro'] = 'Which doctor do you mean? For example: “What actions are pending for Dr. Wilson?”'
            return msg
        if user.role == 'doctor' and doc.id != user.id:
            msg['intro'] = 'Doctors can review pending actions for their own patients only.'
            trace.append('Context Agent: request outside the user’s scope – no data returned.')
            return msg
        tk = [k for k in db.execute(select(Task).where(Task.assignee == doc.id, Task.status != 'Completed')).scalars() if k.patient_id is None or k.patient_id in ids]
        gp = [a for a in open_alerts() if a.rule in ('results_review', 'overdue_followup') and byid[a.patient_id].doctor_id == doc.id]
        trace.append(f'Context Agent: retrieved {len(tk)} open task(s) and {len(gp)} clinical-review gap(s) for {doc.name}.')
        msg['intro'] = f'Pending actions for {doc.name}:' + ('' if tk or gp else ' nothing is pending.')
        rows = [[_cell(label(k.patient_id) if k.patient_id else '—', k.patient_id), _cell(f'Task: {k.title} ({k.id})'), _cell(f'Due {fmt_d(k.due)}'), _cell(k.status)] for k in tk]
        rows += [[_cell(label(a.patient_id), a.patient_id), _cell(f'{a.category}: {a.reason}'), _cell(PRI[a.priority]), _cell(a.status)] for a in gp]
        if rows:
            msg['blocks'].append({'type': 'table', 'head': ['Patient', 'Pending item', 'Due / priority', 'Status'], 'rows': rows})
        return msg
    if re.search(r'(latest|recent).*(activity|update)|summar.*(activity|latest)', low):
        a = list(db.execute(select(AuditLog).where(AuditLog.patient_id.in_(ids), AuditLog.action != 'Viewed patient record')
                            .order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(10)).scalars())
        trace.append('Context Agent: read the 10 most recent audit entries for authorised patients.')
        msg['intro'] = 'Latest recorded activity (from the audit log):' if a else 'No activity is recorded for your patients yet.'
        if a:
            msg['blocks'].append({'type': 'table', 'head': ['When', 'Who', 'Action', 'Patient'],
                                  'rows': [[_cell(f'{fmt_d(x.ts.date())}, {x.ts:%H:%M}'), _cell(x.user_name), _cell(x.action + (f' – {x.detail}' if x.detail else '')),
                                            _cell(label(x.patient_id), x.patient_id)] for x in a]})
        return msg
    if re.search(r'imported|(upload|document|report).*(recent|latest|new)|(recent|latest|new).*(upload|document)', low):
        docs = list(db.execute(select(Document).where(Document.patient_id.in_(ids)).order_by(Document.uploaded_at.desc()).limit(8)).scalars())
        trace.append(f'Context Agent: retrieved {len(docs)} imported document(s) in scope.')
        msg['intro'] = f'{len(docs)} imported document(s) in your scope (newest first):' if docs else 'No imported documents are available in your scope.'
        if docs:
            msg['blocks'].append({'type': 'table', 'head': ['Patient', 'Document', 'Imported', 'Extract (as read from the file)'],
                                  'rows': [[_cell(label(d.patient_id), d.patient_id), _cell(f'{d.filename} ({d.doc_type})'), _cell(fmt_d(d.uploaded_at.date())),
                                            _cell(' '.join((d.extracted_text or '').split())[:140] + '…')] for d in docs]})
        return msg
    if re.search(r'care.?gap|attention|alert|priority', low):
        g = open_alerts()
        trace.append(f'Care-Gap Agent: {len(g)} open gap(s) in scope.')
        msg['intro'] = f'{len(g)} open care gap(s) in your scope, by category:'
        msg['blocks'].append({'type': 'table', 'head': ['Category', 'Open gaps', 'High priority'],
                              'rows': [[_cell(v[0]), _cell(str(sum(1 for a in g if a.rule == r))), _cell(str(sum(1 for a in g if a.rule == r and a.priority == 'high')))]
                                       for r, v in RULES.items()]})
        return msg
    msg['intro'] = ('I can answer questions grounded in the records you are authorised to see. I couldn’t match that to a supported request, and I won’t '
                    'guess. Try one of the suggested questions, name a patient (e.g. “Summarise Sarah Thompson’s patient journey”), or ask me to draft a task or reminder.')
    trace.append('Context Agent: no supported intent matched – no data returned.')
    return msg


# ---------------------------------------------------------------- conversation & proposals
def ask(db: Session, user: User, text: str, context_pid: str | None) -> AssistantMessage:
    _need(user)
    text = text.strip()
    db.add(AssistantMessage(user_id=user.id, ts=utcnow(), role='user', text=text))
    m = answer(db, user, text, context_pid)
    ai = AssistantMessage(user_id=user.id, ts=utcnow(), role='ai', text=m['intro'], patient_id=m['patientId'], payload={'blocks': m['blocks'], 'trace': m['trace']})
    db.add(ai)
    audit(db, user, 'AI assistant query', patient_id=m['patientId'], detail=text[:100])
    db.commit()
    return ai


def history(db: Session, user: User, limit: int = 80) -> list[AssistantMessage]:
    _need(user)
    rows = list(db.execute(select(AssistantMessage).where(AssistantMessage.user_id == user.id).order_by(AssistantMessage.id.desc()).limit(limit)).scalars())
    return rows[::-1]


def clear(db: Session, user: User) -> None:
    _need(user)
    db.execute(delete(AssistantMessage).where(AssistantMessage.user_id == user.id))
    db.commit()


def _proposal(db: Session, user: User, pid: str) -> AssistantProposal:
    _need(user)
    x = db.get(AssistantProposal, pid)
    if x is None:
        fail(404, 'Proposal not found')
    get_visible_patient(db, user, x.patient_id)
    if x.status != 'Proposed':
        fail(409, f'The proposal is already {x.status.lower()}')
    return x


def approve(db: Session, user: User, pid: str) -> AssistantProposal:
    x = _proposal(db, user, pid)
    p = db.get(Patient, x.patient_id)
    if x.type == 'task':
        k = task_svc.create(db, user, title=x.title, patient_id=p.id, priority=x.priority, assignee=x.assignee or p.coord_id or user.id, due=x.due or today(),
                            kind='followup', source='AI recommendation (approved)', description=f'{x.rationale} Approved by {user.name}.', commit=False)
        x.result_ref = k.id
    else:
        r = messaging.send_manual_reminder(db, user, p, kind='Manual', label='AI-proposed reminder (approved)', channel=x.channel or 'SMS', message=x.message or '')
        x.result_ref = r.id
    x.status, x.decided_by, x.decided_at = 'Approved', user.id, utcnow()
    audit(db, user, 'AI proposal approved', patient_id=p.id, entity=x.id, detail=f'{x.type}: {x.title} → {x.result_ref}')
    db.commit()
    return x


def reject(db: Session, user: User, pid: str) -> AssistantProposal:
    x = _proposal(db, user, pid)
    x.status, x.decided_by, x.decided_at = 'Rejected', user.id, utcnow()
    audit(db, user, 'AI proposal rejected', patient_id=x.patient_id, entity=x.id, detail=x.title)
    db.commit()
    return x
