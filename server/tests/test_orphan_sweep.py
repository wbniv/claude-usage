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

# TS-3 (pass-19): the sweep's liveness check uses /proc/<pid>/ existence,
# which is Linux-only. The product itself is Linux-only (.deb + GNOME), so
# we skip this whole module rather than fail on macOS dev machines.
pytestmark = pytest.mark.skipif(
    not Path('/proc').is_dir(),
    reason='_sweep_orphan_tmps uses /proc/<pid>; Linux-only',
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
