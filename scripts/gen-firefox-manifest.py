#!/usr/bin/env python3
"""Generate the Firefox WebExtension manifest from the Chrome MV3 manifest.

Chrome and Firefox share ONE extension source under chrome-extension/. Only the
manifest differs, and that difference is mechanical, so we GENERATE the Firefox
manifest from chrome-extension/manifest.json at build time rather than
hand-maintaining a second copy — a second copy is a drift surface (the same
lesson as gen-js-defaults.py / the gschema parity lints).

Three transforms; everything else is copied from the Chrome manifest verbatim
(name, version, description, permissions, host_permissions, action, icons):
  1. background: {"service_worker": ...} -> {"scripts": ["chrome-compat.js",
     "background.js"]}. Firefox MV3 broadly supports the non-persistent event
     page (scripts); background.service_worker is Firefox >=121 only, and
     background.js uses no service-worker-only globals.
  2. add browser_specific_settings.gecko (stable add-on id + min version).

`chrome-compat.js` (listed FIRST) aliases chrome -> browser so the existing
promise-based chrome.* calls in background.js work unchanged under Firefox.

Usage:
  gen-firefox-manifest.py            # print the Firefox manifest JSON to stdout
  gen-firefox-manifest.py --check    # validate generation + Chrome-parity (CI)

The Firefox manifest is intentionally NOT checked in: it is derived from the
Chrome manifest, so committing it would recreate the divergence this avoids and
would break the manifest.json globs in usage-server.py / build-chrome-zip.sh.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHROME_MANIFEST = REPO / 'chrome-extension' / 'manifest.json'
COMPAT_SHIM = REPO / 'chrome-extension' / 'chrome-compat.js'

GECKO_ID = 'claude-usage@indri.studio'
STRICT_MIN_VERSION = '115.0'
BACKGROUND_SCRIPTS = ['chrome-compat.js', 'background.js']

# Keys copied straight from the Chrome manifest; --check asserts they match.
_SHARED_KEYS = ('manifest_version', 'name', 'version', 'description',
                'permissions', 'host_permissions', 'action', 'icons')


def render():
    chrome = json.loads(CHROME_MANIFEST.read_text())
    ff = dict(chrome)  # preserves insertion order (background stays in place)
    ff['background'] = {'scripts': list(BACKGROUND_SCRIPTS)}
    ff['browser_specific_settings'] = {
        'gecko': {'id': GECKO_ID, 'strict_min_version': STRICT_MIN_VERSION}
    }
    return json.dumps(ff, indent=2) + '\n'


def _check():
    errs = []
    chrome = json.loads(CHROME_MANIFEST.read_text())
    ff = json.loads(render())
    for k in _SHARED_KEYS:
        if chrome.get(k) != ff.get(k):
            errs.append(f"{k} must mirror the Chrome manifest")
    if ff.get('background') != {'scripts': BACKGROUND_SCRIPTS}:
        errs.append("background must be {'scripts': ['chrome-compat.js', 'background.js']}")
    if 'service_worker' in ff.get('background', {}):
        errs.append("service_worker must be dropped for the Firefox event-page build")
    if not ff.get('browser_specific_settings', {}).get('gecko', {}).get('id'):
        errs.append("browser_specific_settings.gecko.id is required for Firefox")
    if not COMPAT_SHIM.exists():
        errs.append(f"{COMPAT_SHIM.relative_to(REPO)} (the chrome->browser shim) is missing")
    if errs:
        for e in errs:
            print(f"gen-firefox-manifest: {e}", file=sys.stderr)
        print(f"gen-firefox-manifest: FAIL ({len(errs)} issue(s))", file=sys.stderr)
        return 1
    print("gen-firefox-manifest: OK (generates cleanly; permissions, "
          "host_permissions and version mirror the Chrome manifest)")
    return 0


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == '--check':
            sys.exit(_check())
        sys.stdout.write(render())
    except (FileNotFoundError, json.JSONDecodeError, PermissionError,
            IsADirectoryError, KeyError) as e:
        sys.stderr.write(
            f"gen-firefox-manifest: failed to read the Chrome manifest "
            f"({type(e).__name__}: {e}) — reinstall the .deb or run install.sh\n")
        raise


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    main()
