/** AI Care Assistant – same layout as V2 PAGES.assistant: conversation + suggested questions, and a patient-context panel. */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAgents, useAssistantActions, useChat, usePrompts } from '../api/assistant'
import { usePatient, usePatients } from '../api/hooks'
import { ChatBlock } from '../components/assistant'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Avatar, Banner, ErrorBanner, PageHead, PriorityBadge } from '../components/ui'
import { age, fmtDateTime, fmtDS } from '../lib/format'

export function AssistantPage() {
  const nav = useNavigate()
  const toast = useToast()
  const chat = useChat()
  const prompts = usePrompts()
  const pool = usePatients({ pageSize: 100, sort: 'name' }).data?.items ?? []
  const { ask, clear } = useAssistantActions()
  const agents = useAgents().data
  const aiOn = !!agents?.agents.find((a) => a.name === 'answer' && a.enabled)
  const [q, setQ] = useState('')
  const [ctx, setCtx] = useState('')
  const cp = usePatient(ctx)
  const box = useRef<HTMLDivElement>(null)
  const msgs = chat.data ?? []
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }) }, [msgs.length, ask.isPending])

  /** Send = template agents (no LLM). Ask AI = one Gemini request through the agent orchestrator. */
  const send = (text = q, ai = false) => {
    const t = text.trim()
    if (!t || ask.isPending) return
    setQ('')
    ask.mutate({ text: t, patientId: ctx || undefined, ai }, { onSuccess: (m) => m.patientId && setCtx(m.patientId), onError: (e) => toast(e.message, true) })
  }
  const questionFor = (id: number) => { const i = msgs.findIndex((m) => m.id === id); return i > 0 && msgs[i - 1].role === 'user' ? msgs[i - 1].text : '' }
  const p = ctx ? cp.data : undefined
  const openGaps = (p?.careGaps ?? []).filter((g) => g.status === 'Open')

  return (
    <>
      <PageHead title="CareFlow AI Assistant" sub="Your intelligent companion for coordinated patient care."
        actions={<button className="btn sec" disabled={!msgs.length} onClick={() => clear.mutate(undefined, { onSuccess: () => toast('Conversation cleared') })}>Clear conversation</button>} />
      <Banner warn icon="spark"><b>Grounded assistant.</b> <b>Send</b> answers with deterministic agents (Context → Care-Gap → Summary → Next-Best-Action) – no language model.
        <b> Ask AI</b> sends one request to Gemini with de-identified facts from the records you are authorised to see; the answer is shown only if every
        statement cites an existing source and passes the safety checks, otherwise you get the standard answer. It never diagnoses or prescribes, and
        drafted tasks or reminders need your approval.</Banner>
      <div className="grid g32 mt2">
        <div className="card chat">
          <div className="msgs" aria-live="polite" ref={box}>
            {msgs.length ? msgs.map((m) => m.role === 'user' ? <div key={m.id} className="msg u">{m.text}{m.ai && <span className="tag s" style={{ marginLeft: 6, background: '#fff', color: '#6b45bd' }}>Ask AI</span>}</div> : (
              <div key={m.id} className="msg a">
                <div className="sm b" style={{ color: 'var(--blue)' }}><Icon name="spark" small /> CareFlow AI · {fmtDateTime(m.ts)}
                  {m.ai ? <span className="tag s" style={{ marginLeft: 6 }}>Written by Gemini · {m.model} · checked against records</span> : <span className="sm mut" style={{ marginLeft: 6, fontWeight: 400 }}>standard answer</span>}</div>
                <div className="mt2">{m.text}</div>
                {m.blocks.map((b, i) => <ChatBlock key={i} b={b} />)}
                {m.offerAi && aiOn && questionFor(m.id) && <div className="row mt2"><button className="btn s" disabled={ask.isPending} onClick={() => send(questionFor(m.id), true)}>
                  <Icon name="spark" small /> Ask AI instead</button></div>}
                <details className="trace"><summary>Agent trace ({m.trace.length} steps)</summary><ul>{m.trace.map((t, i) => <li key={i}>{t}</li>)}</ul></details>
              </div>
            )) : <div className="empty"><div className="b">Ask about your patients</div><div className="sm">Answers are grounded in recorded data and cite their sources.</div></div>}
            {ask.isPending && <div className="msg a"><span className="sm mut">Thinking…</span></div>}
          </div>
          <ErrorBanner error={chat.error} />
          <div className="prompts">{(prompts.data ?? []).map((x) => <button key={x} onClick={() => send(x)}>{x}</button>)}</div>
          <div className="compose">
            <textarea rows={2} placeholder="Ask a question or name a patient…" style={{ minHeight: 44 }} value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
            <button className="btn sec" onClick={() => send()} disabled={ask.isPending}><Icon name="send" small /> Send</button>
            {aiOn && <button className="btn" onClick={() => send(q, true)} disabled={ask.isPending || !q.trim()}
              title={agents?.usage ? `${agents.usage.remaining} of ${agents.usage.perHour} AI requests left this hour` : ''}><Icon name="spark" small /> Ask AI</button>}
          </div>
        </div>
        <div className="card">
          <h2>Patient context</h2>
          <div className="field"><label>Patient</label>
            <select value={ctx} onChange={(e) => setCtx(e.target.value)}><option value="">Select a patient…</option>
              {pool.map((x) => <option key={x.id} value={x.id}>{x.firstName} {x.lastName}</option>)}</select></div>
          {p ? (
            <div className="mt">
              <div className="row"><Avatar name={`${p.firstName} ${p.lastName}`} /><div><b>{p.firstName} {p.lastName}</b><br /><span className="sm mut">{p.id} · {age(p.dob)} · {p.primaryCondition}</span></div></div>
              <dl className="kv mt2" style={{ gridTemplateColumns: '100px 1fr' }}>
                <dt>Priority</dt><dd><PriorityBadge p={p.priority} /></dd><dt>Doctor</dt><dd>{p.doctorName ?? '—'}</dd>
                <dt>Next appt</dt><dd>{p.nextAppt ? fmtDS(p.nextAppt.date) : 'None'}</dd></dl>
              <h3 className="mt2">Open care gaps</h3>
              {openGaps.length ? <div className="list">{openGaps.map((g) => <div key={g.id}><span className="grow sm">{g.category}</span><PriorityBadge p={g.priority} /></div>)}</div>
                : <div className="sm mut">None detected.</div>}
              <div className="row mt">
                <button className="btn s" onClick={() => nav(`/patients/${p.id}`)}>Open profile</button>
                <button className="btn sec s" onClick={() => send(`Summarise ${p.firstName} ${p.lastName}’s patient journey`)}>Summarise</button>
              </div>
            </div>
          ) : <p className="sm mut mt2">Select a patient to see their context here. Naming a patient in a question sets this automatically.</p>}
        </div>
      </div>
    </>
  )
}
