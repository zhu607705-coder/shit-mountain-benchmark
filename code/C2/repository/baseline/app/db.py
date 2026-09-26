"""Versioned durable state shared by HTTP and worker processes."""
import json,sqlite3,time


class Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()


def connect(config):
    conn=sqlite3.connect(str(config['database']),timeout=8,isolation_level=None,factory=Connection)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=8000')
    return conn


def initialize(config):
    config['database'].parent.mkdir(parents=True,exist_ok=True)
    c=connect(config)
    try:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('BEGIN IMMEDIATE')
        c.execute("CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, graph TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,target TEXT NOT NULL,status TEXT NOT NULL,payload TEXT,result TEXT,error TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL,FOREIGN KEY(project_id) REFERENCES projects(id))")
        pcols={r['name'] for r in c.execute('PRAGMA table_info(projects)')}
        jcols={r['name'] for r in c.execute('PRAGMA table_info(jobs)')}
        if 'revision' not in pcols:c.execute('ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
        if 'payload' not in jcols:c.execute('ALTER TABLE jobs ADD COLUMN payload TEXT')
        if 'cancel_requested' not in jcols:c.execute('ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0')
        c.execute('UPDATE jobs SET payload=(SELECT graph FROM projects WHERE id=jobs.project_id) WHERE payload IS NULL')
        c.execute('CREATE INDEX IF NOT EXISTS jobs_by_status ON jobs(status,created)')
        c.execute('PRAGMA user_version=2')
        c.execute('COMMIT')
    except Exception:
        if c.in_transaction:c.execute('ROLLBACK')
        raise
    finally:c.close()


def recover(config):
    with connect(config) as c:
        c.execute("UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'pending' END,updated=? WHERE status='running'",(time.time(),))
