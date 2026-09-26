#!/usr/bin/env python3
"""Re-run the v0.1 legacy reference suite. v0.2 uses scripts/extreme.py."""
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def invoke(args, cwd, timeout=120):
    result = subprocess.run([sys.executable, *args], cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args}: exit={result.returncode}\n{result.stderr}\n{result.stdout}")
    return result.stdout


def main():
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    records, detailed = [], {}
    started = time.perf_counter()
    for task in ("R1", "R2", "C1", "C2"):
        folder = ROOT / ("reasoning" if task.startswith("R") else "code") / task
        before = time.perf_counter()
        if task.startswith("R"):
            submission = results_dir / f"{task}_baseline_output.json"
            invoke(["baseline.py", "--input", "input.json", "--output", str(submission)], folder)
            output = invoke(["judge.py", "--input", "input.json", "--submission", str(submission)], folder)
            result = json.loads(output)
        else:
            core = json.loads(invoke(["judge.py", "--submission", "repository/baseline"], folder))
            environment = json.loads(invoke(["e2e_env_judge.py", "--submission", "repository/baseline"], folder))
            environment_score = environment["environment_score"]
            selftest_score = environment.get("selftest_score")
            if not 0 <= environment_score <= 70 or (selftest_score is not None and not 0 <= selftest_score <= 10):
                raise ValueError(f"{task}: invalid repository score components")
            regression_score = 20 * core["correctness"]["rate"]
            subtotal = environment_score + regression_score
            result = {"task_id": task, "level": "repository", "valid": bool(core["valid"] and environment["valid"]),
                      "raw_score": None if selftest_score is None else round(subtotal + selftest_score, 6),
                      "environment_score": environment_score, "regression_score": regression_score,
                      "selftest_score": selftest_score, "verified_machine_subtotal": round(subtotal, 6),
                      "core_result": core, "environment_result": environment,
                      "note": "Repository-level task. Core microbenchmark raw score is diagnostic and is not the official task quality."}
            for suffix, item in (("core", core), ("environment", environment)):
                (results_dir / f"{task}_{suffix}_verified.json").write_text(json.dumps(item, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        raw = result["raw_score"]
        valid = result["valid"]
        detailed[task] = {"judge_result": result, "wall_seconds_for_baseline_and_judge": round(time.perf_counter() - before, 6)}
        records.append({"model": "author-baseline-v0.1", "task_id": task, "raw_score": raw, "valid": valid})
        (results_dir / f"{task}_verified.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(f"{task}: valid={valid}, raw_score={raw}")
    for task in ("R3", "R4", "C3", "C4"):
        folder = ROOT / ("reasoning" if task.startswith("R") else "code") / task
        before = time.perf_counter()
        result = json.loads(invoke(["judge.py", "--submission", "baseline.py"], folder))
        (results_dir / f"{task}_verified.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        detailed[task] = {"judge_result": result, "wall_seconds_for_baseline_and_judge": round(time.perf_counter() - before, 6)}
        records.append({"model": "author-baseline-v0.1", "task_id": task, "raw_score": result["raw_score"], "valid": result["valid"]})
        print(f"{task}: valid={result['valid']}, raw_score={result['raw_score']}")
    for task in ("F1", "F2", "F3", "F4"):
        records.append({"model": "author-baseline-v0.1", "task_id": task, "raw_score": None, "valid": None,
                        "note": "Pending full functional adjudication and independent blind visual review; see frontend browser verification report."})
    evidence = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
                "platform": platform.platform(), "official_model_comparison": False,
                "total_wall_seconds": round(time.perf_counter() - started, 6), "tasks": detailed}
    (results_dir / "programmatic_verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (results_dir / "baseline_records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Unadjudicated quality components and frontend blind review remain pending. No twelve-task overall score is claimed.")


if __name__ == "__main__":
    main()
