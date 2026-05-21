#!/usr/bin/env python3
"""PL-3 Permutation A — Hand-maintained anchor allowlist.

Strategy:
  - Define an explicit list of section-anchor strings and DOM selectors that
    MUST appear in both scraper.js and background.js's inline scrape region.
  - Lint asserts each entry is present in both files. Anything missing on
    either side is reported.
  - New anchors require updating the allowlist; the lint cannot discover
    them on its own.

Properties:
  - False-positive rate: zero (the list IS the contract).
  - False-negative rate: only what humans forget to add.
  - Maintenance: every time a new section header is introduced, the list
    has to be updated alongside the source change.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
EXT = REPO / 'chrome-extension'

# Hand-maintained — every string here must appear verbatim in both
# scraper.js and background.js's inline scrape region (the executeScript
# func body inside scrapeAndPost).
ANCHOR_STRINGS = [
    'Plan usage limits',
    'Extra usage',
    # Additional anchors are already covered as regex alternation literals
    # in the existing regex-set lint, so they're not enumerated here.
]

# Selectors: scraper.js takes the toggle state as a parameter, so this
# selector appears only in background.js. Listed here as a "presence
# expected in background.js" check — single-side parity, but worth
# pinning so a refactor that drops the query is caught.
DOM_SELECTORS_IN_BACKGROUND = [
    '[role="switch"][aria-label="Extra usage"]',
]


def _extract_inline_scrape(background_text):
    start = background_text.find('function parseResetMinutes')
    end = background_text.find('async function fetchUsage', start)
    if start < 0 or end < 0:
        raise SystemExit('PermA: could not slice background.js scrape region')
    return background_text[start:end]


def check():
    scraper = (EXT / 'scraper.js').read_text()
    background = (EXT / 'background.js').read_text()
    inline = _extract_inline_scrape(background)

    rc = 0
    for s in ANCHOR_STRINGS:
        in_scraper = (f"'{s}'" in scraper) or (f'"{s}"' in scraper)
        in_inline = (f"'{s}'" in inline) or (f'"{s}"' in inline)
        if not (in_scraper and in_inline):
            rc = 1
            print(
                f'PermA: anchor {s!r} '
                f'{"missing in scraper.js " if not in_scraper else ""}'
                f'{"missing in background.js inline" if not in_inline else ""}',
                file=sys.stderr,
            )

    for s in DOM_SELECTORS_IN_BACKGROUND:
        if (f"'{s}'" not in background) and (f'"{s}"' not in background):
            rc = 1
            print(f'PermA: required selector {s!r} missing in background.js',
                  file=sys.stderr)

    if rc == 0:
        print(f'PermA: OK ({len(ANCHOR_STRINGS)} anchors + '
              f'{len(DOM_SELECTORS_IN_BACKGROUND)} selectors present)')
    return rc


if __name__ == '__main__':
    sys.exit(check())
