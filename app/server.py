"""HTTP front end (standard library only).

Endpoints:
  GET  /health                   -> 200 {"status": "ok"}
  POST /api/timelines/project    -> 200 {"projections": [...]} or an error body
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import ApiError
from .projection import project

PROJECT_PATH = "/api/timelines/project"
HEALTH_PATH = "/health"


class Handler(BaseHTTPRequestHandler):
    server_version = "ScoreClock/1.0"
    protocol_version = "HTTP/1.1"

    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _path(self):
        return self.path.split("?", 1)[0]

    def do_GET(self):
        if self._path() == HEALTH_PATH:
            self._send(200, {"status": "ok"})
        else:
            self._send(
                404,
                ApiError("NOT_FOUND", f"unknown path {self._path()}", status=404).to_body(),
            )

    def do_POST(self):
        if self._path() != PROJECT_PATH:
            self._send(
                404,
                ApiError("NOT_FOUND", f"unknown path {self._path()}", status=404).to_body(),
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(max(length, 0))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(
                400,
                ApiError(
                    "MALFORMED_JSON", "request body is not valid JSON", status=400
                ).to_body(),
            )
            return
        try:
            projections = project(payload)
        except ApiError as exc:
            self._send(exc.status, exc.to_body())
            return
        self._send(200, {"projections": projections})


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
