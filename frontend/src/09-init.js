/* ================= bootstrap (V2) ================= */
(async function init(){
 API.init();
 window.__careflow={get DB(){return DB},get GAPS(){return GAPS},get SYNC(){return SYNC},ui,A,commit,go,API,syncIdle,reloadState,render};
 try{
  if(API.token){try{const m=await API.req('GET','/api/me');await loadAfterAuth(m.user.id);persist()}catch(e){API.setToken(null);DB=null}}
  if(!DB){ui.loginUsers=(await API.req('GET','/api/users/public')).users}
 }catch(e){ui.bootErr='Cannot reach the CareFlow V2 server ('+e.message+'). Start it with: python3 -m backend.server'}
 render();
})();
