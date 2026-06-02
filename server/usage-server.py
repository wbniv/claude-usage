#!/usr/bin/env python3
"""Tiny local HTTP server — receives usage JSON from the Chrome extension."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, signal, subprocess, sys, threading, time
from pathlib import Path

import tooltip

_CACHE_HOME = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
_DATA_HOME  = Path(os.environ.get('XDG_DATA_HOME')  or Path.home() / '.local' / 'share')
OUTPUT        = _CACHE_HOME / 'claude-usage' / 'usage.json'
# Source install puts generate-icon.py under XDG_DATA_HOME; .deb under /usr/share.
GENERATE_ICON = next(
    (p for p in [
        _DATA_HOME / 'claude-usage' / 'generate-icon.py',
        Path('/usr/share/claude-usage/generate-icon.py'),
    ] if p.exists()),
    None,
)
if GENERATE_ICON is None:
    print("warning: generate-icon.py not found; dock icon updates disabled", file=sys.stderr, flush=True)
# Single source of truth for both the server's own version AND the bundled
# Chrome extension's expected version — they ship together in every install
# method. Derived at module load to eliminate the drift class the
# port-discovery review's V-2 finding predicted and pass-14 caught: the
# server's hardcoded VERSION fell two patch versions behind the rest of the
# release before anyone noticed. Best-effort read so a stripped-down install
# without packaging/ still starts up.
def _read_manifest_version():
    for p in (
        Path(__file__).resolve().parent / 'chrome-extension' / 'manifest.json',
        Path('/usr/share/claude-usage/chrome-extension/manifest.json'),
        Path.home() / '.local/share/claude-usage/chrome-extension/manifest.json',
    ):
        try:
            if p.exists():
                return json.loads(p.read_text()).get('version')
        except Exception:
            pass
    return None
_MANIFEST_VERSION = _read_manifest_version()
VERSION = _MANIFEST_VERSION or '0.0.0'
if VERSION == '0.0.0':
    print("warning: chrome-extension/manifest.json not found; /hello will report 0.0.0",
          file=sys.stderr, flush=True)
# None when the manifest is missing — that disables the mismatch check
# (POSTs are still accepted), which is the right fallback for stripped installs.
EXPECTED_EXT_VERSION = _MANIFEST_VERSION
# Default fallback range: try 7331 first, fall through if it's taken. CLAUDE_USAGE_PORT
# pins a single port (no fallback) — used by packaging/test-deb-live.sh and any caller
# that wants deterministic binding.
PORT_RANGE = range(7331, 7341)
PORT_FILE  = _CACHE_HOME / 'claude-usage' / 'port'
# Set CLAUDE_USAGE_EXTENSION_ID to the published Chrome Web Store extension ID
# to restrict CORS to only that extension. Unset = allow any chrome-extension://
# or moz-extension:// origin (safe for dev installs and Firefox, whose
# moz-extension:// host is a per-install UUID rather than a stable id; the
# server only binds to 127.0.0.1 regardless). See _cors() for the match.
_EXTENSION_ID  = os.environ.get('CLAUDE_USAGE_EXTENSION_ID', '')
ALLOWED_ORIGINS = {f'chrome-extension://{_EXTENSION_ID}'} if _EXTENSION_ID else None
if not _EXTENSION_ID:
    print("warning: CLAUDE_USAGE_EXTENSION_ID not set; CORS allows any Chrome/Firefox extension",
          file=sys.stderr, flush=True)
MAX_STR_LEN = 128

# Cache schema version this build writes. Readers (GNOME extension, status
# script) check the field on load and warn on mismatch so half-state bugs
# from old-reader/new-writer or new-reader/old-writer combos are visible.
CACHE_SCHEMA = 1

_VALID_ANTHROPIC_KEYS = ('indicator', 'description', 'claude_ai_component_status')

# V-2 (pass-16 §3): top-level keys we recognise. Anything else gets stripped
# before the {**prev, **body} merge in do_POST so the cache can't accumulate
# garbage indefinitely (e.g. _debug from an older Chrome ext version persisted
# for days after the ext stopped sending it). Includes both chrome-emitted keys
# and server-written keys (_schema, _ext_version_mismatch) so they survive
# across the next POST's merge. Symmetric to _anthropic_status's known-keys
# filter pattern already used inside do_POST.
_VALID_TOP_KEYS = frozenset({
    'meters', 'plan',
    '_timestamp', 'timestamp',           # 'timestamp' is legacy epoch-ms; converted at write
    '_scrape_fail_count',
    '_anthropic_status',
    '_ext_version', '_ext_version_mismatch',
    '_period_lengths',
    '_schema',
    '_buffered_at',                       # written by Chrome ext during offline-buffer flush
    '_parse_failure',                     # L-2 (pass-17): scraper distinguishes
                                          # locale/layout failure from "no data"
                                          # so claude-usage-status can surface
                                          # a useful cause for the grey panel.
})


def _bounded_str(v, field, allow_empty=True):
    if v is None:
        return None
    if not isinstance(v, str):
        return f"{field} must be a string or null"
    if not allow_empty and not v:
        return f"{field} must be non-empty"
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
    if 'meters' in body and meters is None:
        return "'meters' must not be null (omit the key to indicate no meter data)"
    if meters is not None:
        if not isinstance(meters, list):
            return "'meters' must be a list when present"
        # V-2 (pass-17): cap list length. _period_lengths is capped at 100;
        # meters was uncapped. claude.ai's usage page shows 3-5 meters, so
        # 50 is generous headroom. Body size cap (256 KB) is the wider
        # defense, but explicit caps document intent.
        if len(meters) > 50:
            return f"'meters' must have ≤ 50 entries (got {len(meters)})"
        for i, m in enumerate(meters):
            if not isinstance(m, dict):
                return f"meters[{i}] must be an object"
            pct = m.get('pct')
            # bool is a subclass of int — reject explicitly before the int check,
            # otherwise {"pct": true} passes and renders as "true%" in the panel.
            if isinstance(pct, bool) or not isinstance(pct, int) or not (0 <= pct <= 100):
                return f"meters[{i}].pct must be an integer in [0, 100]"
            # V-3 (pass-16 §10): label must be non-empty. An empty-label meter
            # would otherwise feed the current_labels set in do_POST's eviction
            # filter and contribute to PL-1's period_lengths wipe.
            err = _bounded_str(m.get('label'), f"meters[{i}].label", allow_empty=False)
            if err:
                return err
            for k in ('reset', 'spent', 'balance'):
                err = _bounded_str(m.get(k), f"meters[{i}].{k}")
                if err:
                    return err
            # Additional-features meters carry count/total instead of a meaningful
            # pct. Bound them so a malicious POST can't widen the popup column to
            # an absurd width via `${count}/${total}`.padStart in extension.js.
            for k in ('count', 'total'):
                v = m.get(k)
                if v is not None and (
                    isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 10**9
                ):
                    return f"meters[{i}].{k} must be a non-negative integer ≤ 10^9 or null"
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
        # AS-1 (pass-15): validate indicator as a bounded string rather than
        # against a hard-coded whitelist. Forward-compat with any future
        # Statuspage indicator value.
        # AS-1 (pass-17): `description` is free-form Anthropic prose that
        # routinely exceeds MAX_STR_LEN; auto-truncate rather than reject
        # the entire POST (the chrome ext also truncates, but defense-in-
        # depth: if any future caller forgets, we don't lose the indicator).
        for k in _VALID_ANTHROPIC_KEYS:
            v = astat.get(k)
            if k == 'description' and isinstance(v, str) and len(v) > MAX_STR_LEN:
                astat[k] = v[:MAX_STR_LEN - 3] + '...'
                continue
            err = _bounded_str(v, f"_anthropic_status.{k}")
            if err:
                return err
    pl = body.get('_period_lengths')
    if pl is not None:
        if not isinstance(pl, dict):
            return "'_period_lengths' must be an object"
        if len(pl) > 100:
            return "'_period_lengths' must have ≤ 100 keys"
        for k, v in pl.items():
            # V-3: keys must be non-empty strings — empty-string keys would
            # accumulate noise in the accumulator and contribute to the
            # current_labels eviction set (PL-1).
            if not isinstance(k, str) or not k or len(k) > MAX_STR_LEN:
                return f"'_period_lengths' keys must be non-empty strings ≤ {MAX_STR_LEN} chars"
            # Same upper bound as reset_minutes (31 days). bool ⊂ int — reject first.
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 60 * 24 * 31:
                return f"'_period_lengths[{k!r}]' must be a non-negative integer ≤ 44640"
    ts = body.get('_timestamp') or body.get('timestamp')
    if ts is not None:
        # bool ⊂ int — reject first so {"_timestamp": true} doesn't pass and end
        # up as anchor_ts=True downstream (time.time() - True = epoch - 1).
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return "'_timestamp' must be a number"
        # Legacy `timestamp` is epoch-ms; current `_timestamp` is epoch-s. Convert
        # legacy to seconds for the bound check (the do_POST assignment at line
        # 296 handles the same translation downstream). ±1 year past, +1 day
        # future — anything wider is clock skew, not a legitimate write to
        # persist. TS-1 (pass-15 §3): an unbounded future timestamp made
        # extension.js's age go negative, bypassing every stale/broken-tier
        # threshold and silently pinning the indicator to NORMAL forever.
        ts_s = ts / 1000 if (body.get('timestamp') and not body.get('_timestamp')) else ts
        now = time.time()
        if not (now - 365 * 86400 < ts_s < now + 86400):
            return "'_timestamp' implausibly far from server time"
    # _ext_version — stamped by the Chrome extension on every POST so the server
    # can detect version skew between Chrome (which doesn't auto-reload on .deb
    # upgrade) and the server. Bounded string; presence optional for backcompat
    # with older extensions that don't include it.
    err = _bounded_str(body.get('_ext_version'), '_ext_version')
    if err:
        return err
    # _schema — written by the server on every POST. Validated as a small int
    # so a malicious POST can't poison the cache with junk that downstream
    # readers might misinterpret.
    sv = body.get('_schema')
    if sv is not None and (isinstance(sv, bool) or not isinstance(sv, int) or sv < 0 or sv > 1000):
        return "'_schema' must be a non-negative integer ≤ 1000"
    # L-2 (pass-17): _parse_failure is a short enum-ish string ('locale_or_layout'
    # today; future could add 'rate_limited', 'page_changed'). Bounded string.
    err = _bounded_str(body.get('_parse_failure'), '_parse_failure')
    if err:
        return err
    # V-1 (pass-17): _buffered_at is whitelisted in _VALID_TOP_KEYS but was
    # never bounded — asymmetric with siblings (_timestamp, _scrape_fail_count
    # all enforce plausibility). It's epoch-ms per the Chrome ext.
    # BA-1 (pass-18): int() the comparison anchor to mirror _timestamp's
    # pure-int comparison style (cosmetic — floats at epoch-ms magnitude
    # have ~0.0002 ms precision, well under bound resolution).
    ba = body.get('_buffered_at')
    if ba is not None:
        if isinstance(ba, bool) or not isinstance(ba, (int, float)):
            return "'_buffered_at' must be a number"
        now_ms = int(time.time() * 1000)
        if not (now_ms - 365 * 86400 * 1000 < ba < now_ms + 86400 * 1000):
            return "'_buffered_at' implausibly far from server time"
    return None


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        # Stamp every response with a server signature so the Chrome extension
        # can detect a POST that hit a squatter on a stale-cached port — the
        # GET /hello probe verifies the server at discovery, this closes the
        # POST-path equivalent. Header-based (not body-based) so existing
        # status codes and response bodies stay unchanged.
        self.send_header('X-Claude-Usage-Server', VERSION)
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # /hello — discovery signature for the Chrome extension. The body
        # identifies this process as claude-usage so a probe across the port
        # range can distinguish our server from any squatter on the same port.
        # No auth; the signature is the body, not access control.
        if self.path == '/hello':
            payload = json.dumps({'app': 'claude-usage', 'version': VERSION}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        # Lowercased — RFC 7231 §3.1.1.1 says media types are case-insensitive.
        # Chrome always sends lowercase, but accept variants defensively.
        ct = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if ct != 'application/json':
            self.send_response(415)
            self._cors()
            self.end_headers()
            self.wfile.write(b'expected application/json')
            return

        # HM-2 (pass-15 §5): a non-numeric Content-Length raised ValueError
        # from int() and dumped a 9-line Python traceback to the journal per
        # malformed request. BaseHTTPRequestHandler swallowed the exception
        # but closed the connection without sending a response. Wrap and
        # return 400, matching the pattern used for json.loads below.
        try:
            length = int(self.headers.get('Content-Length', 0))
        except (ValueError, TypeError):
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(b'bad request: invalid Content-Length')
            return
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
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self.send_response(400)
                self._cors()
                self.end_headers()
                self.wfile.write(f'bad request: {e}'.encode())
                return
            err = _validate(body)
            if err:
                print(f"Validation error: {err}", file=sys.stderr, flush=True)
                status, reply = 422, err.encode()
            else:
                # Drop unknown keys from _anthropic_status so a forward-compat
                # field from Anthropic's statuspage (or a malicious POST) can't
                # silently accumulate in the cache. The three known keys are the
                # only ones any downstream consumer reads.
                astat = body.get('_anthropic_status')
                if isinstance(astat, dict):
                    body['_anthropic_status'] = {
                        k: astat[k] for k in _VALID_ANTHROPIC_KEYS if k in astat
                    }
                # Read previous cache so partial updates (status-only POSTs
                # with no `meters` key) preserve last-known meters/plan, and
                # so period_lengths accumulates over time.
                prev = {}
                if OUTPUT.exists():
                    try:
                        prev = json.loads(OUTPUT.read_text())
                        # CM-1 (pass-17): json.loads accepts non-dict roots
                        # (list, scalar, null). A corrupted cache containing
                        # `[]` would crash every subsequent POST at the dict-
                        # comprehension on line 335. Reset to {} on type mismatch.
                        if not isinstance(prev, dict):
                            print(f"warning: cache at {OUTPUT} is not a JSON object "
                                  f"(got {type(prev).__name__}); resetting",
                                  file=sys.stderr, flush=True)
                            prev = {}
                        else:
                            # CM-1 follow-up (2026-05-30 review): the root-dict
                            # check isn't enough — the merge below trusts the
                            # SHAPE of prev's nested fields. A cache corrupted
                            # out-of-band (hand-edit, bit-rot, older writer) with
                            # a non-dict _period_lengths or non-list meters
                            # crashed every POST in a permanent 400 loop (the
                            # crash skips the write, so the bad cache is never
                            # replaced). Coerce the two fields the merge reads.
                            _pl = prev.get('_period_lengths')
                            if isinstance(_pl, dict):
                                prev['_period_lengths'] = {
                                    k: v for k, v in _pl.items()
                                    if isinstance(k, str) and isinstance(v, int)
                                    and not isinstance(v, bool)
                                }
                            elif _pl is not None:
                                prev.pop('_period_lengths', None)
                            _m = prev.get('meters')
                            if isinstance(_m, list):
                                prev['meters'] = [x for x in _m if isinstance(x, dict)]
                            elif _m is not None:
                                prev.pop('meters', None)
                    except Exception:
                        pass

                # V-2 (pass-16 §3): strip unknown top-level keys from both sides
                # so the {**prev, **body} merge below can't propagate garbage
                # indefinitely. Demonstrated in pass-16: cache still carried a
                # `_debug` field three days after the Chrome ext stopped sending
                # it, because shallow merge keeps prev keys body doesn't override.
                # Filtering prev also one-shot cleans pre-existing garbage on the
                # first POST after this fix lands.
                prev = {k: v for k, v in prev.items() if k in _VALID_TOP_KEYS}
                body = {k: v for k, v in body.items() if k in _VALID_TOP_KEYS}

                # ACC-1 (pass-26): capture whether the INCOMING request carries a
                # timestamp and its meter count BEFORE the merge. After
                # {**prev, **body} + auto-timestamp fill, body['_timestamp'] is
                # never None, so using it for is_full_scrape made the timestamp
                # conjunct a tautology — only len(meters) >= 2 actually gated
                # eviction. A bogus 2-meter POST could wipe accumulated
                # period_lengths. Fix: compute from pre-merge incoming values.
                _incoming_has_ts = ('_timestamp' in body) or ('timestamp' in body)
                _incoming_meters = body.get('meters') if isinstance(body.get('meters'), list) else []

                # Period-lengths merge: start from prev's accumulated dict and
                # dict-update with body's _period_lengths if present, NEVER
                # replace with an empty/missing one. A naive {**prev, **body}
                # spread would clobber the accumulator if a POST included
                # `_period_lengths: {}` (current Chrome ext never does, but
                # the validator accepts the field).
                prev_pl = prev.get('_period_lengths') or {}
                incoming_pl = body.get('_period_lengths') or {}
                period_lengths = dict(prev_pl)
                period_lengths.update(incoming_pl)

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
                for meter in body.get('meters', []) or []:
                    rm = meter.get('reset_minutes')
                    label = meter.get('label')
                    if rm is None or not label:
                        continue
                    period_lengths[label] = max(period_lengths.get(label, 0), rm)
                # Evict labels no longer in the current meter set so stale keys
                # from renamed meters don't skew future pacing calculations.
                # PL-1 (pass-16 §4): only fire on full scrapes — a partial /
                # malicious POST with one fake meter would otherwise wipe the
                # whole accumulator (demonstrated live with one curl). claude.ai
                # always ships ≥ 2 meters on the usage page, so `_timestamp set
                # AND meters ≥ 2` is a reliable "this is a real scrape, not a
                # status-only POST" signal.
                # ACC-1 (pass-26): use pre-merge _incoming_has_ts / _incoming_meters.
                current_labels = {m.get('label') for m in body.get('meters', []) or [] if m.get('label')}
                is_full_scrape = _incoming_has_ts and len(_incoming_meters) >= 2
                if current_labels and is_full_scrape:
                    period_lengths = {k: v for k, v in period_lengths.items() if k in current_labels}
                body['_period_lengths'] = period_lengths

                # Chrome-extension version handshake. Chrome doesn't auto-reload
                # unpacked extensions on .deb upgrade, so the user can run an
                # old extension against a new server indefinitely. Log a stderr
                # warning + persist a flag so claude-usage-status surfaces it.
                ev = body.get('_ext_version')
                if ev and EXPECTED_EXT_VERSION and ev != EXPECTED_EXT_VERSION:
                    print(f"warning: Chrome extension v{ev} differs from server-expected v{EXPECTED_EXT_VERSION}; reload chrome://extensions",
                          file=sys.stderr, flush=True)
                    body['_ext_version_mismatch'] = True
                else:
                    body.pop('_ext_version_mismatch', None)

                # Stamp the schema version on every write. Old readers that
                # don't know about _schema ignore it; new readers that see a
                # mismatch log a warning instead of silently misinterpreting.
                body['_schema'] = CACHE_SCHEMA

                OUTPUT.parent.mkdir(parents=True, exist_ok=True)
                tmp = OUTPUT.with_suffix(OUTPUT.suffix + '.tmp')
                tmp.write_text(json.dumps(body, indent=2))
                os.chmod(tmp, 0o600)
                tmp.replace(OUTPUT)
                print(f"Saved {len(body.get('meters', []))} meters → {OUTPUT}", flush=True)
                if GENERATE_ICON:
                    # stderr inherits from the server (→ systemd journal under
                    # claude-usage-fetch.service) so generate-icon.py crashes
                    # are debuggable via `journalctl --user-unit=...`. stdout
                    # is silenced because the script's success line is noisy.
                    subprocess.Popen([sys.executable, str(GENERATE_ICON)],
                                     stdout=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr, flush=True)
            status, reply = 400, b'error'

        self.send_response(status)
        self._cors()
        self.end_headers()
        self.wfile.write(reply)

    def _cors(self):
        # The browser extension uses host_permissions for 127.0.0.1, so its
        # fetches bypass CORS entirely — Origin is absent on the happy path.
        # Drive-by web pages send their real Origin; only emit Allow-Origin for
        # extension-style origins (Chrome or Firefox) so browsers reject the rest.
        origin = self.headers.get('Origin', '')
        allowed = (
            (ALLOWED_ORIGINS is None and (origin.startswith('chrome-extension://')
                                          or origin.startswith('moz-extension://'))) or
            (ALLOWED_ORIGINS is not None and origin in ALLOWED_ORIGINS)
        )
        if allowed:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def log_message(self, *_):  # silence access log
        pass


def _tooltip_tick():
    """Refresh the dock launcher tooltip every 60 s so the countdown
    timer stays current between scrape POSTs. In-process call
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


def _bind():
    """Bind to 127.0.0.1 on the first free port from the configured range.

    CLAUDE_USAGE_PORT, if set, pins a single port (no fallback) — fail with a
    clear message if that port is taken. Otherwise iterate PORT_RANGE and
    return the first HTTPServer that successfully binds.
    """
    pin = os.environ.get('CLAUDE_USAGE_PORT')
    if pin:
        try:
            port = int(pin)
        except ValueError:
            print(f"CLAUDE_USAGE_PORT={pin!r} is not an integer", file=sys.stderr, flush=True)
            sys.exit(2)
        candidates = [port]
    else:
        candidates = list(PORT_RANGE)
    last_err = None
    for port in candidates:
        try:
            return HTTPServer(('127.0.0.1', port), Handler), port
        except OSError as e:
            last_err = e
            continue
    tried = candidates[0] if len(candidates) == 1 else f"{candidates[0]}–{candidates[-1]}"
    print(f"failed to bind any port in {tried}: {last_err}", file=sys.stderr, flush=True)
    sys.exit(1)


def _write_port_file(port):
    """Atomic, 0600 write of the chosen port for local consumers (CLI, status
    script, etc.). The Chrome extension cannot read arbitrary local files, so
    it probes /hello on the range instead — the port file is for local code."""
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PORT_FILE.with_suffix(PORT_FILE.suffix + '.tmp')
    tmp.write_text(f"{port}\n")
    os.chmod(tmp, 0o600)
    tmp.replace(PORT_FILE)


def _sweep_orphan_tmps():
    """Prune leftover unique-tmp files from crashed writes.

    Two writers use the .tmp.PID.NS scheme to avoid mutual truncation:
      • tooltip.py:update_desktop → ~/.local/share/applications/
      • generate-icon.py:_atomic_write_multisize → user hicolor size dirs
        (MS-1, pass-17: was not swept before)
    A crash between write and replace leaks one tmp per affected size.
    Run-once at server startup; skips tmps whose PID is still alive.
    """
    def _sweep(directory, pattern, pid_position):
        if not directory.is_dir():
            return
        for orphan in directory.glob(pattern):
            # OS-1 (pass-19): parse failure should NOT fall through to unlink.
            # If the filename doesn't match our scheme, it's not ours to delete.
            # (TS-2 was this exact failure mode wearing a different mask —
            # parse raised, except passed, unlink ran on a live tmp.)
            try:
                pid = int(orphan.name.split('.')[pid_position])
            except (ValueError, IndexError):
                continue
            if Path(f'/proc/{pid}').exists():
                continue  # process still alive — not an orphan
            try:
                orphan.unlink()
            except OSError:
                pass

    # Desktop file: claude-usage.desktop.tmp.<PID>.<NS> — PID at index -2.
    _sweep(Path.home() / '.local/share/applications',
           'claude-usage.desktop.tmp.*', -2)
    # Icon files: .claude-usage.tmp.<PID>.<NS>.<SIZE>.png. Splitting on '.':
    #   parts[0]='', [1]='claude-usage', [2]='tmp', [3]=PID, [4]=NS, [5]=SIZE, [6]='png'
    # TS-2 (pass-18): was pid_position=2 — that's the literal 'tmp', so int()
    # raised and the except clause unconditionally unlinked the file,
    # including live in-flight tmps from concurrent generate-icon.py runs.
    data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    hicolor = data_home / 'icons/hicolor'
    if hicolor.is_dir():
        for size_dir in hicolor.glob('*x*/apps'):
            _sweep(size_dir, '.claude-usage.tmp.*.png', 3)


if __name__ == '__main__':
    # SC-1 (pass-26): install SIGCHLD handler here, not at module import. The
    # server is only ever run directly; keeping this at import-time silently
    # mutates the global handler in every test process that exec_modules this
    # file. Auto-reap exited child processes (generate-icon.py spawns). The
    # Popen objects are discarded after dispatch, so without SIGCHLD ignored
    # the kernel keeps zombies around until the next subprocess._cleanup() sweep.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    _sweep_orphan_tmps()
    server, port = _bind()
    _write_port_file(port)
    print(f"Claude Usage server listening on 127.0.0.1:{port}", flush=True)
    # D-2 (pass-16 §8): refresh the dock icon at startup. Without this, the
    # icon stays at whatever was rendered before the last shutdown until the
    # next Chrome alarm fires (up to 7 min — longer if Chrome isn't running).
    # generate-icon.py exits 0 cleanly when the cache doesn't exist yet, so
    # no error on fresh install.
    if GENERATE_ICON and OUTPUT.exists():
        subprocess.Popen([sys.executable, str(GENERATE_ICON)],
                         stdout=subprocess.DEVNULL)
    threading.Thread(target=_tooltip_tick, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
