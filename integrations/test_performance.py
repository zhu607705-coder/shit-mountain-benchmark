#!/usr/bin/env python3
"""Real loopback SSE tests for observable metrics, persistence and trial boundaries."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import statistics
import tempfile
import time
import unittest
from unittest.mock import patch

from performance import Observation, percentile, run_plan, stats, stream_call, sse_payloads
from performance_demo import DEMO_CREDENTIAL, PRIVATE_REASONING_SENTINEL, mock_endpoint


def plan_for(*scenarios):
    return {"prompts": [{"id": f"p{index}-{scenario}", "messages": [{"role": "user", "content": "MOCK_CASE:" + scenario}]} for index, scenario in enumerate(scenarios)]}


def records_at(path):
    return [json.loads(line) for line in (path / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]


class PerformanceTests(unittest.TestCase):
    def test_partial_progress_cannot_extend_absolute_request_deadline(self):
        class EndlessPartialLine:
            def read1(self,size):
                time.sleep(.004)
                return b'data: '
        started=time.perf_counter()
        with self.assertRaises(TimeoutError):
            list(sse_payloads(EndlessPartialLine(),started+.025))
        self.assertLess(time.perf_counter()-started,.5)

    def test_loopback_binding_does_not_need_reverse_dns(self):
        with patch("socket.getfqdn", side_effect=AssertionError("reverse DNS is forbidden in loopback fixture")):
            with mock_endpoint() as (config, server):
                self.assertEqual(server.server_name, "127.0.0.1")
                self.assertTrue(config["base_url"].startswith("http://127.0.0.1:"))

    def test_three_distinct_first_times_and_usage_only_final_chunk(self):
        with mock_endpoint() as (config, server):
            result = stream_call(config, plan_for("standard")["prompts"][0]["messages"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["stream_done_marker"])
        self.assertLess(result["first_event_ms"], result["first_reasoning_delta_ms"])
        self.assertLess(result["first_reasoning_delta_ms"], result["ttft_ms"])
        self.assertLess(result["ttft_ms"], result["total_ms"])
        self.assertGreater(result["observed_reasoning_stream_span_ms"], 0)
        self.assertIsNone(result["thinking_time_ms"])
        self.assertIn("not observable", result["thinking_time_source"])
        self.assertTrue(result["usage_reported"])
        self.assertEqual(result["output_tokens"], 121)
        self.assertEqual(result["reasoning_tokens"], 81)
        self.assertEqual(result["non_reasoning_generated_tokens"], 40)
        self.assertIsNone(result["visible_output_tokens"])
        self.assertIn("invisible formatting", result["output_token_scope"])
        self.assertNotEqual(result["visible_output_chars"], result["output_tokens"])
        self.assertGreater(result["visible_output_bytes"], result["visible_output_chars"])
        self.assertEqual(result["reasoning_stream_events"], 2)
        self.assertNotIn(PRIVATE_REASONING_SENTINEL, json.dumps(result))
        self.assertEqual(server.requests[0]["stream_options"], {"include_usage": True})

    def test_reasoning_without_visible_answer_has_no_visible_ttft(self):
        with mock_endpoint() as (config, _):
            result = stream_call(config, plan_for("reasoning_only")["prompts"][0]["messages"])
        self.assertEqual(result["status"], "completed")
        self.assertIsNotNone(result["first_reasoning_delta_ms"])
        self.assertIsNone(result["ttft_ms"])
        self.assertIsNone(result["thinking_time_ms"])
        self.assertEqual(result["visible_output_chars"], 0)
        self.assertGreater(result["output_tokens"], 0)

    def test_normal_done_without_usage_keeps_missing_tokens_null(self):
        with mock_endpoint() as (config, _):
            result = stream_call(config, plan_for("no_usage")["prompts"][0]["messages"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["usage_reported"])
        for name in ("input_tokens", "output_tokens", "reasoning_tokens", "visible_output_tokens", "thinking_time_ms", "provider_output_tokens_per_second"):
            self.assertIsNone(result[name], name)

    def test_disconnect_before_finish_and_after_stop_are_not_completed(self):
        with mock_endpoint() as (config, _):
            for scenario in ("disconnect", "disconnect_after_stop", "chunk_disconnect"):
                with self.subTest(scenario=scenario):
                    result = stream_call(config, plan_for(scenario)["prompts"][0]["messages"])
                    self.assertNotEqual(result["status"], "completed")
                    self.assertFalse(result["stream_done_marker"])
                    self.assertIsNone(result["output_tokens"])
                    self.assertIsNone(result["thinking_time_ms"])
            self.assertEqual(result["error_code"], "incomplete_http_response")

    def test_single_and_split_credential_echo_become_failed_attempts_without_persistence(self):
        with tempfile.TemporaryDirectory() as temp, mock_endpoint() as (config, _):
            output = Path(temp) / "run"
            summary = run_plan(config, plan_for("credential_echo", "credential_split", "standard"), output,
                               rounds=1, simulated=True)
            rows = records_at(output)
            echoed = [row for row in rows if "credential" in row["prompt_id"]]
            self.assertEqual(len(echoed), 2)
            for row in echoed:
                self.assertEqual(row["error_code"], "credential_echo_refused")
                self.assertNotEqual(row["status"], "completed")
                self.assertEqual(row["response_text"], "")
            self.assertEqual(summary["overall"]["failed_attempts"], 2)
            combined = "\n".join(path.read_text(encoding="utf-8-sig") for path in output.iterdir())
            self.assertNotIn(DEMO_CREDENTIAL, combined)
            self.assertNotIn(PRIVATE_REASONING_SENTINEL, combined)
            self.assertNotIn("more private reasoning", combined)

    def test_json_fallback_does_not_invent_stream_ttft(self):
        with mock_endpoint() as (config, _):
            result = stream_call(config, plan_for("json_fallback")["prompts"][0]["messages"])
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["streamed"])
        self.assertIsNone(result["ttft_ms"])
        self.assertIsNone(result["first_event_ms"])
        self.assertIsNone(result["first_reasoning_delta_ms"])
        self.assertGreater(result["output_tokens"], 0)

    def test_descriptive_stats_include_missingness_and_interpolate_quantiles(self):
        result = stats([1, 2, 5, None, True, float("nan")])
        self.assertEqual(result["observations"], 3)
        self.assertEqual(result["missing"], 3)
        self.assertAlmostEqual(result["mean"], 8 / 3)
        self.assertEqual(result["max"], 5)
        self.assertEqual(result["p50"], 2)
        self.assertAlmostEqual(result["p95"], 4.7)
        self.assertIsNone(stats([None])["mean"])
        self.assertIsNone(percentile([], 0.95))

    def test_three_prompts_three_rounds_keep_all_nine_attempts(self):
        plan = json.loads(Path(__file__).with_name("performance-prompts.example.json").read_text())
        with tempfile.TemporaryDirectory() as temp, mock_endpoint() as (config, server):
            output = Path(temp) / "run"
            summary = run_plan(config, plan, output, rounds=3, seed=260926, simulated=True)
            rows = records_at(output)
            self.assertEqual(len(rows), 9)
            self.assertEqual(len(server.requests), 9)
            self.assertEqual(summary["overall"]["logical_runs"], 9)
            self.assertEqual(summary["overall"]["successful_attempts"], 9)
            self.assertTrue(summary["simulated"])
            for prompt in plan["prompts"]:
                group = [row for row in rows if row["prompt_id"] == prompt["id"]]
                self.assertEqual({row["round"] for row in group}, {1, 2, 3})
                expected = statistics.fmean(row["total_ms"] for row in group)
                self.assertAlmostEqual(summary["by_prompt"][prompt["id"]]["all_attempt_metrics"]["total_ms"]["mean"], expected)
            self.assertEqual(summary["overall"]["all_attempt_metrics"]["thinking_time_ms"]["missing"], 9)
            self.assertIsNone(summary["overall"]["all_attempt_metrics"]["thinking_time_ms"]["p95"])
            with (output / "attempts.csv").open(encoding="utf-8-sig", newline="") as stream:
                csv_rows = list(csv.DictReader(stream))
            self.assertEqual(len(csv_rows), 9)
            for row in csv_rows:
                self.assertEqual(row["simulated"], "True")
                self.assertEqual(row["visible_output_tokens"], "")
                self.assertEqual(row["thinking_time_ms"], "")
                self.assertIn("first_reasoning_delta_ms", row)
            self.assertNotIn(PRIVATE_REASONING_SENTINEL, (output / "attempts.jsonl").read_text())

    def test_warmups_are_retained_but_excluded_from_measured_aggregates(self):
        with tempfile.TemporaryDirectory() as temp, mock_endpoint() as (config, server):
            output = Path(temp) / "run"
            summary = run_plan(config, plan_for("standard", "no_usage"), output, rounds=2, warmups=1, simulated=True)
            rows = records_at(output)
            self.assertEqual(len(rows), 6)
            self.assertEqual(summary["warmup_attempts_excluded"], 2)
            self.assertEqual(summary["overall"]["attempts"], 4)
            self.assertEqual(summary["overall"]["all_attempt_metrics"]["output_tokens"]["missing"], 2)
            self.assertEqual(summary["planned_measured_logical_runs"], 4)

    def test_retries_keep_failure_cost_and_unknown_token_total(self):
        with tempfile.TemporaryDirectory() as temp, mock_endpoint() as (config, _):
            output = Path(temp) / "run"
            summary = run_plan(config, plan_for("retry_once", "always_fail"), output, rounds=1, retries=2, simulated=True)
            rows = records_at(output)
            self.assertEqual(len(rows), 5)
            self.assertEqual(summary["overall"]["attempts"], 5)
            self.assertEqual(summary["overall"]["successful_attempts"], 1)
            self.assertEqual(summary["overall"]["failed_attempts"], 4)
            self.assertEqual(summary["overall"]["logical_runs"], 2)
            self.assertEqual(summary["overall"]["failed_logical_runs"], 1)
            retry = [row for row in rows if "retry_once" in row["prompt_id"]]
            self.assertEqual([row["attempt"] for row in retry], [1, 2])
            self.assertEqual([row["logical_final"] for row in retry], [False, True])
            self.assertGreaterEqual(retry[-1]["logical_total_ms"], sum(row["total_ms"] for row in retry))
            self.assertIsNone(retry[-1]["logical_output_tokens"])
            self.assertEqual(retry[-1]["output_tokens_known_lower_bound"], retry[-1]["output_tokens"])
            self.assertIsNotNone(retry[-1]["logical_ttft_ms"])
            self.assertEqual(summary["overall"]["logical_total_ms"]["observations"], 2)

    def test_conversation_preserves_order_and_resets_between_rounds(self):
        with tempfile.TemporaryDirectory() as temp, mock_endpoint() as (config, server):
            output = Path(temp) / "run"
            summary = run_plan(config, plan_for("standard", "no_usage"), output, rounds=2, conversation=True, simulated=True)
            self.assertEqual([len(request["messages"]) for request in server.requests], [1, 3, 1, 3])
            self.assertEqual(server.requests[1]["messages"][1]["role"], "assistant")
            self.assertIn('"simulated": true', server.requests[1]["messages"][1]["content"])
            self.assertEqual(summary["not_executed_logical_runs"], 0)

    def test_failed_conversation_turn_stops_rest_of_round_and_reports_skipped_runs(self):
        with tempfile.TemporaryDirectory() as temp, mock_endpoint() as (config, server):
            output = Path(temp) / "run"
            summary = run_plan(config, plan_for("standard", "always_fail", "no_usage"), output,
                               rounds=2, retries=1, conversation=True, simulated=True)
            self.assertEqual(len(server.requests), 6)
            self.assertEqual([len(request["messages"]) for request in server.requests], [1, 3, 3, 1, 3, 3])
            self.assertEqual(summary["planned_measured_logical_runs"], 6)
            self.assertEqual(summary["not_executed_logical_runs"], 2)
            self.assertEqual(summary["overall"]["logical_runs"], 4)
            self.assertEqual(summary["overall"]["failed_logical_runs"], 2)
            self.assertFalse(any("no_usage" in row["prompt_id"] for row in records_at(output)))

    def test_strict_counts_do_not_treat_boolean_usage_as_tokens(self):
        observation = Observation(0)
        observation.event({"choices": [], "usage": {"prompt_tokens": True, "completion_tokens": -1, "completion_tokens_details": {"reasoning_tokens": False}}}, 0.1)
        result = observation.result(0.2, streamed=True)
        self.assertIsNone(result["input_tokens"])
        self.assertIsNone(result["output_tokens"])
        self.assertIsNone(result["reasoning_tokens"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
