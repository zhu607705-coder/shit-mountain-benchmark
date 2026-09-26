import copy
import unittest
from extreme_contract import validate_report


def report():
    return {"task_id": "R1", "profile": "extreme", "scale": "full", "seed": 1,
            "dimensions": [{"name": "jobs", "legacy": 48, "current": 576, "ratio": 12, "scope": "generated"}],
            "mechanisms": ["irreversible commitments", "delayed correlated observations"],
            "candidate_result": {"valid": False, "raw_score": 0},
            "verification": {"checks": ["tiny feasible witness", "illegal actions rejected"]}, "audit_passed": True}


class ExtremeContractTests(unittest.TestCase):
    def test_candidate_failure_is_not_a_judge_failure(self):
        self.assertTrue(validate_report(report())["audit_passed"])

    def test_specification_is_not_an_instantiated_tenfold_workload(self):
        r = report(); r["dimensions"][0]["scope"] = "specified"
        with self.assertRaises(ValueError): validate_report(r)

    def test_ratio_must_match_counts_and_bools_are_not_counts(self):
        for field, value in (("ratio", 100), ("legacy", True), ("current", float("inf"))):
            r = report(); r["dimensions"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_report(r)

    def test_smoke_may_be_small_but_keeps_mechanisms(self):
        r = report(); r["scale"] = "smoke"; r["dimensions"][0].update(current=6, ratio=0.125)
        validate_report(r)
        r["mechanisms"] = ["same", "same"]
        with self.assertRaises(ValueError): validate_report(r)

    def test_report_identity_and_unknown_measurements(self):
        r = report(); r["candidate_result"]["raw_score"] = None; validate_report(r)
        for mutation in ({"task_id": "R9"}, {"audit_passed": 1}, {"verification": {}}, {"profile": "legacy"}):
            r = report(); r.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): validate_report(r)


if __name__ == "__main__": unittest.main()
