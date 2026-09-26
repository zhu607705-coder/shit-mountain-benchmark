"""Judge regression and small hand-computed anchors for the independent oracle."""
import copy
import unittest
from pathlib import Path

import judge
from cases import public_cases
from oracle import Engine


class HarnessTests(unittest.TestCase):
    def test_measured_preserves_tamper_semantics_and_tail(self):
        fixture = next(case for case in public_cases() if case["name"] == "result_mutation_ownership")
        expected = [{"value": [7, 8]}, {"value": [7, 8]}]
        baseline = judge.load(Path(__file__).parent / "baseline")
        self.assertEqual(judge.run(Engine, fixture), expected)
        self.assertEqual(judge.run(baseline, fixture), expected)
        _, passed = judge.measured(baseline, fixture, expected)
        self.assertTrue(passed)

    def test_oracle_padded_sum_and_order(self):
        engine = Engine({"a": {"op": "input", "data": [1, 2]},
                         "b": {"op": "input", "data": [3]},
                         "s": {"op": "sum", "deps": ["a", "b"]},
                         "c": {"op": "concat", "deps": ["b", "a", "a"]}}, {})
        self.assertEqual(engine.step({"op": "build", "target": "s"}), {"value": [4, 2]})
        self.assertEqual(engine.step({"op": "build", "target": "c"}), {"value": [3, 1, 2, 1, 2]})

    def test_oracle_error_order_is_contract(self):
        engine = Engine({"f": {"op": "fail", "deps": []},
                         "r": {"op": "sum", "deps": ["f", "missing"]}}, {})
        self.assertEqual(engine.step({"op": "build", "target": "r"}), {"error": "FAILED"})
        self.assertEqual(engine.step({"op": "build", "target": "r", "cancel_at": ["f"]}), {"error": "CANCELLED"})
        engine.step({"op": "set", "name": "r", "node": {"op": "sum", "deps": ["missing", "f"]}})
        self.assertEqual(engine.step({"op": "build", "target": "r"}), {"error": "MISSING"})

    def test_oracle_owns_definitions(self):
        nodes = {"a": {"op": "input", "data": [5]}}
        original = copy.deepcopy(nodes)
        engine = Engine(nodes, {})
        nodes["a"]["data"][0] = 99
        self.assertEqual(engine.step({"op": "build", "target": "a"}), {"value": [5]})
        result = engine.step({"op": "build", "target": "a"})
        result["value"].clear()
        self.assertEqual(engine.step({"op": "build", "target": "a"}), {"value": original["a"]["data"]})


if __name__ == "__main__":
    unittest.main()
