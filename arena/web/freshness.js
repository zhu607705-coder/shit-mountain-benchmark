'use strict';
// UI metadata only: never stores answer files, private cases, API credentials or metrics contents.
const ArenaFreshness = (() => {
  const KEY='bug-arena-ui-restore-v1';
  const fields=['participant','source-path','entrypoint','metrics-path'];
  const views=['briefing','submission','inspection','results'];
  function normalizeSnapshot(value,now=Date.now()) {
    if(!value||typeof value!=='object'||value.schema!==1||!Number.isFinite(value.savedAt)||now-value.savedAt>86400000||value.savedAt>now+60000)return null;
    const copied={};
    for(const key of fields){const text=value.fields?.[key]??'';if(typeof text!=='string'||text.length>8192)return null;copied[key]=text;}
    const matchId=value.matchId??null;
    if(matchId!==null&&(typeof matchId!=='string'||! /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$/.test(matchId)))return null;
    return {schema:1,savedAt:value.savedAt,matchId,fields:copied,roomOpen:value.roomOpen===true,
      view:views.includes(value.view)?value.view:'briefing',stage:Number.isInteger(value.stage)&&value.stage>=0&&value.stage<=2?value.stage:0,
      track:['all','R','C','F'].includes(value.track)?value.track:'all',
      tier:typeof value.tier==='string'?value.tier:null,manualTask:/^[RCF][1-4]$/.test(value.manualTask||'')?value.manualTask:null,
      activeJobId:typeof value.activeJobId==='string'&&/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$/.test(value.activeJobId)?value.activeJobId:null,
      focusField:fields.includes(value.focusField)?value.focusField:null,
      scrollTop:typeof value.scrollTop==='number'&&Number.isFinite(value.scrollTop)?Math.max(0,value.scrollTop):0};
  }
  function createMonitor({loadedId,fetchBuild,storage,capture,navigate,notify,now=()=>Date.now()}) {
    let busy=null,pending=null,dismissed=null;
    async function check(){
      if(busy)return busy;
      busy=Promise.resolve().then(fetchBuild).then(build=>{
        if(build?.schema!==1||typeof build.id!=='string'||!/^[a-f0-9]{64}$/.test(build.id))return false;
        if(build.id===loadedId){pending=null;notify({kind:'current'});return false;}
        pending=build.id;if(dismissed!==build.id)notify({kind:'available',version:typeof build.version==='string'?build.version:''});return true;
      }).catch(()=>false).finally(()=>{busy=null;});
      return busy;
    }
    function reload(){
      try{const snapshot=normalizeSnapshot({...capture(),schema:1,savedAt:now()},now());if(!snapshot)throw new Error('invalid snapshot');
        const serialized=JSON.stringify(snapshot);storage.setItem(KEY,serialized);
        if(storage.getItem(KEY)!==serialized)throw new Error('snapshot was not saved');
      }catch{notify({kind:'error',message:'无法保留当前输入，尚未刷新。'});return false;}
      navigate();return true;
    }
    function takeRestore(){try{const raw=storage.getItem(KEY);if(!raw)return null;storage.removeItem(KEY);if(raw.length>65536)return null;return normalizeSnapshot(JSON.parse(raw),now());}catch{return null;}}
    function dismiss(){dismissed=pending;notify({kind:'dismissed'});}
    return {check,reload,takeRestore,dismiss};
  }
  let monitor=null,booted=false,poll=null;
  function place(){const banner=document.getElementById('ui-update');if(!banner||banner.hidden)return;const dialogs=[...document.querySelectorAll('dialog[open]')];(dialogs.at(-1)||document.body).append(banner);}
  function boot({capture}) {
    if(booted||typeof document==='undefined')return;booted=true;
    const banner=document.getElementById('ui-update'),label=document.getElementById('ui-update-label');
    let storage;try{storage=window.sessionStorage;}catch{storage={getItem(){return null;},setItem(){throw new Error('storage unavailable');},removeItem(){}};}
    monitor=createMonitor({loadedId:document.querySelector('meta[name="arena-ui-build"]')?.content,
      fetchBuild:async()=>{const response=await fetch('/build.txt',{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw new Error('build unavailable');return response.json();},
      storage,capture,navigate:()=>window.location.reload(),notify:event=>{
        if(event.kind==='current'||event.kind==='dismissed'){banner.hidden=true;return;}
        label.textContent=event.kind==='error'?event.message:'新界面已就绪';banner.hidden=false;place();
      }});
    document.getElementById('ui-update-reload').addEventListener('click',()=>monitor.reload());
    document.getElementById('ui-update-later').addEventListener('click',()=>monitor.dismiss());
    function schedule(){clearTimeout(poll);poll=setTimeout(async()=>{if(!document.hidden)await monitor.check();schedule();},30000);}
    document.addEventListener('visibilitychange',()=>{if(!document.hidden){place();monitor.check();}});
    window.addEventListener('focus',()=>{place();monitor.check();});
    document.addEventListener('close',()=>setTimeout(place,0),true);
    monitor.check();schedule();
  }
  return {boot,place,normalizeSnapshot,createMonitor,takeRestore:()=>monitor?.takeRestore()||null,reload:()=>monitor?.reload()??false,check:()=>monitor?.check()};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=ArenaFreshness;
