"""Tests for usage_core.load_ui_config / write_ui_config — the config layer the
macOS preferences window round-trips. Pure Python (no cairo/PIL/PyObjC)."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'server'))

import usage_core  # noqa: E402 — needs server/ on sys.path first


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """Point config_path() at a temp XDG_CONFIG_HOME; return the config.json path."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    return tmp_path / 'claude-usage' / 'config.json'


def test_write_then_load_roundtrip(cfg_file):
    usage_core.write_ui_config({'threshold_warning': 55, 'popup_color_normal': '#123456'})
    cfg = usage_core.load_ui_config()
    assert cfg['threshold_warning'] == 55
    assert cfg['popup_color_normal'] == '#123456'


def test_second_write_preserves_first_key(cfg_file):
    usage_core.write_ui_config({'threshold_warning': 55})
    usage_core.write_ui_config({'threshold_critical': 88})
    raw = json.loads(cfg_file.read_text())
    assert raw['threshold_warning'] == 55
    assert raw['threshold_critical'] == 88


def test_write_drops_invalid_and_unknown(cfg_file):
    usage_core.write_ui_config({
        'threshold_warning': 9999,            # out of range [1, 500]
        'popup_color_normal': 'notacolor',    # invalid hex
        'unknown_key': 'x',                   # not a schema key
        'bar_width': 12,                      # valid → kept
    })
    raw = json.loads(cfg_file.read_text())
    assert 'threshold_warning' not in raw
    assert 'popup_color_normal' not in raw
    assert 'unknown_key' not in raw
    assert raw['bar_width'] == 12


def test_write_is_0600(cfg_file):
    usage_core.write_ui_config({'bar_width': 12})
    assert oct(cfg_file.stat().st_mode)[-3:] == '600'


def test_write_coerces_str_int(cfg_file):
    # NSStepper/intValue may arrive as a string; _coerce int()s it.
    usage_core.write_ui_config({'threshold_critical': '95'})
    assert usage_core.load_ui_config()['threshold_critical'] == 95


def test_load_invalid_falls_back_to_default(cfg_file):
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text('{"threshold_warning": 0, "popup_color_normal": "zzz"}')
    cfg = usage_core.load_ui_config()
    assert cfg['threshold_warning'] == usage_core._SCHEMA_DEFAULTS['threshold_warning']
    assert cfg['popup_color_normal'] == usage_core._SCHEMA_DEFAULTS['popup_color_normal']


def test_write_preserves_unmanaged_existing_key(cfg_file):
    # A key written by another tool (e.g. a ring colour) must survive a prefs write.
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text('{"weekly_color_green": "#abcdef"}')
    usage_core.write_ui_config({'threshold_warning': 60})
    raw = json.loads(cfg_file.read_text())
    assert raw['weekly_color_green'] == '#abcdef'
    assert raw['threshold_warning'] == 60
