#!/usr/bin/env python3
"""Public local judge: deterministic semantics plus gated measured resource utility."""
import argparse
import copy
import datetime
import hashlib
import importlib.util
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

from cases import performance_case, public_cases, randomized
from oracle import solve as reference

CRITICAL_CASE_NAMES = ["ordinary_post", "tenant_namespace", "invalid_is_atomic"]


def load(path):
    sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location("submission_engine", path / "engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.solve


def digest_submission(path):
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*.py")):
        digest.update(str(file.relative_to(path)).encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def same(actual, expected):
    # JSON equality must distinguish 1, 1.0 and True for integer-money outputs.
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", default="baseline")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    path = Path(args.submission)
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    solve = load(path)
    reports = []
    for name, events in public_cases() + randomized():
        expected = reference(events)
        try:
            actual = solve(copy.deepcopy(events))
            passed = same(actual, expected)
            error = None if passed else "output_mismatch"
        except Exception as exc:
            passed, error = False, f"{type(exc).__name__}: {exc}"
        reports.append({"name": name, "passed": passed, **({"error": error} if error else {})})
    perf = performance_case()
    expected = reference(perf)
    samples, memory_peak, perf_passed = [], 0, True
    for _ in range(3):
        payload = copy.deepcopy(perf)
        start = time.perf_counter()
        try:
            output = solve(payload)
            elapsed = time.perf_counter() - start
            perf_passed &= same(output, expected)
        except Exception:
            elapsed = time.perf_counter() - start
            perf_passed = False
        samples.append(elapsed)
    tracemalloc.start()
    try:
        solve(perf)
        memory_peak = tracemalloc.get_traced_memory()[1]
    except Exception:
        perf_passed = False
    finally:
        tracemalloc.stop()
    reports.append({"name": "large_mixed_event_stream", "passed": bool(perf_passed)})
    passed_count = sum(report["passed"] for report in reports)
    rate = passed_count / len(reports)
    seconds = statistics.median(samples)
    all_passed = passed_count == len(reports)
    critical_passed = [report["name"] for report in reports
                       if report["name"] in CRITICAL_CASE_NAMES and report["passed"]]
    within_budget = seconds <= 2.0 and memory_peak <= 128 * 1024**2
    speed = .03 / (.03 + seconds)
    cost = 8 * 1024**2 / (8 * 1024**2 + memory_peak)
    raw_score = 80 * rate + (10 * speed + 10 * cost if all_passed and within_budget else 0)
    suite_digest = hashlib.sha256()
    for source in ["judge.py", "oracle.py", "cases.py", "fixtures/public.json"]:
        suite_digest.update(source.encode())
        suite_digest.update((root / source).read_bytes())
    result = {"benchmark": "C1", "version": "0.1.0", "seed": 2026092601,
              "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "suite_sha256": suite_digest.hexdigest(),
              "valid": len(critical_passed) == len(CRITICAL_CASE_NAMES) and within_budget,
              "critical_case_names": CRITICAL_CASE_NAMES, "critical_passed": critical_passed,
              "submission": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
              "submission_sha256": digest_submission(path),
              "raw_score": round(raw_score, 6), "correctness": {"passed": passed_count,
              "total": len(reports), "rate": rate},
              "performance": {"median_seconds": seconds, "samples_seconds": samples,
              "peak_traced_bytes": memory_peak, "speed_utility": speed, "memory_utility": cost,
              "within_budget": within_budget, "resource_bonus_eligible": all_passed and within_budget},
              "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "security": "same-process trusted local prototype; not a sandbox",
              "tests": reports}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        (root / args.output).write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
