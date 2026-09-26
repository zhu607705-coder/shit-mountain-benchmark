#!/usr/bin/env python3
"""Quality-first, bounded efficiency deductions from independently verified measurements."""
import argparse
import hashlib
import json
import math
from pathlib import Path

DEFAULT_BUDGETS = {'total_ms': 60000, 'ttft_ms': 10000, 'output_tokens': 8192,
                   'reasoning_tokens': 4096, 'max_penalty': .30, 'time_weight': .60}
PROFILES = ('elapsed_only', 'time_only', 'time_tokens', 'reasoning_aware')


def number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(name + ' must be a finite nonnegative/positive number, not bool')
    return value


def bounded_efficiency(measured, budget):
    return 1.0 if measured <= budget else budget / measured


def score_efficiency(quality, valid, metrics, budgets=None, *, profile='elapsed_only', trusted=False):
    if profile not in PROFILES: raise ValueError('unknown efficiency profile')
    if type(trusted) is not bool: raise ValueError('trusted must be an explicit grader boolean')
    if type(valid) is not bool and valid is not None: raise ValueError('quality validity must be boolean or pending')
    budget = {**DEFAULT_BUDGETS, **(budgets or {})}
    if set(budget) != set(DEFAULT_BUDGETS): raise ValueError('unknown budget field')
    for key in ('total_ms', 'ttft_ms', 'output_tokens', 'reasoning_tokens'): number(budget[key], key, positive=True)
    for key in ('max_penalty', 'time_weight'):
        number(budget[key], key)
        if budget[key] > 1: raise ValueError(key + ' must be <=1')
    policy = {'version': '0.2.0', 'profile': profile, 'budgets': budget}
    policy_id = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    result = {'quality_score': quality, 'valid': valid, 'adjusted_quality': None, 'deduction': None,
              'policy': policy, 'score_profile_id': policy_id, 'trusted_measurements': trusted,
              'internal_thinking_time_used': False}
    if valid is False:
        result.update(adjusted_quality=0.0, deduction=None, status='invalid_submission_no_efficiency_rescue'); return result
    if quality is None or valid is None:
        result['status'] = 'quality_pending'; return result
    number(quality, 'quality_score')
    if not isinstance(metrics, dict): raise ValueError('metrics object required')
    if not trusted:
        result['status'] = 'host_or_provider_evidence_not_verified'; return result
    if metrics.get('simulated') is True:
        result['status'] = 'simulated_metrics_not_official'; return result
    elapsed = metrics.get('logical_total_ms', metrics.get('total_ms'))
    ttft = metrics.get('logical_ttft_ms', metrics.get('ttft_ms'))
    output = metrics.get('logical_output_tokens', metrics.get('output_tokens'))
    reasoning = metrics.get('logical_reasoning_tokens', metrics.get('reasoning_tokens'))
    for name, value in [('total_ms', elapsed), ('ttft_ms', ttft), ('output_tokens', output), ('reasoning_tokens', reasoning)]:
        if value is not None: number(value, name)
    if elapsed is not None and ttft is not None and ttft > elapsed:
        raise ValueError('first answer latency cannot exceed the complete elapsed time')
    if output is not None and reasoning is not None and reasoning > output:
        raise ValueError('reasoning tokens cannot exceed the reported generated total')
    if elapsed is None:
        result['status'] = 'elapsed_time_unavailable'; return result
    if profile != 'elapsed_only' and ttft is None:
        result['status'] = 'first_answer_latency_unavailable'; return result
    time_eff = bounded_efficiency(elapsed, budget['total_ms'])
    if profile != 'elapsed_only': time_eff = min(time_eff, bounded_efficiency(ttft, budget['ttft_ms']))
    token_eff = None
    if profile not in ('elapsed_only', 'time_only'):
        if output is None:
            result['status'] = 'output_usage_unavailable'; return result
        token_eff = bounded_efficiency(output, budget['output_tokens'])
        if profile == 'reasoning_aware':
            if reasoning is None:
                result['status'] = 'reasoning_usage_unavailable'; return result
            # A tighter reasoning budget may bind, but total and reasoning tokens are NEVER added.
            token_eff = min(token_eff, bounded_efficiency(reasoning, budget['reasoning_tokens']))
    combined = time_eff if token_eff is None else budget['time_weight'] * time_eff + (1 - budget['time_weight']) * token_eff
    multiplier = 1 - budget['max_penalty'] * (1 - combined)
    adjusted = quality * multiplier
    result.update(adjusted_quality=adjusted, deduction=quality - adjusted, multiplier=multiplier,
                  time_efficiency=time_eff, token_efficiency=token_eff, status='scored',
                  measurement_coverage={'elapsed': True, 'ttft': ttft is not None, 'output_tokens': output is not None, 'reasoning_tokens': reasoning is not None},
                  observed={'total_ms': elapsed, 'ttft_ms': ttft, 'output_tokens': output, 'reasoning_tokens': reasoning})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quality', required=True, type=Path, help='Trusted judge JSON with valid and raw_score')
    parser.add_argument('--telemetry', required=True, type=Path)
    parser.add_argument('--budgets', required=True, type=Path, help='Budget JSON frozen before experiments')
    parser.add_argument('--profile', choices=PROFILES, default='elapsed_only')
    parser.add_argument('--verified-host-evidence', action='store_true', help='Grader asserts independent host/provider evidence was checked; never trust an agent declaration alone')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    quality = json.loads(args.quality.read_text())
    result = score_efficiency(quality.get('raw_score'), quality.get('valid'), json.loads(args.telemetry.read_text()),
                              json.loads(args.budgets.read_text()), profile=args.profile, trusted=args.verified_host_evidence)
    result['quality_artifact_sha256'] = hashlib.sha256(args.quality.read_bytes()).hexdigest()
    result['telemetry_artifact_sha256'] = hashlib.sha256(args.telemetry.read_bytes()).hexdigest()
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(content, encoding='utf-8')
    print(content, end='')


if __name__ == '__main__': main()
