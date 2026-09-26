'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {classifyOutcome} = require('./room.js');
const {jobProgress} = require('./app.js');

const grade = (taskId, values={}, job={}) => classifyOutcome({
  taskId, submission:{id:'s1',status:'graded'},
  report:{id:'s1',valid:true,completed:true,raw_score:100,grade_id:'j1',official:true,...values},
  job:{id:'j1',submission_id:'s1',status:'completed',...job}
});

test('only a completed code contract can trigger success celebration',()=>{
  const result=grade('C1');
  assert.equal(result.kind,'passed');assert.equal(result.canCelebrate,true);assert.equal(result.rawScore,100);
});
test('a completed runner with a failing candidate remains failure, preserving zero',()=>{
  const result=grade('C1',{valid:false,completed:false,raw_score:0});
  assert.equal(result.kind,'failed');assert.equal(result.canCelebrate,false);assert.equal(result.rawScore,0);
});
test('legally completed low-quality reasoning is evaluated, not a perfect victory',()=>{
  const result=grade('R3',{raw_score:20.8333333333,relative_score:100});
  assert.equal(result.kind,'evaluated');assert.equal(result.canCelebrate,false);assert.equal(result.rawScore,20.8333333333);
});
test('frontend semantic pass does not certify full browser experience',()=>{
  const result=grade('F1',{codex_review_required:true,score_scope:'semantic_only',status:'review_pending'});
  assert.equal(result.kind,'semantic');assert.equal(result.canCelebrate,false);
});
test('frontend partial result remains partial even when public status is review_pending',()=>{
  const result=grade('F1',{completed:false,raw_score:33.333333,relative_score:100,codex_review_required:true,status:'review_pending'});
  assert.equal(result.kind,'partial');assert.equal(result.canCelebrate,false);
});
test('diagnostic reruns cannot create a fresh official success',()=>{
  const result=grade('C1',{}, {id:'j2',diagnostic:true,official_result:false});
  assert.equal(result.kind,'diagnostic');assert.equal(result.canCelebrate,false);
});
test('environment errors and cancellations do not manufacture candidate scores',()=>{
  for(const status of ['failed','cancelled']){
    const result=grade('C1',{valid:null,completed:null,raw_score:null},{status});
    assert.equal(result.canCelebrate,false);assert.equal(result.rawScore,null);
    assert.equal(result.kind,status==='failed'?'error':'cancelled');
  }
});
test('explicit pending fields override any older submission score',()=>{
  const result=classifyOutcome({taskId:'C1',submission:{id:'s1',valid:true,completed:true,raw_score:100},
    report:{id:'s1',valid:null,completed:null,raw_score:null},job:{status:'completed'}});
  assert.equal(result.canCelebrate,false);assert.equal(result.rawScore,null);
});
test('stale grade evidence cannot celebrate a newer completed job',()=>{
  const result=grade('C1',{grade_id:'old-job'},{id:'new-job',official_result:true});
  assert.equal(result.canCelebrate,false);
});
test('missing or malformed score values are never displayed as fabricated zero',()=>{
  for(const raw_score of [null,undefined,NaN,Infinity,'100']){
    const result=grade('C1',{raw_score});
    assert.equal(result.rawScore,null);assert.equal(result.canCelebrate,false);
  }
});
test('running case index denotes work in progress, not a completed case',()=>{
  assert.equal(jobProgress({status:'running',progress:{case_index:1,case_count:3}}).fraction,0);
  assert.equal(jobProgress({status:'running',progress:{case_index:2,case_count:3}}).fraction,1/3);
  assert.equal(jobProgress({status:'completed',progress:{case_count:3}}).fraction,1);
  assert.equal(jobProgress({status:'running',progress:{}}).fraction,null);
  assert.equal(jobProgress({status:'failed',progress:{case_index:2,case_count:3}}).fraction,null);
});
