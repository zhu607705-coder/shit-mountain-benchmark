'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

// A deterministic DOM/timer harness exercises the production controllers without
// browser dependencies. Rendering and reduced-motion CSS remain browser checks.
function fixture(script,{reduced=false}={}){
  let now=0,nextId=0;
  const timers=new Map(),frames=new Map(),nodes=new Map();
  const document={activeElement:null,hidden:false,addEventListener(){}};
  class Element{
    constructor(tag='div'){
      this.tagName=tag.toUpperCase();this.dataset={};this.children=[];this.hidden=false;
      this.attributes={};this.listeners=new Map();this.animations=[];this.classEvents=[];
      this.style={values:{},setProperty:(name,value)=>{this.style.values[name]=value;}};
      const classes=new Set();
      this.classList={add:(...names)=>names.forEach(name=>{classes.add(name);this.classEvents.push(['add',name]);}),remove:(...names)=>names.forEach(name=>classes.delete(name)),contains:name=>classes.has(name),toggle:(name,force)=>{if(force??!classes.has(name))classes.add(name);else classes.delete(name);}};
      Object.defineProperty(this,'className',{get:()=>[...classes].join(' '),set:value=>{classes.clear();String(value).split(/\s+/).filter(Boolean).forEach(name=>classes.add(name));}});
    }
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(name,value){this.attributes[name]=String(value);}
    removeAttribute(name){delete this.attributes[name];}
    addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,[]);this.listeners.get(name).push(fn);}
    emit(name,event={}){for(const fn of this.listeners.get(name)||[])fn({target:this,preventDefault(){},...event});}
    focus(){document.activeElement=this;}
    scrollTo(){}
    getBoundingClientRect(){return {left:0,top:0,width:1000,height:800};}
    animate(keyframes,options){const animation={keyframes,options,cancelled:false,cancel(){this.cancelled=true;}};this.animations.push(animation);return animation;}
    querySelectorAll(selector){
      const descendants=[];const visit=node=>{for(const child of node.children){descendants.push(child);visit(child);}};visit(this);
      return descendants.filter(node=>{
        if(selector==='.room-nav [data-room-view]')return node.dataset.roomView!==undefined;
        if(selector==='[data-room-page]')return node.dataset.roomPage!==undefined;
        if(selector==='[data-room-go]')return node.dataset.roomGo!==undefined;
        const page=/^\[data-room-page="(.*)"\]$/.exec(selector);
        if(page)return node.dataset.roomPage===page[1];
        return selector.startsWith('.')?node.classList.contains(selector.slice(1)):node.tagName===selector.toUpperCase();
      });
    }
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  }
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  document.getElementById=get;document.createElement=tag=>new Element(tag);document.body=new Element('body');
  const reducedQuery={matches:reduced,listeners:[],addEventListener(name,fn){this.listeners.push(fn);},change(value){this.matches=value;this.listeners.forEach(fn=>fn({matches:value}));}};
  const dialog=get('work-dialog');dialog.open=true;
  const nav={};
  for(const view of ['briefing','submission','inspection','results']){
    const page=new Element('section');page.dataset.roomPage=view;page.append(new Element('h2'));dialog.append(page);
    const button=new Element('button');button.dataset.roomView=view;dialog.append(button);nav[view]=button;
  }
  const cards=[0,1,2].map(()=>{const card=new Element('article');card.className='stage-card';return card;});
  get('stage-cards').append(...cards);
  const context={module:{exports:{}},document,matchMedia:query=>query.includes('prefers-reduced')?reducedQuery:{matches:true,addEventListener(){}},performance:{now:()=>now},setTimeout(fn,ms){const id=++nextId;timers.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>timers.delete(id),requestAnimationFrame(fn){const id=++nextId;frames.set(id,fn);return id;},cancelAnimationFrame:id=>frames.delete(id)};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,script),'utf8'),context,{filename:script});
  function advance(ms){const end=now+ms;for(;;){const pending=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!pending)break;const [id,timer]=pending;timers.delete(id);now=timer.at;timer.fn();}now=end;}
  function paint(){const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(now));}
  return {api:context.module.exports,get,nav,cards,advance,paint,reduced:reducedQuery,timers};
}
function match(id='m1',job=null){return {id,task_id:'C1',public_scope:{task_id:'C1',tier:'bronze',prompt_segments:[{name:'定位'},{name:'修复'},{name:'回归'}]},submissions:[{id:'s1',participant:'test'}],job};}
function room(options){const f=fixture('room.js',options);f.match=match();f.api.render({match:f.match});f.api.open();f.paint();return f;}
const job=status=>({id:'j1',submission_id:'s1',status});
const report=(grade_id='j1')=>({submission_id:'s1',grade_id,valid:true,completed:true,raw_score:100});

test('task changes preserve all eight plane nodes and update their layout in place',()=>{
  const f=fixture('motion.js'),planes=f.get('blade-field').children.slice();
  assert.equal(planes.length,8);
  const initial=planes[0].style.values['--blade-angle'];
  for(const id of ['R1','C2','F4','R3']){
    f.api.setTask(id);assert.equal(f.get('blade-field').children.length,8);
    planes.forEach((node,index)=>assert.equal(f.get('blade-field').children[index],node));
  }
  assert.notEqual(planes[0].style.values['--blade-angle'],initial);
  assert.equal(f.get('draw-stage').dataset.track,'R');
});

test('stage animation responds to user changes but survives polling without replay',()=>{
  const f=room(),tabs=f.get('room-stage-tabs');tabs.children[1].emit('click');
  assert.equal(f.cards[1].hidden,false);assert.equal(f.cards[1].animations.length,1);
  const original=f.cards[1].animations[0];
  for(let i=0;i<5;i++)f.api.render({match:f.match});
  tabs.children[1].emit('click');
  assert.equal(f.cards[1].animations.length,1);assert.equal(original.cancelled,false);
  tabs.children[2].emit('click');assert.equal(original.cancelled,true);
  assert.equal(f.cards[2].animations.length,1);
  f.nav.submission.emit('click');assert.equal(f.cards[2].animations[0].cancelled,true);
});

test('keyboard stages and reduced motion share the same lifecycle',()=>{
  const f=room(),tabs=f.get('room-stage-tabs');tabs.children[0].focus();
  tabs.emit('keydown',{key:'End'});assert.equal(f.cards[2].animations.length,1);
  f.reduced.change(true);assert.equal(f.cards[2].animations[0].cancelled,true);
  tabs.children[1].emit('click');assert.equal(f.cards[1].hidden,false);assert.equal(f.cards[1].animations.length,0);
});

test('server-accepted seal holds the submission view while the grader starts',()=>{
  const f=room();f.nav.submission.emit('click');assert.equal(f.api.sealAccepted(),true);
  f.api.watchJob('j1');f.api.render({match:match('m1',job('running'))});
  assert.equal(f.get('work-dialog').dataset.roomView,'submission');
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),true);
  f.advance(819);assert.equal(f.get('work-dialog').dataset.roomView,'submission');
  f.advance(1);assert.equal(f.get('work-dialog').dataset.roomView,'inspection');
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),false);
});

test('a fast genuine result waits for the seal and is revealed once',()=>{
  const f=room();f.nav.submission.emit('click');f.api.sealAccepted();f.api.watchJob('j1');
  const completed={match:match('m1',job('completed')),reports:[report()]};
  f.api.render(completed);f.paint();
  assert.equal(f.get('work-dialog').dataset.roomView,'submission');
  assert.equal(f.get('room-verdict').classList.contains('room-reveal'),false);
  f.advance(820);f.paint();assert.equal(f.get('work-dialog').dataset.roomView,'results');
  assert.equal(f.get('room-verdict').classList.contains('room-celebrate'),true);
  for(let i=0;i<3;i++){f.api.render(completed);f.paint();}
  assert.equal(f.get('room-verdict').classEvents.filter(([op,name])=>op==='add'&&name==='room-reveal').length,1);
});

test('a terminal job with stale evidence stays in inspection after seal completion',()=>{
  const f=room();f.nav.submission.emit('click');f.api.sealAccepted();f.api.watchJob('j1');
  f.api.render({match:match('m1',job('completed')),reports:[report('older-job')]});
  f.advance(820);f.paint();assert.equal(f.get('work-dialog').dataset.roomView,'inspection');
  assert.equal(f.get('room-verdict').classList.contains('room-celebrate'),false);
  f.api.render({match:match('m1',job('completed')),reports:[report()]});f.paint();
  assert.equal(f.get('work-dialog').dataset.roomView,'results');
});

test('a stale seal callback cannot cancel a new match seal or move its page',()=>{
  const f=room();f.nav.submission.emit('click');f.api.sealAccepted();
  const stale=[...f.timers.values()].find(timer=>timer.at===820).fn;
  f.api.render({match:match('m2')});f.nav.submission.emit('click');f.api.sealAccepted();
  stale();
  assert.equal(f.get('work-dialog').dataset.roomView,'submission');
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),true);
  assert.equal(f.get('room-verdict').classList.contains('room-celebrate'),false);
});

test('closing cancels the seal and stale callbacks do not reopen or navigate',()=>{
  const f=room();f.nav.submission.emit('click');f.api.sealAccepted();f.api.watchJob('j1');
  const stale=[...f.timers.values()].find(timer=>timer.at===820).fn;
  f.get('work-dialog').open=false;f.api.close();
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),false);
  const view=f.get('work-dialog').dataset.roomView;stale();f.advance(1000);
  assert.equal(f.get('work-dialog').open,false);assert.equal(f.get('work-dialog').dataset.roomView,view);
});

test('deliberate page navigation cancels the seal without a delayed jump',()=>{
  const f=room();f.nav.submission.emit('click');f.api.sealAccepted();f.api.watchJob('j1');
  const stale=[...f.timers.values()].find(timer=>timer.at===820).fn;
  f.nav.briefing.emit('click');stale();f.advance(1000);
  assert.equal(f.get('work-dialog').dataset.roomView,'briefing');
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),false);
});

test('reduced motion skips an accepted seal and settles an in-flight seal immediately',()=>{
  const f=room({reduced:true});f.nav.submission.emit('click');
  assert.equal(f.api.sealAccepted(),false);f.api.watchJob('j1');
  assert.equal(f.get('work-dialog').dataset.roomView,'inspection');
  f.reduced.change(false);f.nav.submission.emit('click');f.api.sealAccepted();
  f.reduced.change(true);
  assert.equal(f.get('work-dialog').dataset.roomView,'inspection');
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),false);
});

test('mere submissions and grading status never invent a seal confirmation',()=>{
  const f=room();f.nav.submission.emit('click');f.api.render({match:match('m1',job('running'))});
  assert.equal(f.get('work-dialog').classList.contains('room-sealing'),false);
  f.api.watchJob('j1');assert.equal(f.get('work-dialog').dataset.roomView,'inspection');
});
