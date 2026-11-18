const {chromium}=require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright');
(async()=>{const b=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});const pg=await b.newPage({viewport:{width:1440,height:900}});
const errs=[];pg.on('pageerror',e=>errs.push('PAGEERR '+e.message));pg.on('console',m=>{if(m.type()==='error')errs.push('CONSOLE '+m.text())});
await pg.goto('http://127.0.0.1:8798/');await pg.waitForSelector('.login');await pg.screenshot({path:'shots/login.png'});
await pg.click('[data-act=signin]');await pg.waitForSelector('.app, .side',{timeout:8000});await pg.waitForTimeout(400);await pg.screenshot({path:'shots/dash.png'});
console.log('role nav:',await pg.$$eval('.side a, .side button',els=>els.map(e=>e.textContent.trim()).filter(Boolean).slice(0,16).join(' | ')));
console.log('sync badge:',await pg.textContent('#syncstat'));
console.log('errors:',errs.length?errs:'none');await b.close()})();
