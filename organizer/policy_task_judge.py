"""Common local adapter for policy and specialist-system tasks. Trusted code only."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


def load(name, path):
    path = Path(path)
    if path.is_dir():
        path = path / "__init__.py"
    parent = str(path.resolve().parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("submission must be a Python module or package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def evaluate(task_id, task_dir, submission):
    task_dir, submission = Path(task_dir), Path(submission)
    if not submission.is_absolute():
        submission = task_dir / submission
    module = load("submission_" + task_id.lower(), submission)
    evaluator = load("evaluator_" + task_id.lower(), task_dir / "evaluator.py")
    details = evaluator.evaluate(module)
    if task_id.startswith("R"):
        valid = details.get("valid", details["valid_episodes"] == details["episodes"])
        loss = details["objective_loss"]
        if isinstance(loss, bool) or not isinstance(loss, (int, float)) or not math.isfinite(loss) or loss < 0:
            raise ValueError("invalid objective loss from trusted evaluator")
        raw = 100 / (1 + loss / 10)
        note = "Fixed quality mapping: 100/(1+objective_loss/10). Public replay, not a sealed hidden set."
    else:
        valid = details["checks_passed"] == details["checks_total"]
        raw = None
        note = "Behavior checks verified. Formal performance workload and quality weights are not calibrated; full raw quality remains pending."
    return {"task_id": task_id, "valid": bool(valid), "raw_score": raw, "details": details, "note": note,
            "execution": "same-process trusted local evaluator; not an untrusted-code sandbox"}


def main(task_id, task_dir):
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", default="baseline.py")
    args = parser.parse_args()
    result = evaluate(task_id, task_dir, args.submission)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
