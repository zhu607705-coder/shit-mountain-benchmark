#!/usr/bin/env python3
"""One command, real baseline and repository regression checks, no model API cost."""
import ast
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label, args, cwd=ROOT, timeout=180):
    print(f"[RUN] {label}", flush=True)
    started = time.perf_counter()
    proc = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    print(proc.stdout, end="", flush=True)
    if proc.returncode:
        raise RuntimeError(f"{label} failed, exit={proc.returncode}")
    return {"name": label, "passed": True, "seconds": round(time.perf_counter() - started, 4)}


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Python >= 3.10 required")
    if shutil.which("node") is None:
        raise SystemExit("Node.js is required for frontend syntax/logic checks; install Node 22+ and retry.")
    checks = []
    for p in ROOT.rglob("*.py"):
        if not {".git", "__pycache__", "submissions", "workspaces", "reports", ".venv"}.intersection(p.parts):
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    checks.append({"name": "python-syntax", "passed": True})
    commands = [
        ("score-normalization", [sys.executable, "-m", "unittest", "discover", "-s", "organizer", "-p", "test_*.py"]),
        ("R1-judge", [sys.executable, "reasoning/R1/selftest.py"]),
        ("R2-judge", [sys.executable, "reasoning/R2/selftest.py"]),
        ("policy-boundaries", [sys.executable, "reasoning/R3/review_selftest.py"]),
        ("C1-oracle", [sys.executable, "-m", "unittest", "discover", "-s", "code/C1", "-p", "test_harness.py"]),
        ("C2-oracle", [sys.executable, "-m", "unittest", "discover", "-s", "code/C2", "-p", "test_harness.py"]),
        ("C2-local-service-portability", [sys.executable, "code/C2/test_environment_harness.py"]),
        ("C3-recovery-regressions", [sys.executable, "-m", "unittest", "discover", "-s", "code/C3", "-p", "test_review.py"]),
        ("C4-cache-regressions", [sys.executable, "-m", "unittest", "discover", "-s", "code/C4", "-p", "test_review.py"]),
        ("frontend-syntax-and-logic", [sys.executable, "frontend/verify_frontend.py"]),
        ("F3-stream-state", ["node", "frontend/F3/selftest.cjs"]),
        ("F4-multiwindow-state", ["node", "frontend/F4/selftest.cjs"]),
        ("API-and-import-adapters", [sys.executable, "-m", "unittest", "discover", "-s", "integrations", "-p", "test_*.py"]),
        ("README-experiment-sealing-and-grading", [sys.executable, "-m", "unittest", "discover", "-s", "experiments", "-p", "test_*.py"]),
        ("arena-draw-scope-sealing-and-grading", [sys.executable, "-m", "unittest", "discover", "-s", "arena", "-p", "test_*.py"]),
        ("arena-browser-script-syntax", ["node", "--check", "arena/web/app.js"]),
        ("arena-motion-script-syntax", ["node", "--check", "arena/web/motion.js"]),
        ("legacy-v01-baselines-and-real-services", [sys.executable, "run_baselines.py"]),
        ("extreme-reasoning-witnesses", [sys.executable, "reasoning/extreme_selftest.py"]),
        ("extreme-code-fault-interactions", [sys.executable, "code/extreme_selftest.py"]),
        ("extreme-frontend-causal-witnesses", [sys.executable, "frontend/extreme_selftest.py"]),
        ("extreme-twelve-task-smoke", [sys.executable, "scripts/extreme.py", "--task", "all", "--scale", "smoke", "--output", "reports/extreme-ci"]),
    ]
    for label, args in commands:
        checks.append(run(label, args))
    for task in ("R1", "R2", "R3", "R4", "C1", "C2", "C3", "C4"):
        result = json.loads((ROOT / "results" / f"{task}_verified.json").read_text())
        if result.get("valid") is not True:
            raise RuntimeError(f"{task}: baseline failed qualification")
        if task in ("C1", "C2"):
            if result["core_result"]["correctness"]["rate"] != 1:
                raise RuntimeError(f"{task}: baseline core regression not complete")
            env = result["environment_result"]
            if env["environment_passed"] != env["environment_total"]:
                raise RuntimeError(f"{task}: baseline environment coverage not complete")
    # The deliberately broken implementations are part of the challenge. CI must detect them.
    for task in ("C1", "C2"):
        proc = subprocess.run([sys.executable, "e2e_env_judge.py", "--submission", "repository/buggy"],
                              cwd=ROOT / "code" / task, capture_output=True, text=True, timeout=180, check=True)
        result = json.loads(proc.stdout)
        (ROOT / "results" / f"{task}_repository_buggy_verified.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if result["valid"] or result["environment_passed"] >= result["environment_total"]:
            raise RuntimeError(f"{task}: buggy control did not exhibit the expected defects")
        checks.append({"name": task + "-broken-control-rejected", "passed": True})
        print(f"[OK] {task} buggy control: {result['environment_passed']}/{result['environment_total']} environments", flush=True)
    for task in ("C3", "C4"):
        proc = subprocess.run([sys.executable, "judge.py", "--submission", "starter"], cwd=ROOT / "code" / task,
                              capture_output=True, text=True, timeout=180, check=True)
        result = json.loads(proc.stdout)
        if result["valid"]:
            raise RuntimeError(f"{task}: broken control unexpectedly qualified")
        (ROOT / "results" / f"{task}_starter_verified.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        checks.append({"name": task + "-broken-control-rejected", "passed": True})
    summary = {"status": "passed", "python": platform.python_version(), "platform": platform.platform(),
               "ci": os.getenv("CI", "false"), "checks": checks,
               "limits": "No live model API call, no browser UI automation in this command, no independent visual judging."}
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "one-click-test.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: legacy compatibility, extreme judges and experiment workflow verified. Weak candidate failures remain failures; human/frontend full scores stay separate.")


if __name__ == "__main__":
    main()
