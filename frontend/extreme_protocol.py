"""Public protocol primitives and deterministic synthetic input. No answer oracle."""
from __future__ import annotations
import hashlib
import json

PROTOCOL = "smb.frontend.extreme/2"

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def fingerprint(rows):
    """Protocol export commitment; callers independently verify the actual rows."""
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: item["id"]):
        digest.update(canonical(row).encode("utf-8") + b"\n")
    return digest.hexdigest()

def stream_row(index, seed):
    return {"id": f"E{index:07d}", "generation": 0, "rev": 1,
            "title": f"incident {index} seed {seed}", "service": f"svc-{index % 37}",
            "severity": index % 4, "status": "open"}

def task_row(index, seed):
    start = (index // 12) * 20
    return {"id": f"T{index:05d}", "generation": 0, "title": f"task {index} seed {seed}",
            "resource": index % 12, "start": start, "end": start + 10,
            "deps": [f"T{index - 12:05d}"] if index >= 12 else [], "notes": ""}

def event(actor, counter, item, fields=None, context=None, kind="patch", generation=0, **extra):
    value = {"id": f"{actor}:{counter}", "actor": actor, "counter": counter,
             "context": context or {}, "item": item, "generation": generation, "kind": kind}
    if fields is not None:
        value["fields"] = fields
    value.update(extra)
    return value
