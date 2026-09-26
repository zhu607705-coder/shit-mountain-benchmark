#!/usr/bin/env python3
"""Deterministic frontend stress traces and semantic-adapter judge.

This runner does not certify a browser UI. DOM, native persistence, download,
accessibility, sustained browser performance and visual quality remain pending.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
from extreme_protocol import PROTOCOL, canonical, fingerprint, stream_row, task_row, event

ROOT = Path(__file__).resolve().parent
MECHANISMS = {
    "F1": ["observed-remove acknowledgement under concurrent actors", "identity alias chains coupled to selection, focus and URL history", "per-record revisions under reordered partial streams", "whole-result export integrity"],
    "F2": ["causal field merge creates new global resource/dependency conflicts", "conditional undo after causally newer remote edits", "reverse causal replay and multi-actor convergence", "offline write failure, refresh and schema migration"],
    "F3": ["per-view frozen snapshot coupled to full export", "tombstone retention under lagging actor and delayed replay", "post-compaction epoch floor forbids resurrection", "500k-row complete export plus shuffled update history"],
    "F4": ["causal versus concurrent field conflicts", "generation-scoped deletion and explicit restoration", "conditional undo coupled to remote causal context", "atomic import and multi-actor reverse causal replay"],
}


def ordered_fingerprint(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update(canonical(row).encode("utf-8") + b"\n")
    return digest.hexdigest()


class Trace:
    def __init__(self, handle):
        self.handle = handle
        self.lines = 0
        self.checks = []
        self.commands = {}
        self.records_loaded = 0
        self.events_delivered = 0
        self.command_meta = {}

    def emit(self, command, label=None, expected=None, export=None):
        self.handle.write(canonical(command) + "\n")
        self.lines += 1
        self.command_meta[self.lines] = {"op": command["op"], "count": len(command.get("rows", command.get("events", [])))}
        self.commands[command["op"]] = self.commands.get(command["op"], 0) + 1
        if command["op"] == "load":
            self.records_loaded += len(command["rows"])
        if command["op"] in ("ingest", "deliver"):
            self.events_delivered += len(command.get("rows", command.get("events", [])))
        if label:
            self.checks.append({"line": self.lines, "name": label, "expected": expected, "export": export})

    def observe(self, label, ids=(), actor="A", **expected):
        self.emit({"op": "observe", "actor": actor, "ids": list(ids)}, label,
                  {"ok": True, **expected})


def load_rows(trace, count, factory, seed):
    for start in range(0, count, 2000):
        trace.emit({"op": "load", "rows": [factory(index, seed) for index in range(start, min(count, start + 2000))]})


def build_stream(task, scale, seed, trace):
    count = (100000 if task == "F1" else 500000) if scale == "full" else (1000 if task == "F1" else 5000)
    trace.emit({"op": "config", "protocol": PROTOCOL, "task": task, "actors": ["A", "B", "C"], "schema": 2})
    load_rows(trace, count, stream_row, seed)
    e = lambda index: f"E{index:07d}"
    trace.observe("full initial population is available", [e(0), e(count - 1)], count=count,
                  records={e(0): stream_row(0, seed), e(count - 1): stream_row(count - 1, seed)})
    if task == "F1":
        trace.emit({"op": "view", "actor": "A", "selection": e(0), "focus": e(0), "filter": {}, "push": True})
        trace.emit({"op": "ack", "actor": "A", "id": e(0), "value": True, "dot": "A:1", "observed": []})
        trace.emit({"op": "ack", "actor": "B", "id": e(0), "value": True, "dot": "B:1", "observed": []})
        trace.emit({"op": "ack", "actor": "A", "id": e(0), "value": False, "dot": "A:2", "observed": ["A:1"]})
        trace.observe("undoing one acknowledgement preserves an unseen concurrent acknowledgement", acked=[e(0)])
        trace.emit({"op": "alias", "old": e(0), "canonical": "Z-incident", "proof": "authoritative mapping", "seq": 2})
        trace.emit({"op": "alias", "old": "Z-incident", "canonical": "Z-canonical", "proof": "authoritative mapping", "seq": 3})
        trace.observe("alias chain rewrites selection focus and acknowledgement identity", selection="Z-canonical", focus="Z-canonical", acked=["Z-canonical"])
        trace.emit({"op": "stream", "stream": "east", "connected": False, "last_seq": 8})
        latest = {**stream_row(0, seed), "id": "Z-canonical", "rev": 9, "title": "latest canonical incident"}
        trace.emit({"op": "ingest", "stream": "west", "seq": 11, "rows": [latest]})
        trace.emit({"op": "ingest", "stream": "east", "seq": 9, "rows": [{**stream_row(0, seed), "rev": 3, "title": "late alias incident"}]})
        trace.observe("late source alias cannot split identity or replace a newer canonical version", [e(0), "Z-canonical"], count=count,
                      records={e(0): None, "Z-canonical": latest}, stale_streams=["east"])
        trace.emit({"op": "view", "actor": "A", "selection": e(1), "focus": e(1), "filter": {"severity": 1}, "push": True})
        trace.emit({"op": "history", "actor": "A", "delta": -1})
        trace.observe("back navigation re-resolves old URL identity against the alias chain", selection="Z-canonical", filter={})
        trace.emit({"op": "history", "actor": "A", "delta": 1})
        trace.observe("forward navigation preserves the complete filter and target", selection=e(1), filter={"severity": 1})
        trace.emit({"op": "ingest", "stream": "west", "seq": 12, "rows": [{"id": e(7), "generation": 0, "rev": 10, "deleted": True}]})
        trace.emit({"op": "ingest", "stream": "west", "seq": 13, "rows": [{**stream_row(7, seed), "rev": 2}]})
        trace.observe("stale retry cannot revive a deleted incident", [e(7)], records={e(7): None})
        expected_rows = (stream_row(index, seed) for index in range(1, count) if index != 7)
        expected_digest = ordered_fingerprint(_chain(expected_rows, [latest]))
        trace.emit({"op": "export", "actor": "A"}, "complete export retains every unaffected incident", export={"count": count - 1, "sha256": expected_digest})
    else:
        trace.emit({"op": "pause", "actor": "A", "value": True, "snapshot": "cut-1"})
        mutations = max(100, count // 10)
        # Every row receives a newer event followed by its stale predecessor.
        for start in range(0, mutations, 1000):
            rows = []
            for index in range(start, min(mutations, start + 1000)):
                rows.extend([{**stream_row(index, seed), "rev": 3, "title": f"current {index}"},
                             {**stream_row(index, seed), "rev": 2, "title": f"stale {index}"}])
            random.Random(seed + start).shuffle(rows)
            trace.emit({"op": "ingest", "stream": "east", "seq": start + 1, "rows": rows})
        trace.observe("a paused view stays on one coherent historical snapshot", [e(0), e(mutations - 1)], actor="A", count=count,
                      records={e(0): stream_row(0, seed), e(mutations - 1): stream_row(mutations - 1, seed)})
        trace.observe("an unpaused second view observes newest versions", [e(0)], actor="B",
                      records={e(0): {**stream_row(0, seed), "rev": 3, "title": "current 0"}})
        original_digest = ordered_fingerprint(stream_row(index, seed) for index in range(count))
        trace.emit({"op": "export", "actor": "A", "snapshot": "cut-1"}, "paused full export uses its frozen cut, not live rows", export={"count": count, "sha256": original_digest})
        trace.emit({"op": "pause", "actor": "A", "value": False})
        trace.observe("resume preserves the maximum revision across shuffled batches", [e(0)],
                      records={e(0): {**stream_row(0, seed), "rev": 3, "title": "current 0"}})
        deleted = {0, mutations - 1}
        trace.emit({"op": "ingest", "stream": "east", "seq": 200001, "rows": [{"id": e(index), "generation": 0, "rev": 10, "deleted": True} for index in sorted(deleted)]})
        trace.emit({"op": "compact", "epoch": 0, "watermarks": {"east": 10, "west": 0}, "floor": 0})
        trace.emit({"op": "ingest", "stream": "west", "seq": 3, "epoch": 0, "rows": [{**stream_row(0, seed), "rev": 4}]})
        trace.observe("lagging actor prevents premature resurrection after compaction", [e(0)], records={e(0): None})
        trace.emit({"op": "compact", "epoch": 1, "watermarks": {"east": 10, "west": 10}, "floor": 10})
        trace.emit({"op": "ingest", "stream": "west", "seq": 4, "epoch": 0, "rows": [{**stream_row(mutations - 1, seed), "rev": 9}]})
        trace.observe("committed epoch floor rejects old-session replay even after safe GC", [e(mutations - 1)], records={e(mutations - 1): None})
        def final_rows():
            for index in range(count):
                if index in deleted:
                    continue
                row = stream_row(index, seed)
                if index < mutations:
                    row.update(rev=3, title=f"current {index}")
                yield row
        trace.emit({"op": "export", "actor": "A"}, "all-record export matches resumed cut after deletion and GC", export={"count": count - len(deleted), "sha256": ordered_fingerprint(final_rows())})
    return count


def _chain(first, second):
    yield from first
    yield from second


def build_tasks(task, scale, seed, trace):
    count = 1200 if scale == "full" else 36
    replicas = [f"R{index:02d}" for index in range(20 if scale == "full" else 3)]
    trace.emit({"op": "config", "protocol": PROTOCOL, "task": task, "actors": ["A", "B", "C", *replicas], "schema": 2})
    load_rows(trace, count, task_row, seed)
    t = lambda index: f"T{index:05d}"
    trace.observe("all initial tasks are present", [t(0), t(count - 1)], count=count,
                  records={t(0): task_row(0, seed), t(count - 1): task_row(count - 1, seed)})
    if task == "F2":
        a1 = event("A", 1, t(0), {"end": 18})
        b1 = event("B", 1, t(12), {"start": 15})
        trace.emit({"op": "deliver", "actor": "A", "events": [a1, b1]})
        trace.observe("two locally valid changes create dependency and resource conflicts after merge", [t(0), t(12)],
                      records={t(0): {**task_row(0, seed), "end": 18}, t(12): {**task_row(12, seed), "start": 15}},
                      issues=["dependency:T00000:T00012", "overlap:T00000:T00012"])
        a2 = event("A", 2, t(1), {"title": "local intent"}, {"A": 1})
        b2 = event("B", 2, t(1), {"title": "remote intent"}, {"B": 1})
        trace.emit({"op": "deliver", "actor": "A", "events": [a2, b2]})
        trace.observe("same-field concurrent changes remain visible for resolution", conflicts=["T00001:title"])
        resolution = event("C", 1, t(1), {"title": "resolved intent"}, {"A": 2, "B": 2})
        trace.emit({"op": "deliver", "actor": "A", "events": [resolution]})
        trace.emit({"op": "undo", "actor": "A", "target": "A:2", "id": "A:3", "context": {"A": 2, "B": 2, "C": 1}})
        trace.observe("old local undo cannot overwrite a causally later resolution", [t(1)], conflicts=[],
                      records={t(1): {**task_row(1, seed), "title": "resolved intent"}})
        legacy = task_row(2, seed)
        legacy["duration"] = legacy.pop("end") - legacy["start"]
        trace.emit({"op": "restore_document", "actor": "M", "document": {"schema": 1, "rows": [legacy], "pending": []}})
        trace.observe("schema-1 recovery converts duration into end without changing the schedule", [t(2)], actor="M", schema=2,
                      records={t(2): task_row(2, seed)})
        trace.emit({"op": "storage", "actor": "D", "fail": True})
        d1 = event("D", 1, t(3), {"notes": "offline unsaved intent"})
        trace.emit({"op": "deliver", "actor": "D", "events": [d1]})
        trace.observe("failed persistence leaves current intent visible and does not claim saved", [t(3)], actor="D", saved=False,
                      records={t(3): {**task_row(3, seed), "notes": "offline unsaved intent"}})
        trace.emit({"op": "storage", "actor": "D", "fail": False})
        trace.emit({"op": "deliver", "actor": "D", "events": [event("D", 2, t(3), {"title": "recovered edit"}, {"D": 1})]})
        trace.emit({"op": "refresh", "actor": "D"})
        trace.observe("refresh after successful persistence recovers both offline edits", [t(3)], actor="D", saved=True,
                      records={t(3): {**task_row(3, seed), "notes": "offline unsaved intent", "title": "recovered edit"}})
    else:
        a1 = event("A", 1, t(0), {"title": "first edit"})
        b1 = event("B", 1, t(0), {"title": "observed successor"}, {"A": 1})
        trace.emit({"op": "deliver", "actor": "A", "events": [a1, b1]})
        trace.observe("sequential remote editing is not classified as concurrent conflict", [t(0)], conflicts=[],
                      records={t(0): {**task_row(0, seed), "title": "observed successor"}})
        trace.emit({"op": "undo", "actor": "A", "target": "A:1", "id": "A:2", "context": {"A": 1, "B": 1}})
        trace.observe("conditional undo preserves a later remote field value", [t(0)],
                      records={t(0): {**task_row(0, seed), "title": "observed successor"}})
        c1 = event("C", 1, t(1), {"start": 8})
        d1 = event("D", 1, t(1), {"end": 5})
        trace.emit({"op": "deliver", "actor": "A", "events": [c1, d1]})
        trace.observe("merged independent fields preserve intent and expose invalid range", [t(1)], issues=["range:T00001"],
                      records={t(1): {**task_row(1, seed), "start": 8, "end": 5}})
        x1 = event("X", 1, t(2), {"title": "X intent"})
        y1 = event("Y", 1, t(2), {"title": "Y intent"})
        trace.emit({"op": "deliver", "actor": "A", "events": [y1, x1]})
        trace.observe("concurrent field contenders use deterministic display order and retain conflict", [t(2)], conflicts=["T00002:title"],
                      records={t(2): {**task_row(2, seed), "title": "Y intent"}})
        deletion = event("K", 1, t(3), kind="delete")
        restored = {**task_row(3, seed), "generation": 1, "title": "explicitly restored"}
        fields = {key: value for key, value in restored.items() if key not in ("id", "generation")}
        restoration = event("K", 2, t(3), fields, {"K": 1}, kind="restore", generation=1, tombstone="K:1")
        stale = event("Z", 999, t(3), {"title": "stale prior generation"}, generation=0)
        trace.emit({"op": "deliver", "actor": "A", "events": [deletion, restoration, stale]})
        trace.observe("explicit restore starts a new generation immune to old high-counter edits", [t(3)], records={t(3): restored})
        original = event("P", 1, t(4), {"notes": "original event"})
        trace.emit({"op": "deliver", "actor": "A", "events": [original]})
        invalid = {**original, "fields": {"notes": "same ID, altered payload"}}
        trace.emit({"op": "deliver", "actor": "A", "events": [event("P", 2, t(5), {"title": "must roll back"}, {"P": 1}), invalid]},
                   "same-ID different-content import rejects the entire batch", expected={"ok": False})
        trace.observe("an invalid import cannot leak its valid prefix", [t(4), t(5)],
                      records={t(4): {**task_row(4, seed), "notes": "original event"}, t(5): task_row(5, seed)})
        trace.emit({"op": "deliver", "actor": "I", "events": [original, original]})
        trace.observe("identical event replay is idempotent", [t(4)], actor="I", event_count=1,
                      records={t(4): {**task_row(4, seed), "notes": "original event"}})
    # Each row has five causally ordered revisions. Actors receive the same
    # causal history in opposite/shuffled transport orders, not different facts.
    history = []
    counter = 0
    for round_index in range(5):
        for index in range(24, count):
            counter += 1
            history.append(event("S", counter, t(index), {"title": f"round-{round_index}-task-{index}"}, {"S": counter - 1} if counter > 1 else {}))
    for replica_index, actor in enumerate(replicas):
        delivered = list(history)
        if replica_index == 1:
            delivered.reverse()
        elif replica_index >= 2:
            random.Random(seed + replica_index).shuffle(delivered)
        for start in range(0, len(delivered), 1000):
            trace.emit({"op": "deliver", "actor": actor, "events": delivered[start:start + 1000]})
        trace.observe(f"causal replay converges for replica {actor} regardless of arrival order", [t(24), t(count - 1)], actor=actor,
                      records={t(24): {**task_row(24, seed), "title": "round-4-task-24"}, t(count - 1): {**task_row(count - 1, seed), "title": f"round-4-task-{count - 1}"}})
    def expected_rows():
        for index in range(count):
            row = task_row(index, seed)
            if index >= 24:
                row["title"] = f"round-4-task-{index}"
            yield row
    digest = ordered_fingerprint(expected_rows())
    for actor in replicas:
        trace.emit({"op": "export", "actor": actor}, f"complete actor {actor} export covers the entire converged document", export={"count": count, "sha256": digest})
    return count


def subset_error(actual, expected, path="response"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{path}: expected object"
        for key, value in expected.items():
            if key not in actual:
                return f"{path}.{key}: missing"
            error = subset_error(actual[key], value, path + "." + key)
            if error:
                return error
        return None
    if type(actual) is not type(expected) or actual != expected:
        return f"{path}: expected {str(expected)[:160]}, received {str(actual)[:160]}"
    return None


def judge_output(output, trace):
    targets = {check["line"]: check for check in trace.checks}
    result = []
    seen_lines = 0
    acknowledged = {"records_loaded": 0, "event_deliveries": 0, "protocol_errors": 0}
    with output.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            seen_lines = number
            check = targets.get(number)
            try:
                response = json.loads(line)
            except (ValueError, RecursionError):
                response = None
            meta = trace.command_meta.get(number, {})
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                acknowledged["protocol_errors"] += 1
            elif response["ok"]:
                if meta.get("op") == "load":
                    acknowledged["records_loaded"] += meta["count"]
                if meta.get("op") in ("ingest", "deliver"):
                    acknowledged["event_deliveries"] += meta["count"]
            if not check:
                continue
            error = subset_error(response, check["expected"]) if check["expected"] is not None else None
            if check["export"]:
                rows = response.get("rows") if isinstance(response, dict) else None
                expected = check["export"]
                if not isinstance(rows, list):
                    error = "export: rows must be an actual complete array"
                elif len(rows) != expected["count"]:
                    error = f"export: expected {expected['count']} rows, received {len(rows)}"
                else:
                    try:
                        ids = [row["id"] for row in rows]
                        if len(set(ids)) != len(ids):
                            error = "export: duplicate stable IDs"
                        elif fingerprint(rows) != expected["sha256"]:
                            error = "export: independently computed full-row SHA-256 differs"
                    except (KeyError, TypeError, ValueError):
                        error = "export: malformed rows"
            result.append({"name": check["name"], "passed": error is None, "detail": error})
    for number, check in targets.items():
        if number > seen_lines:
            result.append({"name": check["name"], "passed": False, "detail": "candidate response missing"})
    return result, seen_lines, acknowledged


def generate(task, scale, seed, path):
    with path.open("w", encoding="utf-8") as handle:
        trace = Trace(handle)
        count = build_stream(task, scale, seed, trace) if task in ("F1", "F3") else build_tasks(task, scale, seed, trace)
    return trace, count


def audit_witnesses():
    from extreme_witness import witness_audit
    return witness_audit()


def export_package(task, scale, seed, destination):
    destination.mkdir(parents=True, exist_ok=True)
    trace, count = generate(task, scale, seed, destination / "trace.jsonl")
    raw_trace = destination / "trace.jsonl"
    with raw_trace.open("rb") as source, (destination / "trace.jsonl.gz").open("wb") as compressed:
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as encoded:
            shutil.copyfileobj(source, encoded)
    raw_trace.unlink()
    (destination / "generate_fixture.py").write_text('''#!/usr/bin/env python3
import argparse, gzip, shutil
from pathlib import Path
parser = argparse.ArgumentParser(description="Expand the public deterministic fixture; contains no answers.")
parser.add_argument("--output", type=Path, default=Path("trace.jsonl"))
args = parser.parse_args()
with gzip.open(Path(__file__).with_name("trace.jsonl.gz"), "rb") as src, args.output.open("wb") as dst:
    shutil.copyfileobj(src, dst)
print(str(args.output.resolve()))
''', encoding="utf-8")
    for name in ("PROMPT.md", "PROTOCOL.md", "trace-viewer.html", "sample.jsonl"):
        shutil.copy2(ROOT / task / "extreme" / name, destination / name)
    shutil.copy2(ROOT / "extreme_weak_adapter.py", destination / "starter_adapter.py")
    shutil.copy2(ROOT / task / "starter.html", destination / "starter.html")
    metadata = {"task": task, "protocol": PROTOCOL, "scale": scale, "seed": seed,
                "records": count, "commands": trace.lines, "events_delivered": trace.events_delivered,
                "contains_answers": False, "starter_status": "legacy UI plus incomplete weak semantic adapter; integrate them into one submitted app"}
    (destination / "fixture.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return metadata


def evaluate(task, scale, seed, submission=None, timeout=90):
    started = time.monotonic()
    audit = audit_witnesses()
    with tempfile.TemporaryDirectory(prefix="smb-frontend-extreme-") as temporary:
        temp = Path(temporary)
        fixture, output, errors = temp / "trace.jsonl", temp / "responses.jsonl", temp / "stderr.txt"
        trace, count = generate(task, scale, seed, fixture)
        path = Path(submission).resolve() if submission else ROOT / "extreme_weak_adapter.py"
        if path.is_dir():
            candidates = [path / name for name in ("adapter.py", "adapter.cjs", "adapter.js", "starter_adapter.py")]
            path = next((candidate for candidate in candidates if candidate.is_file()), path)
        command = ([sys.executable] if path.suffix == ".py" else ["node"] if path.suffix in (".js", ".cjs", ".mjs") else []) + [str(path)]
        failure = None
        with fixture.open("rb") as stdin, output.open("wb") as stdout, errors.open("wb") as stderr:
            try:
                completed = subprocess.run(command, stdin=stdin, stdout=stdout, stderr=stderr,
                                           cwd=path.parent, timeout=timeout, check=False)
                if completed.returncode:
                    failure = f"candidate exited {completed.returncode}"
            except subprocess.TimeoutExpired:
                failure = f"candidate exceeded {timeout}s"
            except (OSError, ValueError) as exc:
                failure = f"candidate launch failed: {exc}"
        checks, response_lines, acknowledged = judge_output(output, trace)
        passed = sum(check["passed"] for check in checks)
        legacy = {"F1": 10000, "F2": 12, "F3": 50000, "F4": 12}[task]
        semantic = {"valid": not failure and response_lines == trace.lines and not acknowledged["protocol_errors"] and passed == len(checks),
                    "passed": passed, "total": len(checks), "semantic_score": round(100 * passed / len(checks), 4),
                    "quality_score": None, "human_visual_score": None, "checks": checks,
                    "failure": failure, "stderr_tail": errors.read_text(errors="replace")[-1500:],
                    "implementation": str(path) if submission else "new weak semantic adapter; legacy HTML was not executed",
                    "scope": "JSONL semantic adapter only, not arbitrary HTML end-to-end certification"}
        return {"task_id": task, "profile": "extreme", "scale": scale, "seed": seed,
                "dimensions": [{"name": "initial_records", "legacy": legacy, "current": count, "ratio": count / legacy, "scope": "generated"},
                               {"name": "initial_records_acknowledged_by_adapter", "legacy": legacy, "current": acknowledged["records_loaded"], "ratio": acknowledged["records_loaded"] / legacy, "scope": "executed"}],
                "mechanisms": MECHANISMS[task], "candidate_result" if submission else "baseline_result": semantic,
                "verification": {"commands_generated": trace.lines, "responses_observed": response_lines,
                                 "initial_records_generated": trace.records_loaded,
                                 "event_deliveries_generated": trace.events_delivered, "adapter_acknowledged": acknowledged,
                                 "command_counts": trace.commands, "elapsed_seconds": round(time.monotonic() - started, 3),
                                 "witnesses": audit, "full_browser_load_executed": False,
                                 "pending": ["native multi-window browser persistence and recovery", "real download and resource usage", "keyboard, IME, narrow viewport and assistive-technology workflows", "independent visual and usability review"],
                                 "trace_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()},
                "audit_passed": audit["passed"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, choices=sorted(MECHANISMS))
    parser.add_argument("--scale", default="smoke", choices=["smoke", "full"])
    parser.add_argument("--seed", type=int, default=260926)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export", type=Path, dest="export_dir")
    parser.add_argument("--submission", type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if args.export_dir:
        result = {"task_id": args.task, "exported": str(args.export_dir.resolve()),
                  **export_package(args.task, args.scale, args.seed, args.export_dir)}
    else:
        result = evaluate(args.task, args.scale, args.seed, args.submission, args.timeout)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result.get("audit_passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
