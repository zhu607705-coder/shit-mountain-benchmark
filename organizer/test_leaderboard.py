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

    def test_task_versions_and_efficiency_policies_cannot_mix(self):
        a, b = rec("a"), rec("b")
        b['task_profile'] = 'extreme'
        with self.assertRaises(ValueError): build([a, b])
        a.update(efficiency_score=40, efficiency_profile_id='budget-a')
        b.update(task_profile='legacy', efficiency_score=50, efficiency_profile_id='budget-b')
        with self.assertRaises(ValueError): build([a, b], metric='efficiency')
        b['efficiency_profile_id'] = 'budget-a'
        rows = build([a, b], metric='efficiency')['rows']
        self.assertEqual({r['model']:r['relative_scores']['R1'] for r in rows}, {'a':80, 'b':100})

    def test_semantic_only_frontend_does_not_become_complete_ui_score(self):
        r=rec(task='F1',score=100)
        r['final_ui_leaderboard_eligible']=False
        self.assertIsNone(build([r])['rows'][0]['relative_scores']['F1'])
        self.assertEqual(build([r],scope='automated')['rows'][0]['relative_scores']['F1'],100)

    def test_smoke_full_and_different_case_sets_cannot_mix(self):
        a,b=rec('a'),rec('b')
        a.update(task_profile='extreme',scale='smoke',comparison_id='same')
        b.update(task_profile='extreme',scale='full',comparison_id='same')
        with self.assertRaises(ValueError): build([a,b])
        b.update(scale='smoke',comparison_id='different')
        with self.assertRaises(ValueError): build([a,b])


if __name__ == "__main__":
    unittest.main()
