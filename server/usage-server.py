#!/usr/bin/env python3
"""Tiny local HTTP server — receives usage JSON from the Chrome extension."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, subprocess, sys
from pathlib import Path

OUTPUT        = Path.home() / '.cache' / 'claude-usage.json'
GENERATE_ICON = Path.home() / '.local/share/claude-usage/generate-icon.py'
PORT = 7331


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            # Normalise timestamp to epoch-seconds
            ts = body.pop('timestamp', None)
            body['_timestamp'] = int(ts / 1000) if ts else 0
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT.write_text(json.dumps(body, indent=2))
            print(f"Saved {len(body.get('meters', []))} meters → {OUTPUT}", flush=True)
            if GENERATE_ICON.exists():
                subprocess.Popen([sys.executable, str(GENERATE_ICON)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr, flush=True)

        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b'ok')

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def log_message(self, *_):  # silence access log
        pass


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    print(f"Claude Usage server listening on 127.0.0.1:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
