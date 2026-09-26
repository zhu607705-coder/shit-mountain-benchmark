'use strict';
const ArenaUI = (() => {
  const tierNames = {bronze:'青铜',silver:'白银',gold:'黄金',diamond:'钻石',king:'王者',nightmare:'噩梦'};
  const trackNames = {R:'推理',C:'代码工程',F:'前端体验'};
  const activeJob = job => job && ['queued','running'].includes(job.status);
  const list = value => Array.isArray(value) ? value : value && typeof value === 'object' ? Object.entries(value).map(([id,row])=>({id,...row})) : [];
  const scopeOf = match => match?.public_scope || match?.public || match?.spec?.public || {};
  const scoreText = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-CN',{maximumFractionDigits:2}) : '待评';
  const duration = ms => typeof ms !== 'number' ? '未提供' : ms >= 3600000 ? `${(ms/3600000).toLocaleString('zh-CN',{maximumFractionDigits:1})} 小时` : ms >= 60000 ? `${(ms/60000).toLocaleString('zh-CN',{maximumFractionDigits:2})} 分钟` : `${(ms/1000).toLocaleString('zh-CN',{maximumFractionDigits:1})} 秒`;
  const tokens = value => typeof value === 'number' ? `${value.toLocaleString('zh-CN')} tokens` : '未提供';
  function submissionState(sub,report,taskId) {
    const status = sub?.status || 'unsubmitted';
    const valid = report?.valid ?? sub?.valid;
    const completed = report?.completed ?? sub?.completed;
    if (['grading','running','queued'].includes(status)) return {label:'检验中',tone:'running'};
    if (status === 'failed') return {label:'检验未完成',tone:'fail'};
    if (status === 'cancelled') return {label:'检验已停止',tone:'neutral'};
    if (valid === false || ['invalid','automatic_failed'].includes(status)) return {label:'自动失败',tone:'fail'};
    if (valid === true && (completed === false || status === 'partial')) return {label:taskId?.startsWith('F')?'语义部分完成':'部分完成',tone:'pending'};
    if (valid === true && completed === true) return {label:taskId?.startsWith('F')?'语义通过 · 完整评阅待定':taskId?.startsWith('R')?'合法完成':'自动通过',tone:taskId?.startsWith('F')?'pending':'pass'};
    if (status === 'review_pending') return {label:'待 Codex 完整评阅',tone:'pending'};
    if (valid === true) return {label:'合法 · 完成度待确认',tone:'pending'};
    if (status === 'sealed') return {label:'已封存 · 待检验',tone:'neutral'};
    return {label:'未提交',tone:'neutral'};
  }
  function caseState(item,taskId) {
    if (item.legal === false || item.valid === false) return {label:'失败',tone:'fail'};
    if (item.completed === true) return {label:taskId?.startsWith('R')?'已评估':taskId?.startsWith('F')?'语义通过':'通过',tone:'pass'};
    if (item.status === 'partial' || item.completed === false && (item.legal === true || item.valid === true)) return {label:'部分完成',tone:'pending'};
    return {label:'待确认',tone:'pending'};
  }
  function createApi(csrf, fetcher = (...args)=>fetch(...args)) {
    return async (path, body) => {
      const options = {method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}};
      if (body !== undefined) {options.headers['Content-Type']='application/json';options.headers['X-Arena-CSRF']=csrf() || '';options.body=JSON.stringify(body);}
      let response,raw;try{response=await fetcher(path,options);raw=await response.text();}catch{throw new Error('连接失败，请重试。');}let value;
      try {value=JSON.parse(raw);} catch {throw new Error(response.ok?'服务端返回了无法读取的数据。':`请求失败（HTTP ${response.status}）。`);}
      if (!response.ok) throw new Error(value.error?.message || value.message || (typeof value.error==='string'?value.error:`请求失败（HTTP ${response.status}）。`));
      return value;
    };
  }
  function jobProgress(job) {
    if (!job) return {fraction:null,label:''};
    const p=job.progress||{},total=p.case_count,current=p.case_index;
    if (job.status==='completed') return {fraction:1,label:Number.isInteger(total)&&total>0?`${total} / ${total} 组检验结束`:'检验结束'};
    if (activeJob(job)&&Number.isInteger(total)&&total>0&&Number.isInteger(current)&&current>=1&&current<=total)
      return {fraction:(current-1)/total,label:`正在执行第 ${current} / ${total} 组`};
    return {fraction:null,label:activeJob(job)?'等待检验进度':job.status==='cancelled'?'检验已停止':'检验未完成'};
  }
  function boot() {
    const $=id=>document.getElementById(id);
    const state={csrf:'',tasks:[],tiers:[],selectedTask:null,selectedTier:null,track:'all',manualTask:null,drawRequest:0,matches:[],match:null,reports:[],board:null,busy:false,poll:null,renderedId:null,readme:'',readmeName:'README.md',matchRequest:0,resultsKey:null};
    const api=createApi(()=>state.csrf);
    function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=String(text);if(className)node.className=className;return node;}
    function icon(name){const node=el('span',null,'lucide-icon');node.setAttribute('aria-hidden','true');node.style.setProperty('--icon-url',`url('/icons/${name}.svg')`);return node;}
    function setIcon(id,name){const node=$(id);if(node){node.replaceChildren(icon(name));}}
    function badge(text,tone){return el('span',text,'badge '+tone);}
    function announce(text,tone='error'){const node=$('notice');const dialogs=[...document.querySelectorAll('dialog[open]')];(dialogs.at(-1)||$('draw-stage')).append(node);node.textContent=text;node.className='notice'+(tone==='success'?' success':'');node.hidden=!text;}
    function motion(){return typeof ArenaMotion!=='undefined'?ArenaMotion:null;}
    function room(){return typeof ArenaRoom!=='undefined'?ArenaRoom:null;}
    function renderRoom(){if(state.match)room()?.render({match:state.match,reports:state.reports,board:state.board});}
    function syncPanels(){document.body.classList.toggle('panel-open',!!document.querySelector('dialog[open]'));motion()?.reset();if(!$('work-dialog').open)room()?.close();}
    function openPanel(id){if(state.busy)return;const dialog=$(id);if(!dialog.open)dialog.showModal();syncPanels();if(id==='work-dialog'){renderRoom();room()?.open();}}
    function closePanel(id){$(id).close();syncPanels();}
    function renderTicket(){if(!state.match)return;const pub=scopeOf(state.match),task=pub.task_id||state.match.task_id;
      $('selected-code').textContent=task;$('draw-heading').textContent=pub.title||state.match.title||task;
      $('selected-title').textContent=`${duration(pub.budgets?.total_ms)} · ${tokens(pub.budgets?.output_tokens)}`;
      $('card-track').textContent=trackNames[task?.charAt(0)]||'CHALLENGE';$('card-tier').textContent=pub.tier_name||tierNames[pub.tier||state.match.tier]||'';
      $('card-scope').textContent=`${pub.fixture_scale==='full'?'完整规模':'精简规模'} · ${pub.cases??'—'} 案例`;
      $('stage-position').textContent=`${task} / #${String(state.match.id).slice(-8)}`;$('start-challenge').hidden=false;
    }
    function track(task){return task.id?.slice(0,1) || 'R';}
    function selectedTask(){return state.tasks.find(task=>task.id===state.selectedTask);}
    function selectedTier(){return state.tiers.find(tier=>tier.id===state.selectedTier);}
    function endpoint(suffix='status'){return `/api/matches/${encodeURIComponent(state.match.id)}/${suffix}`;}
    function formatScope(value){return typeof value==='string'?value:value?.description || value?.label || value?.kind || '';}
    function renderTasks(){
      const rows=state.tasks.filter(task=>state.track==='all'||track(task)===state.track);$('task-count').textContent=`${rows.length} 道题`;
      $('task-grid').replaceChildren();
      for(const task of rows){const button=el('button',null,'task-card');button.type='button';button.setAttribute('aria-pressed',String(task.id===state.manualTask));button.setAttribute('aria-label',`${task.id} ${task.title}`);const top=el('span',null,'task-card-top');top.append(el('span',task.id,'task-code'),el('span',trackNames[track(task)]||task.track,'task-track'));button.append(top,el('strong',task.title));if(task.recommended_tier)button.append(el('small',`推荐 ${tierNames[task.recommended_tier]||task.recommended_tier}`));button.addEventListener('click',()=>{state.manualTask=task.id;state.selectedTask=task.id;renderTasks();renderSelection();closePanel('manual-dialog');});$('task-grid').append(button);}
      if(!rows.length)$('task-grid').append(el('p','这个方向暂无题目。','empty'));
      document.querySelectorAll('#track-tabs button[data-track]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.track===state.track)));
    }
    function renderTiers(){
      $('tier-options').replaceChildren();
      state.tiers.forEach((tier,index)=>{const button=el('button',null,'tier-button');button.type='button';button.setAttribute('aria-pressed',String(tier.id===state.selectedTier));button.setAttribute('aria-label',`${tier.name||tier.label||tierNames[tier.id]}难度`);button.append(el('span',tier.name||tier.label||tierNames[tier.id]||tier.id),el('small',String(index+1).padStart(2,'0')));button.addEventListener('click',()=>{state.selectedTier=tier.id;renderTiers();renderSelection();});$('tier-options').append(button);});
    }
    function metric(label,value){const node=el('span');node.append(el('strong',value),document.createTextNode(' '+label));return node;}
    function renderSelection(){
      const tier=selectedTier();$('tier-details').replaceChildren();$('draw-summary').replaceChildren();
      $('tier-current').textContent=tier?.name||tier?.label||tierNames[tier?.id]||'选择';
      if(tier){$('tier-details').append(el('p',tier.scope_label||tier.description||'以抽签范围为准。','tier-scope'));const metrics=el('div',null,'metric-strip');metrics.append(metric('规模',tier.fixture_scale==='full'?'完整':'精简'),metric('案例',tier.cases??'—'),metric('',duration(tier.total_ms)),metric('',tokens(tier.output_tokens)));$('tier-details').append(metrics);}
      $('manual-choice').hidden=!state.manualTask;$('manual-choice').textContent=state.manualTask?`指定 ${state.manualTask} ×`:'';
      $('draw-button').disabled=!tier||!state.tasks.length||state.busy;$('start-challenge').disabled=state.busy;
    }
    function matchPublic(match){return scopeOf(match);}
    function renderMatches(){
      $('match-list').replaceChildren();const rows=state.matches.slice(0,6);
      if(!rows.length){$('match-list').append(el('p','暂无场次','small-muted'));return;}
      rows.forEach(match=>{const pub=matchPublic(match);const button=el('button',null,'match-item');button.type='button';button.setAttribute('aria-current',String(state.match?.id===match.id));const text=el('span',`${match.task_id||pub.task_id||'挑战'} · ${pub.tier_name||tierNames[match.tier||pub.tier]||match.tier||''}`);text.append(el('small',String(match.id).slice(0,18)));button.append(text,icon('play'));button.addEventListener('click',()=>{if(state.busy)return;loadMatch(match.id,true).then(()=>closePanel('history-dialog')).catch(()=>{});});$('match-list').append(button);});
    }
    async function refreshMatches(){const result=await api('/api/matches');state.matches=list(result.matches||result);renderMatches();}
    function stageMarkdown(segment,index){const pub=scopeOf(state.match);const lines=[`# ${pub.task_id||state.match.task_id} · ${segment.name||segment.title||`阶段 ${index+1}`}`,`比赛：${state.match.id}`,`档位：${pub.tier_name||tierNames[pub.tier]||pub.tier||''}`,`范围：${formatScope(segment.scope)||formatScope(pub.scope)}`,`预算：${duration(segment.budget?.total_ms)} / ${tokens(segment.budget?.output_tokens)}`,'','## 材料',...(segment.materials||[]).map(value=>'- '+value),'','## 交付',...(segment.deliverables||[]).map(value=>'- '+value),'','## 任务',segment.prompt||'请阅读公开题包中的 PROMPT.md 和协议。'];return lines.join('\n');}
    function allMarkdown(){const pub=scopeOf(state.match);const stages=list(pub.prompt_segments||state.match.stages);return [`# ${pub.task_id||state.match.task_id} · ${pub.title||'挑战任务'}`,`场次：${state.match.id}`,`公开题包：${location.origin}${endpoint('download')}`,`档位：${pub.tier_name||tierNames[pub.tier]||''}`,`范围：${formatScope(pub.scope)}`,`案例次数：${pub.cases??'未提供'}`,`总体预算：${duration(pub.budgets?.total_ms)} / ${tokens(pub.budgets?.output_tokens)}`,'','请先阅读公开题包的 PROMPT.md 和协议；提交实际文件、复现命令、自测记录与未解决问题。未经观测的时间或 token 字段保持 null。',...stages.map((segment,index)=>'\n---\n\n'+stageMarkdown(segment,index))].join('\n');}
    function showReadme(text,title,name='README.md'){$('readme-heading').textContent=title;$('readme-content').textContent=text;$('readme-subtitle').textContent='复制到 Agent 会话，或保存为本机文件。';$('copy-status').textContent='';state.readme=text;state.readmeName=name;if(!$('readme-dialog').open)$('readme-dialog').showModal();syncPanels();}
    async function copy(text,statusNode){try{await navigator.clipboard.writeText(text);if(statusNode)statusNode.textContent='已复制';else announce('已复制。','success');}catch{if(statusNode)statusNode.textContent='复制未获浏览器许可，请在下方选中文字复制。';else announce('无法直接复制，请打开任务内容后选中文字复制。');}}
    function renderStages(){
      $('stage-cards').replaceChildren();const pub=scopeOf(state.match);const stages=list(pub.prompt_segments||state.match.stages);
      stages.forEach((stage,index)=>{const card=el('article',null,'stage-card');card.append(el('span',String(index+1).padStart(2,'0'),'stage-number'),el('h3',stage.name||stage.title||`阶段 ${index+1}`),el('p',formatScope(stage.scope),'stage-scope'));const details=el('details',null,'stage-materials');details.append(el('summary','材料与交付'));for(const [title,values] of [['材料',stage.materials],['交付',stage.deliverables]]){details.append(el('h4',title));const items=el('ul');for(const value of values||[])items.append(el('li',value));if(!items.children.length)items.append(el('li','见任务 README'));details.append(items);}card.append(details,el('p',`${duration(stage.budget?.total_ms)} · ${tokens(stage.budget?.output_tokens)}`,'stage-budget'));const actions=el('div',null,'stage-buttons');const view=el('button','查看任务','text-button');view.type='button';view.addEventListener('click',()=>showReadme(stageMarkdown(stage,index),stage.name||`阶段 ${index+1}`,`stage-${index+1}.md`));const copyButton=el('button','复制提示词','text-button');copyButton.type='button';copyButton.addEventListener('click',()=>copy(stageMarkdown(stage,index)));actions.append(view,copyButton);card.append(actions);$('stage-cards').append(card);});
      if(!stages.length)$('stage-cards').append(el('p','服务端尚未提供本场的阶段任务。','empty'));
    }
    function renderJob(){
      const job=state.match?.job;const submissions=list(state.match?.submissions);const label=job?({queued:'等待检验',running:'检验中',completed:'检验已结束',failed:'检验未完成',cancelled:'已停止'}[job.status]||job.status):submissions.length?'已封存':'未提交';$('job-state').textContent=label;$('job-state').className='badge '+(activeJob(job)?'running':job?.status==='failed'?'fail':'neutral');$('job-empty').hidden=!!job;$('job-content').hidden=!job;
      if(!job)return;const progress=typeof job.progress==='object'?job.progress:{};$('job-message').textContent=(job.diagnostic?'诊断复验 · ':'')+(progress.message||job.error?.message||job.error||label);$('job-elapsed').textContent=`${Math.max(0,Number(job.elapsed_seconds)||0).toFixed(1)} 秒`;const meter=jobProgress(job);$('progress-fill').style.width=`${(meter.fraction??0)*100}%`;const track=$('progress-fill').parentElement;track.classList.toggle('indeterminate',!!activeJob(job)&&meter.fraction===null);if(meter.fraction===null)track.removeAttribute('aria-valuenow');else track.setAttribute('aria-valuenow',String(Math.round(meter.fraction*100)));track.setAttribute('aria-valuetext',meter.label);$('job-detail').textContent=meter.label;$('cancel-job').hidden=!activeJob(job);
    }
    function renderResults(){
      const pub=scopeOf(state.match);const subs=list(state.match?.submissions),reports=state.reports,entries=list(state.board?.entries);const signature=JSON.stringify({id:state.match.id,subs,reports,entries,board:state.board});if(signature===state.resultsKey)return;state.resultsKey=signature;const opened=new Set([...$('case-details').querySelectorAll('details[open]')].map(node=>node.dataset.submissionId));const active=document.activeElement;const focusedId=active?.closest?.('[data-submission-id]')?.dataset.submissionId;const focusedKind=active?.tagName==='SUMMARY'?'summary':active?.dataset?.resultAction;const byId=new Map(reports.map(row=>[row.submission_id||row.id,row]));const leaderboard=new Map(entries.map(row=>[row.submission_id||row.id,row]));$('result-rows').replaceChildren();$('case-details').replaceChildren();$('results-empty').hidden=!!subs.length;$('results-table-wrap').hidden=!subs.length;
      for(const sub of subs){const report=byId.get(sub.id)||sub.report||{},rank=leaderboard.get(sub.id)||{},status=submissionState(sub,report,pub.task_id||state.match.task_id);const tr=el('tr');const identity=el('td');identity.append(el('strong',sub.participant||sub.name||'未命名选手'),el('small',String(sub.id).slice(0,16)));const statusCell=el('td');statusCell.append(badge(status.label,status.tone));if(report.codex_review_required&&status.tone!=='running')statusCell.append(el('small','Codex 待评'));const cases=el('td',report.cases_count!=null?`${report.passed_cases??'—'} / ${report.cases_count}`:'待检验');const raw=el('td',scoreText(report.raw_score??sub.raw_score),'numeric');const relative=el('td',scoreText(rank.relative_score??report.relative_score??sub.relative_score),'numeric');const efficiency=el('td',report.efficiency_eligible===true?scoreText(report.efficiency_score):'待核验');const actions=el('td'),buttons=el('div',null,'row-actions');const grade=el('button','检验','text-button');grade.type='button';grade.dataset.submissionId=sub.id;grade.dataset.resultAction='grade';grade.disabled=!!activeJob(state.match.job);grade.setAttribute('aria-label',`检验 ${sub.participant||sub.id}`);grade.addEventListener('click',()=>startGrade(sub.id));buttons.append(grade);actions.append(buttons);tr.append(identity,statusCell,cases,raw,relative,efficiency,actions);$('result-rows').append(tr);
        const reportCases=list(report.cases);if(reportCases.length){const box=el('details',null,'case-box');box.dataset.submissionId=sub.id;box.open=opened.has(sub.id);box.append(el('summary',`${sub.participant||sub.id} · ${reportCases.length} 个案例结果`));reportCases.forEach((item,index)=>{const row=el('div',null,'case-row');const title=el('h4');title.append(el('span',`案例 ${item.index??item.case_index??index+1}`),badge(caseState(item,pub.task_id||state.match.task_id).label,caseState(item,pub.task_id||state.match.task_id).tone));row.append(title);if(item.summary||item.message)row.append(el('p',item.summary||item.message));const failures=list(item.failures||item.failed_checks);if(failures.length){const items=el('ul');failures.forEach(failure=>items.append(el('li',typeof failure==='string'?failure:failure.name||failure.message||failure.detail||'未通过断言')));row.append(items);}box.append(row);});$('case-details').append(box);}
      }
      if(focusedId){const target=[...document.querySelectorAll('[data-submission-id]')].find(node=>node.dataset.submissionId===focusedId&&(focusedKind==='summary'?node.tagName==='DETAILS':node.dataset.resultAction===focusedKind));(focusedKind==='summary'?target?.querySelector('summary'):target)?.focus({preventScroll:true});}
      const champion=subs.find(sub=>sub.id===state.board?.champion);$('leaderboard-note').textContent=state.board?.all_invalid&&subs.length?'本场尚无有效解，未生成相对满分。':champion?(state.board?.champion_scope==='semantic_only'?`语义领先：${champion.participant}。完整 UI 评阅待定。`:`自动成绩领先：${champion.participant}`):(pub.task_id||state.match.task_id||'').startsWith('F')&&subs.length?'当前仅列语义分，完整 UI 评阅待定。':'';
      renderRoom();
    }
    function renderMatch(){
      if(!state.match)return;$('match-section').hidden=false;const pub=scopeOf(state.match);$('match-kicker').textContent=`场次 #${String(state.match.id).slice(-8)}`;$('match-heading').textContent=`${pub.task_id||state.match.task_id} · ${pub.title||state.match.title||'挑战实例'}`;$('match-description').textContent=`${pub.tier_name||tierNames[pub.tier||state.match.tier]||''} · ${formatScope(pub.scope)}`;$('commitment').textContent=pub.commitment||state.match.commitment||'尚未提供';$('download-package').href=endpoint('download');$('download-grading').href=endpoint('grading-request');
      if(state.renderedId!==state.match.id){state.renderedId=state.match.id;renderStages();$('entrypoint').value=(pub.task_id||state.match.task_id||'').startsWith('C')?'.':(pub.task_id||state.match.task_id||'').startsWith('F')?'adapter.py':'policy.py';$('submit-feedback').textContent='';}
      renderJob();renderResults();renderMatches();renderTicket();renderRoom();
    }
    function schedulePoll(){clearTimeout(state.poll);if(!state.match||state.busy)return;state.poll=setTimeout(async()=>{try{await loadMatch(state.match.id,false,true);}catch(error){$('connection-label').textContent='连接中断';$('connection-dot').className='dot error';schedulePoll();}},document.hidden?10000:activeJob(state.match.job)?1400:4000);}
    async function refreshResults(requestVersion=state.matchRequest){if(!state.match)return;const id=state.match.id;const answers=await Promise.allSettled([api(endpoint('report')),api(endpoint('leaderboard'))]);if(state.match?.id!==id||requestVersion!==state.matchRequest)return;const [reports,board]=answers;if(reports.status==='fulfilled')state.reports=list(reports.value.reports||reports.value);if(board.status==='fulfilled')state.board=board.value;renderResults();}
    async function loadMatch(id,reveal=false,quiet=false){
      if(quiet&&(state.busy||state.loadingMatch))return;clearTimeout(state.poll);const requestVersion=++state.matchRequest;state.loadingMatch=requestVersion;
      try {const result=await api(`/api/matches/${encodeURIComponent(id)}/status`);if(requestVersion!==state.matchRequest)return;const match=result.match||result;const changed=state.match?.id!==match.id;if(changed){state.reports=[];state.board=null;}state.match=match;
        renderMatch();await refreshResults(requestVersion);if(requestVersion!==state.matchRequest)return;$('connection-label').textContent='本机已连接';$('connection-dot').className='dot online';
        if(reveal){await motion()?.reveal(scopeOf(match).task_id||match.task_id);if(requestVersion!==state.matchRequest)return;$('start-challenge').hidden=false;}
        schedulePoll();
      }catch(error){if(requestVersion!==state.matchRequest)return;if(!quiet)announce(error.message);throw error;}
      finally{if(state.loadingMatch===requestVersion)state.loadingMatch=null;}
    }
    async function startGrade(submissionId){const mid=state.match?.id;if(!mid)return;try{announce('');const job=await api(`/api/matches/${encodeURIComponent(mid)}/grade`,{submission_id:submissionId});if(state.match?.id!==mid)return;room()?.watchJob(job.id);await loadMatch(mid);if(state.match?.id===mid)$('submit-feedback').textContent='答案已封存，检验已启动。';}catch(error){if(state.match?.id!==mid)return;announce(error.message);$('submit-feedback').textContent='答案仍已封存，可稍后重新开始检验。';await loadMatch(mid,false,true).catch(()=>{});}}
    async function initialize(){
      try{const data=await api('/api/bootstrap');state.csrf=data.csrf||'';state.tasks=list(data.tasks||data.catalog?.tasks);state.tiers=list(data.tiers||data.catalog?.tiers);state.selectedTask=state.selectedTask||state.tasks[0]?.id;state.selectedTier=state.selectedTier||(state.tiers.some(tier=>tier.id==='bronze')?'bronze':state.tiers[0]?.id);state.matches=list(data.matches);renderTasks();renderTiers();renderSelection();renderMatches();$('connection-label').textContent='本机已连接';$('connection-dot').className='dot online';announce('');await refreshMatches();}catch(error){$('connection-label').textContent='服务未连接';$('connection-dot').className='dot error';announce(error.message);$('task-grid').replaceChildren(el('p','题库读取失败，请重新连接。','empty'));}}
    document.querySelectorAll('#track-tabs button[data-track]').forEach(button=>button.addEventListener('click',()=>{if(state.busy)return;state.track=button.dataset.track;state.manualTask=null;renderTasks();renderSelection();}));
    $('open-manual').addEventListener('click',()=>openPanel('manual-dialog'));
    $('open-history').addEventListener('click',()=>{openPanel('history-dialog');refreshMatches().catch(error=>announce(error.message));});
    $('start-challenge').addEventListener('click',()=>{if(state.match){openPanel('work-dialog');$('match-heading').focus({preventScroll:true});}});
    $('close-work').addEventListener('click',()=>closePanel('work-dialog'));
    $('close-tier').addEventListener('click',()=>{$('tier-picker').open=false;});
    $('manual-choice').addEventListener('click',()=>{state.manualTask=null;renderTasks();renderSelection();});
    document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>closePanel(button.dataset.close)));
    document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',syncPanels));
    $('reload-app').addEventListener('click',initialize);$('refresh-matches').addEventListener('click',()=>refreshMatches().catch(error=>announce(error.message)));$('refresh-results').addEventListener('click',()=>state.match&&loadMatch(state.match.id).catch(()=>{}));
    $('draw-button').addEventListener('click',async()=>{
      if(state.busy)return;state.busy=true;const request=++state.drawRequest;++state.matchRequest;clearTimeout(state.poll);$('tier-picker').open=false;renderSelection();motion()?.begin();$('draw-label').textContent='抽取中';
      try{announce('');const result=await api('/api/draw',{task_id:state.manualTask||'random',tier:state.selectedTier,track:state.track});if(request!==state.drawRequest)return;const match=result.match||result;await loadMatch(match.id,true);await refreshMatches().catch(()=>{});}
      catch(error){motion()?.fail(!!state.match);announce(error.message);}
      finally{state.busy=false;$('draw-label').textContent=state.match?'再抽一道':'抽一道';renderSelection();schedulePoll();}
    });
    $('submission-form').addEventListener('submit',async event=>{event.preventDefault();const mid=state.match?.id;if(!mid)return;const participant=$('participant').value.trim(),source_path=$('source-path').value.trim(),entrypoint=$('entrypoint').value.trim(),metrics_path=$('metrics-path').value.trim();if(!participant||!source_path||!entrypoint){announce('请填写选手、答案路径和裁判入口。');return;}$('submit-button').disabled=true;$('submit-feedback').textContent='正在封存…';try{announce('');const payload={participant,source_path,entrypoint};if(metrics_path)payload.metrics_path=metrics_path;const result=await api(`/api/matches/${encodeURIComponent(mid)}/submit`,payload);if(state.match?.id!==mid)return;const sub=result.submission||result;if(!sub.id)throw new Error('服务端未返回提交编号，请刷新确认封存状态。');await loadMatch(mid);if(state.match?.id===mid)await startGrade(sub.id);}catch(error){if(state.match?.id!==mid)return;announce(error.message);$('submit-feedback').textContent='未完成提交，请核对路径与服务端提示。';}finally{$('submit-button').disabled=false;}});
    $('cancel-job').addEventListener('click',async()=>{if(!state.match?.job)return;try{await api(endpoint('cancel'),{job_id:state.match.job.id});await loadMatch(state.match.id);}catch(error){announce(error.message);}});
    $('open-readme').addEventListener('click',()=>state.match&&showReadme(allMarkdown(),'Agent 任务 README'));
    $('close-readme').addEventListener('click',()=>$('readme-dialog').close());$('readme-dialog').addEventListener('click',event=>{if(event.target===$('readme-dialog')){const bounds=event.target.getBoundingClientRect();if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)event.target.close();}});
    $('copy-readme').addEventListener('click',()=>copy(state.readme,$('copy-status')));$('copy-commitment').addEventListener('click',()=>copy(scopeOf(state.match).commitment||state.match.commitment||''));$('download-readme').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([state.readme],{type:'text/markdown;charset=utf-8'}));const link=el('a');link.href=url;link.download=state.readmeName;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.match)loadMatch(state.match.id,false,true).catch(()=>{});});
    setIcon('reload-app','refresh-cw');setIcon('close-readme','circle-x');document.querySelectorAll('[data-icon]').forEach(node=>node.replaceChildren(icon(node.dataset.icon)));room()?.boot();initialize();
  }
  return {boot,createApi,submissionState,caseState,scoreText,duration,tokens,scopeOf,activeJob,jobProgress};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=ArenaUI;
if(typeof document!=='undefined'&&document.getElementById('arena-app'))ArenaUI.boot();
