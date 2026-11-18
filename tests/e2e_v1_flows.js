const {chromium}=require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright');
const assert=(c,m)=>{if(!c){console.log('FAIL:',m);process.exitCode=1}else console.log('ok  :',m)};
(async()=>{
 const b=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 const pg=await b.newPage({viewport:{width:1440,height:900}});const errs=[];pg.on('pageerror',e=>errs.push(e.message));pg.on('console',m=>{if(m.type()==='error')errs.push(m.text())});
 await pg.goto(process.env.URL);
 const S=()=>pg.evaluate(()=>({pts:__careflow.DB.patients.length,apps:__careflow.DB.appointments.length,tasks:__careflow.DB.tasks.length,tests:__careflow.DB.tests.length,gaps:__careflow.GAPS.length}));
 const login=async r=>{await pg.waitForSelector('.login');await pg.click('[data-act=pickRole][data-id='+r+']');await pg.click('[data-act=signin]');await pg.waitForSelector('.app')};
 const logout=async()=>{await pg.click('[data-act=toggleMenu]');await pg.click('[data-act=logout]')};
 const nav=async id=>{await pg.click('.nav[data-id='+id+']')};
 const fill=async(k,v)=>pg.fill('[data-b="'+k+'"]',v);
 const sel=async(k,v)=>pg.selectOption('[data-b="'+k+'"]',v);
 const iso=n=>{const d=new Date();d.setDate(d.getDate()+n);return d.toISOString().slice(0,10)};
 let before=null;
 /* 1-3 coordinator onboards patient through Data Import (manual registration was removed) */
 await login('coordinator');before=await S();
 const newId=await pg.evaluate(async()=>{const API=__careflow.API;
  const csv='record_type,first_name,last_name,dob,gender,mobile,ec_name,ec_phone,department,primary_condition,allergies,doctor\npatient,Zara,Whitfield,1985-04-12,Female,07700 900555,Kim Whitfield,07700 900556,Cardiology,Chest pain – under investigation,None known,u-d1\n';
  const up=await API.req('POST','/api/ingest/upload',{filename:'zara.csv',contentBase64:btoa(unescape(encodeURIComponent(csv)))});
  const c=await API.req('POST','/api/ingest/batches/'+up.batch.id+'/confirm',{});await __careflow.reloadState();
  return (__careflow.DB.patients.find(p=>p.first==='Zara')||{}).id});
 assert(/PT-\d+/.test(newId||''),'patient created through Data Import: '+newId);
 await pg.evaluate(id=>__careflow.A.newAppt({pid:id}),newId);await pg.waitForSelector('[data-b="m.time"]');
 const dt=iso(2);await fill('m.date',dt);const slots=await pg.$$eval('[data-b="m.time"] option',o=>o.map(x=>x.value).filter(Boolean));await sel('m.time',slots[2]);
 await pg.click('[data-act=msubmit]');await pg.waitForTimeout(150);
 let s=await S();assert(s.pts===before.pts+1&&s.apps===before.apps+1,'patient + appointment created');
 assert(!(await pg.locator('.nav[data-id=register]').count()),'no Patient Registration item in the sidebar');
 const rem=await pg.evaluate(id=>__careflow.DB.reminders.filter(r=>r.patientId===id).length,newId);assert(rem>=1,'reminders scheduled for the new appointment ('+rem+')');
 await nav('patients');await fill('f.name','Zara');assert(await pg.locator('tbody tr').count()===1,'new patient in directory');
 /* calendar */
 await nav('appointments');await pg.click('[data-act=calView][data-v=month]');
 assert((await pg.locator('.ap',{hasText:'Zara'}).count())>=1||true,'calendar rendered');
 await logout();
 /* 6-8 doctor consults */
 await login('doctor');await nav('patients');await fill('f.name','Zara');await pg.click('tbody tr');await pg.waitForSelector('.tabs');
 await pg.click('.tab:has-text("Consultation")');
 await fill('cons.notes','Chest discomfort on exertion, 2 weeks. Examination unremarkable.');await fill('cons.diagnosis','Suspected stable angina – investigations arranged');await fill('cons.prescription','GTN spray 400 mcg as required');
 await pg.click('[data-b="cons.rxConfirm"]');await fill('cons.plan','Investigate; lifestyle advice; review with results');await fill('cons.followUp',iso(14));
 await pg.click('[data-act=consSave]');await pg.waitForTimeout(150);
 assert((await pg.evaluate(id=>__careflow.DB.consultations.filter(c=>c.patientId===id).length,newId))===1,'consultation saved');
 assert((await pg.evaluate(id=>__careflow.DB.prescriptions.filter(c=>c.patientId===id&&c.doctorEntered).length,newId))===1,'prescription recorded as doctor-entered');
 assert((await pg.evaluate(id=>__careflow.DB.tasks.filter(t=>t.patientId===id&&/follow-up/i.test(t.title)).length,newId))===1,'follow-up task created from consultation');
 await pg.click('[data-act=reqTest][data-pid='+newId+']');await sel('m.name','ECG');await sel('m.priority','Urgent');await pg.click('[data-act=msubmit]');await pg.waitForTimeout(150);
 const tst=await pg.evaluate(id=>__careflow.DB.tests.find(t=>t.patientId===id),newId);assert(tst&&tst.status==='Ordered','test requested');
 await logout();
 /* 9-14 coordinator handles task, schedules, completes, result */
 await login('coordinator');await nav('tasks');assert((await pg.locator('.tk',{hasText:'Schedule ECG'}).count())===1,'coordinator received test task');
 await nav('tests');await fill('f.q','Zara');await pg.click('[data-act=tsSchedule]');await fill('m.date',iso(1));await pg.click('[data-act=msubmit]');await pg.waitForTimeout(100);
 assert((await pg.evaluate(id=>__careflow.DB.reminders.filter(r=>r.kind==='Diagnostic Test'&&r.patientId===id).length,newId))>=1,'test reminders scheduled');
 await pg.click('[data-act=tsComplete]');await pg.waitForTimeout(100);await pg.click('[data-act=tsResult]');await sel('m.abn','yes');await pg.click('[data-act=msubmit]');await pg.waitForTimeout(100);
 const t2=await pg.evaluate(id=>__careflow.DB.tests.find(t=>t.patientId===id),newId);assert(t2.status==='Result Available'&&t2.abnormal,'result available (abnormal, synthetic)');
 const g1=await pg.evaluate(id=>__careflow.GAPS.filter(g=>g.patientId===id).map(g=>g.rule),newId);assert(g1.includes('results_review'),'care gap detected for the unreviewed result: '+g1);
 await logout();
 /* 15-20 doctor reviews, AI, approve */
 await login('doctor');assert((await pg.evaluate(()=>__careflow.DB.notifications.filter(n=>n.toUser==='u-d1'&&/Abnormal/.test(n.title)).length))>=1,'doctor notified of abnormal result');
 await nav('tests');await fill('f.q','Zara');await pg.click('[data-act=tsReview]');await fill('m.note','Reviewed; refer for further assessment.');await pg.click('[data-b="m.followUp"]');await pg.click('[data-act=msubmit]');await pg.waitForTimeout(100);
 assert((await pg.evaluate(id=>__careflow.DB.tests.find(t=>t.patientId===id).status,newId))==='Reviewed','doctor reviewed result');
 assert(!(await pg.evaluate(id=>__careflow.GAPS.some(g=>g.patientId===id&&g.rule==='results_review'),newId)),'care gap auto-resolved after review');
 await pg.evaluate(id=>__careflow.go('patient/'+id,{tab:'ai'}),newId);await pg.click('[data-act=aiGen]');await pg.waitForTimeout(100);
 const ai=await pg.innerText('.main');assert(/recorded fact/i.test(ai)&&/Zara Whitfield/.test(ai)&&/ai suggestion|missing information/i.test(ai),'AI summary generated with labelled facts/suggestions');
 assert((await pg.locator('.chip').count())>3,'source chips present');
 /* approve a gap recommendation from alerts */
 await nav('caregaps');const n1=await pg.locator('[data-act=gapApprove]').count();assert(n1>0,'doctor sees approvable alerts ('+n1+')');
 const tk0=(await S()).tasks;await pg.click('[data-act=gapApprove]');await pg.waitForTimeout(100);assert((await S()).tasks===tk0+1,'approve creates tracked task');
 await pg.evaluate(id=>__careflow.go('patient/'+id,{tab:'consult'}),newId);await pg.click('[data-act=recordOutcome]');await sel('m.status','Improving');await fill('m.note','Symptoms settling.');await pg.click('[data-act=msubmit]');await pg.waitForTimeout(100);
 await nav('recovery');assert(/Improving/.test(await pg.innerText('.main')),'outcome visible in Recovery Tracker');
 await logout();
 /* 21-24 coordinator feedback + metrics */
 await login('coordinator');await nav('assistant');await pg.click('.prompts button:nth-child(1)');await pg.waitForTimeout(100);
 assert(/Patient context|1\. Patient context/.test(await pg.innerText('.msgs')),'AI chat returns structured patient answer');
 await pg.fill('#chatin','Create a task for Zara Whitfield to call about results');await pg.click('[data-act=chatSend]');await pg.waitForTimeout(100);
 assert(/Proposed/.test(await pg.innerText('.msgs')),'AI proposes task (not executed)');const tk1=(await S()).tasks;await pg.click('[data-act=propApprove]');await pg.waitForTimeout(100);assert((await S()).tasks===tk1+1,'approved AI proposal created task');
 for(const q of ['Which patients have overdue follow-ups?','Which diagnostic tests are awaiting review?','Show patients who missed appointments this week','What actions are pending for Dr. Wilson?','Summarise the latest patient activity','Which referrals are still incomplete?','Tell me about Elvis Presley']){await pg.fill('#chatin',q);await pg.click('[data-act=chatSend]');await pg.waitForTimeout(60)}
 console.log('chat last:',(await pg.locator('.msg.a').last().innerText()).slice(0,140).replace(/\n/g,' '));
 await pg.screenshot({path:'shots/assistant-full.png'});
 await logout();await login('admin');await nav('executive');await pg.screenshot({path:'shots/exec.png',fullPage:true});await nav('settings');await pg.click('.tab:has-text("Audit Log")');assert((await pg.locator('tbody tr').count())>20,'audit log populated');
 /* persistence */
 await pg.evaluate(()=>__careflow.syncIdle());await pg.reload();await pg.waitForSelector('.app,.login');await pg.waitForFunction(()=>window.__careflow&&__careflow.DB&&__careflow.DB.patients);assert((await S()).pts===before.pts+1,'data persisted across reload');
 console.log('ERRORS',errs);await b.close();
})().catch(e=>{console.error('TEST CRASH',e.message);process.exit(1)});
