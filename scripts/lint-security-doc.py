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
    loopback. Glob suffixes (`*`) are stripped — we compare base URLs.

    SL-2 (pass-19): missing-key silent-pass guard. Previously
    `data.get('host_permissions', [])` returned [] → 0 hosts → "OK".
    A future manifest refactor that moves/removes the key would land
    clean. Now we treat absence as failure."""
    data = json.loads(MANIFEST.read_text())
    if 'host_permissions' not in data:
        raise RuntimeError(
            'manifest.json has no host_permissions key — expected for an '
            'MV3 extension that makes outbound calls'
        )
    hosts = data['host_permissions']
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
    """Set of https:// URLs in SECURITY.md, scoped to the outbound section.

    SL-3 (pass-19): previously scanned the whole file, so incidental URLs
    (GitHub issue links, RFC references) could mask a real divergence in
    concert with H-1's substring bypass. Now we look only inside the
    "outbound" paragraph block — bounded by the line "No outbound network
    calls other than:" and the next blank line."""
    text = SECURITY.read_text()
    m = re.search(
        r'No outbound network calls other than:\s*\n((?:.+\n)+?)\n',
        text,
    )
    section = m.group(1) if m else text  # fall back to whole-doc if heading missing
    found = set()
    for hit in re.finditer(r'https://[a-z0-9.\-/_?=&]+', section):
        url = hit.group(0).rstrip('.,;:)`').rstrip('/')
        found.add(url)
    return found


def main():
    try:
        manifest_hosts = _https_hosts_from_manifest()
    except RuntimeError as e:
        print(f'lint-security-doc: {e}', file=sys.stderr)
        return 1
    doc_urls = _https_urls_from_doc()

    # The doc URLs are a SUPERSET (e.g. exact paths the manifest globs).
    # For every manifest host base, at least one doc URL must reference it.
    # SL-1 (pass-19): require path-boundary match. The previous
    # `u.startswith(base)` accepted confusable hosts —
    # `https://claude.ai.evil.com` matched base `https://claude.ai`. Compare
    # as exact host match OR base-plus-path-separator so the boundary is
    # enforced.
    missing = []
    for base in manifest_hosts:
        if not any(u == base or u.startswith(base + '/') for u in doc_urls):
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
