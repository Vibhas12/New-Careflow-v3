/* ================= V2 features: audited priority management + file-based data import ================= */
const PRI_NAME={high:'High',med:'Medium',low:'Low'};
const priBadge2=p=>p?'<span class="badge b-'+p+'">'+esc(PRI_NAME[p])+'</span>':'<span class="badge b-grey">—</span>';
/* Who may change priority: Care Coordinator (any patient) and Doctor (own patients). Admin: never. Enforced again on the server. */
const canChangePriority=p=>{const u=me();return !!u&&!!p&&(u.role==='coordinator'||(u.role==='doctor'&&p.doctorId===u.id))};

/* ---------- priority change modal: select → mandatory comment → review old/new → confirm ---------- */
A.changePriority=d=>{const p=patientById(d.pid);if(!canChangePriority(p)){toast('You are not authorised to change this patient\'s priority.',true);return}
 openModal({title:'Change priority – '+esc(pFull(p)),size:'',noFooter:true,vals:{step:'form',newP:'',comment:'',pid:p.id},body:()=>priBody(p)})};
function priBody(p){const m=ui.forms.m||{},cur=PatientSvc.priority(p.id),sug=PatientSvc.suggestedPriority(p.id);
 if(m.step==='confirm')return '<p class="sub">Please confirm this change. It is recorded permanently in the priority history and cannot be edited afterwards.</p>'+
  '<div class="card" style="background:var(--lb);border-color:#c9dff3"><div class="row" style="gap:14px;font-size:16px"><span class="mut">Current</span>'+priBadge2(cur)+'<span style="font-size:20px">→</span><span class="mut">New</span>'+priBadge2(m.newP)+'</div>'+
  '<dl class="kv mt"><dt>Patient</dt><dd>'+esc(pFull(p))+' <span class="mut">'+p.id+'</span></dd><dt>Reason</dt><dd>“'+esc(m.comment.trim())+'”</dd><dt>Changed by</dt><dd>'+esc(me().name)+' ('+ROLE_NAME[me().role]+')</dd></dl></div>'+
  (m.err?'<div class="err mt2" id="priErr" style="color:var(--red)">'+esc(m.err)+'</div>':'')+
  '<div class="row mt" style="justify-content:flex-end"><button class="btn sec" data-act="priBack">Back</button><button class="btn" data-act="priConfirm" '+(m.busy?'disabled':'')+'>'+(m.busy?'Saving…':'Confirm priority change')+'</button></div>';
 const opts=['high','med','low'].filter(x=>x!==cur).map(x=>[x,PRI_NAME[x]]);
 return '<p class="sub">Current priority: '+priBadge2(cur)+'. Priority is set by people only – the care-gap rules and the AI assistant can suggest, but never change it.</p>'+
  (sug!==cur?'<div class="banner warn" style="margin-bottom:10px">Care-gap rules currently suggest <b>'+PRI_NAME[sug]+'</b> priority (advisory only).</div>':'')+
  '<div class="fg">'+fld('m',{n:'newP',t:'select',l:'New priority',req:true,blank:'Select new priority…',o:opts,full:true})+'</div>'+
  (m.newP?'<div class="row" style="margin:2px 0 10px;font-size:15px">'+priBadge2(cur)+'<span>→</span>'+priBadge2(m.newP)+'</div>':'')+
  '<div class="fg">'+fld('m',{n:'comment',t:'area',rows:3,l:'Reason for the change (mandatory)',req:true,full:true,ph:'e.g. Missed review and abnormal result pending – escalating',h:'Recorded in the audit trail with your name, role and the time.'})+'</div>'+
  '<div class="row mt" style="justify-content:flex-end"><button class="btn sec" data-act="mclose">Cancel</button><button class="btn" data-act="priReview">Review change</button></div>'}
A.priReview=()=>{const m=ui.forms.m,e={};if(!m.newP)e.newP='Select the new priority';if(!(m.comment||'').trim()||m.comment.trim().length<5)e.comment='A comment explaining the reason is mandatory (at least 5 characters)';
 if(Object.keys(e).length){ui.errors.m=e;render();return}ui.errors.m={};m.step='confirm';m.err=null;render()};
A.priBack=()=>{ui.forms.m.step='form';ui.forms.m.err=null;render()};
A.priConfirm=async()=>{const m=ui.forms.m,p=patientById(m.pid);if(m.busy)return;m.busy=true;m.err=null;render();
 try{await syncIdle();const r=await API.req('POST','/api/priority',{patientId:p.id,newPriority:m.newP,comment:m.comment});await reloadState();syncAlerts();ui.modal=null;
  toast('Priority changed: '+PRI_NAME[r.entry.previous]+' → '+PRI_NAME[r.entry.new]+' for '+pFull(patientById(p.id)))}
 catch(e){m.busy=false;m.err=e.message;render()}};
function priorityCard(p){const log=PatientSvc.priorityLog(p.id).slice().reverse(),cur=PatientSvc.priority(p.id),sug=PatientSvc.suggestedPriority(p.id);
 return '<div class="card mt"><div class="row sp"><h2>'+ic('shield')+'Priority &amp; history</h2>'+(canChangePriority(p)?'<button class="btn s" data-act="changePriority" data-pid="'+p.id+'">Change priority</button>':'')+'</div>'+
 '<div class="row" style="margin-bottom:8px"><span class="mut">Current priority</span>'+priBadge2(cur)+(sug!==cur?'<span class="sm mut">Care-gap suggestion (advisory, not applied): '+priBadge2(sug)+'</span>':'')+'</div>'+
 (log.length?'<div class="tw"><table class="tbl"><thead><tr><th>Date &amp; time</th><th>Change</th><th>Comment</th><th>By</th></tr></thead><tbody>'+log.map(h=>'<tr><td>'+fmtDT(h.at)+'</td><td>'+(h.previous?priBadge2(h.previous)+' → ':'<span class="mut">Initial</span> ')+priBadge2(h.new)+'</td><td>'+esc(h.comment)+'</td><td>'+esc(h.user)+'<br><span class="sm mut">'+esc(ROLE_NAME[h.role]||h.role)+'</span></td></tr>').join('')+'</tbody></table></div>':'<p class="mut">No priority history recorded.</p>')+
 '<p class="sm mut mt2">History entries are append-only: they cannot be edited or deleted from the application.</p></div>'}
function docsCard(p){const ds=(DB.documents||[]).filter(d=>d.patientId===p.id);if(!ds.length)return '';
 return '<div class="card mt"><h2>'+ic('task')+'Imported documents</h2><div class="list">'+ds.map(d=>'<div class="cl"><span class="grow"><b>'+esc(d.filename)+'</b><br><span class="sm mut">'+esc(d.docType||d.type)+' · imported '+fmtDT(d.uploadedAt)+' · extracted via '+esc(d.method||'—')+' · batch '+esc(d.batchId)+'</span></span>'+(me().role==='coordinator'||me().role==='doctor'?'<button class="btn sec s" data-act="ingDl" data-id="'+d.id+'" data-name="'+esc(d.filename)+'">Open original</button>':'')+'</div>').join('')+'</div></div>'}

/* ---------- Data Import (Method B) ---------- */
ui.ing={batches:[],batch:null,msg:null,busy:false,loaded:false,showText:false};
const ING_KINDS={patient:'Patient',consultation:'Consultation note',test:'Diagnostic report',appointment:'Appointment',referral:'Referral',medication:'Medication',allergy:'Allergy',history:'Medical history',task:'Outstanding task',unknown:'Unrecognised'};
const ING_FIELDS={patient:['patient_id','first_name','last_name','dob','gender','mobile','email','department','primary_condition','allergies','medications','care_plan'],consultation:['patient_id','first_name','last_name','date','doctor','notes','diagnosis','plan','follow_up'],test:['patient_id','first_name','last_name','dob','test_name','date','summary'],appointment:['patient_id','date','time','type','status'],referral:['patient_id','referred_to','reason','status'],medication:['patient_id','medications'],allergy:['patient_id','allergies'],history:['patient_id','date','type','title','detail'],task:['patient_id','title','date']};
const ING_LABEL=k=>({patient_id:'Patient ID',first_name:'First name',last_name:'Last name',dob:'Date of birth',gender:'Gender',mobile:'Mobile',email:'Email',department:'Department',primary_condition:'Primary condition',allergies:'Allergies',medications:'Medications',care_plan:'Care plan',date:'Date',doctor:'Doctor',notes:'Notes',diagnosis:'Diagnosis',plan:'Plan',follow_up:'Follow-up date',test_name:'Test / report type',summary:'Findings / summary',time:'Time',type:'Type',status:'Status',referred_to:'Referred to',reason:'Reason',title:'Title',detail:'Detail'}[k]||k);
const ingBadge=s=>{const c={matched:'b-low',new:'b-blue',uncertain:'b-med',duplicate:'b-grey',invalid:'b-high','Needs Review':'b-med',Imported:'b-low','Partially Imported':'b-med',Failed:'b-high',Rejected:'b-high',Cancelled:'b-grey'}[s]||'b-grey';return '<span class="badge '+c+'">'+esc(({matched:'Matched',new:'New',uncertain:'Needs review',duplicate:'Duplicate',invalid:'Invalid'}[s])||s)+'</span>'};
const Ingest={
 async refresh(){try{const r=await API.req('GET','/api/ingest/batches');ui.ing.batches=r.batches;if(ui.ing.batch){const b=await API.req('GET','/api/ingest/batches/'+ui.ing.batch.id);ui.ing.batch=b.batch}}catch(e){ui.ing.msg={ok:false,text:e.message}}ui.ing.loaded=true;render()},
 async upload(file){ui.ing.msg=null;const ext=(file.name.split('.').pop()||'').toLowerCase();
  if(!['csv','json','pdf'].includes(ext)){ui.ing.msg={ok:false,text:'Unsupported file type “.'+ext+'”. Please choose a CSV, JSON or PDF file.'};render();return}
  if(file.size>5*1024*1024){ui.ing.msg={ok:false,text:'File is '+(file.size/1048576).toFixed(1)+' MB – the limit is 5 MB.'};render();return}
  ui.ing.busy=true;render();
  try{const buf=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<buf.length;i+=0x8000)bin+=String.fromCharCode.apply(null,buf.subarray(i,i+0x8000));
   const r=await API.req('POST','/api/ingest/upload',{filename:file.name,contentBase64:btoa(bin)});ui.ing.batch=r.batch;ui.ing.showText=false;
   ui.ing.msg={ok:true,text:'“'+file.name+'” uploaded and read successfully ('+r.batch.records+' record'+(r.batch.records===1?'':'s')+'; method: '+r.batch.method+'). Review the extracted information below, then confirm the import. Nothing is saved until you confirm.'}}
  catch(e){ui.ing.msg={ok:false,text:'Upload failed: '+e.message+(e.data&&e.data.batch?' (kept in the import history as '+e.data.batch.id+', status '+e.data.batch.status+')':'')};ui.ing.batch=null}
  ui.ing.busy=false;await Ingest.refresh()},
 async decide(rid,body){try{const r=await API.req('PATCH','/api/ingest/records/'+rid,body);ui.ing.batch=r.batch;ui.ing.msg=null}catch(e){ui.ing.msg={ok:false,text:e.message}}render()},
 async confirm(){const b=ui.ing.batch;ui.ing.busy=true;render();
  try{await syncIdle();const r=await API.req('POST','/api/ingest/batches/'+b.id+'/confirm',{});ui.ing.batch=r.batch;
   ui.ing.msg={ok:r.result.failed===0,text:'Import '+r.result.status.toLowerCase()+': '+r.result.imported+' record(s) saved to the database, '+r.result.skipped+' skipped, '+r.result.failed+' failed/invalid. The new information is now available in patient profiles, care-gap detection and the AI assistant.'};
   await reloadState();syncAlerts();persist();render()}
  catch(e){ui.ing.msg={ok:false,text:'Import not completed: '+e.message}}
  ui.ing.busy=false;await Ingest.refresh()},
 async cancel(){const b=ui.ing.batch;try{const r=await API.req('POST','/api/ingest/batches/'+b.id+'/cancel',{});ui.ing.batch=r.batch;ui.ing.msg={ok:true,text:'Import cancelled – nothing was saved. The original file stays in the import history.'}}catch(e){ui.ing.msg={ok:false,text:e.message}}await Ingest.refresh()}};
function ingSummary(r){const m=r.mapped||{},nm=((m.first_name||'')+' '+(m.last_name||'')).trim();
 const bits={patient:[nm,m.dob?'DOB '+m.dob:'',m.department,m.primary_condition,m.medications?'Meds: '+m.medications:'',m.allergies?'Allergies: '+m.allergies:''],consultation:[m.date,m.notes],test:[m.test_name,m.date,m.summary],appointment:[m.date,m.time,m.type,m.status],referral:[m.referred_to,m.reason],medication:[m.medications],allergy:[m.allergies],history:[m.date,m.title],task:[m.title,m.date&&'due '+m.date],unknown:[]}[r.kind]||[];
 return bits.filter(Boolean).map(x=>esc(String(x).slice(0,140))).join(' · ')||'<span class="mut">—</span>'}
function ingRecordRow(r,editable){const m=r.mapped||{},pidShown=r.patientId||m.patient_id||'';
 let act='';if(editable&&r.kind!=='unknown'){
  if(r.status==='uncertain')act='<div class="sm mut">Choose the patient this belongs to:</div>'+r.candidates.map(c=>'<button class="btn sec s" style="margin:2px 4px 2px 0" data-act="ingLink" data-id="'+r.id+'" data-pid="'+c.id+'" title="'+esc(c.reason)+'">Link to '+c.id+' – '+esc(c.name)+'</button>').join('')+(r.kind==='patient'?'<button class="btn sec s" data-act="ingNew" data-id="'+r.id+'">Create as new patient</button>':'')+'<button class="btn ghost s" data-act="ingSkip" data-id="'+r.id+'">Skip</button>';
  else if(r.status==='invalid')act='<button class="btn sec s" data-act="ingEdit" data-id="'+r.id+'">Edit fields</button>';
  else act='<label class="sw" style="border:0;padding:0"><input type="checkbox" data-act="ingToggle" data-id="'+r.id+'" '+(r.decision==='import'?'checked':'')+'> <span class="sm">Import</span></label> <button class="btn ghost s" data-act="ingEdit" data-id="'+r.id+'">Edit</button>'}
 else act='<span class="sm mut">'+esc(r.message||r.result||'')+'</span>';
 return '<tr><td>'+r.row+'</td><td>'+esc(ING_KINDS[r.kind]||r.kind)+'</td><td>'+(pidShown?'<b style="white-space:nowrap">'+esc(pidShown)+'</b><br>':'')+'<span class="sm mut">'+esc(((m.first_name||'')+' '+(m.last_name||'')).trim())+'</span></td><td class="sm">'+ingSummary(r)+'</td><td>'+ingBadge(r.status)+(r.decision==='pending'?'<br><span class="sm" style="color:var(--amber,#8a5a00)">Decision needed</span>':(r.decision==='skip'&&r.status==='uncertain'?'<br><span class="sm mut">Will be skipped</span>':''))+(r.result?'<br>'+ingBadge(r.result==='saved'?'Imported':r.result==='failed'?'Failed':'Cancelled').replace('Cancelled','Skipped'):'')+'</td><td class="sm">'+r.issues.map(i=>'<div style="color:'+(i.level==='error'?'var(--red)':i.level==='warning'?'#8a5a00':'var(--mut)')+'">'+esc(i.msg)+'</div>').join('')+'</td><td>'+act+'</td></tr>'}
PAGES.ingest=()=>{const I=ui.ing;if(!I.loaded){I.loaded=true;Ingest.refresh()}const b=I.batch,editable=b&&b.status==='Needs Review';
 const cnt=b?['matched','new','uncertain','duplicate','invalid'].map(s=>[s,b.recordList.filter(r=>r.status===s).length]):[];const toImport=b?b.recordList.filter(r=>r.decision==='import').length:0;
 return '<div class="row sp"><div><h1>Data Import</h1><p class="sub">Load patient information from CSV, JSON or PDF reports. Extracted data is shown for review first; duplicates and uncertain patient matches are never merged automatically.</p></div></div>'+
 (I.msg?'<div class="banner '+(I.msg.ok?'':'warn')+'" role="status" id="ingMsg">'+esc(I.msg.text)+'</div>':'')+
 '<div class="card mt"><h2>'+ic('task')+'1 · Choose a file</h2><div class="row"><input type="file" id="ingFile" accept=".csv,.json,.pdf,application/pdf,text/csv,application/json" '+(I.busy?'disabled':'')+'><span class="sm mut">CSV · JSON · PDF (text or scanned – OCR is used when needed) · up to 5 MB. Dates: YYYY-MM-DD or DD/MM/YYYY.</span>'+(I.busy?'<span class="badge b-med">Working…</span>':'')+'</div>'+
 '<p class="sm mut mt2">CSV/JSON columns: <code>patient_id, first_name, last_name, dob, department, …</code>; add <code>record_type</code> (patient, consultation, test, appointment, referral, medication, allergy, history, task) to import clinical records. Patient ID is the primary match key.</p></div>'+
 (b?'<div class="card mt"><div class="row sp"><h2>2 · Review &amp; confirm – '+esc(b.filename)+' <span class="mut sm">'+b.id+'</span> '+ingBadge(b.status)+'</h2><div class="row"><span class="sm mut">'+esc(b.type.toUpperCase())+' · '+Math.round(b.size/102.4)/10+' KB · extraction: '+esc(b.method||'—')+'</span></div></div>'+
  '<div class="row" style="margin:6px 0">'+cnt.map(c=>'<span class="sm">'+ingBadge(c[0])+' '+c[1]+'</span>').join('<span class="mut">·</span>')+'</div>'+
  (b.message&&b.status!=='Needs Review'?'<p class="sm mut">'+esc(b.message)+'</p>':'')+
  (b.document&&b.document.text?'<details class="mt2"'+(I.showText?' open':'')+'><summary class="sm"><b>Extracted text</b> (from the PDF, shown so you can check the extraction)</summary><pre style="white-space:pre-wrap;background:#f6f8fb;border:1px solid var(--line);border-radius:8px;padding:10px;max-height:220px;overflow:auto;font-size:12px">'+esc(b.document.text)+'</pre></details>':'')+
  '<div class="tw mt"><table class="tbl"><thead><tr><th>Row</th><th>Type</th><th>Patient</th><th>Mapped information</th><th>Status</th><th>Checks</th><th>'+(editable?'Decision':'Outcome')+'</th></tr></thead><tbody>'+b.recordList.map(r=>ingRecordRow(r,editable)).join('')+'</tbody></table></div>'+
  (editable?'<div class="row mt" style="justify-content:flex-end">'+(b.pending?'<span class="sm" style="color:#8a5a00">'+b.pending+' record(s) need a patient-match decision before you can confirm.</span>':'<span class="sm mut">'+toImport+' record(s) will be saved; skipped, duplicate and invalid rows are kept in the history.</span>')+'<button class="btn dng s" data-act="ingCancel">Cancel import</button><button class="btn" data-act="ingConfirm" '+(b.pending||I.busy?'disabled':'')+'>Confirm import ('+toImport+')</button></div>':'')+'</div>':'')+
 '<div class="card mt"><div class="row sp"><h2>Import history</h2><button class="btn sec s" data-act="ingRefresh">Refresh</button></div>'+
 (I.batches.length?tbl(['Batch','File','Type','Size','Uploaded','By','Status','Records','Result',''],I.batches.map(x=>'<tr><td>'+x.id+'</td><td>'+esc(x.filename)+'</td><td>'+esc((x.type||'').toUpperCase())+'</td><td>'+Math.round((x.size||0)/102.4)/10+' KB</td><td>'+fmtDT(x.uploadedAt)+'</td><td>'+esc(x.uploadedBy||'')+'</td><td>'+ingBadge(x.status)+'</td><td>'+x.records+'</td><td class="sm">'+(x.status==='Rejected'||x.status==='Failed'?'<span style="color:var(--red)">'+esc(x.message||'')+'</span>':x.imported+' imported · '+x.skipped+' skipped · '+x.failed+' failed')+'</td><td><button class="btn sec s" data-act="ingOpen" data-id="'+x.id+'">'+(x.status==='Needs Review'?'Review':'View')+'</button></td></tr>')):'<p class="mut">No files have been imported yet.</p>')+'</div>'};
A.ingRefresh=()=>Ingest.refresh();
A.ingOpen=async d=>{try{const r=await API.req('GET','/api/ingest/batches/'+d.id);ui.ing.batch=r.batch;ui.ing.msg=null}catch(e){ui.ing.msg={ok:false,text:e.message}}render()};
A.ingConfirm=()=>Ingest.confirm();A.ingCancel=()=>Ingest.cancel();
A.ingLink=d=>Ingest.decide(+d.id,{patientId:d.pid,decision:'import'});
A.ingNew=d=>Ingest.decide(+d.id,{patientId:'NEW',decision:'import'});
A.ingSkip=d=>Ingest.decide(+d.id,{decision:'skip'});
A.ingToggle=d=>{const el=document.querySelector('[data-act=ingToggle][data-id="'+d.id+'"]');Ingest.decide(+d.id,{decision:el&&el.checked?'import':'skip'})};
A.ingEdit=d=>{const r=ui.ing.batch.recordList.find(x=>x.id==d.id);const fs=ING_FIELDS[r.kind]||[];
 openModal({title:'Edit extracted fields – row '+r.row+' ('+(ING_KINDS[r.kind]||r.kind)+')',size:'lg',submit:'Save & re-check',vals:Object.fromEntries(fs.map(k=>[k,(r.mapped||{})[k]||''])),
  body:()=>'<p class="sub">Correct anything the extraction got wrong. The record is re-checked for matches and duplicates when you save.</p><div class="fg">'+fs.map(k=>fld('m',{n:k,l:ING_LABEL(k),t:/notes|summary|detail|reason|care_plan/.test(k)?'area':'text',rows:2,full:/notes|summary|detail|reason|care_plan/.test(k)})).join('')+'</div>',
  onSubmit:v=>{Ingest.decide(r.id,{fields:v});return{}}})};
A.ingDl=async d=>{try{const r=await fetch('/api/ingest/documents/'+d.id+'/file',{headers:{Authorization:'Bearer '+API.token}});if(!r.ok)throw new Error((await r.json()).error);const blob=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=d.name||'document';document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},500)}catch(e){toast('Could not open the original: '+e.message,true)}};
/* file chooser + drag & drop */
document.addEventListener('change',e=>{const t=e.target;if(t&&t.id==='ingFile'&&t.files&&t.files[0]){const f=t.files[0];t.value='';Ingest.upload(f)}});
document.addEventListener('dragover',e=>{if(document.getElementById('ingFile'))e.preventDefault()});
document.addEventListener('drop',e=>{if(document.getElementById('ingFile')&&e.dataTransfer&&e.dataTransfer.files[0]){e.preventDefault();Ingest.upload(e.dataTransfer.files[0])}});
