#!/usr/bin/env python3
"""Dependency-free model API and inert submission adapters. No agent shell runner."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib import request, error, parse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TASKS = {**{t: 'reasoning' for t in ('R1', 'R2')}, **{t: 'code' for t in ('C1', 'C2')}, **{t: 'frontend' for t in ('F1', 'F2')}}
POLICY_TASKS = {'R3', 'R4'}
SPECIALIST_CODE_TASKS = {'C3', 'C4'}
TASKS.update({task: track for track, prefix in [('reasoning', 'R'), ('code', 'C'), ('frontend', 'F')] for task in (prefix + '3', prefix + '4')})
MAX_FILES, MAX_FILE, MAX_TOTAL = 2000, 16 * 1024**2, 64 * 1024**2
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
ENV = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON object key')
        out[key] = value
    return out


def read_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON number')))


def strict_json(text):
    """Accept a JSON object or one complete JSON fence; reject prose and trailing data."""
    text = text.strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', text, re.S)
        if not match:
            raise ValueError('response must contain exactly one JSON object')
        text = match.group(1)
    value = read_json(text)
    if not isinstance(value, dict):
        raise ValueError('response JSON root must be an object')
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')


def validate_config(value):
    allowed = {'alias', 'base_url', 'model', 'api_key_env', 'timeout', 'max_tokens', 'temperature'}
    required = {'alias', 'base_url', 'model', 'api_key_env'}
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - allowed:
        raise ValueError('config must use alias/base_url/model/api_key_env; literal secrets and unknown fields are rejected')
    if not isinstance(value['alias'], str) or not NAME.fullmatch(value['alias']):
        raise ValueError('invalid alias')
    if not isinstance(value['api_key_env'], str) or not ENV.fullmatch(value['api_key_env']):
        raise ValueError('api_key_env must be an environment variable name, never its value')
    if not isinstance(value['model'], str) or not value['model'].strip():
        raise ValueError('model is required')
    url = parse.urlsplit(value['base_url'])
    if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('base_url must be HTTP(S), without credentials, query or fragment')
    if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('unencrypted HTTP is allowed only for local mock endpoints')
    config = dict(value)
    config.setdefault('timeout', 120)
    config.setdefault('max_tokens', 16384)
    config.setdefault('temperature', 0)
    for name, low, high in [('timeout', 1, 600), ('max_tokens', 1, 200000), ('temperature', 0, 2)]:
        x = config[name]
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not low <= x <= high:
            raise ValueError('invalid numeric config option: ' + name)
    if not isinstance(config['max_tokens'], int):
        raise ValueError('max_tokens must be an integer')
    secret = os.environ.get(config['api_key_env'])
    if secret and secret in json.dumps(config):
        raise ValueError('config contains the active credential; refusing to inspect or save it')
    return config


def load_config(path):
    return validate_config(read_json(Path(path).read_text(encoding='utf-8')))


def completion(config, messages):
    """One Chat Completions call, no automatic retry or tool execution."""
    config = validate_config(config)
    secret = os.environ.get(config['api_key_env'])
    if not secret:
        raise ValueError('missing API key environment variable: ' + config['api_key_env'])
    url = config['base_url'].rstrip('/') + '/chat/completions'
    payload = json.dumps({'model': config['model'], 'messages': messages,
                          'max_tokens': config['max_tokens'], 'temperature': config['temperature'],
                          'stream': False}, ensure_ascii=False).encode()
    req = request.Request(url, data=payload, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + secret}, method='POST')
    # Do not follow redirects carrying Authorization to another host.
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=config['timeout']) as response:
            body = response.read(MAX_FILE + 1)
    except error.HTTPError as exc:
        raise ValueError(f'API returned HTTP {exc.code}; response body omitted') from None
    except (error.URLError, TimeoutError, OSError):
        raise ValueError('API connection failed; no response body or credentials logged') from None
    if len(body) > MAX_FILE:
        raise ValueError('API response exceeds size limit')
    # A provider echoing credentials must not make those credentials enter artifacts.
    if secret.encode() in body:
        raise ValueError('API response contains the supplied credential; refusing to save it')
    try:
        decoded = read_json(body.decode('utf-8'))
        if secret in json.dumps(decoded, ensure_ascii=False):
            raise ValueError('API response contains the supplied credential; refusing to save it')
        choice = decoded['choices'][0]
        if choice.get('finish_reason') not in ('stop', None):
            raise ValueError('completion was truncated or requested a tool')
        content = choice['message']['content']
        if not isinstance(content, str):
            raise ValueError('only plain-text assistant content is supported')
        submission = strict_json(content)
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('API response does not contain a valid JSON assistant message') from None
    return submission, {'model': decoded.get('model', config['model']), 'usage': decoded.get('usage'), 'finish_reason': choice.get('finish_reason')}


def safe_relative(name):
    if not isinstance(name, str) or '\\' in name or '\x00' in name or ':' in name:
        raise ValueError('unsafe archive member path')
    raw = name.rstrip('/')
    parts = raw.split('/')
    p = PurePosixPath(raw)
    if not raw or p.is_absolute() or any(x in ('', '.', '..') for x in parts):
        raise ValueError('unsafe archive member path')
    return p


def checked_bytes(data, name):
    if len(data) > MAX_FILE:
        raise ValueError('individual file exceeds size limit: ' + name)
    return data


def bounded_read(path):
    if path.stat().st_size > MAX_FILE:
        raise ValueError('source file exceeds size limit')
    with path.open('rb') as stream:
        return checked_bytes(stream.read(MAX_FILE + 1), path.name)


def source_files(source):
    """Read and validate all files before any destination is created."""
    source = Path(source)
    ensure_plain_parents(source)
    if source.is_symlink():
        raise ValueError('source symlinks are not accepted')
    files = {}
    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES:
                raise ValueError('too many archive members')
            total = 0
            seen = set()
            for info in members:
                path = safe_relative(info.filename)
                name = str(path)
                if name in seen:
                    raise ValueError('duplicate archive member')
                seen.add(name)
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or stat.S_ISLNK(mode):
                    raise ValueError('symlink or special archive member rejected')
                if info.flag_bits & 1:
                    raise ValueError('encrypted archive rejected')
                if info.is_dir():
                    continue
                total += info.file_size
                if info.file_size > MAX_FILE or total > MAX_TOTAL:
                    raise ValueError('archive expands beyond size budget')
                if info.file_size > 1024**2 and info.file_size > max(1, info.compress_size) * 200:
                    raise ValueError('archive compression ratio exceeds limit')
                with archive.open(info) as stream:
                    blob = stream.read(min(MAX_FILE, info.file_size) + 1)
                if len(blob) != info.file_size:
                    raise ValueError('archive size metadata mismatch')
                files[name] = checked_bytes(blob, name)
    elif source.is_dir():
        total = 0
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('directory symlinks are not accepted')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('special file rejected')
            name = str(safe_relative(path.relative_to(source).as_posix()))
            size = path.stat().st_size
            total += size
            if size > MAX_FILE or total > MAX_TOTAL or len(files) >= MAX_FILES:
                raise ValueError('directory exceeds file/size budget')
            files[name] = bounded_read(path)
    elif source.is_file():
        files[str(safe_relative(source.name))] = bounded_read(source)
    else:
        raise ValueError('source must be a regular file, directory or ZIP')
    if not files:
        raise ValueError('submission is empty')
    if '.submission-source.json' in files:
        raise ValueError('reserved metadata filename')
    return files


def ensure_plain_parents(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('destination contains a symlink')


def save_bundle(files, target, metadata):
    """Stage in same filesystem and atomically rename; never merge or overwrite."""
    target = Path(target)
    ensure_plain_parents(target)
    if target.exists():
        raise ValueError('destination already exists; use a new alias or export path')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.submission-stage-', dir=target.parent))
    try:
        for name, content in files.items():
            out = staging.joinpath(*safe_relative(name).parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(content)
        metadata_name = '.task-export.json' if metadata.get('source_type') == 'public-task-export' else '.submission-source.json'
        write_json(staging / metadata_name, metadata)
        if target.exists():
            raise ValueError('destination appeared during import; refusing overwrite')
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def task_files(task):
    if task in POLICY_TASKS | SPECIALIST_CODE_TASKS | {'F3', 'F4'}:
        track = TASKS[task]
        folder = ROOT / track / task
        public_prompt = folder / 'PUBLIC_TASK.md'
        if not public_prompt.exists():
            raise ValueError('public contract has not completed adaptation review')
        files = {'PROMPT.md': public_prompt.read_bytes()}
        if track == 'reasoning':
            files['submission.py'] = (folder / 'submission.py').read_bytes()
            for path in folder.glob('public_*.json'):
                files[path.name] = path.read_bytes()
        elif track == 'frontend':
            files['starter.html'] = (folder / 'starter.html').read_bytes()
        else:
            for path in sorted((folder / 'starter').rglob('*')):
                if path.is_symlink():
                    raise ValueError('export source contains symlink')
                if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                    files['starter/' + path.relative_to(folder / 'starter').as_posix()] = path.read_bytes()
        return files
    folder = ROOT / TASKS[task] / task
    files = {'PROMPT.md': (folder / 'PROMPT.md').read_bytes()}
    if task.startswith('R'):
        files['input.json'] = (folder / 'input.json').read_bytes()
    elif task.startswith('F'):
        for name in ('data.json', 'starter.html'):
            files[name] = (folder / name).read_bytes()
    else:
        for name in ('INCIDENT.md', 'CORE_CONTRACT.md', 'fixtures/public.json'):
            if (folder / name).exists():
                files[name] = (folder / name).read_bytes()
        repository = folder / 'repository' / 'buggy'
        for path in sorted(repository.rglob('*')):
            if path.is_symlink():
                raise ValueError('export source contains symlink')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo'):
                files['repository/buggy/' + path.relative_to(repository).as_posix()] = path.read_bytes()
    return files


def normalize_result(task, raw, alias=None):
    if not isinstance(raw, dict):
        raise ValueError('result must be a JSON object')
    score = raw.get('raw_score', raw.get('score'))
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0):
        raise ValueError('result score must be a finite nonnegative number or null')
    valid = raw.get('valid')
    if valid is not None and not isinstance(valid, bool):
        raise ValueError('valid must be true, false or null')
    return {'task_id': task, 'model': alias or raw.get('model') or raw.get('alias'), 'alias': alias, 'valid': valid, 'raw_score': score,
            'machine_score': raw.get('machine_score'), 'human_visual_score': raw.get('human_visual_score'),
            'metrics': raw.get('metrics', {}), 'source_result': raw}


def run_reasoning(task, config, submissions_dir):
    if task not in ('R1', 'R2'):
        raise ValueError('single-completion runner supports reasoning tasks only')
    target = Path(submissions_dir) / config['alias'] / task
    if target.exists():
        raise ValueError('submission already exists')
    public = task_files(task)
    prompt = public['PROMPT.md'].decode() + '\n\n## Complete input.json\n' + public['input.json'].decode()
    result, usage = completion(config, [{'role': 'system', 'content': 'Solve the benchmark task. Output exactly one JSON object matching its submission contract. Do not output prose or tool calls.'}, {'role': 'user', 'content': prompt}])
    metadata = {'task_id': task, 'alias': config['alias'], 'source_type': 'chat-completions', 'created_at': stamp(), 'config': config, 'api_metadata': usage, 'input_sha256': hashlib.sha256(public['input.json']).hexdigest()}
    save_bundle({'submission.json': (json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()}, target, metadata)
    task_dir = ROOT / 'reasoning' / task
    env = dict(os.environ)
    env.pop(config['api_key_env'], None)
    judged = subprocess.run([sys.executable, str(task_dir / 'judge.py'), '--input', str(task_dir / 'input.json'), '--submission', str(target / 'submission.json')], capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
    if judged.returncode:
        raise ValueError('local judge failed; submission retained for inspection')
    normalized = normalize_result(task, read_json(judged.stdout), config['alias'])
    write_json(target / 'result.json', normalized)
    return {'submission_dir': str(target), 'result': normalized}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('inspect'); c.add_argument('--config', required=True)
    c = commands.add_parser('import-config'); c.add_argument('--source', required=True); c.add_argument('--output', required=True)
    c = commands.add_parser('run-reasoning'); c.add_argument('--task', choices=['R1', 'R2'], required=True); c.add_argument('--config', required=True); c.add_argument('--submissions-dir', default=str(ROOT / 'submissions'))
    c = commands.add_parser('export-task'); c.add_argument('--task', choices=TASKS, required=True); c.add_argument('--output', required=True)
    c = commands.add_parser('import-submission'); c.add_argument('--task', choices=TASKS, required=True); c.add_argument('--alias', required=True); c.add_argument('--source', required=True); c.add_argument('--submissions-dir', default=str(ROOT / 'submissions'))
    c = commands.add_parser('normalize-result'); c.add_argument('--task', choices=TASKS, required=True); c.add_argument('--source', required=True); c.add_argument('--output', required=True); c.add_argument('--alias')
    args = parser.parse_args(argv)
    if args.command == 'inspect':
        config = load_config(args.config)
        out = {'config': config, 'api_key_present': bool(os.environ.get(config['api_key_env'])), 'network_called': False}
    elif args.command == 'import-config':
        config = load_config(args.source)
        output = Path(args.output); ensure_plain_parents(output)
        if output.exists():
            raise ValueError('config output already exists')
        output.parent.mkdir(parents=True, exist_ok=True); write_json(output, config)
        out = {'config_path': str(output), 'secrets_written': False}
    elif args.command == 'run-reasoning':
        out = run_reasoning(args.task, load_config(args.config), args.submissions_dir)
    elif args.command == 'export-task':
        files = task_files(args.task)
        files['EXPORT_README.md'] = ('# Public task workspace\n\n'
            'Start with PROMPT.md. C1/C2 preserve repository/buggy/ as the documented source repository; copy it to your working submission before editing. '
            'C3/C4 expose starter/, R3/R4 expose submission.py, and frontend tasks expose starter.html. '
            'Organizer judge.py/e2e_env_judge.py commands mentioned in the contract describe organizer acceptance and are not bundled here. '
            'Write and run your own self-tests in this workspace, then return the finished submission and test report. '
            'No reference implementation, grader internals, or expected answers are included.\n').encode()
        target = Path(args.output); ensure_plain_parents(target)
        if target.exists():
            raise ValueError('export destination already exists')
        metadata = {'task_id': args.task, 'source_type': 'public-task-export', 'created_at': stamp(), 'excluded': ['baseline', 'oracle', 'expected_outputs', 'judge_internals']}
        if target.suffix.lower() == '.zip':
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as z:
                for name, content in files.items():
                    z.writestr(name, content)
                z.writestr('.task-export.json', json.dumps(metadata))
        else:
            save_bundle(files, target, metadata)
        out = {'export_path': str(target), 'files': len(files), 'model_solution_included': False}
    elif args.command == 'import-submission':
        if not NAME.fullmatch(args.alias):
            raise ValueError('invalid alias')
        files = source_files(args.source)
        target = Path(args.submissions_dir) / args.alias / args.task
        metadata = {'task_id': args.task, 'alias': args.alias, 'source_type': 'inert-import', 'source_name': Path(args.source).name, 'created_at': stamp(), 'executed': False,
                    'files': {name: {'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()} for name, blob in files.items()}}
        save_bundle(files, target, metadata)
        out = {'submission_dir': str(target), 'files': len(files), 'executed': False}
    else:
        output = Path(args.output); ensure_plain_parents(output)
        if output.exists():
            raise ValueError('result output already exists')
        out = normalize_result(args.task, read_json(Path(args.source).read_text()), args.alias)
        output.parent.mkdir(parents=True, exist_ok=True); write_json(output, out)
    print(json.dumps(out, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
