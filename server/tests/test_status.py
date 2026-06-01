"""Regression tests for scripts/claude-usage-status.py corrupt-cache hardening.

STAT-1 (pass-29): the diagnostic reads usage.json BEFORE any new POST, so a
hand-edited / downgraded cache can carry a non-numeric _timestamp,
_scrape_fail_count, or meter pct. Before the fix those flowed into arithmetic
(`time.time() - "x"`), a comparison (`"5" >= 2`), or an int format spec
(`f'{"x":3d}'`) and raised an uncaught exception — crashing the very tool a
user runs when their setup is broken.
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope='module')
def status_mod():
    spec = importlib.util.spec_from_file_location(
        'claude_usage_status', REPO / 'scripts/claude-usage-status.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _point_at(status_mod, tmp_path, monkeypatch, payload):
    p = tmp_path / 'usage.json'
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(status_mod, 'CACHE_JSON', p)


def test_check_cache_survives_non_numeric_timestamp(status_mod, tmp_path, monkeypatch, capsys):
    # Before the fix: `time.time() - "not-a-number"` → uncaught TypeError.
    _point_at(status_mod, tmp_path, monkeypatch, {
        '_timestamp': 'not-a-number', 'plan': 'Max', 'meters': [],
    })
    status_mod._check_cache()  # must not raise
    assert 'Cache:' in capsys.readouterr().out


def test_check_cache_survives_non_int_scrape_fail_and_pct(status_mod, tmp_path, monkeypatch, capsys):
    # Before the fix: `"5" >= 2` and `f'{"high":3d}'` → TypeError / ValueError.
    _point_at(status_mod, tmp_path, monkeypatch, {
        '_timestamp': 0, '_scrape_fail_count': '5',
        'meters': [{'label': 'All models', 'pct': 'high'}],
    })
    status_mod._check_cache()  # must not raise
    assert 'Meter:' in capsys.readouterr().out


def test_check_cache_normal_payload(status_mod, tmp_path, monkeypatch, capsys):
    _point_at(status_mod, tmp_path, monkeypatch, {
        '_timestamp': 0, '_scrape_fail_count': 0, 'plan': 'Max',
        'meters': [{'label': 'All models', 'pct': 42}],
    })
    status_mod._check_cache()
    out = capsys.readouterr().out
    assert 'All models' in out and '42%' in out
