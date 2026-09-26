"""Relative ranking utility. Inputs must come from an independent trusted verifier."""
from __future__ import annotations
import math

def _finite_number(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value)
    except (OverflowError,ValueError):return False


def quality_from_loss(loss: float, scale: float=10.0) -> float:
    if not _finite_number(loss) or loss<0 or not _finite_number(scale) or scale<=0:
        raise ValueError('finite nonnegative loss and positive scale required')
    return 1/(1+loss/scale)

def relative_scores(rows:list[dict])->list[dict]:
    """Row fields: name, quality [0,1], eligible (real bool).
    Ineligible rows get 0. No valid positive quality means no winner.
    """
    if type(rows) is not list:raise ValueError('result rows must be a list')
    seen=set()
    for r in rows:
        if type(r) is not dict or not {'name','quality','eligible'}<=set(r):raise ValueError('invalid trusted result row')
        if type(r['name']) is not str or not r['name'] or r['name'] in seen:raise ValueError('unique nonempty result names required')
        seen.add(r['name'])
        if type(r['eligible']) is not bool or not _finite_number(r['quality']) or not 0<=r['quality']<=1:
            raise ValueError('invalid trusted result row')
    best=max((r['quality'] for r in rows if r['eligible']),default=0)
    return [dict(r,relative_score=(100*r['quality']/best if best>0 and r['eligible'] else 0),
                 leaderboard_has_winner=best>0) for r in rows]

if __name__=='__main__':
    r=relative_scores([{'name':'A','quality':.8,'eligible':True},
                       {'name':'B','quality':.6,'eligible':True},
                       {'name':'invalid','quality':1,'eligible':False}])
    assert [x['relative_score'] for x in r]==[100,75,0]
    assert relative_scores([])==[]
    assert not relative_scores([{'name':'x','quality':0,'eligible':True}])[0]['leaderboard_has_winner']
    print('scoring checks passed')
