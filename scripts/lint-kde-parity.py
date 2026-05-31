#!/usr/bin/env python3
"""Parity + sanity lints for the KDE Plasma plasmoid (desktop/kde/).

The plasmoid is a third consumer of the usage.json data contract (after the
GNOME extension and generate-icon.py) and a third copy of the gschema config
defaults — but, unlike those, QML has no unit-test / qmllint coverage in CI.
The 2026-05-30 code review found it shipped completely broken: StandardPaths
used with no `import QtCore` (ReferenceError on every load), and reads of
phantom fields (reset_ts, period_secs, status, last_update) that the server
never emits. These checks guard exactly those failure modes.

1. import-when-StandardPaths — any QML referencing the StandardPaths singleton
   must import the module that defines it (QtCore, Qt 6.2+).            [KDE-1]
2. usage.json field allowlist — usageData.<f> / meter.<f> / modelData.<f>
   accesses must name a field the server actually writes.              [KDE-2]
3. config-default parity — desktop/kde/contents/config/main.xml defaults must
   equal the GNOME gschema defaults (the single source of truth).      [KDE-5]
4. pacing-floor parity — main.qml::pacingFraction's floor must mirror
   extension.js::pacingPct (the JS↔Python twins are pinned by
   lint-pacing-parity; this brings the QML third copy under the guard). [KDE-2]
5. usage-URL parity — the plasmoid's hardcoded usage URL must equal
   extension.js's USAGE_URL.                                            [KDE-2]

This is a regex-based DRIFT/parity guard, not a QML validator: it can be fooled
by reformatting or by a phantom field read through a differently-named variable
(e.g. `const m = currentMeter(); m.reset_ts`). Pair it with a headless `qmllint`
pass for syntax / unresolved-type / import errors — that is what would have
caught KDE-1 (StandardPaths without `import QtCore`) directly. See
docs/plans/2026-05-30-code-review-fixes.md, "Test coverage & gaps".

Exits 0 on success, 1 on any failure.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KDE = REPO / 'desktop' / 'kde'
MAIN_XML = KDE / 'contents' / 'config' / 'main.xml'
GSCHEMA = REPO / 'desktop' / 'gnome' / 'schemas' / 'org.indri.claude-usage.gschema.xml'
EXTENSION_JS = REPO / 'desktop' / 'gnome' / 'extension.js'
MAIN_QML = KDE / 'contents' / 'ui' / 'main.qml'

# Fields the server actually writes to usage.json (usage-server.py / scraper.js
# / background.js). Keep in sync when the wire schema changes.
TOP_FIELDS = {
    'meters', 'plan', '_timestamp', 'timestamp', '_anthropic_status',
    '_period_lengths', '_scrape_fail_count', '_ext_version', '_parse_failure',
    '_schema', '_ext_version_mismatch', '_buffered_at',
}
METER_FIELDS = {
    'pct', 'label', 'reset', 'reset_minutes', 'count', 'total', 'spent', 'balance',
}

# camelCase KDE (KConfig) key ↔ kebab GNOME gschema key.
KEY_MAP = {
    'weeklyColorGreen': 'weekly-color-green',
    'weeklyColorAmber': 'weekly-color-amber',
    'weeklyColorRed': 'weekly-color-red',
    'sonnetColor': 'sonnet-color',
    'popupColorNormal': 'popup-color-normal',
    'popupColorWarning': 'popup-color-warning',
    'popupColorCritical': 'popup-color-critical',
    'panelColorNormal': 'panel-color-normal',
    'panelColorWarning': 'panel-color-warning',
    'panelColorCritical': 'panel-color-critical',
    'thresholdWarning': 'threshold-warning',
    'thresholdCritical': 'threshold-critical',
    'popupFontFamily': 'popup-font-family',
    'barWidth': 'bar-width',
    'panelFontSize': 'panel-font-size',
    'popupFontSize': 'popup-font-size',
    'panelIconSize': 'panel-icon-size',
    'panelMetric': 'panel-metric',
}

# StandardPaths is provided by QtCore (Qt 6.2+) or the legacy Qt.labs.platform.
# Match an actual import statement, not a bare substring — a comment mentioning
# "import QtCore" must not satisfy the check. Likewise trigger only on real
# `StandardPaths.` member access, not a passing mention in prose.
_IMPORT_RE = re.compile(r'^\s*import\s+(?:QtCore|Qt\.labs\.platform)\b', re.M)
_USES_STANDARDPATHS_RE = re.compile(r'\bStandardPaths\s*\.')
_FIELD_RE = re.compile(r'\b(usageData|meter|modelData)\.([A-Za-z_]\w*)')
# Pacing floor `Math.max(<min-minutes>, period * <fraction>)` — the QML's
# pacingFraction is a third copy of the pacing curve (after extension.js and
# generate-icon.py, which lint-pacing-parity already pins to each other). This
# brings the QML copy under the same drift guard.
_FLOOR_RE = re.compile(r'Math\.max\(\s*(\d+)\s*,\s*period\s*\*\s*([\d.]+)\s*\)')
_USAGE_URL_RE = re.compile(r"USAGE_URL\s*=\s*'([^']+)'")
_QML_USAGE_URL_RE = re.compile(r"https://claude\.ai/settings/usage[^'\"\s<)]*")
# Plasma 5 idiom: lowercase `plasmoid.` — null in a Plasma 6 config page.
_LOWER_PLASMOID_RE = re.compile(r'\bplasmoid\.')


def _qml_files():
    return sorted(KDE.glob('contents/**/*.qml'))


def check_standardpaths_import():
    errs = []
    for f in _qml_files():
        text = f.read_text()
        if _USES_STANDARDPATHS_RE.search(text) and not _IMPORT_RE.search(text):
            errs.append(f"{f.relative_to(REPO)}: uses StandardPaths but imports neither "
                        f"QtCore nor Qt.labs.platform — the singleton is undefined at runtime")
    return errs


def check_usage_fields():
    errs = []
    for f in _qml_files():
        for n, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split('//', 1)[0]  # drop // line comments
            for obj, field in _FIELD_RE.findall(code):
                allowed = TOP_FIELDS if obj == 'usageData' else METER_FIELDS
                if field not in allowed:
                    errs.append(f"{f.relative_to(REPO)}:{n}: {obj}.{field} is not a known "
                                f"usage.json field — real fields: {sorted(allowed)}")
    return errs


def _gschema_defaults():
    root = ET.parse(GSCHEMA).getroot()
    out = {}
    for key in root.iter('key'):
        name, d = key.get('name'), key.find('default')
        if name is not None and d is not None and d.text is not None:
            out[name] = d.text.strip().strip("'")
    return out


def _kcfg_defaults():
    # kcfg declares a default namespace; match tags regardless of prefix.
    root = ET.parse(MAIN_XML).getroot()
    out = {}
    for entry in root.iter():
        if not entry.tag.endswith('entry'):
            continue
        name = entry.get('name')
        d = next((c for c in entry if c.tag.endswith('default')), None)
        if name is not None and d is not None:
            out[name] = (d.text or '').strip()
    return out


def check_config_parity():
    errs = []
    gs, kde = _gschema_defaults(), _kcfg_defaults()
    for kde_key, gs_key in KEY_MAP.items():
        if kde_key not in kde:
            errs.append(f"main.xml: missing config key {kde_key!r} (gschema has {gs_key!r})")
        elif gs_key not in gs:
            errs.append(f"gschema: missing key {gs_key!r} mapped from KDE {kde_key!r}")
        elif kde[kde_key] != gs[gs_key]:
            errs.append(f"default drift: main.xml {kde_key}={kde[kde_key]!r} != "
                        f"gschema {gs_key}={gs[gs_key]!r}")
    return errs


def check_pacing_floor_parity():
    # main.qml::pacingFraction must use the same pacing floor as
    # extension.js::pacingPct (min-minutes, period-fraction). The /100
    # percent-vs-fraction representation differs by design, but the FLOOR — the
    # behaviour constant — must not drift.
    cm = _FLOOR_RE.search(EXTENSION_JS.read_text())
    qm = _FLOOR_RE.search(MAIN_QML.read_text())
    if cm is None:
        return ["extension.js: pacing floor Math.max(<min>, period * <frac>) not found"]
    if qm is None:
        return ["main.qml: pacing floor Math.max(<min>, period * <frac>) not found — "
                "pacingFraction must mirror extension.js::pacingPct"]
    if (cm.group(1), cm.group(2)) != (qm.group(1), qm.group(2)):
        return [f"pacing floor drift: main.qml ({qm.group(1)}, {qm.group(2)}) != "
                f"extension.js pacingPct ({cm.group(1)}, {cm.group(2)}) — (min-minutes, period-fraction)"]
    return []


def check_url_parity():
    errs = []
    m = _USAGE_URL_RE.search(EXTENSION_JS.read_text())
    if not m:
        return ["extension.js: USAGE_URL constant not found"]
    canon = m.group(1)
    for f in _qml_files():
        for n, line in enumerate(f.read_text().splitlines(), 1):
            for url in _QML_USAGE_URL_RE.findall(line):
                base = url.split('?')[0].split('#')[0]
                if base != canon:
                    errs.append(f"{f.relative_to(REPO)}:{n}: usage URL {url!r} != "
                                f"extension.js USAGE_URL {canon!r}")
    return errs


def check_config_idiom():
    """Config pages must use the Plasma 6 cfg_<key> convention, NOT the Plasma 5
    lowercase `plasmoid.configuration`. In Plasma 6 the config page has no
    lowercase `plasmoid` context, so those bindings throw at load and Plasma
    silently drops the page (leaving only Keyboard Shortcuts + About — the
    2026-05-30 live finding). Use `cfg_<key>` aliases (or capital `Plasmoid`)."""
    errs = []
    for f in KDE.glob('contents/**/config/*.qml'):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split('//', 1)[0]  # drop // line comments
            if _LOWER_PLASMOID_RE.search(code):
                errs.append(f"{f.relative_to(REPO)}:{n}: lowercase `plasmoid.` in a config "
                            f"page — Plasma 6 has no `plasmoid` context here; use the "
                            f"cfg_<key> convention (or capital `Plasmoid`)")
    return errs


def main():
    errs = []
    for fn in (check_standardpaths_import, check_usage_fields, check_config_parity,
               check_pacing_floor_parity, check_url_parity, check_config_idiom):
        errs.extend(fn())
    if errs:
        for e in errs:
            print(f"lint-kde-parity: {e}", file=sys.stderr)
        print(f"lint-kde-parity: FAIL ({len(errs)} issue(s))", file=sys.stderr)
        return 1
    print(f"lint-kde-parity: OK ({len(_qml_files())} QML files clean, "
          f"{len(KEY_MAP)} config keys + pacing floor + usage URL mirror the canonical source)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
