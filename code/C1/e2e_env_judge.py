#!/usr/bin/env python3
"""Real HTTP + SQLite + worker matrix. Trusted submissions only; no sandbox."""
import argparse
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def post_event(tenant, identity, amount):
    return {"tenant": tenant, "id": identity, "kind": "post",
            "entries": [["cash", amount], ["equity", -amount]]}


class Environment:
    def __init__(self, submission, directory, relative=False, legacy=False):
        self.root = Path(directory)
        self.repo = self.root / "仓库 空格"
        shutil.copytree(submission, self.repo, ignore=shutil.ignore_patterns("__pycache__"))
        self.db = self.repo / "数据" / "账本.sqlite3" if relative else self.root / "state.sqlite3"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        if legacy:
            make_legacy(self.db)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", LEDGER_DB="数据/账本.sqlite3" if relative else str(self.db),
                        LEDGER_PORT=str(self.port), LEDGER_HOST="127.0.0.1", LEDGER_WORKER_POLL="0.015",
                        LEDGER_LEASE_SECONDS="0.12", LEDGER_WORKER_DELAY="0")
        self.processes, self.logs = [], []
        self.relative = relative

    def start(self, role, delay="0"):
        cwd = self.root / ("别处 api" if role == "serve" else "别处 worker") if self.relative else self.repo
        cwd.mkdir(exist_ok=True)
        log = self.root / f"{role}-{len(self.logs)}.log"
        handle = log.open("w")
        process = subprocess.Popen([sys.executable, str(self.repo / "manage.py"), role], cwd=cwd,
                                   env=dict(self.env, LEDGER_WORKER_DELAY=delay), stdout=handle, stderr=subprocess.STDOUT)
        handle.close()
        self.processes.append(process)
        self.logs.append(log)
        if role == "serve":
            self.until(lambda: self.request("GET", "/health")[0] == 200, timeout=1.2)
        return process

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=.4) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def until(self, predicate, timeout=1.2):
        deadline, last = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except (OSError, urllib.error.URLError, TimeoutError, KeyError) as exc:
                last = str(exc)
            time.sleep(.015)
        raise AssertionError(f"deadline exceeded: {last or 'condition false'}")

    def submit(self, tenant, request_id, events, expected=202):
        status, body = self.request("POST", "/v1/batches", {"tenant": tenant, "request_id": request_id, "events": events})
        assert status == expected, ("submit", status, body)
        return body

    def done(self, tenant, identity):
        path = f"/v1/jobs/{identity}?tenant={tenant}"
        self.until(lambda: self.request("GET", path)[1].get("status") == "done")

    def state(self, tenant):
        status, state = self.request("GET", f"/v1/tenants/{tenant}/state")
        assert status == 200, (status, state)
        return state

    def stop(self, process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=.4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=.4)

    def close(self):
        for process in self.processes:
            self.stop(process)

    def tail(self):
        return {log.name: log.read_text(errors="replace")[-1800:] for log in self.logs if log.exists()}


def make_legacy(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
      PRAGMA user_version=1;
      CREATE TABLE events(event_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL,
        request_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
    """)
    event = post_event("A", "legacy", 7)
    payload = json.dumps([event])  # v1 retained display-oriented JSON whitespace.
    connection.execute("INSERT INTO events VALUES(?,?,?)", ("legacy", "A", json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
    connection.execute("INSERT INTO jobs VALUES(1,?,?,?,?,?)", ("A", "old", payload, "done", time.time()))
    connection.commit()
    connection.close()


def default_flow(env):
    env.start("serve"); env.start("worker")
    health = env.request("GET", "/health")[1]
    assert health["schema_version"] == 2
    job = env.submit("A", "first", [post_event("A", "p", 10)])
    env.done("A", job["job_id"])
    state = env.state("A")
    assert state["balances"] == [["A", "cash", 10], ["A", "equity", -10]], state
    status, listing = env.request("GET", "/v1/jobs?tenant=A")
    assert status == 200 and len(listing["jobs"]) == 1 and listing["jobs"][0]["status"] == "done"
    status, stats = env.request("GET", "/v1/stats?tenant=A")
    assert status == 200 and stats == {"tenant": "A", "jobs": 1, "done": 1, "event_variants": 1}, stats
    assert env.request("GET", f"/v1/jobs/{job['job_id']}?tenant=B")[0] == 404
    env.submit("A", "bad", [post_event("B", "leak", 9)], expected=400)
    env.submit("A", "first", [post_event("A", "different", 8)], expected=409)


def legacy_schema(env):
    env.start("serve"); env.start("worker")
    assert env.request("GET", "/health")[1]["schema_version"] == 2
    job = env.submit("A", "new", [post_event("A", "new", 3)])
    env.done("A", job["job_id"])
    assert env.state("A")["balances"] == [["A", "cash", 10], ["A", "equity", -10]]
    assert env.request("GET", "/v1/jobs/1?tenant=A")[1]["status"] == "done"
    assert env.submit("A", "old", [post_event("A", "legacy", 7)])["job_id"] == 1
    other = env.submit("B", "old", [post_event("B", "legacy", 5)])
    env.done("B", other["job_id"])
    assert env.state("B")["balances"] == [["B", "cash", 5], ["B", "equity", -5]]


def unicode_workdir(env):
    default_flow(env)
    assert env.db.exists()


def interrupted_worker(env):
    env.start("serve")
    worker = env.start("worker", delay="0.65")
    job = env.submit("A", "recover", [post_event("A", "p", 12)])
    env.until(lambda: env.request("GET", f"/v1/jobs/{job['job_id']}?tenant=A")[1]["status"] == "processing")
    worker.kill(); worker.wait(timeout=.4)
    env.start("worker")
    env.done("A", job["job_id"])
    assert env.state("A")["balances"] == [["A", "cash", 12], ["A", "equity", -12]]


def duplicates_reordering(env):
    env.start("serve"); env.start("worker")
    reverse = {"tenant": "A", "id": "r", "kind": "reverse", "target": "p"}
    first = env.submit("A", "r", [reverse]); env.done("A", first["job_id"])
    second = env.submit("A", "p", [post_event("A", "p", 17)])
    assert env.submit("A", "p", [post_event("A", "p", 17)])["job_id"] == second["job_id"]
    env.done("A", second["job_id"])
    assert env.state("A")["balances"] == []
    last = env.submit("A", "conflict", [post_event("A", "p", 18)]); env.done("A", last["job_id"])
    state = env.state("A")
    assert state["balances"] == [] and state["statuses"] == [["A", "p", "CONFLICT"], ["A", "r", "ORPHAN"]], state


def concurrent_isolation(env):
    env.start("serve"); env.start("worker"); env.start("worker")
    def send(pair):
        tenant, index = pair
        return tenant, env.submit(tenant, f"same-{index}", [post_event(tenant, f"p{index}", 2 if tenant == "A" else 7)])["job_id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(send, [(tenant, index) for tenant in ["A", "B"] for index in range(6)]))
    for tenant, job_id in jobs:
        env.done(tenant, job_id)
    for tenant, amount in [("A", 12), ("B", 42)]:
        assert env.state(tenant)["balances"] == [[tenant, "cash", amount], [tenant, "equity", -amount]]
        assert env.request("GET", f"/v1/stats?tenant={tenant}")[1]["jobs"] == 6


def restart_persistence(env):
    env.start("serve"); env.start("worker")
    job = env.submit("A", "stable", [post_event("A", "p", 31)]); env.done("A", job["job_id"])
    before = env.state("A")
    env.close()
    env.start("serve"); env.start("worker")
    assert env.state("A") == before
    assert env.submit("A", "stable", [post_event("A", "p", 31)])["job_id"] == job["job_id"]
    assert env.request("GET", "/v1/stats?tenant=A")[1]["jobs"] == 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", default="repository/baseline")
    parser.add_argument("--output")
    args = parser.parse_args()
    submission = (ROOT / args.submission).resolve()
    cases = [default_flow, legacy_schema, unicode_workdir, interrupted_worker,
             duplicates_reordering, concurrent_isolation, restart_persistence]
    reports, started = [], time.perf_counter()
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="ledger-e2e-") as temp:
            env = Environment(submission, temp, relative=case is unicode_workdir, legacy=case is legacy_schema)
            error = None
            try:
                case(env)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            finally:
                env.close()
            reports.append({"name": case.__name__, "passed": error is None,
                            **({"error": error, "logs": env.tail()} if error else {})})
    core = subprocess.run([sys.executable, str(ROOT / "judge.py"), "--submission", str(submission)],
                          text=True, capture_output=True, timeout=5)
    core_result = json.loads(core.stdout) if core.returncode == 0 else {"correctness": {"rate": 0}, "error": core.stderr[-1000:]}
    selftests = subprocess.run([sys.executable, str(ROOT / "selftest_mutation_judge.py"), "--submission", str(submission)],
                              text=True, capture_output=True, timeout=6)
    selftest_result = json.loads(selftests.stdout) if selftests.returncode == 0 else {"selftest_score": 0, "error": selftests.stderr[-1000:]}
    count = sum(item["passed"] for item in reports)
    core_score = 20 * core_result["correctness"]["rate"]
    score = 10 * count + core_score + selftest_result["selftest_score"]
    critical = ["default_flow", "concurrent_isolation", "restart_persistence"]
    digest = hashlib.sha256()
    for source in ["e2e_env_judge.py", "selftest_mutation_judge.py", "judge.py", "oracle.py", "cases.py", "fixtures/public.json"]:
        digest.update(source.encode()); digest.update((ROOT / source).read_bytes())
    result = {"benchmark": "C1_repository", "version": "0.2.0", "submission": args.submission,
              "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "suite_sha256": digest.hexdigest(), "submission_sha256": core_result.get("submission_sha256"),
              "valid": all(item["passed"] for item in reports if item["name"] in critical),
              "raw_score": round(score, 6), "environment_score": 10 * count,
              "environment_passed": count, "environment_total": len(cases), "core_score": core_score,
              "selftest_score": selftest_result["selftest_score"], "critical_case_names": critical,
              "environment_matrix": reports, "core_correctness": core_result["correctness"],
              "selftest_assessment": selftest_result, "wall_seconds": time.perf_counter() - started,
              "security": "real local processes and temporary SQLite; trusted code only, not a sandbox"}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        (ROOT / args.output).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
