"""Resolve paths relative to the configuration file, not process working directory."""
import json
from pathlib import Path


def load(path):
    source=Path(path).resolve()
    raw=json.loads(source.read_text())
    db=Path(raw.get('database','state/service.sqlite3'))
    if not db.is_absolute(): db=Path.cwd()/db
    prefix=raw.get('api_prefix','').rstrip('/')
    if prefix and not prefix.startswith('/'):raise ValueError('base_path must start with /')
    return dict(database=db.resolve(),base_path=prefix,host='127.0.0.1',port=int(raw.get('port',0)),job_delay=float(raw.get('job_delay',0.10)))
