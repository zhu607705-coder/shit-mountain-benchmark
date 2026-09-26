#!/usr/bin/env python3
"""Evaluate an explicitly selected, trusted local submission and emit a leaderboard record."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def judge(folder, script, args):
    proc = subprocess.run([sys.executable, script, *args], cwd=folder, capture_output=True, text=True, timeout=180, check=True)
    return json.loads(proc.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=tuple(f"{t}{n}" for t in "RCF" for n in range(1, 5)))
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = args.submission.resolve(strict=True)
    task = args.task
    result = {"task_id": task, "model": args.model, "submission": str(path)}
    if task in ("R1", "R2"):
        details = judge(ROOT / "reasoning" / task, "judge.py", ["--input", "input.json", "--submission", str(path)])
        result.update(valid=details["valid"], raw_score=details["raw_score"], details=details)
    elif task in ("C1", "C2"):
        folder = ROOT / "code" / task
        core = judge(folder, "judge.py", ["--submission", str(path)])
        env = judge(folder, "e2e_env_judge.py", ["--submission", str(path)])
        regression = 20 * core["correctness"]["rate"]
        subtotal = env["environment_score"] + regression
        tests = env.get("selftest_score")
        result.update(valid=bool(core["valid"] and env["valid"]), raw_score=None if tests is None else round(subtotal + tests, 6),
                      environment_score=env["environment_score"], regression_score=regression, selftest_score=tests,
                      verified_machine_subtotal=round(subtotal, 6), core_result=core, environment_result=env)
    elif task in ("R3", "R4", "C3", "C4"):
        folder = ROOT / ("reasoning" if task.startswith("R") else "code") / task
        details = judge(folder, "judge.py", ["--submission", str(path)])
        result.update(valid=details["valid"], raw_score=details["raw_score"], details=details)
    else:
        result.update(valid=None, raw_score=None, human_visual_score=None,
                      next_step=f"Open the submitted page and replay frontend/{task}/rubric.md. File presence is not a functional test.")
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
