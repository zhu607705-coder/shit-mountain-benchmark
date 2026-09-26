"""Small dependency-free utilities for the extreme reasoning suite.

The subprocess protocol separates Python objects, not operating-system privileges.
Run untrusted policies in an external sandbox, with private judges on another host.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time


class InvalidAction(ValueError):
    pass


def exact(obj, fields):
    if type(obj) is not dict or set(obj) != set(fields):
        raise InvalidAction('expected exactly fields: ' + ', '.join(fields))


def integer(x, lo, hi, name='integer'):
    if type(x) is not int or not lo <= x <= hi:
        raise InvalidAction(f'{name} must be an integer in [{lo},{hi}]')
    return x


def distinct(items, name):
    if len(items) != len(set(items)):
        raise InvalidAction('duplicate ' + name)


def keyed(seed, *parts):
    digest = hashlib.sha256((':'.join(map(str, (seed,) + parts))).encode()).digest()
    return int.from_bytes(digest[:8], 'big') / 2 ** 64


def clone(x):
    return copy.deepcopy(x)


def strict_loads(raw):
    def pairs(xs):
        d = {}
        for k, v in xs:
            if k in d:
                raise InvalidAction('duplicate JSON key')
            d[k] = v
        return d
    def bad(x):
        raise InvalidAction('nonfinite JSON number: ' + x)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def tail(values, mass=.1):
    need = len(values) * mass
    rem = need
    total = 0.
    for x in sorted(values, reverse=True):
        take = min(1., rem)
        total += take * x
        rem -= take
        if rem < 1e-12:
            break
    return total / need


def scored(rows, *, loss_scale=50):
    losses = [r['loss'] for r in rows]
    mean = sum(losses) / len(losses)
    worst = tail(losses)
    objective = .7 * mean + .3 * worst
    valid = all(r['valid'] for r in rows)
    return {'valid': valid, 'episodes': len(rows),
            'valid_episodes': sum(r['valid'] for r in rows),
            'mean_loss': mean, 'worst_decile_loss': worst,
            'objective_loss': objective,
            'raw_score': 100 / (1 + objective / loss_scale) if valid else 0,
            'loss_scale': loss_scale, 'episodes_detail': rows}


class Policy:
    """Persistent line protocol; each episode receives reset=true at turn zero."""
    def __init__(self, baseline, submission=None, budget_seconds=120, action_timeout=2):
        self.baseline = baseline
        self.path = Path(submission).resolve() if submission else None
        self.budget = budget_seconds
        self.timeout = action_timeout
        self.elapsed = 0.
        self.calls = 0
        self.process = None
        self.selector = None
        self.buffer = b''
        self.constant = None
        if self.path:
            if self.path.suffix == '.json':
                obj = strict_loads(self.path.read_text())
                exact(obj, ['action'])
                self.constant = obj['action']
            elif self.path.suffix == '.py':
                self.process = subprocess.Popen([sys.executable, '-u', str(self.path)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    cwd=str(self.path.parent), start_new_session=True)
                self.selector = selectors.DefaultSelector()
                self.selector.register(self.process.stdout, selectors.EVENT_READ)
            else:
                raise ValueError('submission must be a .py NDJSON process or .json constant action')

    def __call__(self, obs):
        if self.elapsed >= self.budget:
            raise InvalidAction('candidate total decision-time budget exceeded')
        start = time.perf_counter()
        try:
            if not self.path:
                result = self.baseline(clone(obs))
            elif not self.process:
                result = clone(self.constant)
            else:
                payload = (json.dumps(obs, separators=(',', ':'), allow_nan=False) + '\n').encode()
                # Bounded writes are also needed: a policy may stop reading stdin.
                os.set_blocking(self.process.stdin.fileno(), False)
                deadline = time.perf_counter() + min(self.timeout, self.budget - self.elapsed)
                cursor = 0
                while cursor < len(payload):
                    try:
                        cursor += os.write(self.process.stdin.fileno(), payload[cursor:])
                    except BlockingIOError:
                        if time.perf_counter() >= deadline:
                            raise InvalidAction('policy input timeout')
                        time.sleep(.001)
                while b'\n' not in self.buffer:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0 or not self.selector.select(remaining):
                        raise InvalidAction('policy action timeout')
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        raise InvalidAction('policy exited without an action')
                    self.buffer += chunk
                    if len(self.buffer) > 2_000_000:
                        raise InvalidAction('policy response exceeds 2 MB')
                line, self.buffer = self.buffer.split(b'\n', 1)
                result = strict_loads(line)
            return result
        except InvalidAction:
            raise
        except Exception as exc:
            raise InvalidAction(type(exc).__name__ + ': ' + str(exc)[:160]) from exc
        finally:
            self.elapsed += time.perf_counter() - start
            self.calls += 1

    def close(self):
        if self.process:
            import signal
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.selector.close()


def dimension(legacy, actual, full):
    return {'legacy': legacy, 'actual': actual, 'full': full,
            'actual_ratio': actual / legacy, 'full_ratio': full / legacy}
