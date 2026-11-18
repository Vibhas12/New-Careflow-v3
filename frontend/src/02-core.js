'use strict';
/* ================= utilities ================= */
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pad=n=>String(n).padStart(2,'0');
const isoD=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
const todayISO=()=>isoD(new Date());
const parseD=s=>new Date(s.slice(0,10)+'T00:00:00');
const addDays=(s,n)=>{const d=parseD(s);d.setDate(d.getDate()+n);return isoD(d)};
const dayDiff=(a,b)=>Math.round((parseD(a)-parseD(b))/864e5);
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const fmtD=s=>{if(!s)return '—';const d=parseD(s);return d.getDate()+' '+MON[d.getMonth()]+' '+d.getFullYear()};
const fmtDS=s=>{if(!s)return '—';const d=parseD(s);return DOW[d.getDay()]+' '+d.getDate()+' '+MON[d.getMonth()]};
const fmtDT=ts=>{if(!ts)return '—';const d=new Date(ts);return d.getDate()+' '+MON[d.getMonth()]+' '+d.getFullYear()+', '+pad(d.getHours())+':'+pad(d.getMinutes())};
const nowISO=()=>new Date().toISOString();
const ageOf=dob=>{const b=parseD(dob),n=new Date();let a=n.getFullYear()-b.getFullYear();if(n.getMonth()<b.getMonth()||(n.getMonth()===b.getMonth()&&n.getDate()<b.getDate()))a--;return a};
const initials=n=>n.replace(/^Dr\.?\s+/,'').split(/\s+/).map(x=>x[0]).slice(0,2).join('').toUpperCase();
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
const pct=(n,d)=>d?Math.round(n*100/d):null;
const mulberry=a=>()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296};
const hashStr=s=>{let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))|0;return Math.abs(h)};
const dtOf=(date,time)=>new Date(date+'T'+(time||'09:00')+':00');

const PRI={high:0,med:1,low:2};
const PRI_LABEL={high:'High priority',med:'Medium priority',low:'Low priority'};
const DEPTS=['Cardiology','Neurology','Oncology','Orthopedics','General Medicine','Mental Health'];
const APPT_TYPES=['Initial assessment','Consultation','Follow-up review','Diagnostic review','Telehealth review','Medication review'];
const TEST_TYPES=['Blood Test','HbA1c','Lipid Profile','Thyroid Function','ECG','X-Ray','MRI','EEG'];
const TASK_COLS=['New','In Progress','Waiting for Patient','Completed'];
const SLOTS=(()=>{const a=[];for(let h=8;h<18;h++){a.push(pad(h)+':00');a.push(pad(h)+':30')}return a})();
const OUTCOMES=['Recovered','Improving','Stable / managed','Ongoing treatment','Deteriorating','Care transferred'];

/* ================= store (V2: SQLite behind a REST API – NOT browser storage) ================= */
let DB=null, GAPS=[], persistOK=true;
const API={token:null,
 init(){try{this.token=sessionStorage.getItem('cfv2-token')}catch(e){}},
 setToken(t){this.token=t;try{t?sessionStorage.setItem('cfv2-token',t):sessionStorage.removeItem('cfv2-token')}catch(e){}},
 async req(method,path,body){const r=await fetch(path,{method,headers:{'Content-Type':'application/json',...(this.token?{Authorization:'Bearer '+this.token}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  let j=null;try{j=await r.json()}catch(e){}
  if(!r.ok){const e=new Error((j&&j.error)||('Server error ('+r.status+')'));e.status=r.status;e.data=j;throw e}return j}};
/* ---- write-through sync: the UI mutates DB and commit() → persist() sends only what changed to /api/sync ---- */
const ARR_COLLS=['users','patients','appointments','tests','referrals','prescriptions','consultations','tasks','reminders','comms','notifications','feedback','history','audit'];
const BLOB_ARR=['proposals','chat'], BLOB_MAP=['alertState','aiMeta'];
const SYNC={snap:null,busy:false,again:false,status:'ok',err:null,last:null};
function cleanRec(k,o){const c={...o};delete c.srcBatch;if(k==='patients'){delete c.priority;delete c.priorityUpdatedAt}if(k==='tests')delete c.documentId;return c}
function takeSnap(){const s={};
 ARR_COLLS.forEach(k=>{s[k]=new Map(DB[k].map(o=>[o.id,JSON.stringify(cleanRec(k,o))]))});
 BLOB_ARR.forEach(k=>{DB[k].forEach(o=>{if(!o.id)o.id=nextId('CHT')});s[k]=new Map(DB[k].map(o=>[o.id,JSON.stringify(o)]))});
 BLOB_MAP.forEach(k=>{s[k]=new Map(Object.entries(DB[k]||{}).map(([id,o])=>[id,JSON.stringify(o)]))});
 s.settings=JSON.stringify(DB.settings);s.seq=JSON.stringify(DB.seq);return s}
function diffChanges(){const ch={},cur=takeSnap(),prev=SYNC.snap;let any=false;
 ARR_COLLS.forEach(k=>{const up=[],del=[];DB[k].forEach(o=>{if(prev[k].get(o.id)!==cur[k].get(o.id))up.push(cleanRec(k,o))});prev[k].forEach((_,id)=>{if(!cur[k].has(id))del.push(id)});if(up.length||del.length){ch[k]={upsert:up,delete:del};any=true}});
 const bl={};BLOB_ARR.concat(BLOB_MAP).forEach(k=>{const up={},del=[];const src=BLOB_ARR.includes(k)?Object.fromEntries(DB[k].map(o=>[o.id,o])):DB[k];Object.entries(src).forEach(([id,o])=>{if(prev[k].get(id)!==cur[k].get(id))up[id]=o});prev[k].forEach((_,id)=>{if(!cur[k].has(id))del.push(id)});if(Object.keys(up).length||del.length){bl[k]={upsert:up,delete:del};any=true}});
 if(Object.keys(bl).length)ch.blobs=bl;
 if(cur.settings!==prev.settings){ch.settings=DB.settings;any=true}
 if(cur.seq!==prev.seq){ch.seq=DB.seq;any=true}
 return{ch,cur,any}}
function syncBadge(){const el=document.getElementById('syncstat');if(!el)return;const m={ok:['Saved to SQLite','ok'],saving:['Saving…','busy'],error:['Save failed','err'],warn:['Saved (some changes refused)','err']}[SYNC.status];el.className='sync '+m[1];el.textContent=m[0];el.title=SYNC.err||'';}
function persist(){if(!SYNC.snap||!API.token)return;SYNC.again=true;if(!SYNC.busy)flushSync()}
async function flushSync(){SYNC.busy=true;SYNC.status='saving';syncBadge();
 try{while(SYNC.again){SYNC.again=false;const{ch,cur,any}=diffChanges();if(!any)continue;
   const newPids=(ch.patients?ch.patients.upsert:[]).map(p=>p.id).filter(id=>!SYNC.snap.patients.has(id));
   try{const rep=await API.req('POST','/api/sync',{changes:ch});SYNC.snap=cur;SYNC.status='ok';SYNC.err=null;SYNC.last=Date.now();
    if(rep.rejected&&rep.rejected.length){SYNC.status='warn';SYNC.err=rep.rejected.join('; ');console.warn('Sync refused:',SYNC.err)}
    for(const pid of newPids){try{const h=await API.req('GET','/api/priority/'+pid);DB.priorityHistory=DB.priorityHistory.filter(x=>x.patientId!==pid).concat(h.history.map(r=>({id:r.id,patientId:r.patient_id,previous:r.previous_priority,new:r.new_priority,comment:r.comment,userId:r.user_id,user:r.user_name,role:r.user_role,at:r.changed_at})))}catch(e){}}
    if(newPids.length&&typeof render==='function')render();
   }catch(e){SYNC.status='error';SYNC.err=e.message;SYNC.again=false;
    if(e.status===401){API.setToken(null);location.reload();return}
    await reloadState();if(typeof toast==='function')toast('Could not save to the database: '+e.message+' – data reloaded from the database.',true);break}}
 }finally{SYNC.busy=false;syncBadge()}}
const syncIdle=async()=>{for(let i=0;i<400&&(SYNC.busy||SYNC.again);i++)await new Promise(r=>setTimeout(r,25))};
async function reloadState(){const S=await API.req('GET','/api/state');const sess=DB&&DB.session;DB=S;DB.session=sess||null;SYNC.snap=takeSnap();if(typeof render==='function')render()}
function nextId(prefix){DB.seq[prefix]=(DB.seq[prefix]||1000)+1;return prefix+'-'+DB.seq[prefix]}
const me=()=>DB&&DB.session?DB.users.find(u=>u.id===DB.session.userId):null;
const userById=id=>DB.users.find(u=>u.id===id);
const patientById=id=>DB.patients.find(p=>p.id===id);
const pFull=p=>p?p.first+' '+p.last:'Unknown';

/* ================= RBAC ================= */
const NAV=[
 {id:'dashboard',label:'Dashboard',icon:'dash'},{id:'patients',label:'Patients',icon:'users'},
 {id:'ingest',label:'Data Import',icon:'upload'},{id:'caregaps',label:'Care Gaps & Alerts',icon:'alert'},{id:'appointments',label:'Appointments',icon:'cal'},{id:'tests',label:'Diagnostic Tests',icon:'flask'},
 {id:'tasks',label:'Tasks & Follow-ups',icon:'task'},{id:'assistant',label:'AI Care Assistant',icon:'spark'},{id:'comms',label:'Communications',icon:'msg'},
 {id:'recovery',label:'Recovery Tracker',icon:'pulse'},{id:'performance',label:'Doctor Performance',icon:'bars'},{id:'experience',label:'Patient Experience',icon:'heart'},
 {id:'executive',label:'Executive Overview',icon:'trend'},{id:'settings',label:'Settings',icon:'cog'}];
const ROLE_NAV={
 coordinator:['dashboard','patients','ingest','caregaps','appointments','tests','tasks','assistant','comms','recovery','experience','settings'],
 doctor:['dashboard','patients','caregaps','appointments','tests','tasks','assistant','comms','recovery','performance','experience','settings'],
 admin:['dashboard','caregaps','appointments','tasks','recovery','performance','experience','executive','settings']};
const ROLE_NAME={coordinator:'Care Coordinator',doctor:'Doctor',admin:'Operations Manager'};
const CAN={
 'ingest.use':['coordinator'],'priority.change':['coordinator','doctor'],
 'patient.view':['coordinator','doctor'],'appt.book':['coordinator','doctor'],'appt.manage':['coordinator','doctor','admin'],
 'task.create':['coordinator','doctor'],'task.manage':['coordinator','doctor','admin'],'test.request':['doctor'],'test.schedule':['coordinator'],'test.review':['doctor'],
 'consult.write':['doctor'],'outcome.record':['doctor'],'alert.act':['coordinator','doctor'],'reminder.send':['coordinator','doctor'],'feedback.record':['coordinator'],
 'referral.edit':['coordinator','doctor'],'users.manage':['admin'],'audit.view':['admin'],'config.rules':['admin'],'config.reminders':['admin'],'reset':['admin'],'ai.use':['coordinator','doctor']};
const can=a=>{const u=me();return !!u&&(CAN[a]||[]).includes(u.role)};
const canNav=id=>{const u=me();return !!u&&ROLE_NAV[u.role].includes(id)};
const isAdmin=()=>me()&&me().role==='admin';
/* admins see operational data only: patients shown by ID, not name */
const pLabel=pid=>{const p=patientById(pid);if(!p)return pid||'—';return isAdmin()?p.id:pFull(p)};
/* patients this user may open */
const myPatients=()=>{const u=me();if(!u)return[];if(u.role==='doctor')return DB.patients.filter(p=>p.doctorId===u.id&&!p.draft);if(u.role==='coordinator')return DB.patients.filter(p=>!p.draft);return[]};
const canOpenPatient=p=>{const u=me();if(!u||!p)return false;if(u.role==='admin')return false;if(u.role==='doctor')return p.doctorId===u.id;return true};

/* ================= audit & notifications ================= */
function audit(action,o={}){const u=me();DB.audit.unshift({id:nextId('AUD'),ts:nowISO(),userId:u?u.id:'system',user:u?u.name:'System',role:u?u.role:'system',action,patientId:o.pid||null,entity:o.entity||null,detail:o.detail||''});if(DB.audit.length>1500)DB.audit.length=1500}
function notify(o){DB.notifications.unshift({id:nextId('NTF'),ts:nowISO(),toUser:o.toUser||null,toRole:o.toRole||null,title:o.title,text:o.text||'',route:o.route||null,patientId:o.patientId||null,read:false,level:o.level||'info'});if(DB.notifications.length>300)DB.notifications.length=300}
const myNotifs=()=>{const u=me();return u?DB.notifications.filter(n=>n.toUser?n.toUser===u.id:n.toRole===u.role):[]};

/* NOTE (V2): demo data is seeded by the backend (backend/seed.py) into SQLite – there is no client-side seed. */
/* synthetic result generator (no real data) */
function genResult(name,abn){
 const V=(k,v,u,lo,hi)=>{const x=abn?v[1]:v[0];return{k,v:x,u,ref:lo+'–'+hi,flag:x<lo?'L':x>hi?'H':''}};
 const M={'Blood Test':{s:'Full blood count (synthetic report).',v:[V('Haemoglobin',[138,108],'g/L',130,170),V('White cell count',[6.2,13.4],'×10⁹/L',4,11),V('Platelets',[245,480],'×10⁹/L',150,400)]},
 'HbA1c':{s:'Glycaemic markers (synthetic report).',v:[V('HbA1c',[41,62],'mmol/mol',20,42),V('Fasting glucose',[5.1,9.1],'mmol/L',3.9,5.5)]},
 'Lipid Profile':{s:'Lipid panel (synthetic report).',v:[V('Total cholesterol',[4.6,6.8],'mmol/L',0,5),V('LDL cholesterol',[2.4,4.4],'mmol/L',0,3),V('HDL cholesterol',[1.5,0.8],'mmol/L',1,3)]},
 'Thyroid Function':{s:'Thyroid panel (synthetic report).',v:[V('TSH',[2.1,8.4],'mIU/L',0.4,4),V('Free T4',[15,9],'pmol/L',10,22)]},
 'ECG':{s:abn?'Synthetic report: rhythm irregularity noted – for clinical interpretation.':'Synthetic report: regular rhythm, no acute change noted.',v:[V('Heart rate',[72,118],'bpm',50,100),V('QTc',[420,486],'ms',350,460)]},
 'X-Ray':{s:abn?'Synthetic report: possible cortical irregularity – for clinical review.':'Synthetic report: alignment satisfactory, no acute abnormality described.',v:[]},
 'MRI':{s:abn?'Synthetic report: signal change described – for specialist review.':'Synthetic report: no acute findings described.',v:[]},
 'EEG':{s:abn?'Synthetic report: epileptiform activity described – for specialist review.':'Synthetic report: background activity within normal limits.',v:[]}};
 const m=M[name]||M['Blood Test'];return{summary:m.s,values:m.v,source:'Synthetic diagnostic report – demonstration data'};
}
