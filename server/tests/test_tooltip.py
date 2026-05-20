"""Tests for tooltip.parse_reset + format_tooltip.

Closes pass-17 T-1 partially: passes 14–16 fixed real bugs in these
(TS-1, D-1, AS-1, WP-1 — live-countdown path, day-of-week parsing,
empty meters) and the regression guard has been missing. Add at minimum
one test per regex branch + the live-countdown path + the empty cases.
"""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'server'))

spec = importlib.util.spec_from_file_location(
    'tooltip_mod', REPO / 'server/tooltip.py')
_t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_t)


# ── parse_reset: format dispatch ────────────────────────────────────────────

def test_parse_reset_empty_returns_none():
    assert _t.parse_reset('') is None
    assert _t.parse_reset(None) is None


def test_parse_reset_hour_minute_form():
    is_countdown, display = _t.parse_reset('Resets in 3 hr 47 min')
    assert is_countdown is True
    assert display == '3:47'


def test_parse_reset_minute_only_form():
    is_countdown, display = _t.parse_reset('Resets in 45 min')
    assert is_countdown is True
    assert display == '0:45'


def test_parse_reset_minute_pads_to_two_digits():
    _, display = _t.parse_reset('Resets in 5 min')
    assert display == '0:05'


def test_parse_reset_day_time_form():
    """`Resets Tue 1:00 PM` format — countdown-or-day depending on how far
    out it is. parse_reset itself doesn't render the day name; the test
    just confirms the regex matches and returns a non-None tuple."""
    result = _t.parse_reset('Resets Tue 1:00 PM')
    assert result is not None
    is_countdown, display = result
    # Either a countdown ("H:MM") if Tue 1pm is within 12h, or a day-time
    # label otherwise. Both forms include a colon.
    assert ':' in display


def test_parse_reset_unknown_day_returns_none():
    """V-3 sibling: a locale-translated day (e.g. German 'Di') falls
    through to None so caller can show the raw string."""
    assert _t.parse_reset('Resets Foo 1:00 PM') is None


def test_parse_reset_unrecognized_format_returns_none():
    assert _t.parse_reset('Resets Jun 1') is None
    assert _t.parse_reset('Some other string') is None


# ── parse_reset: live countdown path (reset_minutes + anchor_ts) ────────────

def test_parse_reset_live_countdown_freshly_scraped():
    """At the moment of scrape (elapsed_min=0), the countdown matches
    reset_minutes exactly."""
    anchor = time.time()
    is_countdown, display = _t.parse_reset(
        'Resets in 2 hr 37 min', reset_minutes=157, anchor_ts=anchor)
    assert is_countdown is True
    assert display == '2:37'


def test_parse_reset_live_countdown_after_drift():
    """After 30 min of elapsed time, the countdown has counted down by 30."""
    anchor = time.time() - 30 * 60
    _, display = _t.parse_reset(
        'Resets in 2 hr 37 min', reset_minutes=157, anchor_ts=anchor)
    # 157 - 30 = 127 min = 2:07
    assert display == '2:07'


def test_parse_reset_live_countdown_floors_at_zero():
    """A scrape that was hours ago shouldn't yield negative remaining."""
    anchor = time.time() - 10 * 3600  # 10h ago
    _, display = _t.parse_reset(
        'Resets in 1 hr 0 min', reset_minutes=60, anchor_ts=anchor)
    assert display == '0:00'


# ── format_tooltip ──────────────────────────────────────────────────────────

def test_format_tooltip_empty_meters():
    assert _t.format_tooltip([]) == 'Claude Usage'


def test_format_tooltip_with_meters():
    meters = [
        {'label': 'Current session', 'pct': 9, 'reset': 'Resets in 3 hr 47 min'},
        {'label': 'All models', 'pct': 4, 'reset': ''},
    ]
    out = _t.format_tooltip(meters)
    assert 'Claude Usage' in out
    assert '✴' in out
    assert 'current 9%' in out
    assert 'all 4%' in out


def test_format_tooltip_skips_zero_sonnet():
    """Sonnet at 0% is hidden everywhere; tooltip should follow suit."""
    meters = [
        {'label': 'Current session', 'pct': 9},
        {'label': 'Sonnet only', 'pct': 0},
    ]
    out = _t.format_tooltip(meters)
    assert 'sonnet' not in out


def test_format_tooltip_shows_nonzero_sonnet():
    meters = [
        {'label': 'Current session', 'pct': 9},
        {'label': 'Sonnet only', 'pct': 6},
    ]
    out = _t.format_tooltip(meters)
    assert 'sonnet 6%' in out


def test_format_tooltip_no_recognizable_meters():
    """No 'session'/'current'/'all' substring match → fallback title."""
    meters = [{'label': 'Mysterious', 'pct': 5}]
    out = _t.format_tooltip(meters)
    assert out == 'Claude Usage'
