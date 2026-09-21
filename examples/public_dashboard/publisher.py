"""Loopback-only transport for signed demo records, with no directory listing."""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import re


def serve(directory: Path, port: int = 18444) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.lstrip("/")
            if not re.fullmatch(r"(?:gm-demo-[a-z0-9-]+|canary)\.json", name):
                self.send_error(404)
                return
            path = directory / name
            if not path.is_file():
                self.send_error(404)
                return
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            pass

    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    serve(parser.parse_args().directory)
