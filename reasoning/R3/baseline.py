"""Myopic Bayesian experiment selection. Python 3.11+, standard library only.
Contract: act(public_model, history, remaining_budget) -> query or repair.
The policy never receives the sampled hidden hypothesis or simulator seed.
"""
from __future__ import annotations
import itertools
import math


def posterior(model: dict, history: list[dict]) -> list[float]:
    weights = [max(p, 1e-300) for p in model['prior']]
    logs = [math.log(w) for w in weights]
    for item in history:
        qs = model['tests'][item['test']]['probability']
        for h, p in enumerate(qs):
            logs[h] += math.log(max(1e-300, p if item['positive'] else 1-p))
    top = max(logs)
    raw = [math.exp(x-top) for x in logs]
    z = sum(raw)
    return [x/z for x in raw]


def repair_risks(model: dict, belief: list[float]) -> list[float]:
    return [sum(w*loss for w, loss in zip(belief, row))
            for row in model['terminal_losses']]


def act(model: dict, history: list[dict], remaining_budget: float) -> dict:
    belief = posterior(model, history)
    risks = repair_risks(model, belief)
    chosen = min(range(len(risks)), key=risks.__getitem__)
    best_total = risks[chosen]
    best_test = None
    if len(history) >= model['max_queries']:
        return {'repair': model['actions'][chosen]}
    for j, test in enumerate(model['tests']):
        if test['cost'] > remaining_budget + 1e-9:
            continue
        py = sum(w*p for w, p in zip(belief, test['probability']))
        expected_risk = 0.0
        for positive, mass in ((True, py), (False, 1-py)):
            if mass < 1e-12:
                continue
            post = [w*(p if positive else 1-p)/mass
                    for w,p in zip(belief,test['probability'])]
            expected_risk += mass * min(repair_risks(model, post))
        total = test['cost'] + expected_risk
        if total < best_total - 1e-10:
            best_total, best_test = total, j
    if best_test is None:
        return {'repair': model['actions'][chosen]}
    return {'test': best_test}
