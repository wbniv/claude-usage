#!/usr/bin/env python3
"""Tiny local HTTP server — receives usage JSON from the Chrome extension."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, subprocess, sys, time
from pathlib import Path

OUTPUT        = Path.home() / '.cache' / 'claude-usage' / 'usage.json'
# Source install puts generate-icon.py under ~/.local/share; .deb under /usr/share.
GENERATE_ICON = next(
    (p for p in [
        Path.home() / '.local/share/claude-usage/generate-icon.py',
        Path('/usr/share/claude-usage/generate-icon.py'),
    ] if p.exists()),
    None,
)
PORT = 7331
MAX_STR_LEN = 128


def _bounded_str(v, field):
    if v is None:
        return None
    if not isinstance(v, str):
        return f"{field} must be a string or null"
    if len(v) > MAX_STR_LEN:
        return f"{field} exceeds {MAX_STR_LEN} chars"
    return None


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
        # bool is a subclass of int — reject explicitly before the int check,
        # otherwise {"pct": true} passes and renders as "true%" in the panel.
        if isinstance(pct, bool) or not isinstance(pct, int) or not (0 <= pct <= 100):
            return f"meters[{i}].pct must be an integer in [0, 100]"
        for k in ('label', 'reset', 'spent', 'balance'):
            err = _bounded_str(m.get(k), f"meters[{i}].{k}")
            if err:
                return err
    err = _bounded_str(body.get('plan'), 'plan')
    if err:
        return err
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

        length = int(self.headers.get('Content-Length', 0))
        # length <= 0 catches negative values (which would otherwise bypass the
        # cap via self.rfile.read(-1) = read-until-EOF) and missing bodies.
        if length <= 0 or length > 256 * 1024:
            self.send_response(413)
            self._cors()
            self.end_headers()
            self.wfile.write(b'payload too large')
            return

        status, reply = 200, b'ok'
        try:
            body = json.loads(self.rfile.read(length))
            err = _validate(body)
            if err:
                print(f"Validation error: {err}", file=sys.stderr, flush=True)
                status, reply = 422, err.encode()
            else:
                # Accept _timestamp (epoch-s from extension) or legacy timestamp (epoch-ms).
                # 0 is treated as missing — fall back to server time so stale-data warning never fires spuriously.
                if not body.get('_timestamp'):
                    ts = body.pop('timestamp', None)
                    body['_timestamp'] = int(ts / 1000) if ts else int(time.time())
                OUTPUT.parent.mkdir(parents=True, exist_ok=True)
                tmp = OUTPUT.with_suffix(OUTPUT.suffix + '.tmp')
                tmp.write_text(json.dumps(body, indent=2))
                os.chmod(tmp, 0o600)
                tmp.replace(OUTPUT)
                print(f"Saved {len(body.get('meters', []))} meters → {OUTPUT}", flush=True)
                if GENERATE_ICON:
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
