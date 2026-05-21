#!/usr/bin/env python3
"""PL-3 Permutation C — Full string-set symmetric diff (no filter).

Strategy:
  - Extract every quoted string literal from both files' scrape regions.
  - Compute symmetric difference. Report EVERY divergence.
  - No filter, no allowlist — maximum coverage, maximum noise.

Properties:
  - False positives: high — Python-style accessor patterns, console.log
    text, type checks, and one-off strings (e.g. 'AM', 'PM', '...') all
    surface as divergences.
  - False negatives: zero in principle. Any string mismatch is reported.
  - Maintenance: zero, but every legitimate single-side string addition
    requires either an exclusion list (defeating the "no filter" promise)
    or an immediate matching change in the twin (creating churn).

This permutation is included for completeness. In practice it would
require a growing exclusion list — at which point it converges with
Permutation A in reverse (an allowlist of ignored strings instead of
required strings).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
EXT = REPO / 'chrome-extension'


def _strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'([^:])//[^\n]*', r'\1', text)
    return text


def _strings_in(text):
    out = set()
    out |= set(re.findall(r"'([^'\\]*(?:\\.[^'\\]*)*)'", text))
    out |= set(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text))
    return out


def _extract_inline_scrape(background_text):
    """Tighter slice: only the inner `function doScrape()` body inside the
    executeScript func — apples-to-apples with scraper.js's doScrape."""
    start = background_text.find('function doScrape()')
    if start < 0:
        raise SystemExit('PermC: doScrape not found in background.js')
    depth, i = 0, background_text.index('{', start)
    while i < len(background_text):
        if background_text[i] == '{': depth += 1
        elif background_text[i] == '}':
            depth -= 1
            if depth == 0:
                return background_text[start:i + 1]
        i += 1
    raise SystemExit('PermC: could not close doScrape body')


def check():
    scraper = _strip_comments((EXT / 'scraper.js').read_text())
    inline = _strip_comments(_extract_inline_scrape((EXT / 'background.js').read_text()))

    scraper_strs = _strings_in(scraper)
    inline_strs = _strings_in(inline)

    only_scraper = scraper_strs - inline_strs
    only_inline = inline_strs - scraper_strs

    if not only_scraper and not only_inline:
        print(f'PermC: OK ({len(scraper_strs)} strings match)')
        return 0

    print('PermC: DIVERGENCE — string sets do not match', file=sys.stderr)
    if only_scraper:
        print(f'\n  In scraper.js but NOT background.js inline ({len(only_scraper)}):',
              file=sys.stderr)
        for s in sorted(only_scraper):
            print(f'    {s!r}', file=sys.stderr)
    if only_inline:
        print(f'\n  In background.js inline but NOT scraper.js ({len(only_inline)}):',
              file=sys.stderr)
        for s in sorted(only_inline):
            print(f'    {s!r}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(check())
