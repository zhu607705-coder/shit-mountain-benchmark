"""Relative ranking utility. Inputs must come from an independent trusted verifier."""
from __future__ import annotations
import math

def quality_from_loss(loss: float, scale: float=10.0) -> float:
    if not math.isfinite(loss) or loss<0 or not math.isfinite(scale) or scale<=0:
        raise ValueError('finite nonnegative loss and positive scale required')
    return 1/(1+loss/scale)

def relative_scores(rows:list[dict])->list[dict]:
    """Row fields: name, quality [0,1], eligible (real bool).
    Ineligible rows get 0. No valid positive quality means no winner.
    """
    for r in rows:
        if type(r['eligible']) is not bool or not math.isfinite(r['quality']) or not 0<=r['quality']<=1:
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
