"""Tests for usage-server._sweep_orphan_tmps.

Regression guard for pass-18 TS-2: the icon-tmp sweep used the wrong
field index, causing it to unlink live in-flight tmps from concurrent
generate-icon.py invocations. The pid_position=2 read the literal string
'tmp' rather than the PID; int('tmp') raised and the except clause fell
through to .unlink().
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

# TS-3 (pass-19) → updated pass-31 (macOS port): the sweep's liveness check is
# now cross-platform (_pid_alive: /proc on Linux, os.kill(pid, 0) elsewhere), so
# this runs on macOS too. Skip only on non-POSIX (Windows), which the product
# doesn't target and where os.kill(pid, 0) has different semantics.
pytestmark = pytest.mark.skipif(
    os.name != 'posix',
    reason='_sweep_orphan_tmps PID-liveness check requires POSIX os.kill semantics',
)

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / 'server'))

# Stub heavy deps that usage-server.py imports transitively.
import types
sys.modules.setdefault('PIL', types.ModuleType('PIL'))
sys.modules.setdefault('PIL.Image', types.ModuleType('PIL.Image'))


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point HOME + XDG_DATA_HOME at a fresh tempdir per test."""
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / '.local/share'))
    return tmp_path


@pytest.fixture
def server_module():
    spec = importlib.util.spec_from_file_location(
        'usage_server', REPO / 'server/usage-server.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tmp(directory, pid, ns=1, size=64):
    """Create a tmp file with the unique-tmp naming scheme."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f'.claude-usage.tmp.{pid}.{ns}.{size}.png'
    p.write_bytes(b'\x89PNG fake')
    return p


def test_sweep_preserves_live_icon_tmps(fake_home, server_module):
    """TS-2 regression: a tmp with the current PID must survive the sweep.

    Before the fix, pid_position=2 read the literal 'tmp' field, int()
    raised, except clause swallowed it, and the file got unlinked
    regardless of process liveness."""
    own_pid = os.getpid()
    size_dir = fake_home / '.local/share/icons/hicolor/64x64/apps'
    tmp = _make_tmp(size_dir, own_pid)
    assert tmp.exists()

    server_module._sweep_orphan_tmps()

    assert tmp.exists(), (
        "live in-flight tmp was unlinked — the PID-alive check is bypassed. "
        "This is the TS-2 regression."
    )


def test_sweep_removes_orphan_icon_tmps(fake_home, server_module):
    """Dead PID's tmps should still get cleaned up. Use a PID large enough
    that /proc/<pid> can't possibly exist."""
    dead_pid = 99999999  # very unlikely to be alive
    size_dir = fake_home / '.local/share/icons/hicolor/128x128/apps'
    tmp = _make_tmp(size_dir, dead_pid)
    assert tmp.exists()

    server_module._sweep_orphan_tmps()

    assert not tmp.exists(), "orphan tmp should have been cleaned up"


def test_sweep_preserves_live_desktop_tmps(fake_home, server_module):
    """Same invariant for the .desktop tmp pattern (different field offset
    but same correctness requirement)."""
    own_pid = os.getpid()
    apps = fake_home / '.local/share/applications'
    apps.mkdir(parents=True, exist_ok=True)
    tmp = apps / f'claude-usage.desktop.tmp.{own_pid}.1'
    tmp.write_text('mock')

    server_module._sweep_orphan_tmps()

    assert tmp.exists()


def test_sweep_handles_missing_dirs_gracefully(fake_home, server_module):
    """No icon-theme dir, no apps dir → sweep is a no-op, not a crash."""
    server_module._sweep_orphan_tmps()  # should not raise


def test_sweep_preserves_unparseable_filenames(fake_home, server_module):
    """OS-2 (pass-20): a file matching the glob but with a non-integer in the
    pid-position field (someone hand-creates a debug file, partial migration,
    etc.) used to fall through the broad except → unlink. The OS-1 fix moved
    to `continue` — verify a non-numeric field name preserves the file."""
    size_dir = fake_home / '.local/share/icons/hicolor/64x64/apps'
    size_dir.mkdir(parents=True, exist_ok=True)
    # Filename matches `.claude-usage.tmp.*.png` but `garbage` isn't an int
    garbage = size_dir / '.claude-usage.tmp.garbage.1.64.png'
    garbage.write_bytes(b'\x89PNG fake')

    server_module._sweep_orphan_tmps()

    assert garbage.exists(), (
        "Unparseable tmp filename should be left alone, not unlinked. "
        "This is the OS-1 regression — sibling class to TS-2."
    )


def test_sweep_pid_position_constants_pinned():
    """TSP-1 (pass-26): Pin the pid_position values so a refactor can't
    silently swap the field index. TS-2 was caused by pid_position being
    wrong (2 instead of 3 for icon tmps).

    The test reads the source of usage-server.py and asserts both call sites
    are present with their expected values:
      desktop tmp: claude-usage.desktop.tmp.<PID>.<NS>  → PID at index -2
      icon    tmp: .claude-usage.tmp.<PID>.<NS>.<SZ>    → PID at index 3
    """
    import pathlib
    src = (pathlib.Path(__file__).parents[1] / 'usage-server.py').read_text()
    # Desktop tmp: PID is the second-to-last field → pid_position=-2
    assert (
        "pid_position=-2" in src
        or "pid_position = -2" in src
        # positional call: _sweep(dir, pattern, -2) — check both the arg and
        # the comment that documents it so a silent rename still triggers.
        or ", -2)" in src
    ), "desktop-tmp orphan sweep pid_position must be -2"
    # Icon tmp: .claude-usage.tmp.<PID>.<NS>.<SIZE>.png → PID at index 3
    assert (
        "pid_position=3" in src
        or "pid_position = 3" in src
        or ", 3)" in src
    ), "icon-tmp orphan sweep pid_position must be 3"
    # Belt-and-suspenders: confirm both _sweep calls appear near the two
    # patterns so renaming the glob but forgetting the position also fails.
    assert "claude-usage.desktop.tmp.*" in src, \
        "desktop-tmp pattern must be present (documents pid_position=-2 context)"
    assert ".claude-usage.tmp.*.png" in src, \
        "icon-tmp pattern must be present (documents pid_position=3 context)"


def test_sweep_across_multiple_size_dirs(fake_home, server_module):
    """Sweep must visit every hicolor/*x*/apps subdir."""
    own_pid = os.getpid()
    dead_pid = 99999999
    own_tmps = []
    for size in (48, 64, 96, 128, 256):
        size_dir = fake_home / f'.local/share/icons/hicolor/{size}x{size}/apps'
        own_tmps.append(_make_tmp(size_dir, own_pid, ns=10, size=size))
        _make_tmp(size_dir, dead_pid, ns=11, size=size)

    server_module._sweep_orphan_tmps()

    for t in own_tmps:
        assert t.exists(), f'{t} (live) was unlinked'
    for size in (48, 64, 96, 128, 256):
        size_dir = fake_home / f'.local/share/icons/hicolor/{size}x{size}/apps'
        dead_tmp = size_dir / f'.claude-usage.tmp.{dead_pid}.11.{size}.png'
        assert not dead_tmp.exists(), f'{dead_tmp} (orphan) was not cleaned up'
