'use strict';
/* Presentation only: the server and ArenaUI own submissions, jobs and reports. */
const ArenaRoom = (() => {
  const views=['briefing','submission','inspection','results'];
  const tierNames={bronze:'青铜',silver:'白银',gold:'黄金',diamond:'钻石',king:'王者',nightmare:'噩梦'};
  const list=value=>Array.isArray(value)?value:value&&typeof value==='object'?Object.entries(value).map(([id,row])=>({id,...row})):[];
  const numeric=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  const score=value=>numeric(value)===null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:2});
  const scope=match=>match?.public_scope||match?.public||match?.spec?.public||{};
  const terminal=job=>job&&['completed','failed','cancelled'].includes(job.status);
  function classifyOutcome({taskId='',submission={},report={},job={}}={}) {
    submission=submission||{}; report=report||{}; job=job||{};
    const result=(kind,title,note,stamp,kicker,rawScore=null,canCelebrate=false)=>({kind,title,note,stamp,kicker,rawScore,canCelebrate});
    const field=key=>Object.prototype.hasOwnProperty.call(report,key)?report[key]:submission[key];
    const raw=numeric(field('raw_score'));
    if(job.status==='cancelled'||report.status==='cancelled'||submission.status==='cancelled')return result('cancelled','本次已停止。','已封存的答案仍然保留。','STOPPED','RUN CANCELLED');
    if(job.status==='failed'||['environment_error','runner_error','runner_timeout'].includes(report.status)||submission.status==='failed')return result('error','检验未完成。','检验环境未产出有效判分，可稍后重试。','NO VERDICT','CHECK INTERRUPTED');
    if(['running','queued'].includes(job.status)||['grading','running','queued'].includes(submission.status))return result('pending','检验进行中。','独立检验完成后，战报在这里揭晓。','IN PROGRESS','CHECK IN PROGRESS');
    if(job.diagnostic===true||(job.status==='completed'&&job.official_result===false)||report.official===false)return result('diagnostic','诊断复验完成。','首次官方成绩保持冻结。','DIAGNOSTIC','OFFICIAL SCORE FROZEN',raw);
    if(job.status==='completed'&&job.id&&report.grade_id!==job.id)return result('pending','正在同步战报。','等待本次检验的完整报告。','PENDING','AWAITING VERIFIED REPORT');
    const valid=field('valid');
    const completed=field('completed');
    if(valid===false||['candidate_failed','invalid','automatic_failed'].includes(report.status)||['invalid','automatic_failed'].includes(submission.status))return result('failed','这次，未通过。','查看失败案例，修复后再来。','NOT PASSED','BACK TO THE SOURCE',raw);
    if(valid===true&&(completed===false||report.status==='partial'||submission.status==='partial'))return result('partial','部分完成。',taskId.startsWith('F')?'语义部分完成；完整 UI 待评。':'部分案例完成，详情已保留。','PARTIAL','PROGRESS RECORDED',raw);
    if(valid===true&&completed===true){
      if(raw===null)return result('pending','判分待确认。','已收到检验状态，等待有效分数。','PENDING','SCORE PENDING');
      if(taskId.startsWith('F')||report.score_scope==='semantic_only'||report.codex_review_required===true)return result('semantic','语义通过。','完整 UI 待 Codex 评阅。','UI PENDING','SEMANTIC CHECK PASSED',raw);
      if(taskId.startsWith('R')||report.score_scope==='continuous_objective')return result('evaluated','评估完成。','策略合法；质量以原分为准。','EVALUATED','YOUR STRATEGY, MEASURED',raw);
      if(taskId.startsWith('C'))return result('passed','本档通过！','本场选定的自动检验全部通过。','PASSED','MISSION VERIFIED',raw,true);
      return result('evaluated','评估完成。','检验结果已记录。','EVALUATED','RESULT RECORDED',raw);
    }
    if(valid===true)return result('pending','等待完整判定。','完成度仍待确认。','PENDING','REVIEW PENDING',raw);
    if(submission.id||job.id)return result('pending','答案已封存。','开始检验后生成战报。','SEALED','YOUR MOVE IS SEALED');
    return result('pending','等你出招。','提交答案后生成战报。','WAIT','AWAITING ENTRY');
  }
  const state={booted:false,matchId:null,match:null,reports:[],board:null,view:'briefing',stage:0,stageKey:'',stageAnimation:null,watchedJob:null,handled:new Set(),raf:null,entryFrame:null,revealFrame:null,effectTimer:null,seal:null,sealEpoch:0,open:false,reduced:null};
  const $=id=>document.getElementById(id);
  function text(id,value){const node=$(id);if(node)node.textContent=value??'';}
  function show(view,{focus=false,animate=true}={}){
    if(!views.includes(view))return;
    if(view!==state.view){cancelStageMotion();if(state.seal)cancelSeal();}
    state.view=view;
    const dialog=$('work-dialog');if(!dialog)return;
    dialog.dataset.roomView=view;
    dialog.querySelectorAll('[data-room-page]').forEach(node=>{node.hidden=node.dataset.roomPage!==view;});
    dialog.querySelectorAll('.room-nav [data-room-view]').forEach(node=>{if(node.dataset.roomView===view)node.setAttribute('aria-current','step');else node.removeAttribute('aria-current');});
    text('room-page-count',`${String(views.indexOf(view)+1).padStart(2,'0')} — 04`);
    if(animate&&dialog.open&&!state.reduced?.matches){dialog.classList.remove('room-enter');cancelAnimationFrame(state.entryFrame);state.entryFrame=requestAnimationFrame(()=>dialog.classList.add('room-enter'));}
    if(focus&&dialog.open){const page=dialog.querySelector(`[data-room-page="${view}"]`);page?.querySelector('h2')?.focus({preventScroll:true});dialog.scrollTo({top:0,behavior:'instant'});}
  }
  function cancelStageMotion(){state.stageAnimation?.cancel();state.stageAnimation=null;}
  function stageView(index,{user=false}={}){
    const cards=[...$('stage-cards').querySelectorAll('.stage-card')],previous=state.stage;
    state.stage=Math.max(0,Math.min(index,cards.length-1));
    cards.forEach((card,i)=>{card.hidden=i!==state.stage;card.setAttribute('aria-label',`阶段 ${i+1}`);});
    $('room-stage-tabs').querySelectorAll('button').forEach((button,i)=>button.setAttribute('aria-pressed',String(i===state.stage)));
    // Polling refreshes keep this exact card and its animation untouched.
    if(user&&previous!==state.stage){
      cancelStageMotion();
      if(state.open&&state.view==='briefing'&&!state.reduced?.matches){
        const distance=state.stage>previous?22:-22;
        state.stageAnimation=cards[state.stage]?.animate?.([
          {opacity:0,transform:`translateX(${distance}px)`},
          {opacity:1,transform:'translateX(0)'}
        ],{duration:360,easing:'cubic-bezier(.16,.8,.24,1)'});
      }
    }
  }
  function renderStages(pub){
    const stages=list(pub.prompt_segments||state.match?.stages);
    const key=JSON.stringify([state.matchId,stages.map(s=>s.name||s.title)]);
    if(key!==state.stageKey){cancelStageMotion();state.stageKey=key;state.stage=0;const container=$('room-stage-tabs');container.replaceChildren();stages.forEach((stage,index)=>{const button=document.createElement('button');button.type='button';button.setAttribute('aria-pressed',String(index===0));const number=document.createElement('span');number.textContent=String(index+1).padStart(2,'0');const name=document.createElement('b');name.textContent=stage.name||stage.title||`阶段 ${index+1}`;button.append(number,name);button.addEventListener('click',()=>stageView(index,{user:true}));container.append(button);});}
    stageView(state.stage);
  }
  function selection(){
    const job=state.match?.job||{},subs=list(state.match?.submissions);
    const submission=subs.find(sub=>sub.id===job.submission_id)||subs.at(-1)||{};
    const report=state.reports.find(row=>(row.submission_id||row.id)===submission.id)||submission.report||{};
    const rank=list(state.board?.entries).find(row=>(row.submission_id||row.id)===submission.id)||{};
    return {job,submission,report,rank};
  }
  function renderVerdict(){
    const {job,submission,report,rank}=selection();const pub=scope(state.match),taskId=pub.task_id||state.match?.task_id||'';
    const outcome=classifyOutcome({taskId,submission,report,job});
    $('room-verdict').dataset.outcome=outcome.kind;$('work-dialog').dataset.roomOutcome=outcome.kind;
    text('room-result-kicker',outcome.kicker);text('room-verdict-title',outcome.title);text('room-verdict-note',outcome.note);text('room-stamp-text',outcome.stamp);
    text('room-result-score',score(outcome.rawScore));text('room-result-participant',submission.participant||submission.name||'');
    text('room-score-label',taskId.startsWith('F')?'语义原分':outcome.kind==='diagnostic'?'首次官方原分':'自动原分');
    text('room-score-footnote',outcome.rawScore===null?'尚未判分':outcome.kind==='diagnostic'?'OFFICIAL RESULT / FROZEN':taskId.startsWith('F')?'SEMANTIC ONLY / UI PENDING':'RAW QUALITY / 100');
    const unknown=['pending','cancelled','error'].includes(outcome.kind);
    const cases=list(report.cases),count=report.cases_count??(cases.length||null),passed=report.passed_cases??(cases.length?cases.filter(row=>row.completed===true).length:null);
    text('room-result-cases',unknown?'—':count===null?'—':`${passed??'—'} / ${count}`);
    text('room-result-relative',unknown?'待评':numeric(rank.relative_score??report.relative_score??submission.relative_score)===null?'待评':score(rank.relative_score??report.relative_score??submission.relative_score));
    text('room-result-efficiency',!unknown&&report.efficiency_eligible===true&&numeric(report.efficiency_score)!==null?score(report.efficiency_score):'待核验');
    return outcome;
  }
  function reveal(outcome){
    const poster=$('room-verdict'),matchId=state.matchId,jobId=state.match?.job?.id;cancelAnimationFrame(state.revealFrame);poster.classList.remove('room-reveal','room-celebrate');
    if(state.reduced?.matches)return;
    // The class is removed after the sequence, so an identical polling response never replays it.
    state.revealFrame=requestAnimationFrame(()=>{if(!state.open||state.view!=='results'||state.matchId!==matchId||state.match?.job?.id!==jobId||state.reduced?.matches)return;poster.classList.add('room-reveal');if(outcome.canCelebrate)poster.classList.add('room-celebrate');});
    clearTimeout(state.effectTimer);state.effectTimer=setTimeout(()=>poster.classList.remove('room-reveal','room-celebrate'),1400);
  }
  function cancelSeal(){
    const seal=state.seal;state.seal=null;state.sealEpoch++;
    if(seal)clearTimeout(seal.timer);
    $('work-dialog')?.classList.remove('room-sealing');
    return !!seal;
  }
  function finishWatchedJob(outcome){
    const job=state.match?.job||{};
    if(state.seal||state.watchedJob!==job.id||!terminal(job)||state.handled.has(job.id))return false;
    const {report}=selection();
    // Completion may arrive one poll before its report. Never reveal stale evidence.
    if(job.status==='completed'&&job.diagnostic!==true&&report.grade_id!==job.id)return false;
    state.handled.add(job.id);state.watchedJob=null;
    const visible=state.open&&$('work-dialog').open;
    show('results',{focus:visible,animate:false});if(visible)reveal(outcome);
    return true;
  }
  function settleSeal(epoch,matchId){
    if(!state.seal||state.seal.epoch!==epoch||state.matchId!==matchId)return;
    cancelSeal();
    if(!state.open||!$('work-dialog').open||state.view!=='submission')return;
    if(!finishWatchedJob(renderVerdict())&&state.watchedJob)show('inspection',{focus:true});
  }
  // Called only after the server confirms an immutable submission. Never await it:
  // the grader starts immediately while this brief acknowledgement remains visible.
  function sealAccepted(){
    if(typeof document==='undefined'||!state.matchId||!state.open||!$('work-dialog').open||state.view!=='submission'||state.reduced?.matches)return false;
    if(state.seal)return false;
    const epoch=++state.sealEpoch,matchId=state.matchId;
    state.seal={epoch,matchId,timer:setTimeout(()=>settleSeal(epoch,matchId),820)};
    $('work-dialog').classList.add('room-sealing');
    return true;
  }
  function render({match,reports=[],board=null}={}){
    if(typeof document==='undefined'||!match)return;
    boot();
    const changed=state.matchId!==match.id;
    if(changed){cancelSeal();cancelStageMotion();cancelAnimationFrame(state.revealFrame);cancelAnimationFrame(state.raf);$('work-dialog').style.setProperty('--room-x','0');$('work-dialog').style.setProperty('--room-y','0');clearTimeout(state.effectTimer);$('room-verdict').classList.remove('room-reveal','room-celebrate');state.matchId=match.id;state.stageKey='';state.stage=0;state.watchedJob=null;show('briefing',{animate:false});}
    state.match=match;state.reports=list(reports);state.board=board;
    const pub=scope(match),taskId=pub.task_id||match.task_id||'?';
    for(const id of ['room-task-code','room-ambient-code','room-seal-code','room-scan-code'])text(id,taskId);
    text('room-tier',pub.tier_name||tierNames[pub.tier||match.tier]||'—');
    const ms=numeric(pub.budgets?.total_ms);text('room-budget',ms===null?'—':ms>=60000?`${Number((ms/60000).toFixed(1))} 分钟`:`${Number((ms/1000).toFixed(1))} 秒`);
    const tokens=numeric(pub.budgets?.output_tokens);text('room-token-budget',tokens===null?'':`${tokens.toLocaleString('zh-CN')} tokens`);
    renderStages(pub);
    const job=match.job||{};$('work-dialog').dataset.roomJob=job.status||'idle';
    text('room-inspection-verb',job.status==='running'?'检验。':job.status==='queued'?'就位。':terminal(job)?'收卷。':'等你。');
    text('room-scan-phase',job.status==='running'?'SCANNING':job.status==='queued'?'QUEUED':job.status==='completed'?'COMPLETE':job.status==='failed'?'INTERRUPTED':job.status==='cancelled'?'STOPPED':'STANDBY');
    $('room-view-report').hidden=!terminal(job);
    const outcome=renderVerdict();
    finishWatchedJob(outcome);
  }
  function watchJob(jobId){if(!jobId)return;state.watchedJob=jobId;state.handled.delete(jobId);if(typeof document!=='undefined'&&!state.seal)show('inspection',{focus:state.open});}
  function open(){boot();state.open=true;show(state.view,{animate:true});}
  function close(){state.open=false;const held=cancelSeal();cancelStageMotion();if(held&&state.watchedJob)show('inspection',{animate:false});cancelAnimationFrame(state.raf);cancelAnimationFrame(state.entryFrame);cancelAnimationFrame(state.revealFrame);clearTimeout(state.effectTimer);const dialog=$('work-dialog');dialog?.style.setProperty('--room-x','0');dialog?.style.setProperty('--room-y','0');dialog?.classList.remove('room-enter');$('room-verdict')?.classList.remove('room-reveal','room-celebrate');}
  function boot(){
    if(state.booted||typeof document==='undefined'||!$('work-dialog'))return;state.booted=true;state.reduced=matchMedia('(prefers-reduced-motion: reduce)');
    const dialog=$('work-dialog');
    dialog.querySelectorAll('.room-nav [data-room-view]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.roomView,{focus:true})));
    dialog.querySelectorAll('[data-room-go]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.roomGo,{focus:true})));
    $('room-home').addEventListener('click',event=>{event.preventDefault();show('briefing',{focus:true});});
    $('room-stage-tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const buttons=[...$('room-stage-tabs').querySelectorAll('button')];if(!buttons.length)return;event.preventDefault();const current=buttons.indexOf(document.activeElement);const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;stageView(next,{user:true});buttons[next].focus();});
    dialog.addEventListener('pointermove',event=>{if(!state.open||state.reduced.matches||event.pointerType==='touch')return;cancelAnimationFrame(state.raf);const rect=dialog.getBoundingClientRect(),x=(event.clientX-rect.left)/rect.width*2-1,y=(event.clientY-rect.top)/rect.height*2-1;state.raf=requestAnimationFrame(()=>{if(!state.open||state.reduced.matches)return;dialog.style.setProperty('--room-x',x.toFixed(3));dialog.style.setProperty('--room-y',y.toFixed(3));});});
    dialog.addEventListener('pointerleave',()=>{cancelAnimationFrame(state.raf);dialog.style.setProperty('--room-x','0');dialog.style.setProperty('--room-y','0');});
    dialog.addEventListener('close',close);
    state.reduced.addEventListener('change',()=>{if(state.seal)settleSeal(state.seal.epoch,state.seal.matchId);cancelStageMotion();cancelAnimationFrame(state.raf);cancelAnimationFrame(state.revealFrame);cancelAnimationFrame(state.entryFrame);clearTimeout(state.effectTimer);dialog.classList.remove('room-enter');$('room-verdict').classList.remove('room-reveal','room-celebrate');dialog.style.setProperty('--room-x','0');dialog.style.setProperty('--room-y','0');});
    show('briefing',{animate:false});
  }
  return {boot,open,close,render,watchJob,sealAccepted,classifyOutcome};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=ArenaRoom;
