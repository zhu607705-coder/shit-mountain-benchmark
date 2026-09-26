'use strict';
// Decorative CSS planes only. Semantic icons remain the pinned official Lucide set.
const ArenaMotion = (() => {
  let stage, field, frame=0, targetX=0,targetY=0,x=0,y=0,enabled=false,phaseTimer=0,revealResolve=null,started=0;
  const reduce=typeof matchMedia==='function'?matchMedia('(prefers-reduced-motion: reduce)'):null;
  const pointer=typeof matchMedia==='function'?matchMedia('(hover: hover) and (pointer: fine)'):null;
  const layouts={
    all:[[5,17,420,37,-25,1.1],[78,12,510,25,53,.5],[-6,54,470,64,-16,.6],[91,63,390,80,-29,1.4],[42,8,360,20,34,.3],[29,73,490,38,7,.8],[56,84,240,22,-42,1.2],[100,32,310,17,61,.4]],
    R:[[3,16,520,43,-17,1.1],[81,11,580,23,-17,.45],[-7,53,690,72,-17,.7],[94,70,440,53,-17,1.35],[45,9,410,18,-17,.3],[30,77,650,29,-17,.8],[67,86,320,25,-17,1.2],[103,36,370,21,-17,.4]],
    C:[[13,9,720,38,64,1.1],[89,3,660,27,64,.45],[-4,70,530,73,-61,.7],[102,54,780,44,-61,1.35],[40,11,490,19,64,.3],[32,86,730,30,-61,.8],[65,89,450,23,64,1.2],[97,27,490,21,-61,.4]],
    F:[[0,21,430,66,0,1.1],[91,10,510,45,90,.45],[-5,61,720,25,0,.7],[102,64,570,70,0,1.35],[37,2,290,42,90,.3],[20,80,680,55,0,.8],[65,95,420,35,90,1.2],[102,32,350,20,0,.4]]
  };
  function tick(){frame=0;x+=(targetX-x)*.085;y+=(targetY-y)*.085;stage.style.setProperty('--mx',x.toFixed(4));stage.style.setProperty('--my',y.toFixed(4));if(Math.abs(x-targetX)+Math.abs(y-targetY)>.0002)frame=requestAnimationFrame(tick);}
  function schedule(){if(!frame)frame=requestAnimationFrame(tick);}
  function reset(){targetX=targetY=0;schedule();}
  function eligibility(){enabled=!!pointer?.matches&&!reduce?.matches;stage?.classList.toggle('motion-enabled',enabled);if(!enabled&&stage){cancelAnimationFrame(frame);frame=0;x=y=targetX=targetY=0;stage.style.setProperty('--mx','0');stage.style.setProperty('--my','0');}}
  function setTask(id){
    if(!stage)return;
    const track=id?.charAt(0),kind=layouts[track]?track:'all',variant=Number(id?.slice(1))||0;
    stage.dataset.track=kind;
    // Keep the same planes alive: transitions need the previous computed layout.
    layouts[kind].forEach((p,index)=>{
      let blade=field.children[index];
      if(!blade){blade=document.createElement('i');blade.className='blade blade-'+index;field.append(blade);}
      const delta=variant?((variant*13+index*7)%11-5):0;
      const values={x:p[0]+delta*.45,y:p[1]+delta*.3,w:p[2]+delta*8,h:p[3],depth:p[5]};
      for(const [key,value] of Object.entries(values))blade.style.setProperty('--'+key,value);
      blade.style.setProperty('--blade-angle',`${p[4]+(kind==='F'?0:delta*.6)}deg`);
    });
  }
  function phase(name){if(stage)stage.dataset.phase=name;}
  function begin(){clearTimeout(phaseTimer);if(revealResolve){revealResolve(false);revealResolve=null;}started=performance.now();phase('charging');phaseTimer=setTimeout(()=>phase('shuffling'),reduce?.matches?0:190);}
  function reveal(id){clearTimeout(phaseTimer);if(revealResolve){revealResolve(false);revealResolve=null;}return new Promise(resolve=>{revealResolve=resolve;const elapsed=performance.now()-started;const charge=reduce?.matches?0:Math.max(0,190-elapsed);phaseTimer=setTimeout(()=>{if(!reduce?.matches)phase('shuffling');const delay=reduce?.matches?0:Math.max(0,390-(performance.now()-started));phaseTimer=setTimeout(()=>{setTask(id);phase(reduce?.matches?'revealed':'revealing');phaseTimer=setTimeout(()=>{phase('revealed');revealResolve=null;resolve(true);},reduce?.matches?0:750);},delay);},charge);});}
  function fail(hasPrevious){clearTimeout(phaseTimer);if(revealResolve){revealResolve(false);revealResolve=null;}phase(hasPrevious?'revealed':'idle');}
  function boot(){stage=document.getElementById('draw-stage');field=document.getElementById('blade-field');if(!stage||!field)return;setTask(null);eligibility();stage.addEventListener('pointermove',event=>{if(!enabled||document.body.classList.contains('panel-open'))return;const rect=stage.getBoundingClientRect();targetX=Math.max(-1,Math.min(1,(event.clientX-rect.left)/rect.width*2-1));targetY=Math.max(-1,Math.min(1,(event.clientY-rect.top)/rect.height*2-1));schedule();},{passive:true});stage.addEventListener('pointerleave',reset);reduce?.addEventListener('change',eligibility);pointer?.addEventListener('change',eligibility);document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;}else if(enabled)schedule();});}
  return {boot,begin,reveal,fail,reset,setTask};
})();
if(typeof document!=='undefined')ArenaMotion.boot();
if(typeof module!=='undefined'&&module.exports)module.exports=ArenaMotion;
