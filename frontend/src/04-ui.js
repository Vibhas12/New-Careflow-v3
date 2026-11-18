/* ================= UI engine ================= */
const ICONS={
upload:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>',
dash:'<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
users:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',

alert:'<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
cal:'<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
flask:'<path d="M10 2v7.31L4.5 19a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9.31V2"/><path d="M8.5 2h7M7 16h10"/>',
task:'<path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
spark:'<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/>',
msg:'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
pulse:'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',bars:'<path d="M12 20V10M18 20V4M6 20v-4"/>',
heart:'<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
trend:'<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
cog:'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
search:'<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',bell:'<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
help:'<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01"/>',
phone:'<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.58 2.81.7A2 2 0 0 1 22 16.92z"/>',
send:'<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',plus:'<path d="M12 5v14M5 12h14"/>',x:'<path d="M18 6 6 18M6 6l12 12"/>',check:'<path d="M20 6 9 17l-5-5"/>',
chev:'<path d="m9 18 6-6-6-6"/>',chevl:'<path d="m15 18-6-6 6-6"/>',out:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
clock:'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
file:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8"/>',
user:'<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',edit:'<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
info:'<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',refresh:'<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
stetho:'<path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6 6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .3.3"/><path d="M8 15v1a6 6 0 0 0 6 6 6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/>'};
const ic=(n,c='')=>'<svg class="i '+c+'" viewBox="0 0 24 24" aria-hidden="true">'+(ICONS[n]||'')+'</svg>';

/* ---------- small renderers ---------- */
const ST_MAP={'In Progress':'Progress','Result Available':'Result','Waiting for Patient':'Waiting','No Response':'Pending','Under follow-up':'Progress','Awaiting results':'Pending','Active':'Confirmed','Discharged':'Cancelled','Follow-up overdue':'Overdue','Follow-up scheduled':'Confirmed','No follow-up scheduled':'Pending','Not recorded':'Draft'};
const stBadge=s=>'<span class="badge b-'+(ST_MAP[s]||String(s).split(' ')[0].replace(/[^A-Za-z]/g,''))+'">'+esc(s)+'</span>';
const priBadge=p=>'<span class="badge b-'+p+'">'+{high:'High',med:'Medium',low:'Low'}[p]+'</span>';
const avatar=(n,c='')=>'<span class="avatar '+c+'">'+esc(initials(n))+'</span>';
const simTag='<span class="sim" title="Prototype only – no real message is sent">SIMULATED</span>';
const stars=n=>'<span class="stars" aria-label="'+n+' out of 5">'+'★'.repeat(n)+'☆'.repeat(5-n)+'</span>';
const empty=(t,s)=>'<div class="empty"><div class="b">'+esc(t)+'</div>'+(s?'<div class="sm">'+esc(s)+'</div>':'')+'</div>';
const kpi=(label,val,o={})=>'<button class="kpi '+(o.cls||'')+(o.act?'':' static')+'" '+(o.act?'data-act="'+o.act+'" '+(o.args||''):'type="button" tabindex="-1"')+'><span class="v">'+val+'</span><span class="l">'+esc(label)+'</span>'+(o.hint?'<span class="h">'+esc(o.hint)+'</span>':'')+'</button>';
const th=a=>'<tr>'+a.map(x=>'<th>'+x+'</th>').join('')+'</tr>';
const tbl=(heads,rows)=>'<div class="tw"><table class="tbl"><thead>'+th(heads)+'</thead><tbody>'+rows.join('')+'</tbody></table></div>';
const pLink=pid=>{const p=patientById(pid);if(!p)return esc(pid||'—');return canOpenPatient(p)?'<a href="#" class="b" data-act="openPatient" data-id="'+p.id+'" style="color:var(--blue);text-decoration:none">'+esc(pLabel(pid))+'</a>':esc(pLabel(pid))};
const srcChips=(src,B)=>(src||[]).map(n=>'<button class="chip" data-act="openRef" data-ref="'+esc((B.evidence[n-1]||{}).ref)+'" title="'+esc(((B.evidence[n-1]||{}).label||'')+' '+((B.evidence[n-1]||{}).ref||'')+' · '+fmtDT((B.evidence[n-1]||{}).ts))+'">'+n+'</button>').join('');
const asideNote=t=>'<div class="banner">'+ic('info')+'<div>'+t+'</div></div>';

/* ---------- state ---------- */
const ui={route:'dashboard',q:{},stack:[],forms:{},errors:{},modal:null,toast:null,bell:false,menu:false,gs:{q:'',open:false},login:{role:'coordinator'},cal:{view:'week',date:todayISO()},lastRoute:null,help:false};
const fv=(scope,n,d='')=>{const v=(ui.forms[scope]||{})[n];return v===undefined?d:v};
function go(route,q={}){ui.stack.push({route:ui.route,q:ui.q});if(ui.stack.length>40)ui.stack.shift();ui.route=route;ui.q=q;ui.toast=null;ui.forms.f={...q};ui.bell=false;ui.menu=false;ui.gs.open=false;ui.modal=null;render()}
function back(){const s=ui.stack.pop();if(s){ui.route=s.route;ui.q=s.q}else{ui.route='dashboard';ui.q={}}ui.forms.f={...ui.q};ui.modal=null;render()}
function commit(msg,err){syncAlerts();persist();if(msg)ui.toast={msg,err:!!err,id:Date.now()};render();if(msg){const id=ui.toast.id;setTimeout(()=>{if(ui.toast&&ui.toast.id===id){ui.toast=null;render()}},3600)}}
const toast=(msg,err)=>commit(msg,err);

/* ---------- form fields ---------- */
function opt(o,v){return o.map(x=>{const val=Array.isArray(x)?x[0]:x,lab=Array.isArray(x)?x[1]:x;return '<option value="'+esc(val)+'"'+(String(v)===String(val)?' selected':'')+'>'+esc(lab)+'</option>'}).join('')}
function fld(scope,f){const v=fv(scope,f.n,f.d===undefined?'':f.d),e=(ui.errors[scope]||{})[f.n],b='data-b="'+scope+'.'+f.n+'"';let i;
 if(f.t==='check')return '<div class="field '+(f.full?'full':'')+'"><label class="sw" style="border:0;padding:2px 0"><input type="checkbox" '+b+(v?' checked':'')+'> <span>'+f.l+'</span></label>'+(f.h?'<span class="hint">'+f.h+'</span>':'')+'</div>';
 if(f.t==='select')i='<select '+b+(f.dis?' disabled':'')+'>'+(f.blank?'<option value="">'+esc(f.blank)+'</option>':'')+opt(f.o,v)+'</select>';
 else if(f.t==='area')i='<textarea '+b+' placeholder="'+esc(f.ph||'')+'" rows="'+(f.rows||3)+'">'+esc(v)+'</textarea>';
 else i='<input type="'+(f.t||'text')+'" '+b+' value="'+esc(v)+'" placeholder="'+esc(f.ph||'')+'"'+(f.min?' min="'+f.min+'"':'')+(f.max?' max="'+f.max+'"':'')+(f.dis?' disabled':'')+'>';
 return '<div class="field '+(f.full?'full ':'')+(e?'bad':'')+'"><label>'+f.l+(f.req?' <span class="req">*</span>':'')+'</label>'+i+(e?'<span class="err">'+esc(e)+'</span>':f.h?'<span class="hint">'+f.h+'</span>':'')+'</div>'}
function validate(scope,fields){const e={},v=ui.forms[scope]||{};fields.forEach(f=>{const x=String(v[f.n]??'').trim();if(f.req&&!x)e[f.n]=f.l.replace(/<[^>]+>/g,'')+' is required';
 else if(x&&f.t==='email'&&!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(x))e[f.n]='Enter a valid email address';else if(x&&f.t==='tel'&&!/^[+\d][\d\s()-]{6,}$/.test(x))e[f.n]='Enter a valid phone number'});return e}

/* ---------- modal ---------- */
function openModal(o){ui.forms.m={...(o.vals||{})};ui.errors.m={};ui.modal=o;render()}
const closeModal=()=>{ui.modal=null;render()};
function modalHTML(){const m=ui.modal;if(!m)return '';return '<div class="mb-back" data-act="mback"><div class="modal '+(m.size||'')+'" role="dialog" aria-modal="true" aria-label="'+esc(m.title)+'"><div class="mh"><h2>'+m.title+'</h2><button class="icon-btn" data-act="mclose" aria-label="Close">'+ic('x')+'</button></div><div class="mbd">'+m.body()+'</div>'+
 (m.noFooter?'':'<div class="mf">'+(m.extra||[]).map(x=>'<button class="btn '+(x.cls||'sec')+'" data-act="'+x.act+'" '+(x.args||'')+'>'+x.label+'</button>').join('')+'<button class="btn sec" data-act="mclose">'+(m.submit?'Cancel':'Close')+'</button>'+(m.submit?'<button class="btn '+(m.cls||'')+'" data-act="msubmit">'+m.submit+'</button>':'')+'</div>')+'</div></div>'}

/* ---------- charts (inline SVG, one axis, legend for >=2 series, hover tooltips) ---------- */
const SER=['var(--s1)','var(--s2)','var(--s3)','var(--s4)'];
function legend(names){return names.length>1?'<div class="legend">'+names.map((n,i)=>'<span><i style="background:'+SER[i%4]+'"></i>'+esc(n)+'</span>').join('')+'</div>':''}
function barChart(o){const W=640,H=o.h||210,L=38,B=26,Tp=10,R=26,n=o.labels.length,k=o.series.length;const max=o.max||Math.max(1,...o.series.flatMap(s=>s.values.map(v=>v||0)));const step=Math.pow(10,Math.floor(Math.log10(max)));const top=Math.ceil(max/step*1.0)*step||1;
 const iw=W-L-R,ih=H-B-Tp,gw=iw/n,bw=Math.min(34,(gw*.7)/k),fmt=o.fmt||(v=>v);let g='';
 for(let i=0;i<=4;i++){const y=Tp+ih-ih*i/4;g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y+'" y2="'+y+'" stroke="#e3eaf2"/><text x="'+(L-6)+'" y="'+(y+4)+'" text-anchor="end" font-size="10.5" fill="#5b6b7c">'+fmt(Math.round(top*i/4*10)/10)+'</text>'}
 o.labels.forEach((lb,i)=>{const cx=L+gw*i+gw/2;g+='<text x="'+cx+'" y="'+(H-8)+'" text-anchor="middle" font-size="10.5" fill="#5b6b7c">'+esc(lb)+'</text>';
  o.series.forEach((s,j)=>{const v=s.values[i]||0,h=ih*v/top,x=cx-(bw*k+2*(k-1))/2+j*(bw+2);g+='<rect x="'+x+'" y="'+(Tp+ih-h)+'" width="'+bw+'" height="'+Math.max(h,v?1:0)+'" rx="3" fill="'+SER[j%4]+'" data-tip="'+esc(lb+' · '+s.name+': '+fmt(v))+'"/>'})});
 return '<div class="chartbox"><svg viewBox="0 0 '+W+' '+H+'" width="100%" role="img" aria-label="'+esc(o.title||'Bar chart')+'">'+g+'</svg>'+legend(o.series.map(s=>s.name))+'</div>'}
function lineChart(o){const W=640,H=o.h||210,L=38,B=26,Tp=10,R=30,n=o.labels.length;const max=o.max||Math.max(1,...o.series.flatMap(s=>s.values.map(v=>v||0)));const step=Math.pow(10,Math.floor(Math.log10(max)));const top=Math.ceil(max/step)*step||1;
 const iw=W-L-R,ih=H-B-Tp,fmt=o.fmt||(v=>v);let g='';const X=i=>L+(n<2?iw/2:iw*i/(n-1)),Y=v=>Tp+ih-ih*v/top;
 for(let i=0;i<=4;i++){const y=Tp+ih-ih*i/4;g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y+'" y2="'+y+'" stroke="#e3eaf2"/><text x="'+(L-6)+'" y="'+(y+4)+'" text-anchor="end" font-size="10.5" fill="#5b6b7c">'+fmt(Math.round(top*i/4*10)/10)+'</text>'}
 o.labels.forEach((lb,i)=>{g+='<text x="'+X(i)+'" y="'+(H-8)+'" text-anchor="middle" font-size="10.5" fill="#5b6b7c">'+esc(lb)+'</text>'});
 o.series.forEach((s,j)=>{const pts=s.values.map((v,i)=>v==null?null:[X(i),Y(v)]).filter(Boolean);g+='<polyline fill="none" stroke="'+SER[j%4]+'" stroke-width="2" stroke-linejoin="round" points="'+pts.map(p=>p.join(',')).join(' ')+'"/>';
  s.values.forEach((v,i)=>{if(v!=null)g+='<circle cx="'+X(i)+'" cy="'+Y(v)+'" r="4.5" fill="'+SER[j%4]+'" stroke="#fff" stroke-width="2" data-tip="'+esc(o.labels[i]+' · '+s.name+': '+fmt(v))+'"/>'})});
 return '<div class="chartbox"><svg viewBox="0 0 '+W+' '+H+'" width="100%" role="img" aria-label="'+esc(o.title||'Line chart')+'">'+g+'</svg>'+legend(o.series.map(s=>s.name))+'</div>'}
const hbars=(rows,fmt)=>rows.map(r=>'<div style="margin:9px 0"><div class="row sp sm"><span>'+esc(r.l)+'</span><span class="b">'+(r.v==null?'—':(fmt?fmt(r.v):r.v))+'</span></div><div class="bar"><i style="width:'+Math.min(100,r.v||0)+'%;background:'+(r.c||'var(--blue)')+'"></i></div></div>').join('');

/* ---------- actions registry & render ---------- */
const A={};
let PAGES={};
function snapFocus(){const el=document.activeElement;if(!el||!el.dataset)return null;const k=el.dataset.b;if(!k&&!el.id)return null;return{k,id:el.id,s:el.selectionStart,e:el.selectionEnd}}
function render(){
 const app=document.getElementById('app');if(!app)return;
 const mainEl=app.querySelector('.main'),sc=mainEl?mainEl.scrollTop:0,mEl=app.querySelector('.modal'),msc=mEl?mEl.scrollTop:0,chat=app.querySelector('.msgs'),csc=chat?chat.scrollTop:0,cAtEnd=chat?chat.scrollHeight-chat.scrollTop-chat.clientHeight<40:true,foc=snapFocus();
 app.innerHTML=(DB&&DB.session)?shell():loginPage();
 const m2=app.querySelector('.main');if(m2)m2.scrollTop=(ui.lastRoute===ui.route+JSON.stringify(ui.q.tab||''))?sc:0;ui.lastRoute=ui.route+JSON.stringify(ui.q.tab||'');
 const me2=app.querySelector('.modal');if(me2)me2.scrollTop=msc;const c2=app.querySelector('.msgs');if(c2)c2.scrollTop=cAtEnd?c2.scrollHeight:csc;
 if(foc){let el=foc.k?app.querySelector('[data-b="'+foc.k+'"]'):foc.id?document.getElementById(foc.id):null;if(el){el.focus();try{if(foc.s!=null)el.setSelectionRange(foc.s,foc.e)}catch(e){}}}
}
function shell(){
 const u=me(),route=ui.route.split('/')[0];
 const nav=NAV.filter(n=>canNav(n.id)).map(n=>{const on=(route===n.id)||(route==='patient'&&n.id==='patients');const cnt=n.id==='caregaps'?GAPS.filter(g=>alertOpen(g)&&g.priority==='high'&&(u.role==='admin'||canOpenPatient(patientById(g.patientId)))).length:0;
  return '<button class="nav '+(on?'on':'')+'" data-act="nav" data-id="'+n.id+'" '+(on?'aria-current="page"':'')+'>'+ic(n.icon)+'<span>'+n.label+'</span>'+(cnt?'<span class="n">'+cnt+'</span>':'')+'</button>'}).join('');
 const nts=myNotifs(),unread=nts.filter(n=>!n.read).length;
 const gsr=ui.gs.q.trim()?myPatients().filter(p=>(pFull(p)+' '+p.id+' '+p.primary).toLowerCase().includes(ui.gs.q.trim().toLowerCase())).slice(0,7):[];
 const search=u.role==='admin'?'':'<div class="gsearch">'+ic('search')+'<input type="text" id="gs" data-b="gs.q" data-live placeholder="Search patients by name, ID or condition" autocomplete="off" aria-label="Global patient search">'+
   (ui.gs.open&&ui.gs.q.trim()?'<div class="gdrop">'+(gsr.length?gsr.map(p=>'<button data-act="openPatient" data-id="'+p.id+'">'+avatar(pFull(p))+'<span><b>'+esc(pFull(p))+'</b><br><span class="sm mut">'+p.id+' · '+esc(p.primary)+'</span></span></button>').join(''):'<div class="empty">No matching authorised patients</div>')+'</div>':'')+'</div>';
 return '<div class="app"><header class="top"><div class="logo"><span class="mark">'+ic('heart')+'</span><span>Bupa CareFlow<small>Assistant</small></span></div>'+search+
  '<div class="topr"><button class="icon-btn" data-act="toggleBell" aria-label="Notifications">'+ic('bell')+(unread?'<span class="dot">'+unread+'</span>':'')+'</button><button class="icon-btn" data-act="help" aria-label="Help">'+ic('help')+'</button>'+
  '<button class="user" data-act="toggleMenu" aria-label="User menu">'+avatar(u.name)+'<span><b>'+esc(u.name)+'</b><br><span class="rolechip">'+ROLE_NAME[u.role]+'</span></span></button></div>'+
  (ui.bell?'<div class="pop" style="right:70px"><div class="row sp" style="padding:10px 14px;border-bottom:1px solid var(--line)"><b>Notifications</b><button class="btn ghost s" data-act="readAll">Mark all read</button></div>'+(nts.length?nts.slice(0,14).map(n=>'<button class="it '+(n.read?'':'unread')+'" data-act="openNotif" data-id="'+n.id+'"><div class="b">'+esc(n.title)+'</div><div class="sm mut">'+esc(n.text)+'</div><div class="sm mut">'+fmtDT(n.ts)+'</div></button>').join(''):empty('No notifications'))+'</div>':'')+
  (ui.menu?'<div class="pop" style="right:12px;width:270px;padding:12px"><div class="row">'+avatar(u.name,'')+'<div><b>'+esc(u.name)+'</b><div class="sm mut">'+esc(u.title)+'</div><div class="sm mut">'+esc(u.email)+'</div></div></div><div class="hl mt2 sm">Current role: <b>'+ROLE_NAME[u.role]+'</b></div><div class="row mt2"><button class="btn sec s" data-act="nav" data-id="settings">'+ic('cog','sm')+' Settings</button><button class="btn dng s" data-act="logout">'+ic('out','sm')+' Switch role / sign out</button></div></div>':'')+
  '</header><nav class="side" aria-label="Main navigation">'+nav+'<div class="demo-note"><b>V2 prototype.</b> Fictional data only. Notifications are simulated. <span id="syncstat" class="sync ok">Saved to SQLite</span></div></nav>'+
  '<main class="main"><div class="page">'+pageHTML()+'</div></main></div>'+modalHTML()+(ui.toast?'<div class="toast '+(ui.toast.err?'err':'')+'" role="status">'+esc(ui.toast.msg)+'</div>':'');
}
function pageHTML(){const base=ui.route.split('/')[0];
 if(base==='patient'){const p=patientById(ui.route.split('/')[1]);if(!p)return restricted('Patient not found');if(!canOpenPatient(p))return restricted('You are not authorised to open this patient record.');return PAGES.patient(p)}
 if(!canNav(base))return restricted('Your role ('+ROLE_NAME[me().role]+') does not have access to this area.');
 try{return PAGES[base]()}catch(e){console.error(e);return '<div class="card"><h2>Something went wrong</h2><p class="mut">'+esc(e.message)+'</p></div>'}}
const restricted=m=>'<div class="card" style="max-width:560px;margin:40px auto;text-align:center"><div style="color:var(--blue)">'+ic('shield')+'</div><h2 style="justify-content:center">Access restricted</h2><p class="mut">'+esc(m)+'</p><button class="btn" data-act="nav" data-id="dashboard">Back to dashboard</button></div>';
const pageHead=(title,sub,right)=>'<div class="head"><div class="grow"><h1>'+title+'</h1><p class="sub">'+sub+'</p></div>'+(right||'')+'</div>';

/* ---------- login ---------- */
const LU=id=>(ui.loginUsers||[]).find(u=>u.id===id)||{name:'Demo user',email:''};
function loginPage(){const R=[['coordinator','u-c1','Care Coordinator','Import patient data, schedule, chase care gaps and follow-ups.'],['doctor','u-d1','Doctor','Review summaries and results, record consultations, approve AI recommendations.'],['admin','u-a1','Administrator / Operations Manager','Operational dashboards, team activity, users and permissions.']];
 const sel=R.find(r=>r[0]===ui.login.role),u=LU(sel[1]);const err=ui.login.err||ui.bootErr;
 return '<div class="login"><div class="l"><div class="row" style="gap:10px"><span class="logo" style="color:#fff"><span class="mark" style="background:#fff;color:var(--blue)">'+ic('heart')+'</span></span><b style="font-size:18px">Bupa CareFlow Assistant</b></div><h1>Helping care teams stay connected with patients, appointments, and follow-ups.</h1><p>From fragmented patient information to connected, evidence-based and actionable care coordination.</p><div><span class="pill">Care-gap detection</span><span class="pill">Evidence-grounded AI</span><span class="pill">Human-approved actions</span><span class="pill">Full audit trail</span></div><p class="sm" style="margin-top:30px;opacity:.8">Prototype with fictional patients. Not connected to any healthcare system. AI is advisory only and never diagnoses or prescribes.</p></div>'+
 '<div class="r"><h2 style="font-size:20px;margin-bottom:4px">Sign in (demo)</h2><p class="sub">Choose a role to experience the product from that perspective.</p>'+
 R.map(r=>'<button class="rolecard '+(ui.login.role===r[0]?'on':'')+'" data-act="pickRole" data-id="'+r[0]+'">'+avatar(LU(r[1]).name)+'<span><b>'+r[2]+'</b><br><span class="sm mut">'+r[3]+'</span></span></button>').join('')+
 '<div class="fg mt2"><div class="field"><label>Email</label><input type="email" data-b="login.email" value="'+esc(fv('login','email',u.email))+'"></div><div class="field"><label>Password</label><input type="password" data-b="login.pw" value="'+esc(fv('login','pw','careflow-demo'))+'"></div></div>'+
 (err?'<div class="err mt2" style="color:var(--red)">'+esc(err)+'</div>':'')+'<div class="row mt"><button class="btn" data-act="signin">Sign in as '+esc(u.name)+'</button></div><p class="sm mut mt2">Demo password for all users: <code>careflow-demo</code>. Data is stored in a SQLite database on the server. Other demo accounts: Tom Bennett (coordinator), Dr. Arjun Patel (doctor) – see Settings → Role Management.</p></div></div>'}

/* ---------- global event wiring ---------- */
function setBind(el){const [sc,...r]=el.dataset.b.split('.'),n=r.join('.');if(!ui.forms[sc])ui.forms[sc]={};ui.forms[sc][n]=el.type==='checkbox'?el.checked:el.value}
document.addEventListener('click',e=>{
 const t=e.target.closest('[data-act]');
 if(!e.target.closest('.gsearch')&&ui.gs.open){ui.gs.open=false;if(!t)render()}
 if(!t)return;
 if(t.dataset.act==='mback'&&e.target!==t)return;
 if(t.tagName==='A')e.preventDefault();const fn=A[t.dataset.act];if(fn)fn(t.dataset,t,e);else console.warn('No action',t.dataset.act)});
document.addEventListener('input',e=>{const el=e.target.closest('[data-b]');if(!el)return;const rx=el.dataset.b==='cons.prescription',had=rx&&!!((ui.forms.cons||{}).prescription||'').trim();setBind(el);if(rx&&had!==!!el.value.trim())render();if(el.dataset.b==='gs.q')ui.gs.open=true;if(el.dataset.live!==undefined)render()});
document.addEventListener('change',e=>{const el=e.target.closest('[data-b]');if(!el)return;setBind(el);if(['SELECT'].includes(el.tagName)||['checkbox','radio','date','time'].includes(el.type))render()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&ui.modal){closeModal();return}
 if(e.key==='Enter'&&e.target.id==='gs'){const q=ui.gs.q.trim().toLowerCase();const r=myPatients().find(p=>(pFull(p)+' '+p.id).toLowerCase().includes(q));if(r){ui.gs={q:'',open:false};go('patient/'+r.id)}}
 if(e.key==='Enter'&&e.target.id==='chatin'&&!e.shiftKey){e.preventDefault();A.chatSend({})}});
const tipEl=()=>document.getElementById('tip');
document.addEventListener('mouseover',e=>{const t=e.target.closest('[data-tip]');const tp=tipEl();if(!tp)return;if(!t){tp.style.display='none';return}tp.textContent=t.dataset.tip;tp.style.display='block'});
document.addEventListener('mousemove',e=>{const tp=tipEl();if(tp&&tp.style.display==='block'){tp.style.left=Math.min(e.clientX+12,innerWidth-270)+'px';tp.style.top=(e.clientY+14)+'px'}});

/* ---------- core actions ---------- */
A.nav=d=>{ui.toast=null;ui.stack=[];ui.route=d.id;ui.q={};ui.forms.f={};ui.bell=false;ui.menu=false;ui.modal=null;ui.forms.m={};render()};
A.go=d=>go(d.route,d.q?JSON.parse(d.q):{});
A.back=()=>back();
A.mclose=()=>closeModal();A.mback=()=>closeModal();
A.msubmit=()=>{const m=ui.modal;const r=m.onSubmit(ui.forms.m);if(r&&r.errors){ui.errors.m=r.errors;render();return}if(r&&r.keep)return;ui.modal=null;commit(r&&r.ok)};
A.toggleBell=()=>{ui.bell=!ui.bell;ui.menu=false;render()};A.toggleMenu=()=>{ui.menu=!ui.menu;ui.bell=false;render()};
A.readAll=()=>{myNotifs().forEach(n=>n.read=true);commit()};
A.openNotif=d=>{const n=DB.notifications.find(x=>x.id===d.id);n.read=true;ui.bell=false;if(n.route){const base=n.route.split('/')[0];if(base==='patient'&&!canOpenPatient(patientById(n.route.split('/')[1]))){commit();return}if(base!=='patient'&&!canNav(base)){commit();return}ui.stack.push({route:ui.route,q:ui.q});ui.route=n.route;ui.q={};}persist();render()};
A.logout=async()=>{audit('Signed out');persist();await syncIdle();try{await API.req('POST','/api/logout')}catch(e){}API.setToken(null);DB=null;SYNC.snap=null;ui.ing={batches:[],batch:null,msg:null,busy:false,loaded:false,showText:false};ui.menu=false;ui.stack=[];ui.route='dashboard';ui.q={};ui.forms={login:{}};ui.modal=null;render()};
A.pickRole=d=>{ui.login.role=d.id;ui.forms.login={};ui.login.err=null;render()};
async function loadAfterAuth(uid){await reloadState();DB.session={userId:uid};syncAlerts();ReminderSvc.processDue(false)}
A.signin=async()=>{const R={coordinator:'u-c1',doctor:'u-d1',admin:'u-a1'};const def=LU(R[ui.login.role]);const em=(fv('login','email',def.email)).trim().toLowerCase(),pw=fv('login','pw','careflow-demo');
 const u=(ui.loginUsers||[]).find(x=>(x.email||'').toLowerCase()===em);if(!u){ui.login.err='No active demo account with that email.';render();return}
 try{const r=await API.req('POST','/api/login',{userId:u.id,password:pw});API.setToken(r.token);await loadAfterAuth(u.id);ui.login={role:u.role};ui.forms.login={};ui.route='dashboard';ui.q={};ui.bootErr=null;audit('Signed in',{detail:ROLE_NAME[u.role]});commit()}
 catch(e){ui.login.err=e.status===401?'Incorrect password (demo password: careflow-demo).':'Could not sign in: '+e.message;render()}};
A.help=()=>openModal({title:'Help & safe-use notes',body:()=>'<p><b>Bupa CareFlow Assistant</b> helps care teams coordinate patient journeys. Everything shown is <b>fictional demo data</b>.</p><ul><li><b>Care gaps</b> come from explainable, configurable rules (Settings → Priority Configuration). AI only explains and summarises them.</li><li><b>AI suggestions</b> are labelled and need approval by an authorised person before any task or reminder is created.</li><li>Prescriptions are doctor-entered only. The AI never diagnoses or prescribes.</li><li>Reminders, SMS, email and app notifications are <b>simulated</b>; nothing is actually sent.</li><li>Recovery is shown only when a doctor explicitly records an outcome.</li></ul><p class="mut sm">Roles: Care Coordinator, Doctor, Administrator. Use the profile menu (top right) to switch role.</p>'});
A.openPatient=d=>{const p=patientById(d.id);if(!canOpenPatient(p)){toast('You are not authorised to open this patient record.',true);return}ui.gs={q:'',open:false};go('patient/'+d.id,d.tab?{tab:d.tab}:{})};
A.tab=d=>{ui.q={...ui.q,tab:d.id};render()};
A.openRef=d=>{const r=d.ref||'',pre=r.split('-')[0];
 if(pre==='PT'){A.openPatient({id:r})}else if(pre==='APT'&&ApptSvc.byId(r))Modals.apptDetail(r);else if(pre==='TST'&&TestSvc.byId(r))Modals.testDetail(r);else if(pre==='TSK'&&TaskSvc.byId(r))Modals.taskDetail(r);
 else if(['REF','RX','CON'].includes(pre)){const o=[...DB.referrals,...DB.prescriptions,...DB.consultations].find(x=>x.id===r);if(o)A.openPatient({id:o.patientId,tab:pre==='CON'?'history':'overview'})}else toast('Reference '+r+' is a rule/register source and has no single record to open.')};
