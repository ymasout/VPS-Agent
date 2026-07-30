import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def respond(self) -> None:
        body = json.dumps(
            {
                "id": self.headers.get("X-VPS-Agent-Principal-Id"),
                "source": self.headers.get("X-VPS-Agent-Principal-Source"),
                "token": self.headers.get("X-VPS-Agent-Principal-Proxy-Token"),
                "write_token": self.headers.get("X-VPS-Agent-Principal-Write-Token"),
                "origin": self.headers.get("Origin"),
                "sec_fetch_site": self.headers.get("Sec-Fetch-Site"),
                "path": self.path,
            },
            sort_keys=True,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.respond()

    def do_POST(self) -> None:
        self.respond()

    def log_message(self, _format: str, *_args: object) -> None:
        return


ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
