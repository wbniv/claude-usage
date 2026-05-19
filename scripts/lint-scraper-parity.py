#!/usr/bin/env python3
"""SC-3 (pass-15 §8): parity lint between scraper.js and background.js's
inlined scrape.

The two files implement equivalent scraping logic but live separately because
`chrome.scripting.executeScript`'s `func:` runs in the page context and cannot
import ES modules. `scraper.js` is what `chrome-extension/test/scraper.test.js`
exercises; the inlined copy in `background.js` is what production actually
runs. A regex change in one place that misses the other ships green tests
with a broken production scrape.

Strategy: extract every regex literal from the scrape-relevant section of
both files, normalize, and compare the *sets*. The most common drift mode
("someone updated a parsing regex in one place") is a missing regex on one
side — set difference catches it.

Exits 0 on parity, 1 on divergence with a diff report.
"""
import re
import sys
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent / 'chrome-extension'


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
    """Drop // line comments and /* */ block comments. Crude — assumes
    neither appears inside a string literal in our codebase (true today)."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'([^:])//[^\n]*', r'\1', text)
    return text


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


def main():
    scraper = (EXT / 'scraper.js').read_text()
    background = (EXT / 'background.js').read_text()

    scraper_clean = _strip_comments(scraper)
    inline_clean = _strip_comments(_extract_inline_scrape(background))

    scraper_regexes = _regexes_in(scraper_clean)
    inline_regexes = _regexes_in(inline_clean)

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


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    sys.exit(main())
