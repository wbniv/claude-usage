"""Tests for generate-icon.py's derive_tier, ring_color, hex_to_rgba.

Closes pass-17 T-1 partially. Passes 14–16 found real bugs in derive_tier
(V-3 empty-string status, AS-1 forward-compat indicator) and ring_color
(threshold boundaries). The regression net was missing.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'server'))

# Stub cairo + PIL — same recipe as test_pacing.py + test_schema_defaults.py.
for _name in ('cairo',):
    sys.modules.setdefault(_name, types.ModuleType(_name))
_pil = types.ModuleType('PIL')
_pil_image = types.ModuleType('PIL.Image')
_pil_image.LANCZOS = 1
_pil.Image = _pil_image
_pil.ImageOps = types.ModuleType('PIL.ImageOps')
sys.modules.setdefault('PIL', _pil)
sys.modules.setdefault('PIL.Image', _pil_image)
sys.modules.setdefault('PIL.ImageOps', _pil.ImageOps)

_TMP_XDG = Path(tempfile.mkdtemp(prefix='claude-usage-test-icon-'))
_ICON_DIR = _TMP_XDG / 'gnome-shell/extensions/claude-usage@indri.studio/icons'
_ICON_DIR.mkdir(parents=True, exist_ok=True)
(_ICON_DIR / 'claude-64.png').touch()
os.environ['XDG_DATA_HOME'] = str(_TMP_XDG)


@pytest.fixture(scope='module')
def g():
    spec = importlib.util.spec_from_file_location(
        'generate_icon_mod', REPO / 'server/generate-icon.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── derive_tier ──────────────────────────────────────────────────────────────

def test_derive_tier_normal_empty_dict(g):
    assert g.derive_tier({}) == 'normal'


def test_derive_tier_normal_explicit_good(g):
    data = {
        '_anthropic_status': {
            'indicator': 'none',
            'claude_ai_component_status': 'operational',
        },
        '_scrape_fail_count': 0,
    }
    assert g.derive_tier(data) == 'normal'


def test_derive_tier_broken_indicator_minor(g):
    data = {'_anthropic_status': {'indicator': 'minor'}}
    assert g.derive_tier(data) == 'broken'


def test_derive_tier_broken_indicator_unknown(g):
    """AS-1 (pass-15): forward-compat — any non-'none' indicator is broken."""
    data = {'_anthropic_status': {'indicator': 'investigating'}}
    assert g.derive_tier(data) == 'broken'


def test_derive_tier_empty_string_indicator_is_normal(g):
    """V-3 (pass-17): empty string used to flip to broken. Should now
    normalize via `or 'none'` to safe value."""
    data = {'_anthropic_status': {'indicator': ''}}
    assert g.derive_tier(data) == 'normal'


def test_derive_tier_empty_string_component_is_normal(g):
    """V-3 (pass-17): same for claude_ai_component_status."""
    data = {'_anthropic_status': {'claude_ai_component_status': ''}}
    assert g.derive_tier(data) == 'normal'


def test_derive_tier_broken_component_degraded(g):
    data = {'_anthropic_status': {'claude_ai_component_status': 'degraded_performance'}}
    assert g.derive_tier(data) == 'broken'


def test_derive_tier_broken_scrape_fail_count(g):
    assert g.derive_tier({'_scrape_fail_count': 2}) == 'broken'
    assert g.derive_tier({'_scrape_fail_count': 5}) == 'broken'


def test_derive_tier_normal_one_scrape_fail(g):
    """Single fail is transient, not broken."""
    assert g.derive_tier({'_scrape_fail_count': 1}) == 'normal'


def test_derive_tier_safe_on_corrupt_scrape_fail_count(g):
    """DT-1 (pass-18): a pre-existing corrupt cache (e.g. from a downgrade
    or hand-edit) might carry a non-int _scrape_fail_count. Validator
    rejects on POST, but the on-disk cache reads BEFORE any new POST
    arrives. Don't TypeError; treat as the safe value."""
    # Before the fix: `"5" >= 2` → TypeError
    assert g.derive_tier({'_scrape_fail_count': '5'}) == 'normal'
    assert g.derive_tier({'_scrape_fail_count': True}) == 'normal'  # bool ⊂ int
    assert g.derive_tier({'_scrape_fail_count': None}) == 'normal'
    assert g.derive_tier({'_scrape_fail_count': [1, 2, 3]}) == 'normal'


# ── ring_color ───────────────────────────────────────────────────────────────

def test_ring_color_below_warn_is_green(g):
    cfg = dict(g.DEFAULTS)  # threshold_warning=70, threshold_critical=90
    assert g.ring_color(0,  cfg) == g.hex_to_rgba(cfg['weekly_color_green'])
    assert g.ring_color(69, cfg) == g.hex_to_rgba(cfg['weekly_color_green'])


def test_ring_color_at_warn_is_amber(g):
    cfg = dict(g.DEFAULTS)
    assert g.ring_color(70, cfg) == g.hex_to_rgba(cfg['weekly_color_amber'])
    assert g.ring_color(89, cfg) == g.hex_to_rgba(cfg['weekly_color_amber'])


def test_ring_color_at_crit_is_red(g):
    cfg = dict(g.DEFAULTS)
    assert g.ring_color(90,  cfg) == g.hex_to_rgba(cfg['weekly_color_red'])
    assert g.ring_color(150, cfg) == g.hex_to_rgba(cfg['weekly_color_red'])


# ── hex_to_rgba ──────────────────────────────────────────────────────────────

def test_hex_to_rgba_eight_digit_alpha(g):
    # BASE-5 (2026-05-30 review): an 8-digit #RRGGBBAA honours the alpha channel
    # (was silently forced to opaque).
    r, gn, b, a = g.hex_to_rgba('#4dbfff80')
    assert (r, gn, b) == (0x4d / 255, 0xbf / 255, 0xff / 255)
    assert abs(a - 0x80 / 255) < 1e-9


def test_hex_to_rgba_six_digit_stays_opaque(g):
    assert g.hex_to_rgba('#4dbfff')[3] == 1.0


def test_config_json_non_int_threshold_coerced(g, tmp_path, monkeypatch):
    # DIFF-4 (2026-05-30 review): a non-int threshold in config.json must be
    # coerced to the default, not flow into ring_color's numeric comparison
    # (which was `int >= str` → TypeError, aborting every icon render). The
    # GSettings path is immune (get_uint); only the JSON path needed the guard.
    cfgdir = tmp_path / 'claude-usage'
    cfgdir.mkdir()
    (cfgdir / 'config.json').write_text(json.dumps({
        'threshold_warning': 'low', 'threshold_critical': 'high',
        'weekly_color_red': '#ff5933',
    }))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    cfg = g.load_config()
    assert isinstance(cfg['threshold_warning'], int)
    assert isinstance(cfg['threshold_critical'], int)
    g.ring_color(95, cfg)  # must not raise (was TypeError)


def test_config_json_out_of_range_threshold_falls_back(g, tmp_path, monkeypatch):
    """ICN-1 (pass-29): a threshold outside the gschema range (1..500) in a
    hand-edited config.json must fall back to the default — else
    threshold_warning:0 makes ring_color() read every meter as warning."""
    cfgdir = tmp_path / 'claude-usage'
    cfgdir.mkdir()
    (cfgdir / 'config.json').write_text(json.dumps({
        'threshold_warning': 0, 'threshold_critical': 9999,
    }))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    cfg = g.load_config()
    assert cfg['threshold_warning'] == g.DEFAULTS['threshold_warning']
    assert cfg['threshold_critical'] == g.DEFAULTS['threshold_critical']


def test_load_config_schema_absent_falls_back(g, tmp_path, monkeypatch):
    """SRV-1 (pass-29): with no config.json and the gschema unregistered,
    load_config() must return DEFAULTS, not abort. _gsettings_or_none()
    returns None for a missing schema (via SettingsSchemaSource.lookup, which
    returns None instead of the uncatchable SIGTRAP that Gio.Settings.new()
    raises on an unregistered schema id)."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))  # no config.json present
    monkeypatch.setattr(g, '_gsettings_or_none', lambda: None)
    cfg = g.load_config()
    assert cfg == dict(g.DEFAULTS)


def test_hex_to_rgba_with_hash(g):
    r, gn, b, a = g.hex_to_rgba('#ff0000')
    assert r == 1.0
    assert gn == 0.0
    assert b  == 0.0
    assert a  == 1.0


def test_hex_to_rgba_without_hash(g):
    """Caller convenience: accept either '#abcdef' or 'abcdef'."""
    r, gn, b, _ = g.hex_to_rgba('00ff00')
    assert gn == 1.0


def test_hex_to_rgba_mixed_case(g):
    r, _, _, _ = g.hex_to_rgba('#FfAa00')
    assert abs(r - 1.0) < 1e-6
