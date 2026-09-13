"""Static file + JSON server. Standard library only."""

import json
import mimetypes
import os
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def make_handler(aggregator):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Watchdesk"

        def log_message(self, fmt, *args):
            pass                        # a dashboard polling itself is noise

        def _send(self, status, body, content_type):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status, payload):
            self._send(status, json.dumps(payload), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]

            if path == "/api/data":
                return self._send_json(200, aggregator.snapshot())

            if path.startswith("/api/refresh/"):
                key = path.rsplit("/", 1)[-1]
                if key not in ("zabbix", "planner", "deskpro"):
                    return self._send_json(404, {"error": "unknown source"})
                return self._send_json(200, aggregator.refresh_one(key))

            if path == "/api/refresh":
                aggregator.refresh_all()
                return self._send_json(200, aggregator.snapshot())

            return self._serve_static(path)

        def _serve_static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            # Normalise and confine to STATIC_DIR.
            rel = posixpath.normpath(rel).lstrip("/")
            target = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
                return self._send(404, "Not found", "text/plain")

            ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
            with open(target, "rb") as handle:
                self._send(200, handle.read(), ctype)

    return Handler


def serve(aggregator, host, port):
    httpd = ThreadingHTTPServer((host, port), make_handler(aggregator))
    httpd.daemon_threads = True
    return httpd
