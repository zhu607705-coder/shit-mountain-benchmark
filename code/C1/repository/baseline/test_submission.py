"""Baseline-author regression tests. No host judge or expected-answer imports."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import config
import db
import service
import worker


def event(tenant="A", identity="p", amount=4):
    return {"tenant": tenant, "id": identity, "kind": "post", "entries": [["cash", amount], ["equity", -amount]]}


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="candidate-selftest-")
        self.path = Path(self.temp.name) / "test.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_database_path_independent_of_working_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.temp.name)
            self.assertEqual(config.database_path("数据/测试.sqlite3"), (config.BASE_DIR / "数据/测试.sqlite3").resolve())
            self.assertEqual(config.database_path(str(self.path)), self.path.resolve())
        finally:
            os.chdir(previous)

    def test_tenant_request_and_job_read_isolation(self):
        db.initialize(self.path)
        a = service.submit_batch(self.path, "A", "shared", [event("A")])
        b = service.submit_batch(self.path, "B", "shared", [event("B")])
        self.assertNotEqual(a["job_id"], b["job_id"])
        self.assertIsNone(service.get_job(self.path, a["job_id"], "B"))
        self.assertEqual(service.get_job(self.path, a["job_id"], "A")["tenant"], "A")

    def test_bad_batch_does_not_partially_commit(self):
        db.initialize(self.path)
        with self.assertRaises(service.ServiceError) as error:
            service.submit_batch(self.path, "A", "bad", [event("A"), event("B", "foreign")])
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(service.stats(self.path, "A"), {"tenant": "A", "jobs": 0, "done": 0, "event_variants": 0})

    def test_reclaim_abandoned_claim_then_persist_once(self):
        db.initialize(self.path)
        job = service.submit_batch(self.path, "A", "r", [event()])
        with db.connect(self.path) as connection:
            connection.execute("UPDATE jobs SET status='processing',claimed_at=? WHERE id=?", (time.time() - 10, job["job_id"]))
        self.assertTrue(worker.process_once(self.path, .01))
        self.assertFalse(worker.process_once(self.path, .01))
        self.assertEqual(service.state(self.path, "A")["balances"], [["A", "cash", 4], ["A", "equity", -4]])

    def test_legacy_migration_preserves_history_and_identity(self):
        with sqlite3.connect(self.path) as connection:
            connection.executescript("""PRAGMA user_version=1;
              CREATE TABLE events(event_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,payload TEXT NOT NULL);
              CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,tenant TEXT NOT NULL,request_id TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,created_at REAL NOT NULL);""")
            connection.execute("INSERT INTO events VALUES(?,?,?)", ("p", "A", json.dumps(event())))
            connection.execute("INSERT INTO jobs VALUES(1,'A','old',?,'done',?)", (json.dumps([event()]), time.time()))
        db.initialize(self.path)
        with db.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0], "done")
        service.submit_batch(self.path, "B", "old", [event("B")])
        self.assertEqual(service.submit_batch(self.path, "A", "old", [event()])["job_id"], 1)
        self.assertEqual(service.stats(self.path, "A")["event_variants"], 1)


if __name__ == "__main__":
    unittest.main()
