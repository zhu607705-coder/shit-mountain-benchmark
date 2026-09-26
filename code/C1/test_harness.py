"""Hand-computed oracle anchors and metamorphic invariants, independent of baseline."""
import copy
import random
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock
import urllib.request

from cases import post, reverse
from oracle import solve
from e2e_env_judge import Environment, ROOT


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


class EnvironmentTransportTests(unittest.TestCase):
    def test_loopback_server_startup_does_not_require_reverse_dns(self):
        probe = """import sys
from unittest import mock
sys.path.insert(0, sys.argv[1])
import api
with mock.patch('socket.getfqdn', side_effect=AssertionError('reverse DNS must not run for loopback')):
    with mock.patch.object(api.ThreadingHTTPServer, 'serve_forever', return_value=None):
        api.run({'db': 'unused', 'host': '127.0.0.1', 'port': 0})
"""
        for implementation in ("baseline", "buggy"):
            with self.subTest(implementation=implementation):
                result = subprocess.run([sys.executable, "-B", "-c", probe, str(ROOT / "repository" / implementation)],
                                        capture_output=True, text=True, timeout=2)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_loopback_health_ignores_environment_and_system_proxy(self):
        # A dead local proxy is deterministic and cannot leak test traffic.
        proxy_variables = {"http_proxy": "http://127.0.0.1:1", "https_proxy": "http://127.0.0.1:1",
                           "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
                           "no_proxy": "", "NO_PROXY": ""}
        with tempfile.TemporaryDirectory(prefix="ledger-proxy-test-") as temp:
            with mock.patch.dict(os.environ, proxy_variables), mock.patch.object(urllib.request, "_opener", None):
                # Simulate a system proxy too, independently of macOS settings.
                with mock.patch.object(urllib.request, "getproxies", return_value={"http": "http://127.0.0.1:1"}), mock.patch.object(urllib.request, "proxy_bypass", return_value=False):
                    environment = Environment(ROOT / "repository" / "baseline", temp)
                    try:
                        environment.start("serve")
                        status, response = environment.request("GET", "/health")
                        self.assertEqual(status, 200)
                        self.assertEqual(response["schema_version"], 2)
                    finally:
                        environment.close()

    def test_readiness_reports_process_exit_and_log(self):
        with tempfile.TemporaryDirectory(prefix="ledger-startup-test-") as temp:
            environment = Environment(ROOT / "repository" / "baseline", temp)
            (environment.repo / "manage.py").write_text("import sys\nprint('startup exploded', flush=True)\nsys.exit(7)\n")
            try:
                with self.assertRaises(AssertionError) as caught:
                    environment.start("serve")
                self.assertIn("exit_code=7", str(caught.exception))
                self.assertIn("startup exploded", str(caught.exception))
            finally:
                environment.close()


if __name__ == "__main__":
    unittest.main()
