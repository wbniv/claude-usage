#!/usr/bin/env python3
"""Parity lints for hand-synced implementation pairs.

1. SC-3 (pass-15 §8) — scraper.js vs background.js inlined scrape.
   The two files implement equivalent scraping logic but live separately because
   `chrome.scripting.executeScript`'s `func:` runs in the page context and cannot
   import ES modules. `scraper.js` is what `chrome-extension/test/scraper.test.js`
   exercises; the inlined copy in `background.js` is what production actually
   runs. Strategy: compare every regex literal in the scrape-relevant sections.

2. Pacing parity (post-0.11.14) — pacingPct (extension.js) vs pacing_pct
   (generate-icon.py). Both implement identical pacing logic in different
   languages. Strategy: extract numeric literals from both function bodies
   (after stripping comments/docstrings) and compare the sets. A constant
   change in one file that misses the other is the primary drift mode.

Exits 0 on parity, 1 on any divergence.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / 'chrome-extension'


def _regexes_in(text):
    """Return the set of JS regex literals in `text`. Naive scan: matches
    `/pattern/flags` where `pattern` doesn't contain a literal slash (except
    `\\/`). Misses regexes with escaped slashes — we don't use any."""
    # JS regex literal: /...non-slash-or-escaped-slash.../[gimuy]*
    # We anchor on contexts that suggest a regex (= ( , return etc.) to avoid
    # false positives from division — but for the scrape code, just scan all
    # /.../ pairs that don't span lines.
    out = set()
    for m in re.finditer(r'(/(?:\\.|[^/\n\\])+/[gimuy]*)', text):
        lit = m.group(1)
        # Filter likely-not-regex: URL paths (`/api/v2/`), comments are stripped below
        if lit.startswith('//'):
            continue
        out.add(lit)
    return out


def _strip_comments(text):
    """Drop JS // and /* */ comments. Python `#` stripping is delegated to
    _strip_py_comments_tokenize — the regex-based version ate hex-color
    string literals (LK-1, pass-17). Kept the JS regexes since this lint
    only consumes JS files where # has no comment meaning."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'([^:])//[^\n]*', r'\1', text)
    return text


def _strip_py_comments_tokenize(text):
    """Drop Python `#` comments via the tokenize module so string literals
    containing `#` (hex colors etc.) survive unscathed. LK-1, pass-17:
    the previous regex `#[^\\n]*` matched inside `'#abc123'` and chewed off
    the rest of the line."""
    import io
    import tokenize
    out = []
    last_row, last_col = 1, 0
    try:
        for tok in tokenize.tokenize(io.BytesIO(text.encode()).readline):
            if tok.type == tokenize.COMMENT:
                continue
            srow, scol = tok.start
            erow, ecol = tok.end
            # Re-emit any whitespace skipped between tokens.
            if srow > last_row:
                out.append('\n' * (srow - last_row))
                last_col = 0
            if scol > last_col:
                out.append(' ' * (scol - last_col))
            out.append(tok.string)
            last_row, last_col = erow, ecol
    except tokenize.TokenizeError:
        # Fall back to leaving the text unchanged if tokenize chokes — this
        # is a lint, not a build step; better to over-include than to error.
        return text
    return ''.join(out)


def _strip_py_docstrings(text):
    text = re.sub(r'""".*?"""', '', text, flags=re.DOTALL)
    text = re.sub(r"'''.*?'''", '', text, flags=re.DOTALL)
    return text


def _extract_js_function(text, name):
    """Extract a top-level JS function body (name → matching closing brace)."""
    start = text.find(f'function {name}(')
    if start < 0:
        raise SystemExit(f'lint-pacing-parity: {name} not found in extension.js')
    depth, i = 0, text.index('{', start)
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise SystemExit(f'lint-pacing-parity: could not extract {name} body')


def _extract_py_function(text, name):
    """Extract a Python function body by indentation (def line + all indented lines)."""
    lines = text.splitlines()
    start = next(
        (i for i, l in enumerate(lines) if re.match(rf'^def {re.escape(name)}\(', l)),
        None,
    )
    if start is None:
        raise SystemExit(f'lint-pacing-parity: {name} not found in generate-icon.py')
    result = [lines[start]]
    for line in lines[start + 1:]:
        if line and not line[0].isspace():
            break
        result.append(line)
    return '\n'.join(result)


def _raw_string_literals(text):
    """Return all quoted string literal values (both single and double quoted)."""
    strs = set(re.findall(r"'([^'\\]*(?:\\.[^'\\]*)*)'", text))
    strs |= set(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text))
    return strs


def _literals(text, *, shared_strs=None):
    """Extract numeric literals and value-like quoted string literals.

    PL-1 (pass-26): plain numeric scan missed hex colors ('#888', '#abcdef'),
    role names, and Unicode bar characters. We also include quoted strings so
    a hex-color change in one twin that misses the other surfaces as a
    divergence.

    shared_strs: if given, restrict string comparison to strings that either
      (a) start with '#' (hex colors — always interesting), or
      (b) contain non-ASCII chars (Unicode bar chars), or
      (c) appear in shared_strs (constants that both sides use as literals,
          e.g. role names 'on_pace', 'over_pace', 'tick', 'empty').

    This filters out Python-only dict-access keys ('popupNorm', 'label', …)
    and JS-only typeof-check strings ('number') — those are language-specific
    accessor patterns, not shared value constants.
    """
    nums = set(re.findall(r'\b\d+\.?\d*\b', text))
    raw = _raw_string_literals(text)
    if shared_strs is None:
        strs = raw
    else:
        strs = {s for s in raw
                if s.startswith('#')
                or any(ord(c) > 127 for c in s)
                or s in shared_strs}
    return nums | {f's:{s}' for s in strs if s}


def _numeric_literals(text):
    """Return the set of numeric literals (int and float) in code text.

    Kept for the scraper-parity check which only needs numeric literals."""
    return set(re.findall(r'\b\d+\.?\d*\b', text))


def _extract_inline_scrape(background_text):
    """Slice background.js to the regions that mirror scraper.js: the
    top-level `parseResetMinutes` (called after executeScript returns to
    enrich each meter) AND the executeScript callback that contains the
    inlined `isHydrated` + `doScrape`. Together these cover every parsing
    regex that has a counterpart in scraper.js."""
    start = background_text.find('function parseResetMinutes')
    if start < 0:
        raise SystemExit('lint-scraper-parity: parseResetMinutes not found in background.js')
    # End at the next top-level async function after scrapeAndPost — fetchUsage —
    # which has no parsing regexes (just tab/storage management).
    end = background_text.find('async function fetchUsage', start)
    if end < 0:
        end = len(background_text)
    return background_text[start:end]


def check_scraper_parity():
    scraper = (EXT / 'scraper.js').read_text()
    background = (EXT / 'background.js').read_text()

    scraper_regexes = _regexes_in(_strip_comments(scraper))
    inline_regexes = _regexes_in(_strip_comments(_extract_inline_scrape(background)))

    only_scraper = scraper_regexes - inline_regexes
    only_inline = inline_regexes - scraper_regexes

    if not only_scraper and not only_inline:
        print(f'lint-scraper-parity: OK ({len(scraper_regexes)} regexes match between scraper.js and background.js inline)')
        return 0

    print('lint-scraper-parity: DIVERGENCE between scraper.js and background.js inline scrape', file=sys.stderr)
    if only_scraper:
        print('\n  Regexes in scraper.js but NOT in background.js inline:', file=sys.stderr)
        for r in sorted(only_scraper):
            print(f'    {r}', file=sys.stderr)
    if only_inline:
        print('\n  Regexes in background.js inline but NOT in scraper.js:', file=sys.stderr)
        for r in sorted(only_inline):
            print(f'    {r}', file=sys.stderr)
    print('\n  A parsing change in one file likely missed the other.', file=sys.stderr)
    print('  Update both, or update the lint if the divergence is intentional.', file=sys.stderr)
    return 1


# PL-3 (pass-26 deferred, pass-28): section-anchor strings used as literal-
# equality matches (`l === 'Plan usage limits'`) are duplicated between
# scraper.js and background.js's inline scrape but escape check_scraper_parity
# because that lint only diffs regex literals. A typo in one side
# (`'Plan usage limit'`) would produce a silent locale_or_layout partial
# scrape with no diagnostic. Recommendation A from
# docs/investigations/2026-05-21-pl3-scraper-string-parity.md: hand-maintained
# allowlist. Add a string here when a new section anchor lands on the
# claude.ai/settings/usage page.
ANCHOR_STRINGS = [
    'Plan usage limits',
    'Extra usage',
]

# Single-sided pin: scraper.js takes the toggle state as a parameter, so
# this selector exists only in background.js. Listed so a refactor that
# silently drops the query is caught.
DOM_SELECTORS_IN_BACKGROUND = [
    '[role="switch"][aria-label="Extra usage"]',
]


def check_anchor_strings():
    scraper = (EXT / 'scraper.js').read_text()
    background = (EXT / 'background.js').read_text()
    inline = _extract_inline_scrape(background)

    rc = 0
    for s in ANCHOR_STRINGS:
        quoted = (f"'{s}'", f'"{s}"')
        in_scraper = any(q in scraper for q in quoted)
        in_inline = any(q in inline for q in quoted)
        if not (in_scraper and in_inline):
            rc = 1
            sides = []
            if not in_scraper: sides.append('scraper.js')
            if not in_inline: sides.append('background.js inline')
            print(f'lint-anchor-strings: anchor {s!r} missing in {" and ".join(sides)}',
                  file=sys.stderr)

    for s in DOM_SELECTORS_IN_BACKGROUND:
        quoted = (f"'{s}'", f'"{s}"')
        if not any(q in background for q in quoted):
            rc = 1
            print(f'lint-anchor-strings: required selector {s!r} missing in background.js',
                  file=sys.stderr)

    if rc == 0:
        print(f'lint-anchor-strings: OK ({len(ANCHOR_STRINGS)} anchors + '
              f'{len(DOM_SELECTORS_IN_BACKGROUND)} selectors present)')
    else:
        print('\n  A literal-equality anchor changed on one side but not the other.', file=sys.stderr)
        print('  Update both, or update ANCHOR_STRINGS in this lint.', file=sys.stderr)
    return rc


def check_pacing_parity():
    """Check the hand-synced pacing functions stay in numeric-literal sync.

    Four function pairs across two Python files:
      JS (extension.js)   ↔ Python (where)                            twin file
      pacingPct           ↔ pacing_pct                                 generate-icon.py
      elapsedFraction     ↔ elapsed_fraction                           generate-icon.py
      pacingSegments      ↔ pacing_segments     (viz; PS-1 pass-23)    popup-preview.py
      colorFor            ↔ color_for           (viz; PS-1 pass-23)    popup-preview.py
    """
    js_raw = _strip_comments((REPO / 'desktop' / 'gnome' / 'extension.js').read_text())
    gi_raw = _strip_py_docstrings(
        _strip_py_comments_tokenize(
            (REPO / 'server' / 'generate-icon.py').read_text()
        )
    )
    pp_raw = _strip_py_docstrings(
        _strip_py_comments_tokenize(
            (REPO / 'scripts' / 'popup-preview.py').read_text()
        )
    )

    pairs = [
        ('pacingPct',       'pacing_pct',       'generate-icon.py', gi_raw),
        ('elapsedFraction', 'elapsed_fraction', 'generate-icon.py', gi_raw),
        ('pacingSegments',  'pacing_segments',  'popup-preview.py', pp_raw),
        ('colorFor',        'color_for',        'popup-preview.py', pp_raw),
    ]

    rc = 0
    for js_name, py_name, py_file, py_raw in pairs:
        # PL-1 (pass-26): use _literals (numeric + quoted strings) so hex
        # colors and role names are included in the comparison set.
        # Compute the intersection of string literals in both bodies; use
        # that as `shared_strs` so Python-only dict-accessor keys ('label',
        # 'popupNorm', …) and JS-only typeof strings ('number') don't cause
        # false positives. Hex colors ('#xxx') are always included regardless
        # of shared membership — they're the primary drift vector.
        js_body = _extract_js_function(js_raw, js_name)
        py_body = _extract_py_function(py_raw, py_name)
        shared_strs = _raw_string_literals(js_body) & _raw_string_literals(py_body)
        js_lits = _literals(js_body, shared_strs=shared_strs)
        py_lits = _literals(py_body, shared_strs=shared_strs)

        only_js = js_lits - py_lits
        only_py = py_lits - js_lits

        if not only_js and not only_py:
            print(f'lint-pacing-parity: OK ({len(js_lits)} literals match between {js_name} and {py_name})')
            continue

        rc = 1
        print(f'lint-pacing-parity: DIVERGENCE between {js_name} (extension.js) and {py_name} ({py_file})', file=sys.stderr)
        if only_js:
            print(f'\n  Literals in {js_name} (JS) but NOT {py_name} ({py_file}):', file=sys.stderr)
            for n in sorted(only_js, key=lambda x: (x.startswith('s:'), x)):
                print(f'    {n}', file=sys.stderr)
        if only_py:
            print(f'\n  Literals in {py_name} ({py_file}) but NOT {js_name} (JS):', file=sys.stderr)
            for n in sorted(only_py, key=lambda x: (x.startswith('s:'), x)):
                print(f'    {n}', file=sys.stderr)
        print('\n  A constant change in one file likely missed the other.', file=sys.stderr)
        print('  Update both, or update the lint if the divergence is intentional.', file=sys.stderr)
    return rc


def check_pair_inventory():
    """Warn about likely-unregistered parity pairs.

    PL-4 (pass-26): the pair list is hand-maintained. This function scans
    extension.js for top-level JS functions, computes the expected snake_case
    twin name, and warns (to stderr, exit 0) when a matching `def` exists in
    the listed py_files but the pair is NOT in the PAIRS list.

    Does NOT fail the lint — warnings only. Surfaces new pairs for human review
    so the next PS-1-class miss doesn't have to wait for a code review to find it.
    """
    js_raw = _strip_comments((REPO / 'desktop' / 'gnome' / 'extension.js').read_text())
    gi_raw = _strip_py_docstrings(
        _strip_py_comments_tokenize(
            (REPO / 'server' / 'generate-icon.py').read_text()
        )
    )
    pp_raw = _strip_py_docstrings(
        _strip_py_comments_tokenize(
            (REPO / 'scripts' / 'popup-preview.py').read_text()
        )
    )

    pairs = [
        ('pacingPct',       'pacing_pct',       'generate-icon.py', gi_raw),
        ('elapsedFraction', 'elapsed_fraction', 'generate-icon.py', gi_raw),
        ('pacingSegments',  'pacing_segments',  'popup-preview.py', pp_raw),
        ('colorFor',        'color_for',        'popup-preview.py', pp_raw),
    ]
    declared_js = {p[0] for p in pairs}

    py_sources = {
        'generate-icon.py': gi_raw,
        'popup-preview.py': pp_raw,
    }

    js_funcs = set(re.findall(r'function (\w+)\s*\(', js_raw))
    warned = False
    for js_fn in sorted(js_funcs):
        if js_fn in declared_js:
            continue
        # camelCase → snake_case: insert underscore before each uppercase run
        snake = re.sub(r'([A-Z])', r'_\1', js_fn).lower().lstrip('_')
        for py_file, py_raw in py_sources.items():
            py_defs = set(re.findall(r'def (\w+)\s*\(', py_raw))
            if snake in py_defs:
                print(
                    f'WARNING: {js_fn} (extension.js) ↔ {snake} ({py_file}) '
                    f'look like a parity pair but are not in PAIRS',
                    file=sys.stderr,
                )
                warned = True
    if not warned:
        print('lint-pair-inventory: OK (no unregistered JS↔Python pairs detected)')


def main():
    rc = check_scraper_parity()
    rc |= check_anchor_strings()
    rc |= check_pacing_parity()
    check_pair_inventory()
    return rc


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
