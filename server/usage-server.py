#!/usr/bin/env python3
"""Tiny local HTTP server — receives usage JSON from the Chrome extension."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, subprocess, sys
from pathlib import Path

OUTPUT        = Path.home() / '.cache' / 'claude-usage.json'
GENERATE_ICON = Path.home() / '.local/share/claude-usage/generate-icon.py'
PORT = 7331


def _validate(body):
    """Return an error string, or None if the payload is structurally valid."""
    if not isinstance(body, dict):
        return "body must be a JSON object"
    meters = body.get('meters')
    if not isinstance(meters, list):
        return "'meters' must be an array"
    for i, m in enumerate(meters):
        if not isinstance(m, dict):
            return f"meters[{i}] must be an object"
        pct = m.get('pct')
        if not isinstance(pct, int) or not (0 <= pct <= 100):
            return f"meters[{i}].pct must be an integer in [0, 100]"
        label = m.get('label')
        if label is not None and not isinstance(label, str):
            return f"meters[{i}].label must be a string or null"
    ts = body.get('_timestamp') or body.get('timestamp')
    if ts is not None and not isinstance(ts, (int, float)):
        return "'_timestamp' must be a number"
    return None


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        ct = self.headers.get('Content-Type', '').split(';')[0].strip()
        if ct != 'application/json':
            self.send_response(415)
            self._cors()
            self.end_headers()
            self.wfile.write(b'expected application/json')
            return

        status, reply = 200, b'ok'
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            err = _validate(body)
            if err:
                print(f"Validation error: {err}", file=sys.stderr, flush=True)
                status, reply = 422, err.encode()
            else:
                # Accept _timestamp (epoch-s from extension) or legacy timestamp (epoch-ms)
                if '_timestamp' not in body:
                    ts = body.pop('timestamp', None)
                    body['_timestamp'] = int(ts / 1000) if ts else 0
                OUTPUT.parent.mkdir(parents=True, exist_ok=True)
                OUTPUT.write_text(json.dumps(body, indent=2))
                os.chmod(OUTPUT, 0o600)
                print(f"Saved {len(body.get('meters', []))} meters → {OUTPUT}", flush=True)
                if GENERATE_ICON.exists():
                    subprocess.Popen([sys.executable, str(GENERATE_ICON)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr, flush=True)
            status, reply = 400, b'error'

        self.send_response(status)
        self._cors()
        self.end_headers()
        self.wfile.write(reply)

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
