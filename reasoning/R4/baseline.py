"""Deadline-aware online dispatcher. No access to future arrivals or outages."""
from __future__ import annotations


def act(observation:dict) -> list[dict]:
    t=observation['time']; done=set(observation['done'])
    jobs={j['id']:j for j in observation['jobs']}
    waiting=[j for j in jobs.values() if j['state']=='waiting' and all(d in done for d in j['deps'])]
    free=[m for m in observation['machines'] if m['available']]
    power=observation['free_power']; actions=[]; used=set()
    # A direct child bonus is observable, unlike future release information.
    children={j['id']:sum(k['weight']*.18 for k in jobs.values() if k['state']=='waiting' and j['id'] in k['deps']) for j in waiting}
    while free:
        candidates=[]
        for m in free:
            for j in waiting:
                if j['id'] in used or m['id'] not in j['eligible'] or j['power']>power:continue
                p=max(1,j['duration']*m['speed'])+(0 if m['family']==j['family'] else 3)
                slack=j['deadline']-t-p
                urgency=(j['weight']+children[j['id']])/(p**.65) * (1+max(0,12-slack)/8)
                candidates.append((urgency,-p,j['id'],m['id'],j,m))
        if not candidates:break
        *_,j,m=max(candidates,key=lambda x:x[:4])
        actions.append({'job':j['id'],'machine':m['id']});used.add(j['id']);power-=j['power'];free.remove(m)
    return actions
