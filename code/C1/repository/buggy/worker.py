"""Durable queue consumer. Claim and completion are separate transactions."""
import json
import time
import traceback
from db import connect
from engine import solve


def claim_job(path, lease):
    now = time.time()
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        connection.execute("UPDATE jobs SET status='processing',claimed_at=? WHERE id=?", (now, row["id"]))
        return {**dict(row), "claimed_at": now}


def process_once(path, lease, delay=0):
    job = claim_job(path, lease)
    if job is None:
        return False
    if delay:
        time.sleep(delay)
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute("SELECT status,claimed_at FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if current["status"] != "processing" or current["claimed_at"] != job["claimed_at"]:
            return False
        events = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM events WHERE tenant=? ORDER BY rowid", (job["tenant"],))]
        result = solve(events)
        connection.execute("INSERT INTO projections(tenant,result,generation) VALUES(?,?,?) ON CONFLICT(tenant) DO UPDATE SET result=excluded.result,generation=MAX(projections.generation,excluded.generation)",
                           (job["tenant"], json.dumps(result, ensure_ascii=False), job["id"]))
        connection.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))
    return True


def run(settings):
    while True:
        try:
            if not process_once(settings["db"], settings["lease"], settings["delay"]):
                time.sleep(settings["poll"])
        except Exception:
            traceback.print_exc()
            time.sleep(settings["poll"])
