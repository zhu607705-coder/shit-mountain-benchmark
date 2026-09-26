#!/usr/bin/env python3
"""Run submission-authored unittest tests, then five public behavioral mutants."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile

BOOTSTRAP = r'''
import json, os, pathlib, sys, unittest
root=pathlib.Path(sys.argv[1]); mutant=sys.argv[2]
sys.path.insert(0,str(root)); os.chdir(root)
import config, db, service, worker
if mutant == "tenant_job_leak":
    original=service.get_job
    def leaking(path, identity, tenant):
        with db.connect(path) as c:
            row=c.execute("SELECT tenant FROM jobs WHERE id=?",(identity,)).fetchone()
        return original(path,identity,row[0] if row else tenant)
    service.get_job=leaking
elif mutant == "cwd_dependent_path":
    config.database_path=lambda value: pathlib.Path(value).resolve()
elif mutant == "abandoned_job_never_reclaimed":
    original=worker.claim_job
    worker.claim_job=lambda path, lease: original(path,10**12)
elif mutant == "mixed_tenant_batch_accepted":
    original=service.validate_batch
    def permit(tenant, request_id, events):
        return None
    service.validate_batch=permit
elif mutant == "migration_drops_history":
    original=db.initialize
    def dropping(path):
        import sqlite3
        with sqlite3.connect(path) as c:
            old=c.execute("PRAGMA user_version").fetchone()[0]
        original(path)
        if old == 1:
            with db.connect(path) as c:
                c.execute("DELETE FROM events"); c.commit()
    db.initialize=dropping
suite=unittest.defaultTestLoader.discover(str(root),pattern="test_submission.py")
count=suite.countTestCases()
result=unittest.TextTestRunner(stream=sys.stderr,verbosity=1).run(suite)
print(json.dumps({"tests":count,"passed":result.wasSuccessful() and count>0,"failures":len(result.failures),"errors":len(result.errors)}))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    args = parser.parse_args()
    path = Path(args.submission).resolve()
    mutations = ["tenant_job_leak", "cwd_dependent_path", "abandoned_job_never_reclaimed",
                 "mixed_tenant_batch_accepted", "migration_drops_history"]
    reports = []
    for name in ["clean"] + mutations:
        try:
            with tempfile.TemporaryDirectory(prefix="ledger-mutation-") as temp:
                isolated = Path(temp) / "submission"
                shutil.copytree(path, isolated, ignore=shutil.ignore_patterns("__pycache__", "*.sqlite3*"))
                process = subprocess.run([sys.executable, "-B", "-c", BOOTSTRAP, str(isolated), name],
                                         capture_output=True, text=True, timeout=.9)
            result = json.loads(process.stdout) if process.returncode == 0 else {"passed": False, "bootstrap_error": process.stderr[-1000:]}
        except Exception as exc:
            result = {"passed": False, "bootstrap_error": str(exc)}
        reports.append({"name": name, **result})
    clean = reports[0]["passed"]
    killed = [row["name"] for row in reports[1:] if not row["passed"] and "bootstrap_error" not in row]
    print(json.dumps({"selftest_score": 2 * len(killed) if clean else 0, "clean_passed": clean,
                      "mutants_killed": killed if clean else [], "mutants_total": len(mutations),
                      "test_origin": "test_submission.py inside the submitted repository; not host-supplied tests",
                      "reports": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
