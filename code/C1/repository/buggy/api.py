"""Small JSON API: separate API process, no implicit in-process queue runner."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, unquote, urlparse
import traceback
import service
from db import connect


def run(settings):
    path = settings["db"]

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            try:
                if self.path != "/v1/batches":
                    return self.reply(404, {"error": "NOT_FOUND"})
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1_000_000:
                    raise service.ServiceError(400, "BAD_BODY")
                body = json.loads(self.rfile.read(size))
                result = service.submit_batch(path, body["tenant"], body["request_id"], body["events"])
                self.reply(202, result)
            except service.ServiceError as exc:
                self.reply(exc.status, {"error": exc.code})
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error": "BAD_BODY"})
            except Exception:
                traceback.print_exc()
                self.reply(500, {"error": "INTERNAL"})

        def do_GET(self):
            try:
                url = urlparse(self.path)
                tenant = parse_qs(url.query).get("tenant", [""])[0]
                if url.path == "/health":
                    with connect(path) as connection:
                        version = connection.execute("PRAGMA user_version").fetchone()[0]
                    return self.reply(200, {"status": "ok", "schema_version": version})
                if url.path == "/v1/jobs":
                    return self.reply(200, service.list_jobs(path, tenant))
                if url.path == "/v1/stats":
                    return self.reply(200, service.stats(path, tenant))
                if url.path.startswith("/v1/jobs/"):
                    job = service.get_job(path, int(url.path.rsplit("/", 1)[1]), tenant)
                    return self.reply(200, job) if job else self.reply(404, {"error": "NOT_FOUND"})
                if url.path.startswith("/v1/tenants/") and url.path.endswith("/state"):
                    return self.reply(200, service.state(path, unquote(url.path.split("/")[3])))
                self.reply(404, {"error": "NOT_FOUND"})
            except Exception:
                traceback.print_exc()
                self.reply(500, {"error": "INTERNAL"})

    server = ThreadingHTTPServer((settings["host"], settings["port"]), Handler)
    print(f"api ready at {settings['host']}:{settings['port']} db={path}", flush=True)
    server.serve_forever()
