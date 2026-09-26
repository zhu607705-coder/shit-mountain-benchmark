#!/usr/bin/env python3
"""Runnable weak semantic adapter, NOT an execution of the legacy HTML pages.

Uses familiar v0.1 strategies: stream revisions, global pause queue, arrival-order
field merging and whole-operation undo. Deliberately incomplete for the new
causal, generation, retention and cross-field semantics. It is an honest lower
baseline, not a full reference solution. No judge imports are allowed here.
"""
from __future__ import annotations
import copy
import json
import sys

class WeakAdapter:
    def __init__(self):
        self.task = None
        self.rows = {}
        self.versions = {}
        self.views = {}
        self.replicas = {}
        self.seen = {}
        self.before = {}
        self.acks = set()
        self.frozen = {}
        self.freshness = {}
        self.stored = {}
        self.storage_ok = {}

    def replica(self, actor):
        if actor not in self.replicas:
            self.replicas[actor] = copy.deepcopy(self.rows)
            self.seen[actor] = {}
        return self.replicas[actor]

    def view(self, actor):
        return self.views.setdefault(actor, {"selection": None, "focus": None, "filter": {}, "history": [], "cursor": -1})

    def run(self, command):
        op = command["op"]
        actor = command.get("actor", "A")
        if op == "config":
            self.task = command["task"]
        elif op == "load":
            for row in command["rows"]:
                self.rows[row["id"]] = copy.deepcopy(row)
                self.versions[row["id"]] = row.get("rev", 0)
        elif op == "ingest":
            for row in command["rows"]:
                rid = row["id"]
                if row["rev"] <= self.versions.get(rid, -1):
                    continue
                self.versions[rid] = row["rev"]
                if row.get("deleted"):
                    self.rows.pop(rid, None)
                else:
                    self.rows[rid] = copy.deepcopy(row)
        elif op == "alias":
            # Copies record, but leaves old references and per-alias revisions.
            old, new = command["old"], command["canonical"]
            if old in self.rows:
                self.rows[new] = {**self.rows.pop(old), "id": new}
        elif op == "ack":
            if command["value"]:
                self.acks.add(command["id"])
            else:
                self.acks.discard(command["id"])
        elif op == "view":
            view = self.view(actor)
            for key in ("selection", "focus", "filter"):
                if key in command:
                    view[key] = copy.deepcopy(command[key])
            if command.get("push"):
                view["history"] = view["history"][:view["cursor"] + 1]
                view["history"].append({key: copy.deepcopy(view[key]) for key in ("selection", "filter")})
                view["cursor"] += 1
        elif op == "history":
            view = self.view(actor)
            view["cursor"] = max(0, min(len(view["history"]) - 1, view["cursor"] + command["delta"]))
            if view["history"]:
                view.update(copy.deepcopy(view["history"][view["cursor"]]))
        elif op == "stream":
            self.freshness[command["stream"]] = command["connected"]
        elif op == "pause":
            if command["value"]:
                self.frozen[actor] = dict(self.rows)
            else:
                self.frozen.pop(actor, None)
        elif op == "compact":
            # Naive GC discards anti-resurrection knowledge.
            self.versions = {rid: rev for rid, rev in self.versions.items() if rid in self.rows}
        elif op == "deliver":
            rows = self.replica(actor)
            for event in command["events"]:
                previous = self.seen[actor].get(event["id"])
                if previous == event:
                    continue
                self.seen[actor][event["id"]] = copy.deepcopy(event)
                rid = event["item"]
                self.before[(actor, event["id"])] = copy.deepcopy(rows.get(rid))
                if event["kind"] == "delete":
                    rows.pop(rid, None)
                elif event["kind"] == "restore":
                    rows[rid] = {"id": rid, "generation": event["generation"], **event["fields"]}
                elif rid in rows:
                    rows[rid].update(copy.deepcopy(event.get("fields", {})))
            if self.storage_ok.get(actor, True):
                self.stored[actor] = copy.deepcopy(rows)
        elif op == "undo":
            rows = self.replica(actor)
            before = self.before.get((actor, command["target"]))
            target = self.seen[actor].get(command["target"])
            if before and target:
                for key in target.get("fields", {}):
                    rows[target["item"]][key] = copy.deepcopy(before[key])
        elif op == "storage":
            self.storage_ok[actor] = not command["fail"]
        elif op == "refresh":
            self.replicas[actor] = copy.deepcopy(self.stored.get(actor, self.rows))
        elif op == "restore_document":
            self.replicas[actor] = {row["id"]: copy.deepcopy(row) for row in command["document"]["rows"]}
            self.views.setdefault(actor, {})["schema"] = command["document"]["schema"]
        elif op == "observe":
            rows = self.replica(actor) if self.task in ("F2", "F4") else self.frozen.get(actor, self.rows)
            view = self.view(actor)
            return {"ok": True, "count": len(rows),
                    "records": {rid: rows.get(rid) for rid in command.get("ids", [])},
                    "selection": view.get("selection"), "focus": view.get("focus"),
                    "filter": view.get("filter", {}), "acked": sorted(self.acks),
                    "stale_streams": sorted(key for key, value in self.freshness.items() if not value),
                    "conflicts": [], "issues": [], "schema": view.get("schema", 2),
                    "saved": self.storage_ok.get(actor, True), "event_count": len(self.seen.get(actor, {}))}
        elif op == "export":
            # Weak baseline exports newest data even when this view is paused.
            rows = self.replica(actor) if self.task in ("F2", "F4") else self.rows
            return {"ok": True, "rows": list(rows.values())}
        else:
            return {"ok": False, "error": "unsupported operation"}
        return {"ok": True}

if __name__ == "__main__":
    adapter = WeakAdapter()
    for line in sys.stdin:
        try:
            response = adapter.run(json.loads(line))
        except Exception as exc:
            response = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
