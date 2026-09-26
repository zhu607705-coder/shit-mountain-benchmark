"""Environment configuration shared by the API and independent worker process."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def database_path(value):
    raw = Path(value).expanduser()
    return (raw if raw.is_absolute() else BASE_DIR / raw).resolve()


def settings():
    return {"db": database_path(os.environ.get("LEDGER_DB", "runtime/ledger.sqlite3")),
            "host": os.environ.get("LEDGER_HOST", "127.0.0.1"),
            "port": int(os.environ.get("LEDGER_PORT", "8000")),
            "poll": float(os.environ.get("LEDGER_WORKER_POLL", "0.05")),
            "lease": float(os.environ.get("LEDGER_LEASE_SECONDS", "2")),
            "delay": float(os.environ.get("LEDGER_WORKER_DELAY", "0"))}
