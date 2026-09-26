"""Durable batch acceptance and read models consumed by the HTTP layer."""
import json
import time
from db import connect


class ServiceError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def validate_batch(tenant, request_id, events):
    if not isinstance(tenant, str) or not tenant or not isinstance(request_id, str) or not request_id:
        raise ServiceError(400, "BAD_BATCH")
    if not isinstance(events, list) or len(events) > 200:
        raise ServiceError(400, "BAD_BATCH")
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"] or not isinstance(event.get("kind"), str):
            raise ServiceError(400, "BAD_EVENT_ENVELOPE")
        if event.get("tenant") != tenant:
            raise ServiceError(400, "TENANT_MISMATCH")


def submit_batch(path, tenant, request_id, events):
    validate_batch(tenant, request_id, events)
    payload = canonical(events)
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute("SELECT id,payload FROM jobs WHERE request_id=?", (request_id,)).fetchone()
        if previous is not None:
            if previous["payload"] != payload:
                raise ServiceError(409, "REQUEST_CONFLICT")
            return {"job_id": previous["id"], "duplicate": True}
        cursor = connection.execute("INSERT INTO jobs(tenant,request_id,payload,status,created_at) VALUES(?,?,?,'pending',?)",
                                    (tenant, request_id, payload, time.time()))
        for event in events:
            connection.execute("INSERT OR IGNORE INTO events(tenant,event_id,payload) VALUES(?,?,?)",
                               (tenant, event["id"], canonical(event)))
        return {"job_id": cursor.lastrowid, "duplicate": False}


def get_job(path, identity, tenant):
    with connect(path) as connection:
        row = connection.execute("SELECT id,tenant,request_id,status FROM jobs WHERE id=? AND tenant=?", (identity, tenant)).fetchone()
        return dict(row) if row else None


def list_jobs(path, tenant):
    with connect(path) as connection:
        return {"jobs": [dict(row) for row in connection.execute("SELECT id,tenant,request_id,status FROM jobs WHERE tenant=? ORDER BY id", (tenant,))]}


def state(path, tenant):
    with connect(path) as connection:
        row = connection.execute("SELECT result,generation FROM projections WHERE tenant=?", (tenant,)).fetchone()
    return {"tenant": tenant, "generation": row["generation"] if row else 0,
            **(json.loads(row["result"]) if row else {"balances": [], "statuses": []})}


def stats(path, tenant):
    with connect(path) as connection:
        jobs = connection.execute("SELECT COUNT(*),COALESCE(SUM(status='done'),0) FROM jobs WHERE tenant=?", (tenant,)).fetchone()
        variants = connection.execute("SELECT COUNT(*) FROM events WHERE tenant=?", (tenant,)).fetchone()[0]
        return {"tenant": tenant, "jobs": jobs[0], "done": jobs[1], "event_variants": variants}
