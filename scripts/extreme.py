#!/usr/bin/env python3
"""Unified v0.2 generator and trusted-submission runner for twelve extreme tasks."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "organizer"))
from extreme_contract import TASKS, validate_report


def execute(command, timeout):
    process = subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        raise RuntimeError(f"runner exceeded {timeout}s; process group stopped; stderr={stderr[-1800:]}")
    if process.returncode:
        raise RuntimeError(f"runner exit {process.returncode}: {stderr[-2500:]}\n{stdout[-1000:]}")
    return stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("all", *TASKS), default="all")
    parser.add_argument("--scale", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--seed", default="260926", help="Integer for public replay, or random for a fresh organizer instance")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/extreme")
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--timeout", type=float, help="Whole runner budget; defaults to 180s smoke / 900s full, minimum 5s for cleanup")
    args = parser.parse_args()
    if args.submission and args.task == "all":
        parser.error("a submission is evaluated against exactly one task")
    if args.timeout is None: args.timeout = 900 if args.scale == 'full' else 180
    if not math.isfinite(args.timeout) or args.timeout < 5:
        parser.error("finite runner timeout >=5 seconds required")
    seed = secrets.randbits(63) if args.seed == "random" else int(args.seed)
    tasks = TASKS if args.task == "all" else (args.task,)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.export:
        export = args.export.resolve()
        if export.exists():
            parser.error("export directory already exists; use a fresh path")
    results = []
    started = time.perf_counter()
    for task in tasks:
        track = {"R": "reasoning", "C": "code", "F": "frontend"}[task[0]]
        runner = ROOT / track / "extreme.py"
        target = output / f"{task}.json"
        command = [sys.executable, str(runner), "--task", task, "--scale", args.scale, "--seed", str(seed), "--output", str(target)]
        if track in ('reasoning', 'code'):
            normal = 120 if track == 'reasoning' else (600 if args.scale == 'full' else 28)
            command.extend(['--budget-seconds',str(min(normal,args.timeout-3))])
        else:
            command.extend(['--timeout',str(min(90,args.timeout-3))])
        if args.submission:
            command.extend(["--submission", str(args.submission.resolve(strict=True))])
        if args.export:
            command.extend(["--export", str(export / task)])
        execute(command, args.timeout)
        if args.export:
            bundle = export / task
            if not bundle.is_dir() or not (bundle / "PROMPT.md").is_file():
                raise RuntimeError(f"{task}: export did not create its public task contract")
            public_files = [p for p in bundle.rglob('*') if p.is_file()]
            results.append({'task_id': task, 'artifact_type': 'public-task-export', 'files': len(public_files),
                            'bytes': sum(p.stat().st_size for p in public_files),
                            'sha256': {str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest() for p in public_files}})
            print(f"{task}: public workspace exported ({len(public_files)} files)", flush=True)
            continue
        report = validate_report(json.loads(target.read_text(encoding="utf-8")))
        if report["task_id"] != task or report["scale"] != args.scale or report["seed"] != seed:
            raise ValueError("runner returned an unrelated task instance")
        if not report["audit_passed"]:
            raise RuntimeError(f"{task}: evaluator/witness audit failed; see {target}")
        results.append({"task_id": task, "report": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        "audit_passed": True, "dimensions": report["dimensions"], "candidate": report.get("candidate_result", report.get("baseline_result"))})
        candidate = results[-1]["candidate"]
        print(f"{task}: judge audit passed; candidate valid={candidate.get('valid')}; raw_score={candidate.get('raw_score')}", flush=True)
    manifest = {"suite_version": "0.2.0", "profile": "extreme", "scale": args.scale, "seed": seed,
                "seed_scope": "organizer report; do not distribute as a hidden evaluation secret", "python": platform.python_version(),
                "platform": platform.platform(), "wall_seconds": round(time.perf_counter() - started, 4), "tasks": results,
                "interpretation": "Workload ratios are measured proxies; they do not establish a 10x increase in cognitive difficulty or any model's inability to solve the tasks."}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.export:
        print(f"Exported {len(tasks)} public task bundles. Export alone is not an evaluator or candidate pass.")
    else:
        print(f"Verified {len(tasks)} task audits. Candidate failures are retained as evidence, not converted to artificial passes.")


if __name__ == "__main__":
    main()
