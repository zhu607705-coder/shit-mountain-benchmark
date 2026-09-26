#!/usr/bin/env python3
"""Normalize frozen, trusted judge records; never execute candidate submissions."""
import argparse
import json
import math
import sys
from pathlib import Path

TASKS = tuple(f"{track}{number}" for track in ("R", "C", "F") for number in range(1, 5))


def build(records):
    table = {}
    models = set()
    for record in records:
        task, model = record["task_id"], record["model"]
        if task not in TASKS or not isinstance(model, str) or not model.strip():
            raise ValueError("unknown task or invalid model")
        key = (model, task)
        if key in table:
            raise ValueError(f"duplicate official result: {key}")
        valid, raw = record.get("valid"), record.get("raw_score")
        if not isinstance(valid, bool) and valid is not None:
            raise ValueError("valid must be a boolean or null for pending judgment")
        if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0):
            raise ValueError("raw_score must be a finite nonnegative number or null")
        if valid is None and raw is not None:
            raise ValueError("pending qualification requires raw_score=null")
        if valid is False:
            raw = 0.0
        table[key] = {"valid": valid, "raw_score": raw}
        models.add(model)
    maxima = {}
    for task in TASKS:
        scores = [r["raw_score"] for (m, t), r in table.items() if t == task and r["valid"] is True and r["raw_score"] is not None]
        maxima[task] = max(scores, default=0)
    rows = []
    for model in sorted(models):
        scores, raw_scores = {}, {}
        for task in TASKS:
            record = table.get((model, task))
            if record is None:
                scores[task], raw_scores[task] = 0.0, None
            else:
                raw = record["raw_score"]
                raw_scores[task] = raw
                scores[task] = None if raw is None else (100 * (raw / maxima[task]) if maxima[task] > 0 else 0.0)
        tracks = {}
        for name, ids in (("reasoning", ("R1", "R2", "R3", "R4")), ("code", ("C1", "C2", "C3", "C4")), ("frontend", ("F1", "F2", "F3", "F4"))):
            values = [scores[x] for x in ids]
            tracks[name] = sum(values) / len(values) if all(v is not None for v in values) else None
        total = sum(scores.values()) / len(TASKS) if all(v is not None for v in scores.values()) else None
        rows.append({"model": model, "raw_scores": raw_scores, "relative_scores": scores, "tracks": tracks, "total": total,
                     "missing_tasks": [task for task in TASKS if (model, task) not in table],
                     "pending_tasks": [task for task in TASKS if (model, task) in table and table[(model, task)]["raw_score"] is None]})
    rows.sort(key=lambda row: (row["total"] is None, -(row["total"] or 0), row["model"]))
    return {"normalization": "100 * raw_score / best_valid_raw_score; no positive result => 0", "best_raw_scores": maxima,
            "note": "Missing submissions count as 0. Pending judgments remain null. A sole valid entrant receiving 100 does not prove absolute quality.", "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        records = json.loads(args.records.read_text(encoding="utf-8"))
        result = build(records)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"invalid results: {exc}", file=sys.stderr)
        return 2
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
