"""Public deterministic smoke checks; not a replacement for browser scenarios."""
from pathlib import Path
import json
import subprocess
import tempfile
import re
from datetime import datetime, timezone

ROOT = Path(__file__).parent
STAMP = datetime.now(timezone.utc).isoformat()

def scripts(path):
    return [content for attrs,content in re.findall(r'<script([^>]*)>(.*?)</script>',path.read_text(),re.S) if 'application/json' not in attrs]

for problem in ('F1','F2'):
    checks=[]
    for name in ('baseline.html','starter.html'):
        code='\n'.join(scripts(ROOT/problem/name))
        with tempfile.NamedTemporaryFile(mode='w',suffix='.js') as f:
            f.write(code);f.flush()
            result=subprocess.run(['node','--check',f.name],capture_output=True,text=True)
            assert result.returncode==0, result.stderr
        checks.append({'id':f'{name}:syntax','passed':True,'method':'node --check'})
    data=json.loads((ROOT/problem/'data.json').read_text())
    if problem=='F1':
        events=data['events']; byid={e['id']:e for e in events}
        assert len(events)==10000 and len(byid)==10000
        assert 'EVT-10000' in byid and 'onerror=' in byid['EVT-00043']['title']
        assert len([e for e in events if e['trace']=='TR-INCIDENT-042'])==6
        for event in events:
            seen=set(); cur=event
            while cur:
                assert cur['id'] not in seen
                seen.add(cur['id']);cur=byid[cur['parent']] if cur['parent'] else None
        checks.append({'id':'fixture_integrity','passed':True,'method':'10000 unique IDs, reachable parents, acyclic relations, 6 incident records, literal HTML and tail sentinel'})
    else:
        code='\n'.join(scripts(ROOT/problem/'baseline.html'))
        logic=code[code.index('function validate('):code.index('function dirty(')]
        harness='const fixture='+json.dumps(data)+';let tasks=fixture.tasks;const resourceName=id=>fixture.resources.find(x=>x.id===id).name;\n'+logic+'''
const assert=require('node:assert/strict');
assert.equal(validate().length,5);
assert.equal(hasCycle(tasks),false);
let loop=structuredClone(tasks);loop[0].deps=['T02'];assert.equal(hasCycle(loop),true);
const pair=[{id:'A',resource:'bench',start:0,duration:40,deps:[]},{id:'B',resource:'bench',start:40,duration:20,deps:['A']}];
assert.equal(validate(pair).length,0);pair[1].start=39;assert.equal(validate(pair).length,2);
console.log(JSON.stringify({initialIssues:validate().length,acyclic:true,cycleDetection:true,boundaryCheck:true}));
'''
        with tempfile.NamedTemporaryFile(mode='w',suffix='.cjs') as f:
            f.write(harness);f.flush()
            result=subprocess.run(['node',f.name],capture_output=True,text=True)
            assert result.returncode==0,result.stderr
        checks.append({'id':'constraint_logic','passed':True,'method':'execute actual validate/hasCycle functions in Node, independently assert initial=5, cycle, adjacent and overlap boundaries','output':json.loads(result.stdout)})
    report={'task_id':problem,'generated_at':STAMP,'valid':None,'valid_reason':'Cross-window mechanisms revised; full browser qualification has not been assigned by this smoke-check script.','machine_score':None,'human_visual_score':None,'raw_score':None,'checked':checks,'pending':['Complete browser F01-F12 and A01-A04; see parent browser report for observed subset','Independent anonymous human visual evaluation'],'known_failures':[],'cross_window_regression':'Pending independent browser replay; F1 uses per-event keys, F2 locks and refuses stale shared writes with recoverable drafts.','evidence_scope':'This file contains only executed syntax and deterministic logic checks, not browser or visual claims.'}
    (ROOT/problem/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(problem+': '+str(len(checks))+' executed checks passed; browser and human scores unassigned')
