/* ================= service layer (swap for real APIs / FHIR later) ================= */
/* Each service maps to a FHIR resource family noted in comments, so a backend can replace it behind the same interface. */

/* ---- Patient management (FHIR Patient) ---- */
const PatientSvc={
 appts:pid=>DB.appointments.filter(a=>a.patientId===pid),
 /* last visit = latest completed appointment OR recorded consultation (imported consultations have no appointment row) */
 lastVisit:pid=>{const T=todayISO();const l=DB.appointments.filter(a=>a.patientId===pid&&a.status==='Completed').map(a=>a.date).concat(DB.consultations.filter(c=>c.patientId===pid&&c.date&&c.date<=T).map(c=>c.date)).sort().pop();return l||null},
 nextAppt:pid=>{const T=todayISO();return DB.appointments.filter(a=>a.patientId===pid&&['Scheduled','Confirmed'].includes(a.status)&&a.date>=T).sort((a,b)=>(a.date+a.time).localeCompare(b.date+b.time))[0]||null},
 doctor:p=>userById(p.doctorId),coord:p=>userById(p.coordId),
 /* V2: priority is a STORED value changed only by a Care Coordinator or Doctor (POST /api/priority, with a mandatory comment).
   The care-gap engine and the AI never change it – they can only suggest (suggestedPriority). */
 priority(pid){const p=patientById(pid);return (p&&p.priority)||'med'},
 suggestedPriority(pid){const g=openGapsFor(pid);if(g.some(x=>x.priority==='high'))return 'high';if(g.some(x=>x.priority==='med'))return 'med';return 'low'},
 priorityLog:pid=>(DB.priorityHistory||[]).filter(h=>h.patientId===pid).sort((a,b)=>a.id-b.id),
 status(p){if(p.discharged)return 'Discharged';if(DB.tests.some(t=>t.patientId===p.id&&['Ordered','Scheduled','Completed','Result Available'].includes(t.status)))return 'Awaiting results';
   if(p.reviewDue||PatientSvc.nextAppt(p.id))return 'Under follow-up';return 'Active'},
 followUpStatus(p){if(p.discharged)return 'Discharged – none required';if(GAPS.some(g=>g.patientId===p.id&&g.rule==='overdue_followup'&&alertOpen(g)))return 'Follow-up overdue';if(PatientSvc.nextAppt(p.id))return 'Follow-up scheduled';return 'No follow-up scheduled'}
};

/* ---- Appointments (FHIR Appointment) ---- */
const ApptSvc={
 byId:id=>DB.appointments.find(a=>a.id===id),
 active:a=>['Scheduled','Confirmed'].includes(a.status),
 free(doctorId,date,time,ignoreId){return !DB.appointments.some(a=>a.id!==ignoreId&&a.doctorId===doctorId&&a.date===date&&a.time===time&&ApptSvc.active(a))},
 slots(doctorId,date,ignoreId){return SLOTS.filter(t=>ApptSvc.free(doctorId,date,t,ignoreId))},
 book(f){
  if(!ApptSvc.free(f.doctorId,f.date,f.time))return {error:'That slot is already booked for this doctor.'};
  const p=patientById(f.patientId);
  const a={id:nextId('APT'),patientId:f.patientId,doctorId:f.doctorId,dept:f.dept||p.department,date:f.date,time:f.time,type:f.type,status:'Scheduled',createdOn:nowISO(),notes:f.notes||'',bookedBy:me().id};
  DB.appointments.push(a);ReminderSvc.scheduleForAppt(a);
  audit('Appointment booked',{pid:a.patientId,entity:a.id,detail:fmtD(a.date)+' '+a.time+' · '+a.type});
  if(me().role!=='doctor')notify({toUser:a.doctorId,title:'Appointment booked',text:pFull(p)+' – '+fmtD(a.date)+' '+a.time,route:'appointments',patientId:p.id});
  return {appt:a}},
 reschedule(id,date,time,reason){const a=ApptSvc.byId(id);if(!ApptSvc.free(a.doctorId,date,time,id))return{error:'That slot is already booked for this doctor.'};const old=a.date+' '+a.time;a.date=date;a.time=time;a.status='Scheduled';a.notes=(a.notes?a.notes+' | ':'')+'Rescheduled from '+old+(reason?': '+reason:'');
  ReminderSvc.dropScheduled('Appointment',id);ReminderSvc.scheduleForAppt(a);audit('Appointment rescheduled',{pid:a.patientId,entity:id,detail:old+' → '+date+' '+time});return{appt:a}},
 cancel(id,reason){const a=ApptSvc.byId(id);a.status='Cancelled';a.notes=(a.notes?a.notes+' | ':'')+'Cancelled: '+(reason||'no reason given');ReminderSvc.dropScheduled('Appointment',id);audit('Appointment cancelled',{pid:a.patientId,entity:id,detail:reason||''})},
 confirm(id){const a=ApptSvc.byId(id);a.status='Confirmed';DB.reminders.filter(r=>r.refId===id&&['Delivered','Sent'].includes(r.status)).slice(-1).forEach(r=>r.status='Confirmed');audit('Appointment confirmed',{pid:a.patientId,entity:id,detail:'Patient confirmation recorded'})},
 complete(id){const a=ApptSvc.byId(id);a.status='Completed';audit('Appointment completed',{pid:a.patientId,entity:id,detail:a.type})},
 miss(id){const a=ApptSvc.byId(id);a.status='Missed';audit('Appointment marked missed',{pid:a.patientId,entity:id,detail:fmtD(a.date)});const p=patientById(a.patientId);
  notify({toUser:a.doctorId,title:'Patient missed appointment',text:pFull(p)+' did not attend on '+fmtD(a.date)+'.',route:'patient/'+p.id,patientId:p.id,level:'high'});
  Comms.log({direction:'To Doctor',category:'Missed Appointments',recipientId:a.doctorId,patientId:p.id,message:pFull(p)+' did not attend the appointment on '+fmtD(a.date)+'.',channel:'App'})}
};

/* ---- Diagnostics (FHIR ServiceRequest / Observation / DiagnosticReport) ---- */
const TestSvc={
 byId:id=>DB.tests.find(t=>t.id===id),
 order(f){const p=patientById(f.patientId);const t={id:nextId('TST'),patientId:f.patientId,name:f.name,orderedBy:me().id,orderedOn:todayISO(),scheduledDate:null,status:'Ordered',completedOn:null,resultOn:null,reviewedOn:null,reviewedBy:null,reviewNote:'',abnormal:false,result:null,priority:f.priority||'Routine',notes:f.notes||''};
  DB.tests.push(t);audit('Diagnostic test requested',{pid:p.id,entity:t.id,detail:t.name+' ('+t.priority+')'});
  const k=TaskSvc.create({title:'Schedule '+t.name+' for '+pFull(p),patientId:p.id,priority:t.priority==='Urgent'?'high':'med',assignee:p.coordId,due:addDays(todayISO(),t.priority==='Urgent'?1:3),kind:'test',source:'Doctor test request',desc:'Requested by '+me().name+(t.notes?'. Notes: '+t.notes:''),testId:t.id},true);
  notify({toUser:p.coordId,title:'Test requested – task created',text:t.name+' for '+pFull(p),route:'tasks',patientId:p.id});return{test:t,task:k}},
 schedule(id,date){const t=TestSvc.byId(id);t.scheduledDate=date;t.status='Scheduled';ReminderSvc.scheduleForTest(t);audit('Diagnostic test scheduled',{pid:t.patientId,entity:id,detail:t.name+' on '+fmtD(date)})},
 complete(id){const t=TestSvc.byId(id);t.status='Completed';t.completedOn=todayISO();audit('Patient completed test',{pid:t.patientId,entity:id,detail:t.name});
  notify({toUser:t.orderedBy,title:'Patient completed test',text:t.name+' – '+pLabel(t.patientId)+'. Result pending.',route:'tests',patientId:t.patientId})},
 simulateResult(id,abn){const t=TestSvc.byId(id);t.status='Result Available';t.resultOn=todayISO();t.abnormal=!!abn;t.result=genResult(t.name,!!abn);t.resultAt=nowISO();
  audit('Result received (simulated feed)',{pid:t.patientId,entity:id,detail:t.name+(abn?' – values outside reference range':'')});
  notify({toUser:t.orderedBy,title:abn?'Abnormal result flagged for review':'Diagnostic result available',text:t.name+' – '+pLabel(t.patientId),route:'tests',patientId:t.patientId,level:abn?'high':'info'});
  Comms.log({direction:'To Doctor',category:'Pending Test Results',recipientId:t.orderedBy,patientId:t.patientId,message:t.name+' result is available for review.',channel:'App'})},
 review(id,note){const t=TestSvc.byId(id);t.status='Reviewed';t.reviewedOn=todayISO();t.reviewedAt=nowISO();t.reviewedBy=me().id;t.reviewNote=note||'';audit('Result reviewed by doctor',{pid:t.patientId,entity:id,detail:t.name+(note?' – '+note:'')})}
};

/* ---- Tasks ---- */
const TaskSvc={
 byId:id=>DB.tasks.find(t=>t.id===id),
 create(f,silent){const k={id:nextId('TSK'),title:f.title,patientId:f.patientId||null,priority:f.priority||'med',assignee:f.assignee,created:todayISO(),due:f.due,status:f.status||'New',kind:f.kind||'followup',source:f.source||'Manual',desc:f.desc||'',completedOn:null,alertId:f.alertId||null,testId:f.testId||null,
  history:[{ts:nowISO(),by:me()?me().name:'System',text:'Task created ('+(f.source||'Manual')+') and assigned to '+(userById(f.assignee)||{}).name}]};
  DB.tasks.push(k);audit('Task created',{pid:k.patientId,entity:k.id,detail:k.title+' → '+(userById(k.assignee)||{}).name+' ('+k.source+')'});
  if(f.assignee&&me()&&f.assignee!==me().id)notify({toUser:f.assignee,title:'New task assigned',text:k.title,route:'tasks',patientId:k.patientId});return k},
 update(id,patch,text){const k=TaskSvc.byId(id);const before=k.status;Object.assign(k,patch);if(patch.status==='Completed'&&before!=='Completed')k.completedOn=todayISO();if(patch.status&&patch.status!=='Completed')k.completedOn=null;
  k.history.push({ts:nowISO(),by:me().name,text:text||'Task updated'});audit('Task updated',{pid:k.patientId,entity:id,detail:text||''})},
 setStatus(id,st){const k=TaskSvc.byId(id);if(k.status===st)return;TaskSvc.update(id,{status:st},'Status: '+k.status+' → '+st)},
 reassign(id,uid){const k=TaskSvc.byId(id);const old=(userById(k.assignee)||{}).name;TaskSvc.update(id,{assignee:uid},'Reassigned '+old+' → '+userById(uid).name);if(uid!==me().id)notify({toUser:uid,title:'Task reassigned to you',text:k.title,route:'tasks',patientId:k.patientId})}
};

/* ---- Referrals (FHIR ServiceRequest) ---- */
const RefSvc={create(f){const r={id:nextId('REF'),patientId:f.patientId,to:f.to,reason:f.reason,status:'Pending',createdOn:todayISO(),by:me().id};DB.referrals.push(r);audit('Referral created',{pid:r.patientId,entity:r.id,detail:r.to});return r},
 setStatus(id,st){const r=DB.referrals.find(x=>x.id===id);r.status=st;audit('Referral '+st.toLowerCase(),{pid:r.patientId,entity:id,detail:r.to})}};

/* ---- Notifications, reminders & messages (simulated delivery) ---- */
const Comms={log(f){const rec=f.recipientId?userById(f.recipientId):null;DB.comms.unshift({id:nextId('MSG'),ts:nowISO(),direction:f.direction,category:f.category,recipient:f.recipient||(rec?rec.name:(patientById(f.patientId)?pFull(patientById(f.patientId)):'—')),recipientId:f.recipientId||null,patientId:f.patientId||null,message:f.message,channel:f.channel,status:f.status||'Sent',sender:me()?me().name:'System',simulated:true})}};
const ReminderSvc={
 offsets:{'7d':7*864e5,'3d':3*864e5,'1d':864e5,'2h':2*36e5},
 scheduleForAppt(a){const cfg=DB.settings.reminders;const chs=Object.keys(cfg.channels).filter(c=>cfg.channels[c]);if(!chs.length)return;const when=dtOf(a.date,a.time);let i=0;
  Object.entries(ReminderSvc.offsets).forEach(([o,ms])=>{if(!cfg.offsets[o])return;const sch=new Date(when-ms);if(sch<new Date())return;
   DB.reminders.push({id:nextId('REM'),kind:'Appointment',refId:a.id,patientId:a.patientId,offset:o,channel:chs[i++%chs.length],scheduledFor:sch.toISOString(),status:'Scheduled',sentAt:null,label:'Appointment reminder ('+o+' before)',message:'Reminder: appointment on '+fmtD(a.date)+' at '+a.time+'.',simulated:true})})},
 scheduleForTest(t){const when=dtOf(t.scheduledDate,'08:00');const chs=Object.keys(DB.settings.reminders.channels).filter(c=>DB.settings.reminders.channels[c]);if(!chs.length)return;
  DB.reminders=DB.reminders.filter(r=>!(r.kind==='Diagnostic Test'&&r.refId===t.id&&r.status==='Scheduled'));
  [['1d',864e5],['2h',2*36e5]].forEach(([o,ms],i)=>{const sch=new Date(when-ms);if(sch<new Date())return;DB.reminders.push({id:nextId('REM'),kind:'Diagnostic Test',refId:t.id,patientId:t.patientId,offset:o,channel:chs[i%chs.length],scheduledFor:sch.toISOString(),status:'Scheduled',sentAt:null,label:t.name+' reminder ('+o+' before)',message:t.name+' scheduled on '+fmtD(t.scheduledDate)+'. Please attend as arranged.',simulated:true})})},
 dropScheduled(kind,refId){DB.reminders=DB.reminders.filter(r=>!(r.kind===kind&&r.refId===refId&&r.status==='Scheduled'))},
 manual(f){const r={id:nextId('REM'),kind:f.kind||'Manual',refId:f.refId||null,patientId:f.patientId,offset:'manual',channel:f.channel,scheduledFor:nowISO(),status:'Sent',sentAt:nowISO(),label:f.label||'Manual reminder',message:f.message,simulated:true};DB.reminders.unshift(r);
  Comms.log({direction:'To Patient',category:f.category||'Appointment Reminders',patientId:f.patientId,message:f.message,channel:f.channel,status:'Sent'});audit('Reminder sent (simulated)',{pid:f.patientId,entity:r.id,detail:f.channel+' · '+f.message.slice(0,70)});
  setTimeout(()=>{if(r.status==='Sent'){r.status=hashStr(r.id)%9===0?'Failed':'Delivered';const m=DB.comms.find(c=>c.patientId===r.patientId&&c.message===r.message&&c.status==='Sent');if(m)m.status=r.status;commit()}},1400);return r},
 deliver(r){const fail=hashStr(r.id)%9===0;r.status=fail?'Failed':'Delivered';r.sentAt=r.sentAt||nowISO();Comms.log({direction:'To Patient',category:r.kind==='Diagnostic Test'?'Diagnostic Test Reminders':'Appointment Reminders',patientId:r.patientId,message:r.message,channel:r.channel,status:r.status})},
 processDue(force){let n=0;DB.reminders.forEach(r=>{if(r.status==='Scheduled'&&(force||new Date(r.scheduledFor)<=new Date())){ReminderSvc.deliver(r);n++}});if(n)audit('Reminder delivery simulation run',{detail:n+' due reminder(s) processed (simulated)'});return n},
 confirm(id){const r=DB.reminders.find(x=>x.id===id);r.status='Confirmed';if(r.kind==='Appointment'&&r.refId){const a=ApptSvc.byId(r.refId);if(a&&a.status==='Scheduled')ApptSvc.confirm(a.id)}audit('Patient confirmation recorded',{pid:r.patientId,entity:id,detail:r.label})}
};

/* ---- Consultations & prescriptions (FHIR Encounter / MedicationRequest / CarePlan) ---- */
const ConsultSvc={
 save(f){const p=patientById(f.patientId);const c={id:nextId('CON'),patientId:p.id,doctorId:me().id,date:f.date,notes:f.notes,diagnosis:f.diagnosis||'',prescription:f.prescription||'',plan:f.plan||'',followUp:f.followUp||null,instructions:f.instructions||'',createdOn:nowISO()};
  DB.consultations.push(c);if(f.plan)p.treatmentPlan=f.plan;if(f.followUp)p.reviewDue=f.followUp;
  if(f.prescription){DB.prescriptions.push({id:nextId('RX'),patientId:p.id,drug:f.prescription,prescribedBy:me().id,date:f.date,refillDue:addDays(f.date,28),status:'Active',doctorEntered:true});audit('Prescription recorded (doctor-entered)',{pid:p.id,entity:c.id,detail:f.prescription})}
  audit('Consultation notes saved',{pid:p.id,entity:c.id,detail:(f.diagnosis?'Dx: '+f.diagnosis+' · ':'')+(f.followUp?'follow-up '+fmtD(f.followUp):'')});
  if(f.makeTask&&f.followUp){TaskSvc.create({title:'Arrange follow-up appointment for '+fmtD(f.followUp),patientId:p.id,priority:'med',assignee:p.coordId,due:addDays(f.followUp,-3),kind:'followup',source:'Doctor consultation',desc:'Requested by '+me().name+'.'+(f.instructions?' Instructions: '+f.instructions:'')},true)}
  return c},
 outcome(pid,status,note,discharge){const p=patientById(pid);p.outcome={status,note,date:todayISO(),by:me().id};if(discharge)p.discharged=true;audit('Clinical outcome recorded',{pid,entity:pid,detail:status+(discharge?' · discharged':'')})}
};

/* ================= Care-gap detection: deterministic, configurable, explainable ================= */
const RULE_DEFS=[
 {id:'missed_appt',cat:'Missed Appointments',name:'Missed appointment with no later appointment',desc:'An appointment is marked Missed and the patient has no later scheduled, confirmed or completed appointment.'},
 {id:'overdue_followup',cat:'Overdue Follow-ups',name:'Review date passed without consultation',desc:'The recorded review date has passed (plus grace days), no completed appointment exists on/after it and none is scheduled.'},
 {id:'pending_test',cat:'Pending Diagnostic Tests',name:'Test not scheduled or not completed',desc:'A test is Ordered but unscheduled for N days, or Scheduled with a date that has passed without completion.'},
 {id:'referral',cat:'Outstanding Referrals',name:'Referral pending beyond threshold',desc:'A referral is still Pending after N days.'},
 {id:'results_review',cat:'Results Awaiting Doctor Review',name:'Result available but not reviewed',desc:'A result is available and no doctor review is recorded. Priority depends on whether values fall outside the reference range.'},
 {id:'med_adherence',cat:'Potential Medication Adherence Concerns',name:'Prescription refill overdue or due soon',desc:'The recorded refill date has passed with no renewal, or falls inside the renewal window. This is a prompt for review, not a clinical judgement.'},
 {id:'incomplete',cat:'Incomplete Care Activities',name:'Overdue task or unconfirmed upcoming appointment',desc:'A task is past its due date, or an appointment within N days is still unconfirmed.'}];
function computeGaps(){
 const R=DB.settings.rules,T=todayISO(),out=[];const en=R.enabled,pr=R.priorities;
 const add=(rule,p,entity,priority,reason,evidence,action,assignee)=>{const def=RULE_DEFS.find(x=>x.id===rule);out.push({id:'ALR-'+rule+'-'+entity,rule,cat:def.cat,ruleName:def.name,patientId:p.id,priority,reason,evidence,action,assignee:assignee||p.coordId,entity})};
 const refA=a=>({ref:a.id,text:'Appointment '+fmtD(a.date)+' '+a.time+' ('+a.type+') – status '+a.status,ts:a.createdOn||a.date});
 for(const p of DB.patients){if(p.draft||p.discharged)continue;const appts=DB.appointments.filter(a=>a.patientId===p.id);const later=(d0)=>appts.some(a=>a.date>d0&&['Scheduled','Confirmed','Completed'].includes(a.status));
  if(en.missed_appt)appts.filter(a=>a.status==='Missed'&&!later(a.date)).forEach(a=>add('missed_appt',p,a.id,pr.missed_appt,'The appointment on '+fmtD(a.date)+' was missed and no later appointment is recorded.',[refA(a),{ref:p.id,text:'No scheduled, confirmed or completed appointment after '+fmtD(a.date),ts:nowISO()}],{type:'task',title:'Contact patient and rebook missed appointment',text:'Contact the patient and rebook the missed appointment.',kind:'contact',due:addDays(T,1)}));
  if(en.overdue_followup&&p.reviewDue&&p.reviewDue<addDays(T,-R.followupGraceDays)){const done=appts.some(a=>a.status==='Completed'&&a.date>=p.reviewDue),fut=appts.some(a=>['Scheduled','Confirmed'].includes(a.status)&&a.date>=T);
   if(!done&&!fut)add('overdue_followup',p,p.id+'-'+p.reviewDue,pr.overdue_followup,"The patient's scheduled review date ("+fmtD(p.reviewDue)+', '+dayDiff(T,p.reviewDue)+' days ago) has passed and no completed consultation or future appointment is recorded.',[{ref:p.id,text:'Review due '+fmtD(p.reviewDue),ts:p.reviewDue},{ref:'APT',text:'Last completed visit: '+fmtD(PatientSvc.lastVisit(p.id)),ts:PatientSvc.lastVisit(p.id)||p.registeredOn}],{type:'task',title:'Contact patient and arrange follow-up appointment',text:'Contact the patient and arrange a follow-up appointment.',kind:'followup',due:addDays(T,1)})}
  if(en.pending_test)DB.tests.filter(t=>t.patientId===p.id).forEach(t=>{const refT={ref:t.id,text:t.name+' – status '+t.status+', ordered '+fmtD(t.orderedOn)+(t.scheduledDate?', scheduled '+fmtD(t.scheduledDate):''),ts:t.orderedOn};
   if(t.status==='Ordered'&&dayDiff(T,t.orderedOn)>=R.testPendingDays)add('pending_test',p,t.id,pr.pending_test,t.name+' was ordered '+dayDiff(T,t.orderedOn)+' days ago and has not been scheduled.',[refT],{type:'task',title:'Schedule '+t.name+' with patient',text:'Contact the patient to schedule the '+t.name+'.',kind:'test',due:addDays(T,1)});
   if(t.status==='Scheduled'&&t.scheduledDate<T)add('pending_test',p,t.id,pr.pending_test,t.name+' was scheduled for '+fmtD(t.scheduledDate)+' but no completion is recorded.',[refT],{type:'task',title:'Confirm whether '+t.name+' was completed',text:'Check with the patient/provider whether the '+t.name+' took place and rebook if not.',kind:'test',due:addDays(T,1)})});
  if(en.results_review)DB.tests.filter(t=>t.patientId===p.id&&t.status==='Result Available').forEach(t=>add('results_review',p,t.id,t.abnormal?pr.results_abnormal:pr.results_normal,t.name+' result available since '+fmtD(t.resultOn)+(t.abnormal?'; one or more values fall outside the reference range.':'.')+' No doctor review recorded.',[{ref:t.id,text:t.name+' result – '+(t.abnormal?'values outside reference range flagged':'within reference range'),ts:t.resultAt||t.resultOn}],{type:'task',title:'Review '+t.name+' result',text:'Doctor to review the '+t.name+' result.',kind:'review',due:T},p.doctorId));
  if(en.referral)DB.referrals.filter(r=>r.patientId===p.id&&r.status==='Pending'&&dayDiff(T,r.createdOn)>=R.referralDays).forEach(r=>add('referral',p,r.id,pr.referral,'Referral to '+r.to+' has been pending for '+dayDiff(T,r.createdOn)+' days (threshold '+R.referralDays+').',[{ref:r.id,text:'Referral to '+r.to+' created '+fmtD(r.createdOn)+' – Pending',ts:r.createdOn}],{type:'task',title:'Chase referral: '+r.to,text:'Contact the receiving service and confirm a booking date for the referral.',kind:'referral',due:addDays(T,2)}));
  if(en.med_adherence)DB.prescriptions.filter(x=>x.patientId===p.id&&x.status==='Active').forEach(x=>{const dd=dayDiff(x.refillDue,T);
   if(dd<0)add('med_adherence',p,x.id,pr.med_adherence,'Refill for "'+x.drug+'" was due '+fmtD(x.refillDue)+' and no renewal is recorded – possible adherence concern.',[{ref:x.id,text:x.drug+' – refill due '+fmtD(x.refillDue)+', no renewal recorded',ts:x.date}],{type:'task',title:'Check prescription renewal with patient',text:'Contact the patient about the overdue prescription refill and ask the doctor to review renewal.',kind:'medication',due:addDays(T,1)});
   else if(dd<=R.medRefillWindowDays)add('med_adherence',p,x.id,pr.med_adherence,'Prescription renewal for "'+x.drug+'" falls due on '+fmtD(x.refillDue)+' (within '+R.medRefillWindowDays+' days).',[{ref:x.id,text:x.drug+' – refill due '+fmtD(x.refillDue),ts:x.date}],{type:'task',title:'Prepare prescription renewal review',text:'Flag the upcoming renewal to the doctor for review.',kind:'medication',due:addDays(x.refillDue,-2)})});
  if(en.incomplete){DB.tasks.filter(k=>k.patientId===p.id&&k.status!=='Completed'&&k.due<addDays(T,-R.taskGraceDays)).forEach(k=>add('incomplete',p,k.id,pr.incomplete,'Task "'+k.title+'" was due '+fmtD(k.due)+' and is still '+k.status+'.',[{ref:k.id,text:'Task due '+fmtD(k.due)+' – '+k.status,ts:k.created}],{type:'task',title:'Complete or reassign overdue task: '+k.title,text:'Complete or reassign the overdue task.',kind:'admin',due:T},k.assignee));
   appts.filter(a=>a.status==='Scheduled'&&a.date>=T&&dayDiff(a.date,T)<=R.confirmWindowDays).forEach(a=>add('incomplete',p,a.id,pr.incomplete,'Appointment on '+fmtD(a.date)+' '+a.time+' is within '+R.confirmWindowDays+' days and the patient has not confirmed.',[refA(a)],{type:'task',title:'Call patient to confirm appointment',text:'Call the patient to confirm the upcoming appointment.',kind:'contact',due:addDays(a.date,-1)}))}}
 return out.sort((a,b)=>PRI[a.priority]-PRI[b.priority]);
}
function syncAlerts(){
 const gaps=computeGaps(),seen=new Set();
 gaps.forEach(g=>{seen.add(g.id);let s=DB.alertState[g.id];if(!s)s=DB.alertState[g.id]={firstSeen:nowISO(),status:'Open'};
  if(s.status==='Resolved'){s.status='Open';delete s.resolvedOn}s.snap={patientId:g.patientId,cat:g.cat,reason:g.reason,priority:g.priority,ruleName:g.ruleName}});
 Object.entries(DB.alertState).forEach(([id,s])=>{if(!seen.has(id)&&(s.status==='Open'||s.status==='Actioned')){s.status='Resolved';s.resolvedOn=nowISO();audit('Care gap resolved automatically',{pid:s.snap&&s.snap.patientId,entity:id,detail:'Rule no longer fires – '+(s.snap?s.snap.reason:'')})}});
 GAPS=gaps;
}
const alertState=g=>DB.alertState[g.id]||{status:'Open'};
const alertOpen=g=>alertState(g).status==='Open';
const openGapsFor=pid=>GAPS.filter(g=>g.patientId===pid&&alertOpen(g));
const gapsFor=pid=>GAPS.filter(g=>g.patientId===pid&&alertState(g).status!=='Dismissed');
function approveGap(gid,over={}){
 const g=GAPS.find(x=>x.id===gid);if(!g)return null;const s=alertState(g);if(s.taskId&&TaskSvc.byId(s.taskId)&&TaskSvc.byId(s.taskId).status!=='Completed')return TaskSvc.byId(s.taskId);
 const a=g.action,p=patientById(g.patientId);
 const k=TaskSvc.create({title:over.title||(a.title+' – '+pFull(p)),patientId:p.id,priority:over.priority||g.priority,assignee:over.assignee||s.assignee||g.assignee,due:over.due||a.due,kind:a.kind,source:'Care-gap alert (approved)',desc:(over.text||a.text)+' Rule: '+g.ruleName+'. Approved by '+me().name+'.',alertId:g.id},true);
 s.status='Actioned';s.taskId=k.id;s.assignee=k.assignee;s.actionedBy=me().id;s.actionedOn=nowISO();
 audit(over.title?'Recommendation modified and approved':'Recommendation approved',{pid:p.id,entity:g.id,detail:g.cat+' → task '+k.id+' ('+(userById(k.assignee)||{}).name+')'});return k}
function dismissGap(gid,reason){const g=GAPS.find(x=>x.id===gid);const s=DB.alertState[gid];s.status='Dismissed';s.dismissReason=reason;s.dismissedBy=me().id;audit('Alert dismissed',{pid:g.patientId,entity:gid,detail:g.cat+' – '+reason})}

/* ================= AI agents (prototype: deterministic templates; NO LLM connected) ================= */
/* Context Agent → Care-Gap Agent → Summary Agent → Next-Best-Action Agent. In production, the summary
   agent would call an LLM (e.g. Azure OpenAI) over retrieved FHIR records; rules stay deterministic. */
const AI={
 context(pid){const p=patientById(pid);return{p,appts:DB.appointments.filter(a=>a.patientId===pid).sort((a,b)=>(a.date+a.time).localeCompare(b.date+b.time)),tests:DB.tests.filter(t=>t.patientId===pid),refs:DB.referrals.filter(r=>r.patientId===pid),rx:DB.prescriptions.filter(r=>r.patientId===pid),
  cons:DB.consultations.filter(c=>c.patientId===pid).sort((a,b)=>a.date.localeCompare(b.date)),tasks:DB.tasks.filter(t=>t.patientId===pid),docs:(DB.documents||[]).filter(d=>d.patientId===pid)}},
 careGaps:pid=>gapsFor(pid),
 brief(pid){
  const cx=AI.context(pid),p=cx.p,T=todayISO(),srcs=[],S=(ref,label,ts)=>{let i=srcs.findIndex(s=>s.ref===ref);if(i<0){srcs.push({ref,label,ts});i=srcs.length-1}return i+1};
  const f=(t,src,k)=>({t,k:k||'fact',src:src||[]});const B={context:[],history:[],gaps:[],appts:[],results:[],evidence:[],next:[]};
  const doc=PatientSvc.doctor(p);
  B.context.push(f(pFull(p)+', '+ageOf(p.dob)+', '+p.gender+'. Primary condition: '+p.primary+(p.secondary&&p.secondary!=='None'?'; also '+p.secondary:'')+'. Department: '+p.department+'.',[S(p.id,'Patient record',p.registeredOn)]));
  B.context.push(f('Assigned doctor: '+(doc?doc.name:'not recorded')+'. Registered '+fmtD(p.registeredOn)+'. Current treatment plan: '+p.treatmentPlan+'.',[S(p.id,'Patient record',p.registeredOn)]));
  {const pl=PatientSvc.priorityLog(pid),lp=pl[pl.length-1],cur=PatientSvc.priority(pid),sug=PatientSvc.suggestedPriority(pid),W={high:'High',med:'Medium',low:'Low'};
   B.context.push(f('Current priority: '+W[cur]+(lp?' – set by '+lp.user+' ('+(ROLE_NAME[lp.role]||lp.role)+') on '+fmtDT(lp.at)+': “'+lp.comment+'”.':'.'),[S('PRI-'+(lp?lp.id:p.id),'Priority history',lp?lp.at:p.registeredOn)]));
   if(sug!==cur)B.context.push(f('Open care gaps would suggest '+W[sug]+' priority. This is advisory only – priority is changed solely by a Care Coordinator or Doctor, with a comment.',[S('RULES','Care-gap rule engine',nowISO())],'suggestion'))}
  if(p.outcome)B.context.push(f('Clinician-recorded outcome: '+p.outcome.status+' ('+fmtD(p.outcome.date)+').',[S(p.id,'Patient record',p.outcome.date)]));
  const lc=cx.cons[cx.cons.length-1];
  B.history.push(f('Previous diagnoses: '+p.prevDx+'. Previous surgeries: '+p.prevSurg+'. Family history: '+p.famHist+'.',[S(p.id,'Patient record',p.registeredOn)]));
  if(lc)B.history.push(f('Latest consultation note ('+fmtD(lc.date)+(lc.srcBatch?', imported from file '+lc.srcBatch:'')+'): '+lc.notes,[S(lc.id,'Consultation',lc.createdOn)]));
  cx.docs.forEach(d=>B.history.push(f('Imported document “'+d.filename+'” ('+d.docType+', imported '+fmtD(d.uploadedAt.slice(0,10))+', extracted by '+d.method+'). Extract: '+(d.text||'').replace(/\s+/g,' ').slice(0,260)+'…',[S(d.id,'Imported document',d.uploadedAt)])));
  if(p.allergies&&p.allergies!=='None recorded'&&p.allergies!=='None')B.history.push(f('Recorded allergy: '+p.allergies+'.',[S(p.id,'Patient record',p.registeredOn)]));else B.history.push(f('Allergy status is not recorded in the available data.',[],'missing'));
  if(p.meds&&p.meds!=='None')B.history.push(f('Existing medication (as recorded): '+p.meds+'.',[S(p.id,'Patient record',p.registeredOn)]));
  const lv=PatientSvc.lastVisit(pid);if(lv)B.history.push(f('Last completed visit: '+fmtD(lv)+'.',[S(cx.appts.filter(a=>a.status==='Completed').pop().id,'Appointment',lv)]));else B.history.push(f('No completed visit is recorded.',[],'missing'));
  const gs=gapsFor(pid);
  if(!gs.length)B.gaps.push(f('No outstanding care gaps are detected by the current rules.',[S('RULES','Care-gap rule engine',nowISO())]));
  gs.forEach(g=>B.gaps.push(f('['+g.cat+'] '+g.reason+(alertState(g).status==='Actioned'?' (action in progress)':''),g.evidence.map(e=>S(e.ref,'Record',e.ts)))));
  const up=cx.appts.filter(a=>['Scheduled','Confirmed'].includes(a.status)&&a.date>=T);
  if(up.length)up.forEach(a=>B.appts.push(f('Upcoming: '+fmtDS(a.date)+' '+a.time+' with '+(userById(a.doctorId)||{}).name+' ('+a.type+', '+a.status+').',[S(a.id,'Appointment',a.createdOn)])));else B.appts.push(f('No upcoming appointment is recorded.',[S('APT','Appointment register',nowISO())],'missing'));
  const pend=cx.tests.filter(t=>t.status!=='Reviewed');if(!pend.length)B.results.push(f('No pending diagnostic results.',[]));
  pend.forEach(t=>B.results.push(f(t.name+(t.srcBatch?' (imported)':'')+': '+t.status+(t.status==='Result Available'?(t.abnormal?' – values outside reference range, awaiting doctor review.':' – awaiting doctor review.'):'.'),[S(t.id,'Diagnostic test',t.resultAt||t.orderedOn)])));
  cx.refs.filter(r=>r.status!=='Completed').forEach(r=>B.results.push(f('Referral to '+r.to+': '+r.status+' (created '+fmtD(r.createdOn)+').',[S(r.id,'Referral',r.createdOn)])));
  if(!p.email)B.history.push(f('No email address is recorded for this patient.',[],'missing'));
  const ev=srcs;B.evidence=ev.map((s,i)=>({n:i+1,...s}));
  gs.filter(g=>alertOpen(g)).forEach(g=>B.next.push({gapId:g.id,t:g.action.text+' ('+g.cat+')',k:'suggestion',src:g.evidence.map(e=>S(e.ref,'Record',e.ts)),priority:g.priority}));
  if(!B.next.length)B.next.push({t:'No coordination action is suggested at this time.',k:'suggestion',src:[]});
  B.evidence=srcs.map((s,i)=>({n:i+1,...s}));B.generatedAt=nowISO();return B},
 generate(pid){const B=AI.brief(pid);audit('AI summary generated',{pid,detail:'Prototype summary agent (template-based) · '+B.evidence.length+' sources cited'});DB.aiMeta[pid]={at:B.generatedAt,rev:DB.audit.filter(a=>a.patientId===pid).length};return B},
 stale:pid=>{const m=DB.aiMeta[pid];return !m||m.rev!==DB.audit.filter(a=>a.patientId===pid).length}
};
