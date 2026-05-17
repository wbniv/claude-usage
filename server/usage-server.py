#!/usr/bin/env python3
"""Tiny local HTTP server — receives usage JSON from the Chrome extension."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, signal, subprocess, sys, threading, time
from pathlib import Path

import tooltip

# Auto-reap exited child processes (generate-icon.py spawns). The Popen
# objects are discarded after dispatch, so without SIGCHLD ignored the
# kernel keeps zombies around until the next subprocess._cleanup() sweep.
signal.signal(signal.SIGCHLD, signal.SIG_IGN)

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
    """Return an error string, or None if the payload is structurally valid.

    `meters` is optional: a partial update (e.g. scrape-failed status-only
    POST) will be merged into the existing cache by do_POST, preserving the
    last-known meters/plan/_timestamp.
    """
    if not isinstance(body, dict):
        return "body must be a JSON object"
    meters = body.get('meters')
    if meters is not None:
        if not isinstance(meters, list):
            return "'meters' must be a list when present"
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
            rm = m.get('reset_minutes')
            # Upper bound = 31 days. Longest plausible period is the 7-day weekly
            # meter; 31 days has headroom for any hypothetical monthly meter and
            # caps poisoned `_period_lengths` accumulation from huge inputs.
            if rm is not None and (
                isinstance(rm, bool) or not isinstance(rm, int) or rm < 0 or rm > 60 * 24 * 31
            ):
                return f"meters[{i}].reset_minutes must be in [0, 44640] or null"
    err = _bounded_str(body.get('plan'), 'plan')
    if err:
        return err
    sfc = body.get('_scrape_fail_count')
    if sfc is not None:
        if isinstance(sfc, bool) or not isinstance(sfc, int):
            return "'_scrape_fail_count' must be an integer"
        if sfc < 0 or sfc > 1000:
            return "'_scrape_fail_count' must be in [0, 1000]"
    astat = body.get('_anthropic_status')
    if astat is not None:
        if not isinstance(astat, dict):
            return "'_anthropic_status' must be an object"
        for k in ('indicator', 'description', 'claude_ai_component_status'):
            err = _bounded_str(astat.get(k), f"_anthropic_status.{k}")
            if err:
                return err
    pl = body.get('_period_lengths')
    if pl is not None:
        if not isinstance(pl, dict):
            return "'_period_lengths' must be an object"
        for k, v in pl.items():
            if not isinstance(k, str) or len(k) > MAX_STR_LEN:
                return f"'_period_lengths' keys must be strings ≤ {MAX_STR_LEN} chars"
            # Same upper bound as reset_minutes (31 days). bool ⊂ int — reject first.
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 60 * 24 * 31:
                return f"'_period_lengths[{k!r}]' must be a non-negative integer ≤ 44640"
    ts = body.get('_timestamp') or body.get('timestamp')
    # bool ⊂ int — reject first so {"_timestamp": true} doesn't pass and end
    # up as anchor_ts=True downstream (time.time() - True = epoch - 1).
    if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
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
                # Read previous cache so partial updates (status-only POSTs
                # with no `meters` key) preserve last-known meters/plan, and
                # so period_lengths accumulates over time.
                prev = {}
                if OUTPUT.exists():
                    try:
                        prev = json.loads(OUTPUT.read_text())
                    except Exception:
                        pass
                # Merge: dict-spread keeps prev keys not present in body,
                # body keys override prev keys. Full scrape updates carry
                # meters/plan/_timestamp and replace those; status-only
                # updates carry only _scrape_fail_count/_anthropic_status.
                body = {**prev, **body}

                # Accept _timestamp (epoch-s from extension) or legacy timestamp (epoch-ms).
                # 0 is treated as missing — fall back to server time so stale-data warning never fires spuriously.
                if not body.get('_timestamp'):
                    ts = body.pop('timestamp', None)
                    body['_timestamp'] = int(ts / 1000) if ts else int(time.time())
                # Accumulate per-meter period lengths from observed reset_minutes.
                # The max ever seen per label converges to the true period
                # (~5 h for session meters, ~7 d for weekly). Used downstream
                # to compute pacing-based colors.
                period_lengths = body.get('_period_lengths', {}) or {}
                for meter in body.get('meters', []) or []:
                    rm = meter.get('reset_minutes')
                    label = meter.get('label')
                    if rm is None or not label:
                        continue
                    period_lengths[label] = max(period_lengths.get(label, 0), rm)
                body['_period_lengths'] = period_lengths
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
        # The Chrome extension uses host_permissions for 127.0.0.1, so its
        # fetches bypass CORS entirely — Origin is absent on the happy path.
        # Drive-by web pages send their real Origin; only emit Allow-Origin
        # for extension-style origins so browsers reject the rest.
        origin = self.headers.get('Origin', '')
        if origin.startswith('chrome-extension://'):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def log_message(self, *_):  # silence access log
        pass


def _tooltip_tick():
    """Refresh the dock launcher tooltip every 60 s so the countdown
    timer stays current between 15-min scrape POSTs. In-process call
    via tooltip.update_desktop — no subprocess fork/exec."""
    while True:
        time.sleep(60)
        try:
            if OUTPUT.exists():
                data = json.loads(OUTPUT.read_text())
                tooltip.update_desktop(
                    data.get('meters', []),
                    scrape_ts=data.get('_timestamp'),
                )
        except Exception as e:
            print(f"tooltip tick: {e}", file=sys.stderr, flush=True)


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    print(f"Claude Usage server listening on 127.0.0.1:{PORT}", flush=True)
    threading.Thread(target=_tooltip_tick, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
