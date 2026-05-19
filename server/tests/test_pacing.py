"""Pytest coverage for generate-icon.py::pacing_pct.

Regression guard for the 0.11.14 fix: a single Opus turn (3 % pct, 6 min into
a 295 min Current session period) used to pace to ~150 % under the previous
fraction <= 0.01 floor, tripping the panel-label red. The replacement floor
is a 15-min minimum elapsed.

Imports the hyphenated module via importlib (same pattern as test_validate.py).
Stubs cairo + PIL + tooltip before exec so the test runs on a bare runner
without the .deb's runtime deps (CI runs pytest outside the docker image
that has python3-cairo/python3-pil installed).
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

# Stub the heavy module-load imports — pacing_pct is pure Python and touches
# none of them. Mirrors the pattern in docs/plans/screenshots/.../render-mockups.py.
_stub_cairo = types.ModuleType('cairo')
sys.modules.setdefault('cairo', _stub_cairo)

_stub_image = types.ModuleType('PIL.Image')
_stub_image.LANCZOS = 1  # generate-icon.py reads getattr(Image, 'Resampling', Image).LANCZOS
_stub_imageops = types.ModuleType('PIL.ImageOps')
_stub_pil = types.ModuleType('PIL')
_stub_pil.Image = _stub_image
_stub_pil.ImageOps = _stub_imageops
sys.modules.setdefault('PIL', _stub_pil)
sys.modules.setdefault('PIL.Image', _stub_image)
sys.modules.setdefault('PIL.ImageOps', _stub_imageops)

_stub_tooltip = types.ModuleType('tooltip')
_stub_tooltip.update_desktop = lambda *a, **k: None
sys.modules.setdefault('tooltip', _stub_tooltip)

_SPEC = importlib.util.spec_from_file_location(
    'generate_icon',
    _SERVER_DIR / 'generate-icon.py',
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
pacing_pct = _MOD.pacing_pct


# ── Regression: live capture from the 19:40 incident ─────────────────────────

def test_session_3pct_at_6min_does_not_pace():
    """The case that prompted the fix: 3 % usage 6 min into a 295 min session.
    Old floor (fraction <= 0.01 → 3 min) lets pacing fire → 147.5 %. New floor
    (elapsed < 15 min) suppresses it → returns raw 3."""
    meter = {'label': 'Current session', 'pct': 3, 'reset_minutes': 289}
    assert pacing_pct(meter, {'Current session': 295}) == 3


# ── Floor boundary cases ────────────────────────────────────────────────────

@pytest.mark.parametrize('elapsed_min,expect_suppressed', [
    (0, True),
    (1, True),
    (14, True),     # one below boundary
    (15, False),    # boundary — pacing kicks in
    (16, False),
    (60, False),
])
def test_15_minute_boundary(elapsed_min, expect_suppressed):
    period = 295
    meter = {
        'label': 'Current session',
        'pct': 5,
        'reset_minutes': period - elapsed_min,
    }
    result = pacing_pct(meter, {'Current session': period})
    if expect_suppressed:
        assert result == 5, f"elapsed={elapsed_min}min should suppress, got pacing={result}"
    else:
        # 5% in a fraction of the period — pacing strictly greater than raw pct.
        assert result > 5, f"elapsed={elapsed_min}min should pace, got {result}"


# ── Weekly bucket: 15 min on a week is barely 0.15 %; pacing fires hot ──────

def test_weekly_bucket_at_16min_paces():
    """The weekly bucket loses ~82 min of suppression vs the old 1 % floor,
    but that's fine: at minute 16 of a week, raw pct is small enough that
    pacing only crosses 90 if usage is genuinely extreme."""
    meter = {'label': 'All models', 'pct': 9, 'reset_minutes': 9680 - 16}
    result = pacing_pct(meter, {'All models': 9680})
    # 9 / (16/9680) ≈ 5445 — clearly hot, which is correct: 9 % in 16 min IS
    # extreme usage on a weekly bucket and the user should see a warning.
    assert result > 1000


# ── Pass-throughs ───────────────────────────────────────────────────────────

def test_zero_pct_returns_zero():
    meter = {'label': 'Current session', 'pct': 0, 'reset_minutes': 100}
    assert pacing_pct(meter, {'Current session': 295}) == 0


def test_missing_reset_minutes_returns_raw_pct():
    meter = {'label': 'Sonnet only', 'pct': 42}
    assert pacing_pct(meter, {'Sonnet only': 9680}) == 42


def test_missing_period_returns_raw_pct():
    meter = {'label': 'Unknown', 'pct': 42, 'reset_minutes': 100}
    assert pacing_pct(meter, {}) == 42


def test_none_meter_returns_zero():
    assert pacing_pct(None, {}) == 0


def test_non_int_pct_returns_falsy():
    """pacing_pct's input contract is integer pct; the float path is unused."""
    meter = {'label': 'Current session', 'pct': None, 'reset_minutes': 100}
    assert pacing_pct(meter, {'Current session': 295}) == 0
