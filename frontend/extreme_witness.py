"""Bounded independent feasibility witnesses, not a complete frontend solution."""
from copy import deepcopy
from itertools import permutations
import json


def dominates(newer, older):
    return (newer["actor"] == older["actor"] and newer["counter"] > older["counter"]) or newer.get("context", {}).get(older["actor"], 0) >= older["counter"]


def small_register(events):
    """An exhaustive <= 8-event reference register used only in audit witnesses."""
    if len(events) > 8:
        raise ValueError("witness limited to eight events; not a full task engine")
    maximal = [event for event in events if not any(other is not event and dominates(other, event) for other in events)]
    winner = max(maximal, key=lambda event: (event["counter"], event["actor"], event["id"]))
    return {"value": winner["value"], "conflict": len(maximal) > 1, "candidates": sorted(event["id"] for event in maximal)}


def atomic_union(existing, events):
    staging = deepcopy(existing)
    for event in events:
        if event["id"] in staging and staging[event["id"]] != event:
            return False, deepcopy(existing)
        staging[event["id"]] = deepcopy(event)
    return True, staging


def witness_audit():
    a = {"id": "A:9", "actor": "A", "counter": 9, "context": {}, "value": "old"}
    b = {"id": "B:1", "actor": "B", "counter": 1, "context": {"A": 9}, "value": "new"}
    c = {"id": "C:1", "actor": "C", "counter": 1, "context": {}, "value": "concurrent"}
    resolution = {"id": "D:1", "actor": "D", "counter": 1, "context": {"A": 9, "B": 1, "C": 1}, "value": "resolved"}
    sequential = [small_register(list(order)) for order in permutations([a, b])]
    concurrent = small_register([b, c])
    resolved = [small_register(list(order)) for order in permutations([a, b, c, resolution])]
    # Transport order changes naive LWW's outcome while the partial order does not.
    naive = [order[-1]["value"] for order in permutations([a, b])]
    adds, removals = set(), set()
    operations = [("add", "A:1"), ("add", "B:1"), ("remove", "A:1")]
    observed_remove = []
    for order in permutations(operations):
        adds.clear(); removals.clear()
        for kind, dot in order:
            (adds if kind == "add" else removals).add(dot)
        observed_remove.append(sorted(adds - removals))
    existing = {"P:1": {"id": "P:1", "value": "old"}}
    accepted, persisted = atomic_union(existing, [{"id": "P:2", "value": "legal prefix"}, {"id": "P:1", "value": "altered ID"}])
    duplicate_ok, duplicate = atomic_union(existing, [existing["P:1"], existing["P:1"]])
    # Locally valid independent interval changes can make their merge invalid.
    left, right = {"a_end": 18, "b_start": 20}, {"a_end": 10, "b_start": 15}
    # A generation barrier works for either transport order of the new restore
    # and old-generation patch after an already-observed deletion.
    restored_versions = []
    for order in permutations([("restore", 1, "restored"), ("patch", 0, "stale")]):
        generation, alive, title = 0, False, None
        for kind, incoming_generation, value in order:
            if kind == "restore" and incoming_generation == generation + 1:
                generation, alive, title = incoming_generation, True, value
            elif kind == "patch" and alive and incoming_generation == generation:
                title = value
        restored_versions.append((generation, title))
    checks = {
        "observed_remove_preserves_unseen_add_under_all_six_orders": all(value == ["B:1"] for value in observed_remove),
        "merge_creates_new_global_conflict_from_locally_valid_edits": left["a_end"] <= left["b_start"] and right["a_end"] <= right["b_start"] and left["a_end"] > right["b_start"],
        "noncommuting_transport_has_convergent_causal_result": len(set(naive)) == 2 and all(value == {"value": "new", "conflict": False, "candidates": ["B:1"]} for value in sequential),
        "true_concurrency_retains_two_candidates": concurrent["conflict"] and concurrent["candidates"] == ["B:1", "C:1"],
        "causal_resolution_wins_all_twenty_four_permutations": all(value == {"value": "resolved", "conflict": False, "candidates": ["D:1"]} for value in resolved),
        "atomic_rejection_rolls_back_valid_prefix": not accepted and persisted == existing and "P:2" not in persisted,
        "identical_event_union_is_idempotent": duplicate_ok and duplicate == existing,
        "restoration_generation_blocks_old_patches_in_both_orders": all(value == (1, "restored") for value in restored_versions),
    }
    return {"passed": all(checks.values()), "checks": checks, "scope": "bounded exhaustive witnesses (at most 8 events); not a full task implementation or optimum"}


if __name__ == "__main__":
    result = witness_audit()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
