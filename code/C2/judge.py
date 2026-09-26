#!/usr/bin/env python3
"""Trusted local reference runner. Not a security boundary or hidden judge."""
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
from oracle import Engine as Reference

CRITICAL_CASE_NAMES = ["ordinary_build", "failure_repair", "result_mutation_ownership"]


def load(path):
    sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location("submission_engine", path / "engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Engine


def run(engine_class, case):
    engine = engine_class(copy.deepcopy(case["nodes"]), copy.deepcopy(case["aliases"]))
    outputs, last = [], None
    for command in case["commands"]:
        if command["op"] == "tamper_last":
            if last is not None and isinstance(last.get("value"), list):
                last["value"][:] = [command["value"]]
            continue
        result = engine.step(copy.deepcopy(command))
        outputs.append(copy.deepcopy(result))
        if "value" in result:
            last = result
    return outputs


def same(actual, expected):
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True)


def measured(engine_class, case, expected):
    """Time constructor + step only; compare each result outside timed regions."""
    nodes, aliases = copy.deepcopy(case["nodes"]), copy.deepcopy(case["aliases"])
    start = time.perf_counter()
    engine = engine_class(nodes, aliases)
    seconds = time.perf_counter() - start
    passed, answer_index, last = True, 0, None
    for command in case["commands"]:
        if command["op"] == "tamper_last":
            if last is not None and isinstance(last.get("value"), list):
                last["value"][:] = [command["value"]]
            continue
        payload = copy.deepcopy(command)
        start = time.perf_counter()
        try:
            result = engine.step(payload)
            seconds += time.perf_counter() - start
            passed &= answer_index < len(expected) and same(result, expected[answer_index])
            if "value" in result:
                last = result
        except Exception:
            seconds += time.perf_counter() - start
            passed = False
        answer_index += 1
    return seconds, passed and answer_index == len(expected)


def digest_submission(path):
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*.py")):
        digest.update(str(file.relative_to(path)).encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", default="baseline")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    path = Path(args.submission)
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    engine_class = load(path)
    reports = []
    for case in public_cases() + randomized():
        expected = run(Reference, case)
        try:
            actual = run(engine_class, case)
            passed = same(actual, expected)
            error = None if passed else "output_mismatch"
        except Exception as exc:
            passed, error = False, f"{type(exc).__name__}: {exc}"
        reports.append({"name": case["name"], "passed": passed, **({"error": error} if error else {})})
    case = performance_case()
    expected = run(Reference, case)
    samples, memory_peak, perf_passed = [], 0, True
    for _ in range(3):
        try:
            elapsed, correct = measured(engine_class, case, expected)
            perf_passed &= correct
        except Exception:
            elapsed = 1_000_000_000.0
            perf_passed = False
        samples.append(elapsed)
    tracemalloc.start()
    try:
        measured(engine_class, case, expected)
        memory_peak = tracemalloc.get_traced_memory()[1]
    except Exception:
        perf_passed = False
    finally:
        tracemalloc.stop()
    reports.append({"name": "incremental_branch_updates", "passed": bool(perf_passed)})
    passed_count = sum(report["passed"] for report in reports)
    rate = passed_count / len(reports)
    seconds = statistics.median(samples)
    all_passed = passed_count == len(reports)
    critical_passed = [report["name"] for report in reports
                       if report["name"] in CRITICAL_CASE_NAMES and report["passed"]]
    within_budget = seconds <= 4.0 and memory_peak <= 128 * 1024**2
    speed = .02 / (.02 + seconds)
    cost = 16 * 1024**2 / (16 * 1024**2 + memory_peak)
    suite_digest = hashlib.sha256()
    for source in ["judge.py", "oracle.py", "cases.py", "fixtures/public.json"]:
        suite_digest.update(source.encode())
        suite_digest.update((root / source).read_bytes())
    result = {"benchmark": "C2", "version": "0.1.0", "seed": 2026092602,
              "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "suite_sha256": suite_digest.hexdigest(),
              "valid": len(critical_passed) == len(CRITICAL_CASE_NAMES) and within_budget,
              "critical_case_names": CRITICAL_CASE_NAMES, "critical_passed": critical_passed,
              "submission": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
              "submission_sha256": digest_submission(path),
              "raw_score": round(80 * rate + (10 * speed + 10 * cost if all_passed and within_budget else 0), 6),
              "correctness": {"passed": passed_count, "total": len(reports), "rate": rate},
              "performance": {"median_seconds": seconds, "samples_seconds": samples,
              "peak_traced_bytes": memory_peak, "speed_utility": speed, "memory_utility": cost,
              "within_budget": within_budget, "resource_bonus_eligible": all_passed and within_budget},
              "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "security": "same-process trusted local prototype; not a sandbox", "tests": reports}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        (root / args.output).write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
