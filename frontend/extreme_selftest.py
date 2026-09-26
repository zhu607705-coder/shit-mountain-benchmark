#!/usr/bin/env python3
"""Meaningful judge/fixture regressions. Expected weak-baseline failures are data."""
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from extreme import Trace, audit_witnesses, evaluate, export_package, generate, judge_output, subset_error
from extreme_protocol import fingerprint, stream_row
from extreme_witness import small_register


class ExtremeFrontendTests(unittest.TestCase):
    def test_independent_exhaustive_feasibility_witnesses(self):
        audit = audit_witnesses()
        self.assertTrue(audit["passed"])
        self.assertGreaterEqual(len(audit["checks"]), 8)
        with self.assertRaises(ValueError):
            small_register([{}] * 9)

    def test_deterministic_trace_and_seed_sensitivity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            first, count = generate("F2", "smoke", 260926, path / "a")
            second, _ = generate("F2", "smoke", 260926, path / "b")
            generate("F2", "smoke", 260927, path / "c")
            self.assertEqual((path / "a").read_bytes(), (path / "b").read_bytes())
            self.assertNotEqual((path / "a").read_bytes(), (path / "c").read_bytes())
            self.assertEqual(first.checks, second.checks)
            self.assertEqual(count, first.records_loaded)

    def test_wrong_types_cannot_impersonate_integer_or_boolean(self):
        self.assertIsNotNone(subset_error({"count": True}, {"count": 1}))
        self.assertIsNotNone(subset_error({"ok": 1}, {"ok": True}))
        self.assertIsNone(subset_error({"ok": True, "extra": "permitted"}, {"ok": True}))

    def test_export_is_verified_from_actual_rows_and_is_order_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            rows = [stream_row(index, 7) for index in range(3)]
            trace = Trace(io.StringIO())
            trace.emit({"op": "export", "actor": "A"}, "actual export", export={"count": 3, "sha256": fingerprint(rows)})
            output.write_text(json.dumps({"ok": True, "rows": list(reversed(rows))}) + "\n")
            self.assertTrue(judge_output(output, trace)[0][0]["passed"])
            output.write_text(json.dumps({"ok": True, "rows": [rows[0], rows[0], rows[2]], "sha256": fingerprint(rows)}) + "\n")
            self.assertFalse(judge_output(output, trace)[0][0]["passed"])
            output.write_text(json.dumps({"ok": True, "count": 3, "sha256": fingerprint(rows)}) + "\n")
            self.assertFalse(judge_output(output, trace)[0][0]["passed"])

    def test_missing_malformed_output_and_unexecuted_records_are_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            trace = Trace(io.StringIO())
            trace.emit({"op": "load", "rows": [stream_row(0, 7)]})
            trace.observe("required observation", count=1)
            output.write_text("not json\n")
            checks, count, ack = judge_output(output, trace)
            self.assertFalse(checks[0]["passed"])
            self.assertEqual(ack["records_loaded"], 0)
            self.assertEqual(ack["protocol_errors"], 1)
            self.assertEqual(count, 1)

    def test_public_package_has_inputs_and_starter_without_answer_judge(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "public"
            info = export_package("F3", "smoke", 13, path)
            self.assertFalse(info["contains_answers"])
            self.assertTrue((path / "starter.html").is_file())
            self.assertTrue((path / "starter_adapter.py").is_file())
            self.assertFalse((path / "extreme.py").exists())
            self.assertFalse((path / "extreme_witness.py").exists())
            self.assertFalse((path / "trace.jsonl").exists())
            with gzip.open(path / "trace.jsonl.gz", "rt") as handle:
                commands = [json.loads(line) for line in handle]
            self.assertEqual(sum(len(c["rows"]) for c in commands if c["op"] == "load"), 5000)
            self.assertFalse(any("expected" in command or "checks" in command for command in commands))
            self.assertLess(max(f.stat().st_size for f in path.iterdir()), 16 * 1024 * 1024)

    def test_each_smoke_baseline_executes_and_has_both_capabilities_and_failures(self):
        for task in ("F1", "F2", "F3", "F4"):
            with self.subTest(task=task):
                result = evaluate(task, "smoke", 260926)
                baseline, verification = result["baseline_result"], result["verification"]
                self.assertTrue(result["audit_passed"])
                self.assertIsNone(baseline["failure"])
                self.assertGreater(baseline["passed"], 0)
                self.assertLess(baseline["passed"], baseline["total"])
                self.assertEqual(verification["commands_generated"], verification["responses_observed"])
                self.assertEqual(verification["initial_records_generated"], verification["adapter_acknowledged"]["records_loaded"])
                self.assertFalse(verification["full_browser_load_executed"])
                self.assertIsNone(baseline["quality_score"])

    def test_launch_failure_cannot_claim_executed_scale(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing-adapter.py"
            result = evaluate("F1", "smoke", 260926, path)
            self.assertEqual(result["dimensions"][1]["current"], 0)
            self.assertFalse(result["candidate_result"]["valid"])
            self.assertIsNotNone(result["candidate_result"]["failure"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
