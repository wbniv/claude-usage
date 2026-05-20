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


def _numeric_literals(text):
    """Return the set of numeric literals (int and float) in code text."""
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


def check_pacing_parity():
    """Check the hand-synced pacing functions stay in numeric-literal sync.

    Four function pairs across two Python files:
      JS (extension.js)   ↔ Python (where)                            twin file
      pacingPct           ↔ pacing_pct                                 generate-icon.py
      elapsedFraction     ↔ elapsed_fraction                           generate-icon.py
      pacingSegments      ↔ pacing_segments     (viz; PS-1 pass-23)    popup-preview.py
      colorFor            ↔ color_for           (viz; PS-1 pass-23)    popup-preview.py
    """
    js_raw = _strip_comments((REPO / 'gnome-extension' / 'extension.js').read_text())
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
        js_nums = _numeric_literals(_extract_js_function(js_raw, js_name))
        py_nums = _numeric_literals(_extract_py_function(py_raw, py_name))

        only_js = js_nums - py_nums
        only_py = py_nums - js_nums

        if not only_js and not only_py:
            print(f'lint-pacing-parity: OK ({len(js_nums)} numeric literals match between {js_name} and {py_name})')
            continue

        rc = 1
        print(f'lint-pacing-parity: DIVERGENCE between {js_name} (extension.js) and {py_name} ({py_file})', file=sys.stderr)
        if only_js:
            print(f'\n  Literals in {js_name} (JS) but NOT {py_name} ({py_file}):', file=sys.stderr)
            for n in sorted(only_js, key=float):
                print(f'    {n}', file=sys.stderr)
        if only_py:
            print(f'\n  Literals in {py_name} ({py_file}) but NOT {js_name} (JS):', file=sys.stderr)
            for n in sorted(only_py, key=float):
                print(f'    {n}', file=sys.stderr)
        print('\n  A constant change in one file likely missed the other.', file=sys.stderr)
        print('  Update both, or update the lint if the divergence is intentional.', file=sys.stderr)
    return rc


def main():
    rc = check_scraper_parity()
    rc |= check_pacing_parity()
    return rc


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
