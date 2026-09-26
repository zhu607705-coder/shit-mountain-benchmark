"""No provider account required. Uses a loopback HTTP mock and temporary files."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('integration_cli', Path(__file__).with_name('cli.py'))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.key = 'mock-credential-never-saved-86473'
        self.cfg = {'alias': 'mock-model', 'base_url': 'http://127.0.0.1:1/v1', 'model': 'mock-test', 'api_key_env': 'INTEGRATION_TEST_KEY'}

    def zip_with(self, name, data=b'x', mode=None):
        path = self.root / 'input.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            info = zipfile.ZipInfo(name)
            if mode:
                info.external_attr = mode << 16
            z.writestr(info, data)
        return path

    def test_reject_paths_and_symlink(self):
        for name in ['../outside', '/tmp/outside', 'C:/outside', 'x\\..\\outside', 'a/../../b', './a']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                cli.source_files(self.zip_with(name))
        with self.assertRaises(ValueError):
            cli.source_files(self.zip_with('link', b'/tmp', stat.S_IFLNK | 0o777))
        directory = self.root / 'tree'; directory.mkdir()
        (directory / 'link').symlink_to('/tmp')
        with self.assertRaises(ValueError):
            cli.source_files(directory)

    def test_reject_bomb_and_duplicates(self):
        path = self.root / 'bomb.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('bomb', b'0' * (2 * 1024**2))
        with self.assertRaises(ValueError):
            cli.source_files(path)
        with patch.object(cli, 'MAX_TOTAL', 2), self.assertRaises(ValueError):
            cli.source_files(self.zip_with('large', b'four'))
        path = self.root / 'duplicate.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('same', b'one'); z.writestr('same', b'two')
        with self.assertRaises(ValueError):
            cli.source_files(path)

    def test_inert_import_and_no_overwrite(self):
        archive = self.zip_with('app/main.py', b'raise RuntimeError("must not execute")')
        files = cli.source_files(archive)
        target = self.root / 'submissions' / 'model' / 'C1'
        cli.save_bundle(files, target, {'source_type': 'inert-import', 'executed': False})
        self.assertTrue((target / 'app' / 'main.py').exists())
        self.assertFalse(json.loads((target / '.submission-source.json').read_text())['executed'])
        with self.assertRaises(ValueError):
            cli.save_bundle(files, target, {})

    def test_configs_never_write_key(self):
        source = self.root / 'source.json'; dest = self.root / 'config.json'
        source.write_text(json.dumps(self.cfg))
        with patch.dict(os.environ, {'INTEGRATION_TEST_KEY': self.key}), contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(['import-config', '--source', str(source), '--output', str(dest)])
            cli.main(['inspect', '--config', str(dest)])
        self.assertNotIn(self.key, dest.read_text() + out.getvalue())
        with self.assertRaises(ValueError):
            cli.validate_config({**self.cfg, 'api_key': self.key})
        with patch.dict(os.environ, {}, clear=True), patch.object(cli.request, 'build_opener') as opener:
            with self.assertRaises(ValueError):
                cli.completion(self.cfg, [])
            opener.assert_not_called()

    def test_strict_json(self):
        self.assertEqual(cli.strict_json('```json\n{"ok":true}\n```'), {'ok': True})
        for text in ['Prose {"ok":true}', '{"a":1,"a":2}', '{"a":NaN}', '{} trailing', '[]']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                cli.strict_json(text)

    def mock_server(self, content=None):
        observed = []
        content = content or '{"format_version":1,"tree":{"action":"A10"}}'
        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
                observed.append((handler.path, handler.headers.get('Authorization'), body))
                response = {'model': 'mock-test', 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
                raw = json.dumps(response).encode(); handler.send_response(200)
                handler.send_header('Content-Type', 'application/json'); handler.send_header('Content-Length', str(len(raw)))
                handler.end_headers(); handler.wfile.write(raw)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return {**self.cfg, 'base_url': f'http://127.0.0.1:{server.server_port}/v1'}, observed

    def test_mock_http_full_reasoning_to_local_judge(self):
        cfg, observed = self.mock_server()
        with patch.dict(os.environ, {'INTEGRATION_TEST_KEY': self.key}):
            result = cli.run_reasoning('R2', cli.validate_config(cfg), self.root / 'submissions')
        self.assertTrue(result['result']['valid'])
        self.assertIsInstance(result['result']['raw_score'], (int, float))
        path, auth, request = observed[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(auth, 'Bearer ' + self.key)
        self.assertIn('Complete input.json', request['messages'][1]['content'])
        self.assertIn('worlds', request['messages'][1]['content'])
        saved = ''.join(p.read_text() for p in (self.root / 'submissions').rglob('*.json'))
        self.assertNotIn(self.key, saved)

    def test_provider_credential_echo_refused(self):
        cfg, _ = self.mock_server(json.dumps({'leaked': self.key}))
        with patch.dict(os.environ, {'INTEGRATION_TEST_KEY': self.key}), self.assertRaises(ValueError):
            cli.completion(cfg, [])

    def test_task_exports_exclude_solutions(self):
        for task in cli.TASKS:
            with self.subTest(task=task):
                files = cli.task_files(task)
                self.assertIn('PROMPT.md', files)
                self.assertFalse(any('baseline' in name or 'oracle' in name or '__pycache__' in name for name in files))
                if task in ('C1', 'C2'):
                    self.assertIn('repository/buggy/engine.py', files)
                    self.assertIn('fixtures/public.json', files)
                elif task == 'C3':
                    self.assertIn('starter/store.py', files)
                elif task == 'C4':
                    self.assertIn('starter/engine.py', files)
                elif task in ('R3', 'R4'):
                    self.assertIn('submission.py', files)
                    self.assertTrue(any(name.startswith('public_') for name in files))
        path = self.root / 'C1.zip'
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(['export-task', '--task', 'C1', '--output', str(path)])
        self.assertIn('repository/buggy/engine.py', cli.source_files(path))
        self.assertIn('EXPORT_README.md', cli.source_files(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
