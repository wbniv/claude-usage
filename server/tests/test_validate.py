"""Pytest coverage for usage-server.py::_validate.

Imports the hyphenated module via importlib because Python's import system
rejects 'usage-server' as a module name. The test file stays small and
focused — one test per numbered failure path in the validator + happy paths.
"""
import importlib.util
import sys
from pathlib import Path

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


def test_anthropic_status_indicator_whitelist():
    valid = (None, 'none', 'minor', 'major', 'critical', 'maintenance')
    for v in valid:
        assert _validate({'_anthropic_status': {'indicator': v}}) is None, f"rejected valid {v!r}"
    err = _validate({'_anthropic_status': {'indicator': 'whatever'}})
    assert err and 'indicator' in err


def test_anthropic_status_field_lengths():
    too_long = 'x' * 129
    err = _validate({'_anthropic_status': {'description': too_long}})
    assert err and 'description' in err
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
    assert err and 'keys must be strings' in err


# ── _timestamp ───────────────────────────────────────────────────────────────

def test_timestamp_accepts_int_and_float():
    assert _validate({'_timestamp': 1700000000}) is None
    assert _validate({'_timestamp': 1700000000.5}) is None
    assert _validate({'_timestamp': 0}) is None  # legacy: 0 is "missing" downstream


def test_timestamp_rejects_bool_subclass():
    # bool ⊂ int — if accepted, downstream `time.time() - True = epoch - 1`
    # and the stale-data warning fires spuriously.
    assert _validate({'_timestamp': True}) == "'_timestamp' must be a number"
    assert _validate({'_timestamp': False}) is None  # falsy → treated as missing


def test_timestamp_rejects_string():
    assert _validate({'_timestamp': '1700000000'}) == "'_timestamp' must be a number"


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
        '_timestamp': 1779000000,
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
        '_timestamp': 1779000000,
    }
    assert _validate(body) is None
