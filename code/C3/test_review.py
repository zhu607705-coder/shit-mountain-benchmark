"""Independent fault-injection regressions for the adapted conservative baseline."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import baseline


class DurabilityFailureTests(unittest.TestCase):
    def check_acknowledged_followup(self, store, directory):
        acknowledged = False
        try:
            store.commit("after-error", [{"op": "put", "key": "after", "value": "must-survive"}])
            acknowledged = True
        except RuntimeError:
            pass  # Fail-closed is a legal safe recovery policy.
        finally:
            store.close()
        with baseline.Store(directory) as reopened:
            self.assertEqual(reopened.get("stable"), "yes")
            if acknowledged:
                self.assertEqual(reopened.get("after"), "must-survive")

    def test_compaction_post_replace_failure_cannot_ack_to_unlinked_wal(self):
        with tempfile.TemporaryDirectory() as directory:
            store = baseline.Store(directory)
            store.commit("stable", [{"op": "put", "key": "stable", "value": "yes"}])
            with mock.patch.object(baseline, "_syncdir", side_effect=OSError("injected directory fsync failure")):
                with self.assertRaises(OSError):
                    store.compact()
            self.check_acknowledged_followup(store, directory)

    def test_partial_wal_write_failure_cannot_ack_behind_bad_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            store = baseline.Store(directory)
            store.commit("stable", [{"op": "put", "key": "stable", "value": "yes"}])
            def partial(fd, data):
                os.write(fd, data[:10])
                raise OSError("injected short WAL write")
            with mock.patch.object(baseline, "_writeall", side_effect=partial):
                with self.assertRaises(OSError):
                    store.commit("partial", [{"op": "put", "key": "unstable", "value": "x" * 2048}])
            self.check_acknowledged_followup(store, directory)

    def test_open_handle_path_survives_cwd_change(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                store = baseline.Store("数据库 空格")
                store.commit("x", [{"op": "put", "key": "stable", "value": "yes"}])
                Path("elsewhere").mkdir()
                os.chdir("elsewhere")
                try:
                    store.compact()
                    self.assertEqual(store.get("stable"), "yes")
                finally:
                    store.close()
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
