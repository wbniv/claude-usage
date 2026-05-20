#!/usr/bin/env python3
"""SD-1 (pass-18): assert SECURITY.md's outbound-URL claim matches reality.

SECURITY.md states the Chrome extension only ever fetches two HTTPS
endpoints (claude.ai/settings/usage + status.claude.com/api/v2/...).
The enforcement gate is `chrome-extension/manifest.json:host_permissions`.
This lint cross-checks the two lists so a future `host_permissions`
addition can't land without updating the doc.

Exits 0 on parity, 1 on divergence with a diff report.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / 'chrome-extension' / 'manifest.json'
SECURITY = REPO / 'SECURITY.md'


def _https_hosts_from_manifest():
    """Set of https:// origins in manifest.host_permissions, excluding
    loopback. Glob suffixes (`*`) are stripped — we compare base URLs."""
    data = json.loads(MANIFEST.read_text())
    hosts = data.get('host_permissions', [])
    out = set()
    for h in hosts:
        if not h.startswith('https://'):
            continue                     # skip 127.0.0.1 / http://*
        # Strip trailing globs / paths past the first slash after the host;
        # we want a base URL the doc can plausibly reference.
        m = re.match(r'^(https://[a-z0-9.-]+)(/[^*]*)?', h)
        if m:
            base = m.group(1) + (m.group(2) or '')
            out.add(base.rstrip('*').rstrip('/'))
    return out


def _https_urls_from_doc():
    """Set of https:// URLs mentioned in SECURITY.md (any form)."""
    text = SECURITY.read_text()
    found = set()
    for m in re.finditer(r'https://[a-z0-9.\-/_?=&]+', text):
        url = m.group(0).rstrip('.,;:)`')
        # Same normalization as manifest side — drop trailing slash.
        url = url.rstrip('/')
        found.add(url)
    return found


def main():
    manifest_hosts = _https_hosts_from_manifest()
    doc_urls = _https_urls_from_doc()

    # The doc URLs are a SUPERSET (e.g. exact paths the manifest globs).
    # For every manifest host base, at least one doc URL must start with it.
    missing = []
    for base in manifest_hosts:
        if not any(u.startswith(base) for u in doc_urls):
            missing.append(base)

    if not missing:
        print(f'lint-security-doc: OK ({len(manifest_hosts)} manifest hosts '
              f'all documented in SECURITY.md)')
        return 0

    print('lint-security-doc: DIVERGENCE — manifest.host_permissions has hosts '
          'not documented in SECURITY.md', file=sys.stderr)
    for base in sorted(missing):
        print(f'  · {base}', file=sys.stderr)
    print('\n  Either add the host to SECURITY.md\'s outbound-URL section,',
          file=sys.stderr)
    print('  or remove it from manifest.json host_permissions.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
