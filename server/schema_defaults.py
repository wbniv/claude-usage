"""Single source of truth for gschema-tied constants.

Parses `desktop/gnome/schemas/org.indri.claude-usage.gschema.xml`
at import time and exposes every `<default>` + `<range>` as plain Python
dicts. Closes pass-17's drift cluster (DG-1, DR-1..4, PR-1 via prefs.js
introspection) at the architectural level: there is now one place where
defaults and ranges live, and every Python consumer reads from here.

Consumers updated to import from this module:
  • server/generate-icon.py — was `DEFAULTS = {...}` literal (drifted to 50/80)
  • scripts/popup-preview.py — was hard-coded fallback dict (drifted to #cccccc)
  • scripts/_doc_render.py   — was inline production-mode CFG
  • scripts/render-panel-screenshot.py — was hard-coded `#d07000` literal

For JS code (extension.js, prefs.js), Gio.Settings + SettingsSchemaKey.get_range()
already gives schema introspection — see prefs.js's `_schemaRange` helper.

CI runs scripts/lint-schema-drift.py to catch any hand-copy that sneaks back in.
"""
import os
import xml.etree.ElementTree as ET
from pathlib import Path

_SCHEMA_FILENAME = 'org.indri.claude-usage.gschema.xml'


def _find_schema():
    """Locate the gschema XML. Checked in order:
      1. Source-checkout sibling (desktop/gnome/schemas/)
      2. Same dir as this installed module (build-deb copies it next door)
      3. System glib schemas dir
      4. User-local GNOME extension dir
    """
    here = Path(__file__).resolve().parent
    data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    candidates = [
        here.parent / 'desktop' / 'gnome' / 'schemas' / _SCHEMA_FILENAME,
        here / 'schemas' / _SCHEMA_FILENAME,
        Path('/usr/share/glib-2.0/schemas') / _SCHEMA_FILENAME,
        data_home / 'gnome-shell/extensions/claude-usage@indri.studio/schemas'
            / _SCHEMA_FILENAME,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"schema_defaults: could not locate {_SCHEMA_FILENAME}. "
        f"Searched: {[str(c) for c in candidates]}"
    )


def _parse_default(text, type_attr):
    """gschema <default>'s text is a serialized GVariant literal. We support
    the three types this schema uses: strings ('s'), uint32 ('u'), bool ('b')."""
    text = text.strip()
    if type_attr == 's':
        # String defaults are wrapped in single quotes: '#abc123' / 'monospace'
        return text.strip("'\"")
    if type_attr == 'u':
        return int(text)
    if type_attr == 'b':
        return text.lower() == 'true'
    raise ValueError(
        f"schema_defaults: unsupported gschema type {type_attr!r} "
        f"(extend _parse_default when a new key type is added)"
    )


def _kebab_to_snake(key):
    return key.replace('-', '_')


def _load():
    tree = ET.parse(_find_schema())
    root = tree.getroot()
    defaults = {}
    ranges = {}
    for key in root.findall('.//key'):
        name = _kebab_to_snake(key.attrib['name'])
        type_attr = key.attrib['type']
        d = key.find('default')
        if d is not None and d.text is not None:
            defaults[name] = _parse_default(d.text, type_attr)
        r = key.find('range')
        if r is not None:
            ranges[name] = (int(r.attrib['min']), int(r.attrib['max']))
    return defaults, ranges


# MD-2 (pass-18): wrap so the failure mode is debuggable — bare ImportError
# tracebacks from inside _load were unhelpful for users hitting a missing
# schema XML (e.g. partial install, broken build). Hint at the fix, then
# re-raise so callers still know the module isn't usable.
# MD-3 (pass-19): broaden to ParseError (corrupt XML), Permission, IsADirectory.
# MD-4 (pass-20): also catch ValueError / KeyError — a malformed-but-XML-valid
# schema (`<key type="i">` for an unsupported type → _parse_default raises
# ValueError; missing `name`/`type` attr → key.attrib['type'] raises
# KeyError) was still surfacing as a bare traceback.
try:
    DEFAULTS, RANGES = _load()
except (FileNotFoundError, ET.ParseError, PermissionError, IsADirectoryError,
        ValueError, KeyError) as _e:
    import sys as _sys
    _sys.stderr.write(
        f"schema_defaults: failed to load schema XML "
        f"({type(_e).__name__}: {_e}) — reinstall the .deb or run install.sh\n"
    )
    raise
