#!/usr/bin/env python3
"""Local-only SSE transport demonstration. Every result is simulated=true.

This is neither an agent launcher nor a commercial-model benchmark. It uses a
synthetic loopback credential, returns synthetic text/usage and makes no remote
API requests. The mock is also reused by test_performance.py.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
from socketserver import TCPServer
import socket
import threading
import time

from performance import run_plan

DEMO_KEY_ENV = "SMB_PERFORMANCE_LOCAL_DEMO_CREDENTIAL"
DEMO_CREDENTIAL = "local-synthetic-demo-credential-no-provider-access"
PRIVATE_REASONING_SENTINEL = "PRIVATE_REASONING_TEXT_MUST_NEVER_BE_SAVED"


class LoopbackHTTPServer(HTTPServer):
    """Avoid HTTPServer.server_bind's reverse-DNS lookup on the local host."""
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def address_string(self):
        return self.client_address[0]

    def _event(self, value):
        wire = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(("data: " + wire + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def _chunk(self, delta=None, finish=None):
        return {"model": "local-synthetic-sse-model", "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}

    def do_POST(self):
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer " + DEMO_CREDENTIAL:
            self.send_error(401)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        # Only public request bodies are captured for in-memory assertions;
        # no Authorization header or returned reasoning text is logged.
        self.server.requests.append(request)
        request_index = len(self.server.requests)
        last_user = next((message["content"] for message in reversed(request["messages"]) if message["role"] == "user"), "")
        marker = "MOCK_CASE:"
        scenario = last_user.split(marker, 1)[1].split()[0] if marker in last_user else "standard"
        self.server.scenario_counts[scenario] = self.server.scenario_counts.get(scenario, 0) + 1
        scenario_attempt = self.server.scenario_counts[scenario]
        actual = "disconnect" if scenario == "always_fail" or scenario == "retry_once" and scenario_attempt == 1 else scenario
        generated = 120 + request_index
        usage = {"prompt_tokens": 18 + len(request["messages"]), "completion_tokens": generated,
                 "total_tokens": generated + 18 + len(request["messages"]),
                 "completion_tokens_details": {"reasoning_tokens": 80 + request_index}}
        answer = json.dumps({"simulated": True, "request": request_index, "message": "本机SSE样本，不是解题成绩"}, ensure_ascii=False)
        if actual == "json_fallback":
            data = json.dumps({"model": "local-synthetic-json-model", "choices": [{"index": 0, "message": {"content": answer}, "finish_reason": "stop"}], "usage": usage}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if actual == "chunk_disconnect":
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self.close_connection = True
        try:
            if actual == "chunk_disconnect":
                frame = ("data: " + json.dumps(self._chunk({"role": "assistant"})) + "\n\n").encode()
                self.wfile.write(f"{len(frame):X}\r\n".encode() + frame + b"\r\n")
                self.wfile.flush()
                # An announced chunk is deliberately cut short, without a zero chunk.
                self.wfile.write(b"80\r\ndata: {")
                self.wfile.flush()
                return
            self._event(self._chunk({"role": "assistant"}))
            pause = 0.003 + (request_index % 3) * 0.001
            time.sleep(pause)
            self._event(self._chunk({"reasoning_content": PRIVATE_REASONING_SENTINEL}))
            time.sleep(pause)
            self._event(self._chunk({"reasoning_content": "more private reasoning"}))
            time.sleep(pause)
            if actual == "credential_echo":
                self._event(self._chunk({"content": DEMO_CREDENTIAL}))
                return
            if actual == "credential_split":
                middle = len(DEMO_CREDENTIAL) // 2
                self._event(self._chunk({"content": DEMO_CREDENTIAL[:middle]}))
                self._event(self._chunk({"content": DEMO_CREDENTIAL[middle:]}))
                self._event(self._chunk(finish="stop"))
                self._event("[DONE]")
                return
            if actual == "provider_error":
                self._event({"error": {"message": "synthetic service failure"}})
                return
            if actual != "reasoning_only":
                middle = len(answer) // 2
                self._event(self._chunk({"content": answer[:middle]}))
                time.sleep(pause)
                if actual == "disconnect":
                    return
                self._event(self._chunk({"content": answer[middle:]}))
            self._event(self._chunk(finish="stop"))
            if actual == "disconnect_after_stop":
                return
            if actual != "no_usage":
                # A standards-compatible final usage-only chunk has empty choices.
                self._event({"model": "local-synthetic-sse-model", "choices": [], "usage": usage})
            self._event("[DONE]")
        except (BrokenPipeError, ConnectionResetError):
            # Expected when the recorder refuses a credential echo and closes early.
            pass


@contextmanager
def mock_endpoint():
    previous = os.environ.get(DEMO_KEY_ENV)
    os.environ[DEMO_KEY_ENV] = DEMO_CREDENTIAL
    server = LoopbackHTTPServer(("127.0.0.1", 0), MockHandler)
    server.requests = []
    server.scenario_counts = {}
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    config = {"alias": "local-simulated-demo", "base_url": f"http://127.0.0.1:{server.server_port}/v1",
              "model": "local-synthetic-sse-model", "api_key_env": DEMO_KEY_ENV,
              "timeout": 5, "max_tokens": 512, "temperature": 0}
    try:
        yield config, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if previous is None:
            os.environ.pop(DEMO_KEY_ENV, None)
        else:
            os.environ[DEMO_KEY_ENV] = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new directory for simulated artifacts")
    parser.add_argument("--prompts", type=Path, default=Path(__file__).with_name("performance-prompts.example.json"))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=260926)
    parser.add_argument("--conversation", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.prompts.read_text(encoding="utf-8"))
    with mock_endpoint() as (config, server):
        summary = run_plan(config, plan, args.output, rounds=args.rounds, warmups=0, retries=0,
                           seed=args.seed, conversation=args.conversation, simulated=True)
        requests = len(server.requests)
    receipt = {"simulated": True, "network_scope": "127.0.0.1 loopback only; no real API or provider credential",
               "prompts": len(plan["prompts"]), "rounds": args.rounds, "actual_http_requests": requests,
               "output": str(args.output.resolve()), "overall": summary["overall"]}
    (args.output / "DEMO_README.md").write_text(
        "# 本机模拟演示\n\n所有数据均 simulated=true。仅用于验收流式采样接口和多轮统计。\n"
        "这里的回答与provider usage是本机HTTP服务合成值；实际测量的是本机回环与短sleep的时延。\n"
        "不是模型能力、真实服务延迟或隐藏思考耗时。每个prompt保留全部轮次，不挑最好一次。\n"
        "attempts.jsonl保留可见回答，attempts.csv用于表格比较，summary.json有均值/最大值/P50/P95。\n"
        "真正解题需按实验README由Agent自行执行并提交源码/答案，再由Codex裁判按公开契约评分。\n",
        encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
