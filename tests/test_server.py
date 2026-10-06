"""HTTP-level behaviour of the server."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.server import Handler

VALID = {
    "ticksPerQuarter": 480,
    "sampleRate": 48000,
    "tempoPoints": [{"tick": 0, "microsPerQuarter": 500000, "mode": "hold"}],
    "cues": [{"id": "a", "tick": 480}],
}


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def post(self, body, raw=False):
        data = body if raw else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/api/timelines/project",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read()), {"status": "ok"})

    def test_project_ok(self):
        status, body = self.post(VALID)
        self.assertEqual(status, 200)
        self.assertEqual(
            body["projections"],
            [{"id": "a", "tick": 480, "nanoseconds": 500_000_000, "frame": 24000}],
        )

    def test_domain_error_has_stable_code_and_no_partial_results(self):
        bad = dict(VALID)
        bad["tempoPoints"] = [
            {"tick": 0, "microsPerQuarter": 500000, "mode": "hold"},
            {"tick": 0, "microsPerQuarter": 400000, "mode": "hold"},
        ]
        status, body = self.post(bad)
        self.assertEqual(status, 422)
        self.assertNotIn("projections", body)
        self.assertEqual(body["error"]["code"], "DUPLICATE_TICK")
        self.assertEqual(body["error"]["position"]["index"], 1)

    def test_malformed_json(self):
        status, body = self.post(b"{not json", raw=True)
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "MALFORMED_JSON")

    def test_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/nope", timeout=5)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
