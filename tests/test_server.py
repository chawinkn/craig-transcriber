import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from helpers import FakeEngine

from craig_transcriber import server
from craig_transcriber.project import Project
from craig_transcriber.transcribe import (
    Job,
)


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Project(Path(tmp.name))
        self.srv = server.make_server("127.0.0.1", 0, p, Job(p, FakeEngine))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def request(self, method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        self.addCleanup(c.close)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        return r.status, r.getheader("Content-Type"), r.read()

    def test_pages_and_assets(self):
        status, ctype, body = self.request("GET", "/")
        self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
        self.assertIn(b'href="/style.css"', body)
        self.assertIn(b'src="/app.js"', body)
        for path, want in (("/app.js", "text/javascript; charset=utf-8"), ("/style.css", "text/css; charset=utf-8")):
            status, ctype, body = self.request("GET", path)
            self.assertEqual((status, ctype), (200, want))
            self.assertTrue(body)

    def test_blocks_foreign_host_and_origin(self):
        self.assertEqual(self.request("GET", "/", {"Host": "evil.example"})[0], 403)
        host = f"127.0.0.1:{self.srv.server_address[1]}"
        self.assertEqual(self.request("POST", "/api/cancel", {"Host": host, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/cancel", {"Host": host, "Origin": f"http://{host}"})[0], 200)


if __name__ == "__main__":
    unittest.main()
