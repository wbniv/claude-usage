"""CORS origin policy for usage-server.py::_cors.

On the happy path the browser extension's host_permissions make its POST
origin-less, so _cors does nothing. Its only job is the drive-by-web-page
defense: emit Access-Control-Allow-Origin ONLY for extension origins
(chrome-extension:// or moz-extension://), never for an ordinary web page.

Imports the hyphenated module via importlib (same shim as test_validate.py).
"""
import importlib.util
import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

_SPEC = importlib.util.spec_from_file_location(
    'usage_server', _SERVER_DIR / 'usage-server.py')
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def _allow_origin_for(origin, allowed_origins=None):
    """Run _cors with the given request Origin under the given ALLOWED_ORIGINS
    policy; return the Access-Control-Allow-Origin header it emitted (or None)."""
    sent = {}

    class _H:
        headers = {'Origin': origin} if origin is not None else {}

        def send_header(self, key, value):
            sent[key] = value

    orig = _MOD.ALLOWED_ORIGINS
    _MOD.ALLOWED_ORIGINS = allowed_origins
    try:
        _MOD.Handler._cors(_H())
    finally:
        _MOD.ALLOWED_ORIGINS = orig
    return sent.get('Access-Control-Allow-Origin')


# ── wildcard default (CLAUDE_USAGE_EXTENSION_ID unset → ALLOWED_ORIGINS is None) ──

def test_chrome_extension_origin_allowed():
    assert _allow_origin_for('chrome-extension://abcdef') == 'chrome-extension://abcdef'


def test_firefox_extension_origin_allowed():
    # moz-extension:// host is a per-install UUID; the wildcard default accepts it.
    o = 'moz-extension://2f8a1e3c-0000-4a00-9000-abcdef012345'
    assert _allow_origin_for(o) == o


def test_web_page_origin_rejected():
    assert _allow_origin_for('https://evil.example.com') is None


def test_missing_origin_emits_nothing():
    # Happy path: the extension fetch carries no Origin → no Allow-Origin header.
    assert _allow_origin_for(None) is None


# ── pinned ID (CLAUDE_USAGE_EXTENSION_ID set → exact-match set) ────────────────

def test_pinned_extension_id_exact_match_only():
    pin = {'chrome-extension://pinnedid'}
    assert _allow_origin_for('chrome-extension://pinnedid', allowed_origins=pin) \
        == 'chrome-extension://pinnedid'
    # When a specific ID is pinned, every other origin is rejected.
    assert _allow_origin_for('chrome-extension://other', allowed_origins=pin) is None
    assert _allow_origin_for('moz-extension://some-uuid', allowed_origins=pin) is None
