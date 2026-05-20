"""Pytest coverage for usage-server.py::_validate and do_POST merge behaviour.

Imports the hyphenated module via importlib because Python's import system
rejects 'usage-server' as a module name. The test file stays small and
focused — one test per numbered failure path in the validator + happy paths,
plus a `_do_post` harness for pass-16's V-2 / PL-1 merge regressions.
"""
import importlib.util
import io
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_SERVER_DIR = Path(__file__).resolve().parent.parent
# usage-server.py does `import tooltip` which needs server/ on sys.path.
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

_SPEC = importlib.util.spec_from_file_location(
    'usage_server',
    _SERVER_DIR / 'usage-server.py',
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
_validate = _MOD._validate


# ── Top-level shape ──────────────────────────────────────────────────────────

def test_rejects_non_dict():
    assert _validate([]) == "body must be a JSON object"
    assert _validate('hi') == "body must be a JSON object"
    assert _validate(None) == "body must be a JSON object"


def test_accepts_empty_dict():
    # Partial update with no fields is structurally valid; do_POST merges it
    # into prev and ends up no-op other than the schema/timestamp write.
    assert _validate({}) is None


# ── meters ───────────────────────────────────────────────────────────────────

def test_meters_null_rejected():
    # NM-1 (pass-26): explicit null previously bypassed the isinstance check
    # and poisoned the cache with meters=None, crashing every downstream consumer.
    err = _validate({'meters': None})
    assert err is not None and 'meters' in err


def test_meters_must_be_list():
    assert _validate({'meters': {}}) == "'meters' must be a list when present"


def test_meter_must_be_dict():
    assert _validate({'meters': ['x']}) == "meters[0] must be an object"


def test_meter_pct_required_integer():
    # Missing pct
    assert 'pct' in _validate({'meters': [{}]})
    # Float pct
    assert 'pct' in _validate({'meters': [{'pct': 50.5}]})
    # String pct
    assert 'pct' in _validate({'meters': [{'pct': '50'}]})


def test_meter_pct_rejects_bool_subclass():
    # bool ⊂ int in Python — must be rejected explicitly so {"pct": true}
    # doesn't pass and render as "true%" downstream.
    assert _validate({'meters': [{'pct': True}]}) == "meters[0].pct must be an integer in [0, 100]"


def test_meter_pct_range():
    assert _validate({'meters': [{'pct': -1}]}) == "meters[0].pct must be an integer in [0, 100]"
    assert _validate({'meters': [{'pct': 101}]}) == "meters[0].pct must be an integer in [0, 100]"
    assert _validate({'meters': [{'pct': 0}]}) is None
    assert _validate({'meters': [{'pct': 100}]}) is None


def test_meter_string_field_length():
    too_long = 'x' * 129  # MAX_STR_LEN = 128
    assert 'label' in _validate({'meters': [{'pct': 50, 'label': too_long}]})
    assert _validate({'meters': [{'pct': 50, 'label': 'x' * 128}]}) is None


def test_meter_count_total_bounds():
    # Negative
    err = _validate({'meters': [{'pct': 0, 'count': -1, 'total': 10}]})
    assert err and 'count' in err
    # > 10^9
    err = _validate({'meters': [{'pct': 0, 'count': 10**9 + 1, 'total': 10}]})
    assert err and 'count' in err
    # bool
    err = _validate({'meters': [{'pct': 0, 'count': True, 'total': 10}]})
    assert err and 'count' in err
    # Valid
    assert _validate({'meters': [{'pct': 0, 'count': 5, 'total': 10}]}) is None


def test_meter_reset_minutes_boundary():
    # 31 days = 44640 — accept; 44641 — reject
    assert _validate({'meters': [{'pct': 0, 'reset_minutes': 44640}]}) is None
    assert _validate({'meters': [{'pct': 0, 'reset_minutes': 44641}]}) == \
        "meters[0].reset_minutes must be in [0, 44640] or null"
    assert _validate({'meters': [{'pct': 0, 'reset_minutes': -1}]}) == \
        "meters[0].reset_minutes must be in [0, 44640] or null"
    # bool subclass
    assert 'reset_minutes' in _validate({'meters': [{'pct': 0, 'reset_minutes': True}]})


# ── plan ─────────────────────────────────────────────────────────────────────

def test_plan_string_length():
    assert _validate({'plan': 'x' * 129}) == "plan exceeds 128 chars"
    assert _validate({'plan': 'x' * 128}) is None
    assert _validate({'plan': None}) is None


# ── _scrape_fail_count ───────────────────────────────────────────────────────

def test_scrape_fail_count():
    assert _validate({'_scrape_fail_count': True}) == "'_scrape_fail_count' must be an integer"
    assert _validate({'_scrape_fail_count': -1}) == "'_scrape_fail_count' must be in [0, 1000]"
    assert _validate({'_scrape_fail_count': 1001}) == "'_scrape_fail_count' must be in [0, 1000]"
    assert _validate({'_scrape_fail_count': 0}) is None
    assert _validate({'_scrape_fail_count': 1000}) is None


# ── _anthropic_status ────────────────────────────────────────────────────────

def test_anthropic_status_must_be_dict():
    assert _validate({'_anthropic_status': 'hi'}) == "'_anthropic_status' must be an object"
    assert _validate({'_anthropic_status': None}) is None
    assert _validate({'_anthropic_status': {}}) is None


def test_anthropic_status_indicator_accepts_any_string():
    """AS-1: indicator is validated as a bounded string, not a whitelist.
    Forward-compat with any future Statuspage value (e.g. 'investigating' has
    appeared historically). The previous whitelist would have rejected the
    entire POST on first unknown value — dropping data during the exact moment
    we wanted to surface it. Type and length checks remain in force."""
    for v in (None, 'none', 'minor', 'major', 'critical', 'maintenance',
              'investigating', 'identified', 'unknown-future-value'):
        assert _validate({'_anthropic_status': {'indicator': v}}) is None, f"rejected {v!r}"
    err = _validate({'_anthropic_status': {'indicator': 123}})
    assert err and 'indicator' in err
    err = _validate({'_anthropic_status': {'indicator': 'x' * 129}})
    assert err and 'indicator' in err


def test_anthropic_status_field_lengths():
    too_long = 'x' * 129
    # AS-1 (pass-17): description auto-truncates rather than rejecting the
    # whole POST. Real Statuspage prose routinely exceeds MAX_STR_LEN, and
    # rejecting drops the very indicator/outage signal we want to surface.
    body = {'_anthropic_status': {'description': too_long}}
    assert _validate(body) is None
    desc = body['_anthropic_status']['description']
    assert len(desc) <= 128 and desc.endswith('...')
    # claude_ai_component_status is a short enum-ish field; still rejects
    # since values like "operational"/"degraded_performance" are short.
    err = _validate({'_anthropic_status': {'claude_ai_component_status': too_long}})
    assert err and 'claude_ai_component_status' in err


# ── _period_lengths ──────────────────────────────────────────────────────────

def test_period_lengths_must_be_dict():
    assert _validate({'_period_lengths': []}) == "'_period_lengths' must be an object"
    assert _validate({'_period_lengths': None}) is None
    assert _validate({'_period_lengths': {}}) is None


def test_period_lengths_key_count_boundary():
    pl_100 = {f'k{i}': 1 for i in range(100)}
    assert _validate({'_period_lengths': pl_100}) is None
    pl_101 = {f'k{i}': 1 for i in range(101)}
    assert _validate({'_period_lengths': pl_101}) == "'_period_lengths' must have ≤ 100 keys"


def test_period_lengths_value_bounds():
    assert _validate({'_period_lengths': {'k': 44640}}) is None
    err = _validate({'_period_lengths': {'k': 44641}})
    assert err and 'k' in err
    err = _validate({'_period_lengths': {'k': -1}})
    assert err and 'k' in err
    # bool subclass
    err = _validate({'_period_lengths': {'k': True}})
    assert err and 'k' in err


def test_period_lengths_key_length():
    too_long = 'x' * 129
    err = _validate({'_period_lengths': {too_long: 5}})
    assert err and 'keys must be' in err


# ── _timestamp ───────────────────────────────────────────────────────────────

def test_timestamp_accepts_int_and_float():
    # Use time.time() rather than a literal epoch: TS-1's ±1-year bound makes
    # a hard-coded historical timestamp drift out of range as wall-clock time
    # advances past the literal's first birthday.
    now = int(time.time())
    assert _validate({'_timestamp': now}) is None
    assert _validate({'_timestamp': now + 0.5}) is None
    assert _validate({'_timestamp': 0}) is None  # legacy: 0 is "missing" downstream


def test_timestamp_rejects_bool_subclass():
    # bool ⊂ int — if accepted, downstream `time.time() - True = epoch - 1`
    # and the stale-data warning fires spuriously.
    assert _validate({'_timestamp': True}) == "'_timestamp' must be a number"
    assert _validate({'_timestamp': False}) is None  # falsy → treated as missing


def test_timestamp_rejects_string():
    assert _validate({'_timestamp': '1700000000'}) == "'_timestamp' must be a number"


def test_timestamp_plausibility_bound():
    """TS-1 (pass-15 §3): an unbounded future timestamp made extension.js's
    age calc negative, bypassing every stale/broken threshold and silently
    pinning the indicator to NORMAL forever. Validator now bounds to ±1 year
    past, +1 day future."""
    now = int(time.time())
    # In-bounds
    assert _validate({'_timestamp': now - 86400}) is None       # 1 day ago
    assert _validate({'_timestamp': now - 30 * 86400}) is None  # 30 days ago
    assert _validate({'_timestamp': now + 86400 - 60}) is None  # ~1 day future
    # Future-bound: +1 week is out
    err = _validate({'_timestamp': now + 7 * 86400})
    assert err and '_timestamp' in err
    # Year-5138 attack vector from pass-15 live evidence
    err = _validate({'_timestamp': 99999999999})
    assert err and '_timestamp' in err
    # Pre-bound ancient timestamp (year 2001)
    err = _validate({'_timestamp': 1000000000})
    assert err and '_timestamp' in err
    # Legacy `timestamp` (epoch-ms) form is also bounded after ms→s conversion
    err = _validate({'timestamp': 99999999999000})
    assert err and '_timestamp' in err
    # Legacy `timestamp` in valid range (epoch-ms) accepted
    assert _validate({'timestamp': now * 1000}) is None


# ── _ext_version (V-1) ───────────────────────────────────────────────────────

def test_ext_version_accepts_semver():
    assert _validate({'_ext_version': '0.11.0'}) is None
    assert _validate({'_ext_version': '0.11.1-alpha'}) is None
    assert _validate({'_ext_version': None}) is None


def test_ext_version_length_bounded():
    assert _validate({'_ext_version': 'x' * 129}) == "_ext_version exceeds 128 chars"


def test_ext_version_type():
    err = _validate({'_ext_version': 123})
    assert err and '_ext_version' in err


# ── _schema (A-1) ────────────────────────────────────────────────────────────

def test_schema_accepts_small_int():
    assert _validate({'_schema': 0}) is None
    assert _validate({'_schema': 1}) is None
    assert _validate({'_schema': 1000}) is None


def test_schema_rejects_huge_or_bool():
    assert _validate({'_schema': 1001}) == "'_schema' must be a non-negative integer ≤ 1000"
    assert _validate({'_schema': -1}) == "'_schema' must be a non-negative integer ≤ 1000"
    assert _validate({'_schema': True}) == "'_schema' must be a non-negative integer ≤ 1000"


# ── Realistic full + partial payloads ────────────────────────────────────────

def test_full_payload_happy_path():
    body = {
        'meters': [
            {'pct': 43, 'label': 'Current session', 'reset': 'Resets in 2 hr 58 min',
             'reset_minutes': 178},
            {'pct': 41, 'label': 'All models', 'reset': 'Resets Tue 1:00 PM',
             'reset_minutes': 3600},
        ],
        'plan': 'Max',
        '_timestamp': int(time.time()),
        '_scrape_fail_count': 0,
        '_anthropic_status': {'indicator': 'none', 'description': 'All Systems Operational',
                               'claude_ai_component_status': 'operational'},
        '_ext_version': '0.11.1',
    }
    assert _validate(body) is None


def test_partial_status_only_payload():
    # Scrape-failure path: no meters, only the fail counter + status snapshot.
    body = {
        '_scrape_fail_count': 3,
        '_anthropic_status': {'indicator': 'minor', 'description': 'Elevated error rate'},
        '_ext_version': '0.11.1',
    }
    assert _validate(body) is None


def test_old_chrome_payload_accepted():
    # Backcompat: a pre-V-1 Chrome ext omits _ext_version and reset_minutes.
    # The server must accept the older shape so users on stale extensions
    # don't have their POSTs silently rejected.
    body = {
        'meters': [{'pct': 50, 'label': 'All models', 'reset': 'Resets in 1 hr 0 min'}],
        'plan': 'Max plan',
        '_timestamp': int(time.time()),
    }
    assert _validate(body) is None


# ── V-3 (pass-16 §10) — empty-string label / _period_lengths key rejection ───

def test_meter_label_must_be_non_empty():
    """An empty label would otherwise feed the eviction wipe in PL-1."""
    err = _validate({'meters': [{'pct': 50, 'label': ''}]})
    assert err and 'label' in err and 'non-empty' in err


def test_meter_label_missing_still_accepted():
    """Backcompat: meters with no `label` key (None) keep working — only the
    explicit empty-string case is rejected."""
    assert _validate({'meters': [{'pct': 50}]}) is None


def test_period_lengths_key_must_be_non_empty():
    err = _validate({'_period_lengths': {'': 100}})
    assert err and '_period_lengths' in err and 'non-empty' in err


# ── V-2 / PL-1 (pass-16 §3, §4) — do_POST merge regression harness ──────────

def _do_post(body, prev_cache=None):
    """Drive Handler.do_POST against an in-memory request and tmpdir cache.

    Mocks the BaseHTTPRequestHandler I/O surfaces (headers/rfile/wfile +
    response helpers) so we exercise the full merge path without spinning up
    an HTTPServer. Returns the parsed cache content written by the POST.
    """
    payload = json.dumps(body).encode()
    tmp = Path(tempfile.mkdtemp(prefix='claude-usage-test-merge-'))
    orig_output = _MOD.OUTPUT
    _MOD.OUTPUT = tmp / 'usage.json'
    try:
        if prev_cache is not None:
            _MOD.OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            _MOD.OUTPUT.write_text(json.dumps(prev_cache))

        class _Handler:
            headers = {
                'Content-Type': 'application/json',
                'Content-Length': str(len(payload)),
                'Origin': 'chrome-extension://fake',
            }
            rfile = io.BytesIO(payload)
            wfile = io.BytesIO()

            def send_response(self, code): self._status = code
            def send_header(self, *a, **k): pass
            def end_headers(self): pass
            def _cors(self): pass

        handler = _Handler()
        # bind do_POST as if it were a method on _Handler
        _MOD.Handler.do_POST(handler)
        # Inhibit the generate-icon.py subprocess that do_POST fires.
        # Already side-effect-isolated (icon write goes to user XDG cache),
        # but we don't read it in tests so no special handling needed beyond
        # letting it fire-and-forget. Test assertions hit OUTPUT directly.
        return json.loads(_MOD.OUTPUT.read_text())
    finally:
        _MOD.OUTPUT = orig_output


def test_unknown_top_level_keys_filtered_from_cache():
    """V-2: top-level keys not in _VALID_TOP_KEYS are stripped before merge.
    Both the prev-cache garbage and any incoming garbage must be discarded."""
    prev = {
        'meters': [{'pct': 50, 'label': 'A'}],
        '_period_lengths': {'A': 100},
        '_debug': {'old': 'data from a previous Chrome ext version'},
        'random_garbage_key': 'x' * 50,
    }
    # Partial status-only POST with one extra garbage key
    result = _do_post(
        {'_scrape_fail_count': 1, 'another_evil_key': 'y'},
        prev_cache=prev,
    )
    assert '_debug' not in result, "prev's _debug should have been filtered out"
    assert 'random_garbage_key' not in result, "prev's garbage key should have been filtered"
    assert 'another_evil_key' not in result, "body's garbage key should have been filtered"
    assert result.get('_scrape_fail_count') == 1, "legitimate body key must survive"
    assert 'A' in (result.get('_period_lengths') or {}), "legit period_lengths must survive"


def test_cache_reset_on_non_dict_prev():
    """CM-1 (pass-17): if the cache file's JSON root is not a dict (corruption,
    legacy schema, hand-edit), the merge layer must reset prev to {} rather
    than crashing on the dict-comprehension that strips unknown keys.

    CV-2/CV-3 (pass-19): test originally included a `None` case that doesn't
    exercise the reset path — `_do_post(prev_cache=None)` skips writing the
    file entirely, hitting the no-prev branch. Dropped. Also strengthened
    the assertions: verify meters lands in the cache, not just _scrape_fail_count.

    Before the fix: prev.items() raised AttributeError → every subsequent
    POST died until the user manually deleted usage.json. After the fix:
    the type check resets and the POST succeeds normally."""
    # Each case is a JSON-valid root that's NOT a dict. Excludes None
    # because the test harness skips writing a None prev_cache to disk —
    # which would test the no-prev path, not the reset path.
    for bad_prev in ([], [1, 2, 3], 'not a dict', 42):
        result = _do_post(
            {'_scrape_fail_count': 1, 'meters': [{'pct': 9, 'label': 'x'}]},
            prev_cache=bad_prev,
        )
        assert result.get('_scrape_fail_count') == 1, (
            f'POST should succeed against corrupt prev={bad_prev!r}, got {result!r}')
        # CV-4 (pass-20): subset check instead of exact equality. The intent
        # is "the meter survived the reset"; an exact-equality assertion
        # would fail if any future commit enriches meters server-side (e.g.,
        # adds a pacing_status field). Test the invariant, not the literal.
        meters = result.get('meters') or []
        assert len(meters) == 1 and meters[0].get('label') == 'x', (
            f'meters from body should land in cache after reset; '
            f'corrupt prev={bad_prev!r}, got {meters!r}')
        assert '_schema' in result, (
            f'server stamps _schema on every write; missing after reset path '
            f'(corrupt prev={bad_prev!r})')


def test_partial_post_does_not_wipe_period_lengths():
    """PL-1: a single-meter POST without _timestamp / with < 2 meters should
    NOT evict the period_lengths accumulator. Previously, any POST with
    `meters` set wiped every label not in that POST."""
    prev = {
        'meters': [
            {'pct': 50, 'label': 'Current session'},
            {'pct': 50, 'label': 'All models'},
        ],
        '_period_lengths': {'Current session': 295, 'All models': 9680},
    }
    # Single-meter "fake" POST — mimics a malicious or buggy ext payload.
    # No _timestamp set → not a "full scrape" → eviction must skip.
    result = _do_post(
        {'meters': [{'pct': 0, 'label': 'fake-meter'}]},
        prev_cache=prev,
    )
    pl = result.get('_period_lengths') or {}
    assert 'Current session' in pl, "Current session period must survive partial POST"
    assert 'All models' in pl, "All models period must survive partial POST"


def test_full_scrape_still_evicts_renamed_labels():
    """Eviction still fires on a legit full scrape so a renamed-by-Anthropic
    meter eventually drops out of the accumulator."""
    prev = {
        'meters': [{'pct': 50, 'label': 'OldName'}],
        '_period_lengths': {'OldName': 100, 'AnotherOld': 200},
    }
    result = _do_post(
        {
            'meters': [
                {'pct': 50, 'label': 'NewName', 'reset_minutes': 100},
                {'pct': 50, 'label': 'OtherNew', 'reset_minutes': 200},
            ],
            '_timestamp': int(time.time()),
        },
        prev_cache=prev,
    )
    pl = result.get('_period_lengths') or {}
    assert 'OldName' not in pl, "renamed label should be evicted on full scrape"
    assert 'AnotherOld' not in pl, "stale label should be evicted on full scrape"
    assert 'NewName' in pl and pl['NewName'] == 100
    assert 'OtherNew' in pl and pl['OtherNew'] == 200
