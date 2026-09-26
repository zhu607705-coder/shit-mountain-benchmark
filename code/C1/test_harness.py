"""Hand-computed oracle anchors and metamorphic invariants, independent of baseline."""
import copy
import random
import unittest

from cases import post, reverse
from oracle import solve


class OracleTests(unittest.TestCase):
    def test_tenant_identity_and_reverse(self):
        events = [reverse("A", "r", "p"), post("B", "p", 20), post("A", "p", 10)]
        self.assertEqual(solve(events), {
            "balances": [["B", "cash", 20], ["B", "equity", -20]],
            "statuses": [["A", "p", "REVERSED"], ["A", "r", "APPLIED"], ["B", "p", "ACTIVE"]]})

    def test_conflict_precedes_validation_and_orphans(self):
        events = [post("A", "p"), {"tenant": "A", "id": "p", "kind": "post", "entries": []},
                  reverse("A", "r", "p")]
        self.assertEqual(solve(events), {"balances": [], "statuses": [["A", "p", "CONFLICT"], ["A", "r", "ORPHAN"]]})

    def test_money_types_and_zero_sum(self):
        events = [post("A", "p", True), post("A", "q", 1.0), post("A", "r", 5)]
        self.assertEqual(solve(events), {"balances": [["A", "cash", 5], ["A", "equity", -5]],
                                       "statuses": [["A", "p", "INVALID"], ["A", "q", "INVALID"], ["A", "r", "ACTIVE"]]})

    def test_metamorphic_permutation_duplicates_and_conservation(self):
        events = [post("A", f"p{i}", i * 7) for i in range(30)] + [reverse("A", "r", "p3")]
        expected = solve(events)
        altered = copy.deepcopy(events * 3)
        random.Random(12345).shuffle(altered)
        self.assertEqual(solve(altered), expected)
        self.assertEqual(sum(row[2] for row in expected["balances"]), 0)


if __name__ == "__main__":
    unittest.main()
