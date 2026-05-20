"""Schema-defaults SOT tests.

Verifies that every Python consumer that previously hand-copied gschema
constants now reads them from server/schema_defaults — and the values match.
A failure here means someone re-introduced a hardcoded literal that's
expected to match the schema; fix it before merging.

This is the drift-detector for the architectural fix that closes pass-17
DG-1, DR-2, DR-4 (and any future variant of the same class). It runs in
the regular `task test` aggregate via pytest discovery.
"""
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'server'))
sys.path.insert(0, str(REPO / 'scripts'))

# Stub heavy imports that generate-icon.py pulls (mirrors test_pacing.py).
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

_TMP_XDG = Path(tempfile.mkdtemp(prefix='claude-usage-test-schema-'))
_ICON_DIR = _TMP_XDG / 'gnome-shell/extensions/claude-usage@indri.studio/icons'
_ICON_DIR.mkdir(parents=True, exist_ok=True)
(_ICON_DIR / 'claude-64.png').touch()
os.environ['XDG_DATA_HOME'] = str(_TMP_XDG)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def schema():
    return _load('schema_defaults', REPO / 'server/schema_defaults.py')


@pytest.fixture(scope='module')
def generate_icon():
    return _load('generate_icon', REPO / 'server/generate-icon.py')


@pytest.fixture(scope='module')
def doc_render():
    return _load('_doc_render', REPO / 'scripts/_doc_render.py')


# ── schema_defaults sanity ──────────────────────────────────────────────────


def test_schema_loads_all_expected_keys(schema):
    """If a new key is added to the gschema, this test will start passing
    a larger set — bump the expected list deliberately. Failing here means
    a key was REMOVED from the schema, which deserves a deliberate update."""
    expected = {
        'weekly_color_green', 'weekly_color_amber', 'weekly_color_red',
        'sonnet_color',
        'popup_color_normal', 'popup_color_warning', 'popup_color_critical',
        'threshold_warning', 'threshold_critical',
        'bar_width',
        'panel_color_normal', 'panel_color_warning', 'panel_color_critical',
        'panel_font_size', 'panel_label_spacing', 'panel_icon_size',
        'popup_font_size', 'popup_font_family',
        'panel_metric',
    }
    assert expected.issubset(schema.DEFAULTS.keys())


def test_schema_color_keys_are_hex(schema):
    """Every color default in the schema is a #rrggbb string."""
    import re
    color_keys = [k for k in schema.DEFAULTS if 'color' in k]
    assert color_keys, 'expected at least one color key'
    for k in color_keys:
        v = schema.DEFAULTS[k]
        assert re.match(r'^#[0-9a-fA-F]{6}$', v), f'{k}={v!r} is not #rrggbb'


def test_schema_numeric_keys_have_ranges(schema):
    """Every uint key with a range exposes it in RANGES."""
    for k in ('threshold_warning', 'threshold_critical', 'bar_width',
              'panel_font_size', 'panel_label_spacing', 'popup_font_size',
              'panel_icon_size'):
        assert k in schema.RANGES, f'{k} missing from RANGES'
        lo, hi = schema.RANGES[k]
        assert lo < hi, f'{k} range malformed: {lo}..{hi}'
        assert lo <= schema.DEFAULTS[k] <= hi, (
            f'{k} default {schema.DEFAULTS[k]} outside range [{lo},{hi}]')


# ── consumer parity ─────────────────────────────────────────────────────────


def test_generate_icon_defaults_match_schema(schema, generate_icon):
    """generate-icon.py's DEFAULTS dict must match the schema for every key
    it carries. Closes pass-17 DG-1 (was 50/80, schema is 70/90)."""
    for k, expected in schema.DEFAULTS.items():
        if k in generate_icon.DEFAULTS:
            assert generate_icon.DEFAULTS[k] == expected, (
                f'generate-icon.py DEFAULTS[{k!r}]={generate_icon.DEFAULTS[k]!r} '
                f'but schema says {expected!r}')


def test_doc_render_default_cfg_matches_schema(schema, doc_render):
    """_doc_render.default_cfg() must return schema-derived values for every
    constant it exposes. Closes pass-17 DR-4."""
    cfg = doc_render.default_cfg()
    assert cfg['tWarn'] == schema.DEFAULTS['threshold_warning']
    assert cfg['tCrit'] == schema.DEFAULTS['threshold_critical']
    assert cfg['popupNorm'] == schema.DEFAULTS['popup_color_normal']
    assert cfg['popupWarn'] == schema.DEFAULTS['popup_color_warning']
    assert cfg['popupCrit'] == schema.DEFAULTS['popup_color_critical']
    assert cfg['panelNorm'] == schema.DEFAULTS['panel_color_normal']
    assert cfg['panelWarn'] == schema.DEFAULTS['panel_color_warning']
    assert cfg['panelCrit'] == schema.DEFAULTS['panel_color_critical']
    assert cfg['barWidth']  == schema.DEFAULTS['bar_width']
