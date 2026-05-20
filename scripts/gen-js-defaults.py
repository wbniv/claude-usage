#!/usr/bin/env python3
"""Generate `gnome-extension/_defaults.js` from the gschema XML.

JS-1 (pass-18): `extension.js`'s `safeColor` carries hardcoded hex
fallbacks (`#2a9a2a`, `#d07000`, etc.) used when GSettings reads return
an invalid value. The Python SOT `server/schema_defaults.py` doesn't help
because GJS can't import Python. Pass-19 chose option (b): generate a JS
constants file from the same gschema XML, check it in, and let CI assert
it stays in sync.

Output is a plain ES module under `gnome-extension/` so `extension.js`
can `import { DEFAULTS } from './_defaults.js'`. The header notes that
the file is auto-generated; do not hand-edit.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / 'gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml'
OUT = REPO / 'gnome-extension/_defaults.js'

# GD-1 (pass-23): import the gschema parser from server/schema_defaults
# instead of duplicating it. JS-1's original landing inlined a copy of
# `_parse_default` and `_kebab_to_snake`; the duplication recreated the
# very drift surface JS-1 was meant to close.
sys.path.insert(0, str(REPO / 'server'))
from schema_defaults import _parse_default, _kebab_to_snake  # noqa: E402

HEADER = """\
// AUTO-GENERATED from gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
// DO NOT HAND-EDIT — regenerate with `task gen-js-defaults`.
//
// JS-1 (pass-18, option b chosen post-pass-21): extension.js's `safeColor`
// fallbacks needed a single-source-of-truth check against the gschema
// without copy-paste drift. Python consumers read schema_defaults.py;
// JS consumers read this file. CI runs lint-js-defaults to assert both
// stay synced to the schema XML.

"""


def _load():
    """Return the dict the JS side needs (snake_case keys, JS-shaped values)."""
    tree = ET.parse(SCHEMA)
    root = tree.getroot()
    defaults = {}
    for key in root.findall('.//key'):
        name = _kebab_to_snake(key.attrib['name'])
        type_attr = key.attrib['type']
        d = key.find('default')
        if d is not None and d.text is not None:
            defaults[name] = _parse_default(d.text, type_attr)
    return defaults


def _js_value(v):
    """Encode Python value as a JS literal."""
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        # JSON-safe single-line string. Strings in the schema today are
        # short hex/identifier values with no embedded quotes; using JSON
        # for safety.
        import json
        return json.dumps(v)
    raise TypeError(f'cannot encode {type(v).__name__} as JS literal')


def render(defaults):
    lines = [HEADER, 'export const DEFAULTS = Object.freeze({']
    for k in sorted(defaults):
        lines.append(f'    {k}: {_js_value(defaults[k])},')
    lines.append('});')
    lines.append('')
    return '\n'.join(lines)


def main():
    # GD-2 (pass-23): mirror schema_defaults.py's helpful-error wrapper.
    # Malformed schema or missing file previously surfaced as a bare
    # ParseError/FileNotFoundError traceback; emit a hint first.
    try:
        defaults = _load()
    except (FileNotFoundError, ET.ParseError, PermissionError,
            IsADirectoryError, ValueError, KeyError) as e:
        sys.stderr.write(
            f'gen-js-defaults: failed to load schema XML '
            f'({type(e).__name__}: {e}) — reinstall the .deb or run install.sh\n'
        )
        raise
    content = render(defaults)
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        existing = OUT.read_text() if OUT.exists() else ''
        if existing != content:
            print(f'gen-js-defaults: {OUT} is out of date — run '
                  f'`task gen-js-defaults`', file=sys.stderr)
            sys.exit(1)
        print(f'gen-js-defaults: {OUT} is in sync with the schema')
        return
    OUT.write_text(content)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    main()
