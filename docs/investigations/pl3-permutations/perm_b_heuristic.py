#!/usr/bin/env python3
"""PL-3 Permutation B — All-string diff with anchor-shape heuristic filter.

Strategy:
  - Extract every quoted string literal from both files' scrape regions.
  - Compute symmetric difference.
  - Filter the diff to "anchor-shaped" strings:
      * multi-word (contains a space), OR
      * starts with an attribute-selector character ('[' for DOM selectors)
    Filter intentionally excludes single-word strings like 'complete',
    'switch', 'role' that produce noise.
  - Report any anchor-shaped string in one file but not the other.

Properties:
  - False positives: low if heuristic holds. A single-word anchor (e.g. a
    future 'Limits' section header) would be silently ignored.
  - False negatives: a string that exists in both but with a typo on one
    side (e.g. 'Plan usage limit' vs 'Plan usage limits') IS caught —
    they appear in the symmetric difference.
  - Maintenance: zero — no list to update. Heuristic alone defines scope.
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
    """Tighter than the existing lint: only the inner `function doScrape()`
    body inside the executeScript func, which is what mirrors scraper.js's
    doScrape. Excludes scrapeAndPost's wrapper console.warn strings."""
    start = background_text.find('function doScrape()')
    if start < 0:
        raise SystemExit('PermB: doScrape not found in background.js')
    depth, i = 0, background_text.index('{', start)
    while i < len(background_text):
        if background_text[i] == '{': depth += 1
        elif background_text[i] == '}':
            depth -= 1
            if depth == 0:
                return background_text[start:i + 1]
        i += 1
    raise SystemExit('PermB: could not close doScrape body')


def _is_anchor_shaped(s):
    if not s:
        return False
    if s.startswith('['):                       # DOM attribute selector
        return True
    if ' ' in s and s[0].isupper():             # English UI phrase
        return True
    return False


def check():
    scraper = _strip_comments((EXT / 'scraper.js').read_text())
    inline = _strip_comments(_extract_inline_scrape((EXT / 'background.js').read_text()))

    scraper_strs = {s for s in _strings_in(scraper) if _is_anchor_shaped(s)}
    inline_strs = {s for s in _strings_in(inline) if _is_anchor_shaped(s)}

    only_scraper = scraper_strs - inline_strs
    only_inline = inline_strs - scraper_strs

    if not only_scraper and not only_inline:
        print(f'PermB: OK ({len(scraper_strs & inline_strs)} anchor-shaped strings '
              f'match between scraper.js and background.js inline)')
        return 0

    print('PermB: DIVERGENCE between scraper.js and background.js inline scrape',
          file=sys.stderr)
    if only_scraper:
        print('\n  Anchor-shaped strings in scraper.js but NOT in background.js inline:',
              file=sys.stderr)
        for s in sorted(only_scraper):
            print(f'    {s!r}', file=sys.stderr)
    if only_inline:
        print('\n  Anchor-shaped strings in background.js inline but NOT in scraper.js:',
              file=sys.stderr)
        for s in sorted(only_inline):
            print(f'    {s!r}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(check())
