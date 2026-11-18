import { useRef, useState, type DragEvent } from 'react'
import { ApiError } from '../api/client'
import { downloadFile, useBatch, useBatches, useDemoDatasets, useIngestActions } from '../api/phase3'
import type { BatchDetail, IngestRecord } from '../api/types'
import { Field } from '../components/dialogs'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Empty, ErrorBanner, Loading, Modal, PageHead } from '../components/ui'
import { fmtDateTime, PRIORITY_LABEL } from '../lib/format'

const KINDS: Record<string, string> = { patient: 'Patient', consultation: 'Consultation note', test: 'Diagnostic report', appointment: 'Appointment', referral: 'Referral',
  medication: 'Medication', allergy: 'Allergy', history: 'Medical history', task: 'Outstanding task', priority: 'Priority change', unknown: 'Unrecognised' }
const FIELDS: Record<string, string[]> = {
  patient: ['patient_id', 'first_name', 'last_name', 'dob', 'gender', 'mobile', 'email', 'department', 'primary_condition', 'allergies', 'medications', 'care_plan'],
  consultation: ['patient_id', 'first_name', 'last_name', 'date', 'doctor', 'notes', 'diagnosis', 'plan', 'follow_up'],
  test: ['patient_id', 'first_name', 'last_name', 'dob', 'test_name', 'date', 'summary'], appointment: ['patient_id', 'date', 'time', 'type', 'status'],
  referral: ['patient_id', 'referred_to', 'reason', 'status'], medication: ['patient_id', 'medications'], allergy: ['patient_id', 'allergies'],
  history: ['patient_id', 'date', 'type', 'title', 'detail'], task: ['patient_id', 'title', 'date'], priority: ['patient_id', 'new_priority', 'reason'],
}
const LABEL = (k: string) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()).replace('Dob', 'Date of birth').replace('New priority', 'New priority (High/Medium/Low)')
const BADGE: Record<string, string> = { matched: 'b-low', new: 'b-blue', uncertain: 'b-med', duplicate: 'b-grey', invalid: 'b-high', 'Needs Review': 'b-med', Imported: 'b-low', 'Partially Imported': 'b-med', Failed: 'b-high', Rejected: 'b-high', Cancelled: 'b-grey' }
const NAMES: Record<string, string> = { matched: 'Matched', new: 'New', uncertain: 'Needs review', duplicate: 'Duplicate', invalid: 'Invalid' }
const Badge = ({ s }: { s: string }) => <span className={`badge ${BADGE[s] ?? 'b-grey'}`}>{NAMES[s] ?? s}</span>

function summary(r: IngestRecord): string {
  const m = r.mapped, nm = [m.first_name, m.last_name].filter(Boolean).join(' ')
  const bits: Record<string, (string | undefined)[]> = {
    patient: [nm, m.dob && `DOB ${m.dob}`, m.department, m.primary_condition, m.medications && `Meds: ${m.medications}`, m.allergies && `Allergies: ${m.allergies}`],
    consultation: [m.date, m.notes], test: [m.test_name, m.date, m.summary], appointment: [m.date, m.time, m.type, m.status], referral: [m.referred_to, m.reason],
    medication: [m.medications], allergy: [m.allergies], history: [m.date, m.title], task: [m.title, m.date && `due ${m.date}`],
    priority: [m.new_priority && `Set priority to ${PRIORITY_LABEL[m.new_priority as 'high'] ?? m.new_priority}`, m.reason && `Reason: ${m.reason}`],
  }
  return (bits[r.kind] ?? []).filter(Boolean).map((x) => String(x).slice(0, 140)).join(' · ') || '—'
}

export function ImportPage() {
  const toast = useToast()
  const [batchId, setBatchId] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [editing, setEditing] = useState<IngestRecord | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const demos = useDemoDatasets()
  const history = useBatches()
  const batch = useBatch(batchId)
  const act = useIngestActions()
  const busy = act.upload.isPending || act.loadDemo.isPending || act.confirm.isPending

  const opened = (b: BatchDetail, text: string) => {
    setBatchId(b.id); setMsg({ ok: true, text })
    setTimeout(() => document.getElementById('ingReview')?.scrollIntoView({ behavior: 'smooth' }), 50)
  }
  const failed = (e: Error) => {
    const data = e instanceof ApiError ? (e.data as { batch?: BatchDetail } | undefined) : undefined
    if (data?.batch) setBatchId(data.batch.id)
    setMsg({ ok: false, text: `Not imported: ${e.message}${data?.batch ? ` (kept in the import history as ${data.batch.id}, status ${data.batch.status})` : ''}` })
  }
  const pick = (f?: File) => {
    if (!f) return
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!['csv', 'json', 'pdf'].includes(ext)) return setMsg({ ok: false, text: `Unsupported file type “.${ext}”. Choose a CSV, JSON or PDF file.` })
    if (f.size > 5 * 1024 * 1024) return setMsg({ ok: false, text: `File is ${(f.size / 1048576).toFixed(1)} MB – the limit is 5 MB.` })
    act.upload.mutate(f, { onSuccess: (b) => opened(b, `“${f.name}” read successfully (${b.records} records, ${b.method}). Review below, then confirm – nothing is saved until you confirm.`), onError: failed })
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); pick(e.dataTransfer.files[0]) }

  const b = batch.data
  const editable = b?.status === 'Needs Review'
  const toImport = b?.recordList.filter((r) => r.decision === 'import').length ?? 0
  const decide = (rid: number, body: { patientId?: string; decision?: 'import' | 'skip'; fields?: Record<string, string | null> }) =>
    act.review.mutate({ rid, ...body }, { onError: (e) => toast(e.message, true) })

  return (
    <>
      <PageHead title="Data Import" sub="Load patient information from CSV, JSON or PDF. Everything is shown for review first; uncertain matches and duplicates are never merged automatically." />
      {msg && <div className={'banner' + (msg.ok ? '' : ' warn')} role="status">{msg.text}</div>}

      <div className="card mt">
        <div className="row sp"><h2><Icon name="upload" /> Demo data – load without choosing a file</h2>
          <span className="sm mut">Same patients (PT-3001 … PT-3010) at different times. Load 1 → 2 → 3 and confirm each to watch their priority change.</span></div>
        {demos.isLoading ? <Loading /> : (
          <div className="list mt2">{demos.data?.map((d) => (
            <div className="cl" key={d.id}>
              <span className="grow"><b>{d.title}</b> <span className="sm mut">{d.records} rows</span><br /><span className="sm">{d.summary}</span><br /><span className="sm mut">Priority effect: {d.effect}</span></span>
              <button className="btn ghost s" onClick={() => downloadFile(`/api/ingest/demo/${d.id}/file`, `demo_${d.id}.csv`).catch((e) => toast(e.message, true))}>View CSV</button>
              <button className="btn s" disabled={busy} onClick={() => act.loadDemo.mutate(d.id, { onSuccess: (bb) => opened(bb, `Demo dataset “${d.title}” loaded (${bb.records} records). Priority rows show current → new. Nothing is saved until you confirm.`), onError: failed })}>Load into review</button>
            </div>
          ))}</div>
        )}
      </div>

      <div className="card mt" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
        <h2><Icon name="task" /> 1 · Choose a file</h2>
        <div className="row mt2">
          <input ref={fileRef} type="file" accept=".csv,.json,.pdf,application/pdf,text/csv,application/json" disabled={busy} onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          <span className="sm mut">CSV · JSON · PDF (text or scanned – OCR is used when needed) · up to 5 MB. Dates: YYYY-MM-DD or DD/MM/YYYY.</span>
          {busy && <span className="badge b-med">Working…</span>}
        </div>
        <p className="sm mut mt2">CSV/JSON columns: <code>patient_id, first_name, last_name, dob, department, …</code>; add <code>record_type</code> (patient, consultation, test, appointment, referral, medication, allergy, history, task, priority) to import clinical records. Priority rows need <code>priority</code> (High/Medium/Low) and a mandatory <code>reason</code>. Patient ID is the primary match key.</p>
      </div>

      {batchId && (batch.isLoading ? <Loading /> : b && (
        <div className="card mt" id="ingReview">
          <div className="row sp"><h2>2 · Review &amp; confirm – {b.filename} <span className="sm mut">{b.id}</span> <Badge s={b.status} /></h2>
            <span className="sm mut">{b.type?.toUpperCase()} · {Math.round((b.size ?? 0) / 102.4) / 10} KB · extraction: {b.method ?? '—'}</span></div>
          <div className="row" style={{ margin: '6px 0' }}>{(['matched', 'new', 'uncertain', 'duplicate', 'invalid'] as const).map((s) => <span key={s} className="sm"><Badge s={s} /> {b.recordList.filter((r) => r.status === s).length}</span>)}</div>
          {b.message && !editable && <p className="sm mut">{b.message}</p>}
          {b.document?.text && <details className="mt2"><summary className="sm"><b>Extracted text</b> (check the PDF extraction)</summary><pre style={{ whiteSpace: 'pre-wrap', background: '#f6f8fb', border: '1px solid var(--line)', borderRadius: 8, padding: 10, maxHeight: 220, overflow: 'auto', fontSize: 12 }}>{b.document.text}</pre></details>}
          {b.recordList.length > 0 && (
            <div className="tw mt"><table className="tbl">
              <thead><tr><th>Row</th><th>Type</th><th>Patient</th><th>Mapped information</th><th>Status</th><th>Checks</th><th>{editable ? 'Decision' : 'Outcome'}</th></tr></thead>
              <tbody>{b.recordList.map((r) => (
                <tr key={r.id}>
                  <td>{r.row}</td><td>{KINDS[r.kind] ?? r.kind}</td>
                  <td>{(r.patientId || r.mapped.patient_id) && <b className="nowrap">{r.patientId || r.mapped.patient_id}</b>}<br /><span className="sm mut">{[r.mapped.first_name, r.mapped.last_name].filter(Boolean).join(' ')}</span></td>
                  <td className="sm">{summary(r)}</td>
                  <td><Badge s={r.status} />{r.decision === 'pending' && <><br /><span className="sm" style={{ color: 'var(--amb)' }}>Decision needed</span></>}
                    {r.result && <><br /><Badge s={r.result === 'saved' ? 'Imported' : r.result === 'failed' ? 'Failed' : 'Cancelled'} /></>}</td>
                  <td className="sm">{r.issues.map((i, k) => <div key={k} style={{ color: i.level === 'error' ? 'var(--red)' : i.level === 'warning' ? 'var(--amb)' : 'var(--mut)' }}>{i.msg}</div>)}</td>
                  <td>{!editable || r.kind === 'unknown' ? <span className="sm mut">{r.message ?? ''}</span> : r.status === 'uncertain' ? (
                    <div><div className="sm mut">Choose the patient:</div>
                      {r.candidates.map((c) => <button key={c.id} className="btn sec s" style={{ margin: '2px 4px 2px 0' }} title={c.reason} onClick={() => decide(r.id, { patientId: c.id, decision: 'import' })}>Link to {c.id} – {c.name}</button>)}
                      {r.kind === 'patient' && <button className="btn sec s" onClick={() => decide(r.id, { patientId: 'NEW', decision: 'import' })}>Create as new patient</button>}
                      <button className="btn ghost s" onClick={() => decide(r.id, { decision: 'skip' })}>Skip</button></div>
                  ) : r.status === 'invalid' ? <button className="btn sec s" onClick={() => setEditing(r)}>Edit fields</button> : (
                    <span className="row" style={{ gap: 6 }}>
                      <label className="sw" style={{ border: 0, padding: 0 }}><input type="checkbox" checked={r.decision === 'import'} onChange={(e) => decide(r.id, { decision: e.target.checked ? 'import' : 'skip' })} /> <span className="sm">Import</span></label>
                      <button className="btn ghost s" onClick={() => setEditing(r)}>Edit</button>
                    </span>
                  )}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
          {editable && (
            <div className="row mt" style={{ justifyContent: 'flex-end' }}>
              {b.pending ? <span className="sm" style={{ color: 'var(--amb)' }}>{b.pending} record(s) need a patient-match decision before you can confirm.</span>
                : <span className="sm mut">{toImport} record(s) will be saved; skipped, duplicate and invalid rows stay in the history.</span>}
              <button className="btn dng s" onClick={() => act.cancel.mutate(b.id, { onSuccess: () => setMsg({ ok: true, text: 'Import cancelled – nothing was saved.' }) })}>Cancel import</button>
              <button className="btn" disabled={!!b.pending || busy} onClick={() => act.confirm.mutate(b.id, {
                onSuccess: (r) => setMsg({ ok: r.result.failed === 0, text: `Import ${r.result.status.toLowerCase()}: ${r.result.imported} saved, ${r.result.skipped} skipped, ${r.result.failed} failed/invalid. Profiles and care gaps are updated.` }),
                onError: (e) => setMsg({ ok: false, text: e.message }),
              })}>Confirm import ({toImport})</button>
            </div>
          )}
          <ErrorBanner error={act.review.error} />
        </div>
      ))}

      <div className="card mt">
        <div className="row sp"><h2>Import history</h2><button className="btn sec s" onClick={() => history.refetch()}>Refresh</button></div>
        {history.isLoading ? <Loading /> : !history.data?.length ? <Empty title="No files imported yet" /> : (
          <div className="tw"><table className="tbl">
            <thead><tr><th>Batch</th><th>File</th><th>Uploaded</th><th>By</th><th>Status</th><th>Records</th><th>Result</th><th></th></tr></thead>
            <tbody>{history.data.map((x) => (
              <tr key={x.id}><td>{x.id}</td><td>{x.filename}<br /><span className="sm mut">{x.type?.toUpperCase()} · {Math.round((x.size ?? 0) / 102.4) / 10} KB</span></td>
                <td>{fmtDateTime(x.uploadedAt)}</td><td>{x.uploadedBy}</td><td><Badge s={x.status} /></td><td>{x.records}</td>
                <td className="sm">{['Rejected', 'Failed'].includes(x.status) ? <span style={{ color: 'var(--red)' }}>{x.message}</span> : `${x.imported} imported · ${x.skipped} skipped · ${x.failed} failed`}</td>
                <td><button className="btn sec s" onClick={() => { setBatchId(x.id); setMsg(null) }}>{x.status === 'Needs Review' ? 'Review' : 'View'}</button></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {editing && <EditRecordDialog rec={editing} onSave={(fields) => { decide(editing.id, { fields }); setEditing(null) }} onClose={() => setEditing(null)} />}
    </>
  )
}

function EditRecordDialog({ rec, onSave, onClose }: { rec: IngestRecord; onSave: (f: Record<string, string | null>) => void; onClose: () => void }) {
  const fields = FIELDS[rec.kind] ?? []
  const [v, setV] = useState<Record<string, string>>(Object.fromEntries(fields.map((k) => [k, rec.mapped[k] ?? ''])))
  const long = (k: string) => /notes|summary|detail|reason|care_plan/.test(k)
  return (
    <Modal title={`Edit extracted fields – row ${rec.row} (${KINDS[rec.kind] ?? rec.kind})`} onClose={onClose}
      footer={<><button className="btn sec" onClick={onClose}>Cancel</button><button className="btn" onClick={() => onSave(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x.trim() || null])))}>Save &amp; re-check</button></>}>
      <p className="sub">Correct anything the extraction got wrong. The record is re-checked for matches and duplicates when you save.</p>
      <div className="fg">{fields.map((k) => (
        <Field key={k} label={LABEL(k)} full={long(k)}>
          {long(k) ? <textarea rows={2} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} /> : <input type="text" value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />}
        </Field>
      ))}</div>
    </Modal>
  )
}
