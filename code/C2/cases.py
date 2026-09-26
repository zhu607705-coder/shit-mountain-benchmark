"""Public fixtures and fixed-seed tests for graph edits and result ownership."""
import copy
import json
import random
from pathlib import Path


def public_cases():
    cases = json.loads((Path(__file__).parent / "fixtures" / "public.json").read_text())
    chain = {"n0": {"op": "input", "data": [1, 2]}}
    for index in range(1, 181):
        chain[f"n{index}"] = {"op": "sum", "deps": [f"n{index - 1}"]}
    cases.append({"name": "deep_cycle_after_cache", "nodes": chain, "aliases": {},
                  "commands": [{"op": "build", "target": "n180"},
                               {"op": "set", "name": "n0", "node": {"op": "sum", "deps": ["n180"]}},
                               {"op": "build", "target": "n180"}]})
    diamond = {"n0": {"op": "input", "data": [1]}}
    for index in range(1, 31):
        diamond[f"n{index}"] = {"op": "sum", "deps": [f"n{index - 1}", f"n{index - 1}"]}
    cases.append({"name": "shared_dag_is_not_cycle", "nodes": diamond, "aliases": {},
                  "commands": [{"op": "build", "target": "n30"}]})
    cases.append({"name": "long_alias_chain", "nodes": {"end": {"op": "input", "data": [11]}},
                  "aliases": {**{f"a{i}": f"a{i + 1}" for i in range(199)}, "a199": "end"},
                  "commands": [{"op": "build", "target": "a0"}]})
    return cases


def randomized(seed=2026092602, count=36):
    rng, cases = random.Random(seed), []
    for i in range(count):
        nodes = {f"i{k}": {"op": "input", "data": [rng.randint(-20, 20) for _ in range(7)]}
                 for k in range(6)}
        names = list(nodes)
        for k in range(16):
            name = f"n{k}"
            nodes[name] = {"op": rng.choice(["sum", "concat", "sort", "unique", "scale"]),
                           "deps": [rng.choice(names), rng.choice(names)], "factor": rng.randint(-2, 3)}
            names.append(name)
        aliases = {"main": "n15", "shortcut": "i0", "long": "shortcut"}
        commands = [{"op": "build", "target": "main"}]
        for j in range(45):
            mode = rng.randrange(8)
            if mode < 2:
                commands.append({"op": "set", "name": f"i{rng.randrange(6)}",
                                 "node": {"op": "input", "data": [rng.randint(-50, 50) for _ in range(7)]}})
            elif mode == 2:
                commands.append({"op": "alias", "name": "shortcut", "target": rng.choice(names)})
            elif mode == 3:
                commands.append({"op": "set", "name": f"n{rng.randrange(16)}",
                                 "node": {"op": rng.choice(["sum", "unique", "fail", "unknown"]),
                                          "deps": [rng.choice(names), "long"]}})
            elif mode == 4:
                commands.append({"op": "delete", "name": f"i{rng.randrange(6)}"})
            elif mode == 5:
                commands.append({"op": "build", "target": rng.choice(names), "cancel_at": [rng.choice(names)]})
            elif mode == 6:
                commands.append({"op": "tamper_last", "value": 99999 + j})
            else:
                commands.append({"op": "unalias", "name": "shortcut"})
            commands.append({"op": "build", "target": rng.choice(["main", "long"] + names)})
        cases.append({"name": f"public_random_{i:02}", "nodes": nodes, "aliases": aliases, "commands": commands})
    base = {"name": "metamorphic_base", "nodes": {"a": {"op": "input", "data": [2, -3, 7]},
            "b": {"op": "scale", "deps": ["a"], "factor": 3}}, "aliases": {},
            "commands": [{"op": "build", "target": "b"}]}
    sibling = copy.deepcopy(base)
    sibling["name"] = "metamorphic_unreachable_edit"
    sibling["commands"] = [{"op": "set", "name": "garbage", "node": {"op": "fail", "deps": []}},
                           {"op": "build", "target": "b"}]
    return cases + [base, sibling]


def performance_case():
    rng = random.Random(10691)
    nodes = {f"i{k}": {"op": "input", "data": [rng.randrange(100000) for _ in range(2048)]}
             for k in range(20)}
    for k in range(20):
        nodes[f"s{k}"] = {"op": "sort", "deps": [f"i{k}"]}
        nodes[f"u{k}"] = {"op": "unique", "deps": [f"s{k}"]}
    nodes["root"] = {"op": "concat", "deps": [f"u{k}" for k in range(20)]}
    commands = []
    for j in range(45):
        if j % 3 == 0:
            commands.append({"op": "set", "name": f"i{j % 20}",
                             "node": {"op": "input", "data": [rng.randrange(100000) for _ in range(2048)]}})
        commands.append({"op": "build", "target": "root"})
    return {"name": "incremental_branch_updates", "nodes": nodes, "aliases": {}, "commands": commands}
