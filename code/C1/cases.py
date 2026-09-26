"""Public generators. Seeds are reproducible public tests, never hidden tests."""
import copy
import json
import random
from pathlib import Path


def post(tenant, identity, amount=10, source="cash", destination="equity"):
    return {"tenant": tenant, "id": identity, "kind": "post",
            "entries": [[source, amount], [destination, -amount]]}


def reverse(tenant, identity, target):
    return {"tenant": tenant, "id": identity, "kind": "reverse", "target": target}


def public_cases():
    values = json.loads((Path(__file__).parent / "fixtures" / "public.json").read_text())
    edge = [
        ("bad_row", [{"tenant": "A", "id": "p", "kind": "post", "entries": [["a", 1, 2], ["b", -1]]}]),
        ("non_list_entries", [{"tenant": "A", "id": "p", "kind": "post", "entries": "bad"}]),
        ("float_money", [post("A", "p", 1.0)]),
        ("out_of_range_money", [post("A", "p", 10**12 + 1)]),
        ("empty_reverse_target", [reverse("A", "r", "")]),
        ("tenant_reverse_isolation", [post("A", "p"), reverse("B", "r", "p")]),
        ("conflict_precedes_invalid", [post("A", "p"), {"tenant": "A", "id": "p", "kind": "post", "entries": []}]),
    ]
    # Aggregates exceed 2**53 although every input amount remains contract-valid.
    large = [post("A", f"p{i}", 10**12 - 1) for i in range(10000)]
    edge.append(("aggregate_exceeds_float_exactness", large))
    return [(case["name"], case["events"]) for case in values] + edge


def randomized(seed=2026092601, count=36):
    rng = random.Random(seed)
    result = []
    for case_index in range(count):
        events = []
        for i in range(rng.randint(20, 65)):
            tenant = rng.choice(["alpha", "beta", "gamma", "租户"])
            identity = f"p{i % 18}"
            account = f"a{rng.randrange(6)}"
            event = post(tenant, identity, rng.randrange(-10**12, 10**12), account, "reserve")
            choice = rng.random()
            if choice < .25:
                event = reverse(tenant, f"r{i % 13}", rng.choice([identity, "missing", f"r{i % 5}"]))
            elif choice < .35:
                event["entries"][0][1] += 1
            elif choice < .40:
                event["entries"] = [["cash", True], ["reserve", -1]]
            elif choice < .45:
                event["entries"].extend([[account, 9], [account, -9]])
            events.append(event)
            if rng.random() < .35:
                events.append(copy.deepcopy(event))
        rng.shuffle(events)
        result.append((f"public_random_{case_index:02}", events))
    # Explicit metamorphic siblings: permutations, duplicate delivery, tenant rename.
    base = [post("A", f"p{i}", i * 1321) for i in range(20)]
    base += [reverse("A", f"r{i}", f"p{i}") for i in range(0, 20, 3)]
    shuffled = copy.deepcopy(base)
    rng.shuffle(shuffled)
    renamed = copy.deepcopy(base)
    for event in renamed:
        event["tenant"] = "renamed"
    return result + [("metamorphic_base", base), ("metamorphic_permutation", shuffled),
                     ("metamorphic_idempotence", base + base + base),
                     ("metamorphic_tenant_rename", renamed)]


def performance_case():
    rng = random.Random(10331)
    events = []
    for i in range(6000):
        tenant = f"t{i % 11}"
        event = post(tenant, f"p{i}", 10**12 - i, f"a{i % 97}", "reserve")
        events.append(event)
        if i % 4 == 0:
            events.append(copy.deepcopy(event))
        if i % 7 == 0:
            events.append(reverse(tenant, f"r{i}", f"p{i}"))
        if i % 31 == 0:
            changed = copy.deepcopy(event)
            changed["entries"][0][1] -= 1
            changed["entries"][1][1] += 1
            events.append(changed)
    rng.shuffle(events)
    return events
