#!/usr/bin/env python3
"""Generate `kde-plasmoid/contents/config/main.xml` (KConfigXT) from the gschema XML.

The KDE Plasmoid is a second front end over the same `usage.json` contract as
the GNOME extension (see docs/plans/2026-05-25-kde-plasma-support.md). Its
config schema must carry the SAME defaults and ranges as the gschema, or the
two front ends drift — exactly the DG-1/PL-* class of bug this repo already
fights with single-source-of-truth generators + parity lints.

So, mirroring `gen-js-defaults.py`: parse the one gschema XML and emit the
KConfigXT `main.xml`. CI runs `lint-kde-config.py` (this script with --check)
to assert the checked-in file stays byte-identical to a fresh generation.

Type mapping (gschema -> KConfigXT):
  's' + #rrggbb default + 'color' in name -> Color   (QML reads a QColor)
  's' (otherwise)                         -> String
  'u'                                     -> Int  (with <min>/<max> from <range>)
  'b'                                     -> Bool

Name mapping: gschema kebab-case -> KConfigXT/QML camelCase
  weekly-color-green -> weeklyColorGreen   (QML: plasmoid.configuration.weeklyColorGreen)
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / 'gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml'
OUT = REPO / 'kde-plasmoid/contents/config/main.xml'

# Reuse the gschema default parser from the Python SOT rather than re-inlining
# it (GD-1's lesson: a second copy is a new drift surface).
sys.path.insert(0, str(REPO / 'server'))
from schema_defaults import _parse_default  # noqa: E402

_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<!-- AUTO-GENERATED from gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
     DO NOT HAND-EDIT - regenerate with `task gen-kde-config`.

     KConfigXT config schema for the KDE Plasma 6 plasmoid. Every entry mirrors
     a gschema key so the GNOME extension and the plasmoid share defaults and
     ranges. CI runs lint-kde-config.py to keep this synced to the schema XML. -->
<kcfg xmlns="http://www.kde.org/standards/kcfg/1.0"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:schemaLocation="http://www.kde.org/standards/kcfg/1.0
                          http://www.kde.org/standards/kcfg/1.0/kcfg.xsd">
  <kcfgfile name=""/>
  <group name="General">
"""

FOOTER = """\
  </group>
</kcfg>
"""


def _kebab_to_camel(key):
    head, *rest = key.split('-')
    return head + ''.join(w.capitalize() for w in rest)


def _xml_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _entry(key_el):
    """Render one <entry> block from a gschema <key>."""
    name = key_el.attrib['name']
    type_attr = key_el.attrib['type']
    camel = _kebab_to_camel(name)
    d = key_el.find('default')
    default = _parse_default(d.text, type_attr) if (d is not None and d.text) else (
        '' if type_attr == 's' else 0)
    summary_el = key_el.find('summary')
    summary = summary_el.text.strip() if (summary_el is not None and summary_el.text) else name

    # Decide the KConfigXT type.
    if type_attr == 's':
        is_color = ('color' in name) and bool(_COLOR_RE.match(str(default)))
        kcfg_type = 'Color' if is_color else 'String'
    elif type_attr == 'u':
        kcfg_type = 'Int'
    elif type_attr == 'b':
        kcfg_type = 'Bool'
    else:
        raise ValueError(f'gen-kde-config: unsupported gschema type {type_attr!r}')

    lines = [f'    <entry name="{camel}" type="{kcfg_type}">']
    lines.append(f'      <label>{_xml_escape(summary)}</label>')

    if kcfg_type == 'Bool':
        lines.append(f'      <default>{"true" if default else "false"}</default>')
    else:
        lines.append(f'      <default>{_xml_escape(str(default))}</default>')

    r = key_el.find('range')
    if r is not None:
        lines.append(f'      <min>{int(r.attrib["min"])}</min>')
        lines.append(f'      <max>{int(r.attrib["max"])}</max>')

    lines.append('    </entry>')
    return '\n'.join(lines)


def render():
    tree = ET.parse(SCHEMA)
    root = tree.getroot()
    # Preserve gschema document order so the output is deterministic.
    entries = [_entry(k) for k in root.findall('.//key')]
    return HEADER + '\n'.join(entries) + '\n' + FOOTER


def main():
    try:
        content = render()
    except (FileNotFoundError, ET.ParseError, PermissionError,
            IsADirectoryError, ValueError, KeyError) as e:
        sys.stderr.write(
            f'gen-kde-config: failed to load schema XML '
            f'({type(e).__name__}: {e}) - reinstall the .deb or run install.sh\n')
        raise
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        existing = OUT.read_text() if OUT.exists() else ''
        if existing != content:
            print(f'gen-kde-config: {OUT} is out of date - run '
                  f'`task gen-kde-config`', file=sys.stderr)
            sys.exit(1)
        print(f'gen-kde-config: {OUT} is in sync with the schema')
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    main()
