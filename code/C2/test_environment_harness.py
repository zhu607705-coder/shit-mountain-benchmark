"""Portable loopback regressions: no DNS/proxy discovery and useful startup failures."""
import importlib.util,json,os,socket,subprocess,sys,tempfile,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('c2_environment_harness',ROOT/'e2e_env_judge.py')
harness=importlib.util.module_from_spec(spec);spec.loader.exec_module(harness)


class PortabilityTests(unittest.TestCase):
    def test_standard_server_demonstrates_reverse_dns_before_readiness(self):
        with patch.object(socket,'getfqdn',side_effect=AssertionError('controlled DNS lookup')) as resolver:
            with self.assertRaisesRegex(AssertionError,'controlled DNS lookup'):
                ThreadingHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
            resolver.assert_called_once_with('127.0.0.1')

    def test_both_repository_servers_bind_without_dns(self):
        script="""
import json,socket,sys
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler
sys.path.insert(0,sys.argv[1])
from app.api import LoopbackHTTPServer
with patch.object(socket,'getfqdn',side_effect=AssertionError('unexpected reverse DNS')) as resolver:
    server=LoopbackHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
    try:
        assert server.server_name=='localhost'
        assert server.server_port==server.server_address[1]>0
        assert not resolver.called
        print(json.dumps({'bound':True,'port':server.server_port}))
    finally:server.server_close()
"""
        for variant in ['baseline','buggy']:
            with self.subTest(variant=variant):
                result=subprocess.run([sys.executable,'-c',script,str(ROOT/'repository'/variant)],capture_output=True,text=True,timeout=4,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
                self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)['bound'])

    def test_real_http_flow_ignores_bad_proxy_and_proxy_discovery(self):
        bad={'http_proxy':'http://127.0.0.1:9','HTTP_PROXY':'http://127.0.0.1:9','https_proxy':'http://127.0.0.1:9','HTTPS_PROXY':'http://127.0.0.1:9','all_proxy':'http://127.0.0.1:9','ALL_PROXY':'http://127.0.0.1:9','no_proxy':'','NO_PROXY':''}
        stack=None
        try:
            with patch.dict(os.environ,bad),patch.object(harness.urllib.request,'getproxies',side_effect=AssertionError('proxy discovery is not needed')),patch.object(harness.urllib.request,'proxy_bypass',side_effect=AssertionError('proxy bypass discovery is not needed')):
                stack=harness.Stack(ROOT/'repository/baseline');stack.start_all();harness.ordinary(stack)
        finally:
            if stack:stack.close()

    def fixture_failure(self,source,timeout=.6):
        with tempfile.TemporaryDirectory(prefix='c2-startup-test-') as directory:
            root=Path(directory);(root/'cli.py').write_text(source);stack=harness.Stack(root)
            try:
                with patch.object(harness,'STARTUP_TIMEOUT',timeout):
                    with self.assertRaises(harness.StartupFailure) as caught:stack.start('serve')
                return caught.exception.evidence
            finally:stack.close()

    def test_early_exit_preserves_returncode_and_stderr(self):
        evidence=self.fixture_failure("import sys\nsys.stderr.write('intentional startup failure\\n')\nsys.exit(7)\n")
        self.assertEqual(evidence['returncode'],7);self.assertEqual(evidence['reason'],'process_exited');self.assertIn('intentional startup failure',evidence['stderr'])

    def test_partial_stdout_still_obeys_deadline_and_captures_stack(self):
        started=time.monotonic()
        evidence=self.fixture_failure("import sys,time\nsys.stdout.write('partial-ready');sys.stdout.flush()\ntime.sleep(10)\n",timeout=.5)
        self.assertLess(time.monotonic()-started,2)
        self.assertEqual(evidence['reason'],'timeout');self.assertIsNone(evidence['returncode']);self.assertIn('partial-ready',evidence['stdout'])
        if hasattr(harness.signal,'SIGUSR1'):
            self.assertEqual(evidence['stack_probe'],'SIGUSR1_stack_dump');self.assertIn('cli.py',evidence['stderr'])

    def test_invalid_ready_is_reported_with_original_stdout(self):
        evidence=self.fixture_failure("import time\nprint('{\"ready\":true,\"port\":true}',flush=True)\ntime.sleep(10)\n")
        self.assertTrue(evidence['reason'].startswith('invalid_ready:'));self.assertIn('"port":true',evidence['stdout'])


if __name__=='__main__':unittest.main()
