"""SQLite schema, transactions and legacy migration entry point."""
import contextlib
import json
import sqlite3
from pathlib import Path

JOBS = """CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL, request_id TEXT NOT NULL,
  payload TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
  claimed_at REAL, UNIQUE(tenant, request_id))"""
EVENTS = """CREATE TABLE IF NOT EXISTS events(
  tenant TEXT NOT NULL, event_id TEXT NOT NULL, payload TEXT NOT NULL,
  UNIQUE(tenant, event_id, payload))"""


@contextlib.contextmanager
def connect(path):
    connection = sqlite3.connect(str(path), timeout=2.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=2000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def migrate_v1(connection):
    connection.execute("ALTER TABLE jobs RENAME TO jobs_v1")
    connection.execute(JOBS)
    for row in connection.execute("SELECT * FROM jobs_v1").fetchall():
        payload = json.dumps(json.loads(row["payload"]), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        connection.execute("INSERT INTO jobs(id,tenant,request_id,payload,status,created_at,claimed_at) VALUES(?,?,?,?,?,?,NULL)",
                           (row["id"], row["tenant"], row["request_id"], payload, row["status"], row["created_at"]))
    connection.execute("DROP TABLE jobs_v1")
    connection.execute("ALTER TABLE events RENAME TO events_v1")
    connection.execute(EVENTS)
    for row in connection.execute("SELECT * FROM events_v1").fetchall():
        payload = json.dumps(json.loads(row["payload"]), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        connection.execute("INSERT OR IGNORE INTO events(tenant,event_id,payload) VALUES(?,?,?)", (row["tenant"], row["event_id"], payload))
    connection.execute("DROP TABLE events_v1")


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise ValueError(f"Unsupported schema version: {version}")
        if version == 1:
            migrate_v1(connection)
        connection.execute(JOBS)
        connection.execute(EVENTS)
        connection.execute("CREATE TABLE IF NOT EXISTS projections(tenant TEXT PRIMARY KEY, result TEXT NOT NULL, generation INTEGER NOT NULL)")
        connection.execute("PRAGMA user_version=2")
