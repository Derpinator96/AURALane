"""SageMaker's container contract, shared by the brain and CT images.

GET /ping answers 200 when ready; POST /invocations does the work; both on port
8080. For an asynchronous endpoint the request body is the object at the
caller's InputLocation and the response body is written to the endpoint's S3
output path. An exception becomes a 500 with the error, which SageMaker writes
to the failure path; core/providers/aws/inference.py reads and raises it.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


def split_s3(uri: str) -> tuple[str, str]:
    u = urlparse(uri)
    return u.netloc, u.path.lstrip("/")


def serve(run) -> None:
    """run: request dict -> response dict (JSON-serialisable)."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200 if self.path == "/ping" else 404)

        def do_POST(self):
            if self.path != "/invocations":
                return self._send(404)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                self._send(200, json.dumps(run(json.loads(body))).encode())
            except Exception as e:
                self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode())

    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
