import unittest
from leaderboard import build


def rec(model="a", task="R1", score=50, valid=True):
    return {"model": model, "task_id": task, "raw_score": score, "valid": valid}


class LeaderboardTests(unittest.TestCase):
    def test_ratios_ties_and_invalid(self):
        result = build([rec("a", score=50), rec("b", score=100), rec("c", score=100), rec("d", score=1000, valid=False)])
        scores = {r["model"]: r["relative_scores"]["R1"] for r in result["rows"]}
        self.assertEqual(scores, {"a": 50, "b": 100, "c": 100, "d": 0})

    def test_all_zero_does_not_award_full_marks(self):
        self.assertEqual(build([rec(score=0)])["rows"][0]["relative_scores"]["R1"], 0)

    def test_large_finite_scores_stay_finite(self):
        self.assertEqual(build([rec(score=1e308)])["rows"][0]["relative_scores"]["R1"], 100)

    def test_pending_does_not_claim_total(self):
        result = build([rec(task="F1", score=None, valid=None)])["rows"][0]
        self.assertIsNone(result["total"])
        self.assertIsNone(result["tracks"]["frontend"])
        self.assertEqual(result["pending_tasks"], ["F1"])

    def test_duplicate_and_invalid_scores_are_rejected(self):
        with self.assertRaises(ValueError):
            build([rec(), rec()])
        for value in (-1, float("nan"), float("inf"), True, "50"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build([rec(score=value)])
        with self.assertRaises(ValueError):
            build([rec(score=50, valid=None)])

    def test_missing_submissions_zero_and_track_balance(self):
        row = build([rec()])["rows"][0]
        self.assertEqual(row["tracks"]["reasoning"], 25)
        self.assertAlmostEqual(row["total"], 100 / 12)


if __name__ == "__main__":
    unittest.main()
