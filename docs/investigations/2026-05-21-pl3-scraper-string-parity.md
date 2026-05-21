# PL-3 — scraper.js ↔ background.js inline string parity

**Status**: investigation, recommendation included.
**TODO**: `PL-3` (Deferred).
**Origin**: pass-26 ([review](2026-05-20-code-review-pass26.md)).

## The gap

`scripts/lint-scraper-parity.py` extends the existing
`check_scraper_parity()` to compare every JS **regex literal** in
`scraper.js` against the inline-scrape region of `background.js`. It does
not compare:

1. Section-anchor strings used as literal-equality matches:
   ```js
   const planStart  = lines.findIndex(l => l === 'Plan usage limits');
   const extraStart = lines.findIndex(l => l === 'Extra usage');
   ```
   Both strings are duplicated verbatim in both files. A typo in one
   side (`'Plan usage limit'`) would not surface in the lint or in the
   unit tests (which exercise scraper.js only).

2. The DOM selector that drives the Extra-usage toggle read:
   ```js
   document.querySelector('[role="switch"][aria-label="Extra usage"]');
   ```
   This selector appears only in `background.js`. `scraper.js` takes
   the toggle's boolean state as a parameter (`extraToggleChecked`),
   so there is no parity to lint — but the selector is a fragile DOM
   contract worth pinning somehow.

## Candidate implementations

Each permutation is implemented as a runnable Python module under
`docs/investigations/pl3-permutations/`. All operate on the live source
tree and are reproducible with `python3 docs/investigations/pl3-permutations/perm_*.py`.

### A — Hand-maintained anchor allowlist

`docs/investigations/pl3-permutations/perm_a_allowlist.py`

```python
ANCHOR_STRINGS = ['Plan usage limits', 'Extra usage']
DOM_SELECTORS_IN_BACKGROUND = ['[role="switch"][aria-label="Extra usage"]']

# For each anchor: assert presence in both scraper.js AND background.js.
# For each selector: assert presence in background.js (single-sided pin).
```

Output against live source:
```
PermA: OK (2 anchors + 1 selectors present)
```

### B — All strings, anchor-shape heuristic filter

`docs/investigations/pl3-permutations/perm_b_heuristic.py`

Extract every quoted string literal from both `doScrape` bodies, filter
to anchor-shaped (multi-word capitalised English OR starts with `[`),
report any in the symmetric difference.

Output against live source:
```
PermB: DIVERGENCE between scraper.js and background.js inline scrape
  Anchor-shaped strings in background.js inline but NOT in scraper.js:
    '[role="switch"][aria-label="Extra usage"]'
```

The lone "divergence" is the DOM selector — present only in
`background.js` by design (scraper.js takes the toggle state as a
parameter). Out of the box this gives a false positive. Tightening the
heuristic to drop bracketed strings would suppress it, at the cost of
losing the ability to pin selector strings.

### C — Full string-set symmetric diff

`docs/investigations/pl3-permutations/perm_c_full_diff.py`

No filter. Every string-literal mismatch surfaces.

Output against live source (with both slices narrowed to just `doScrape`):
```
PermC: DIVERGENCE — string sets do not match
  In scraper.js but NOT background.js inline (2):  'AM', 'PM'
  In background.js inline but NOT scraper.js (4):
    '[role="switch"][aria-label="Extra usage"]', 'aria-checked',
    'switch', 'true'
```

Six items, none of them drift — `'AM'`/`'PM'` are inside scraper.js's
`parseResetMinutes` (not `doScrape`); the bracketed/aria strings are the
toggle-query plumbing that lives only in `background.js`. Useful
divergence (`'Plan usage limits'` mistyped on one side) would be lost
in this noise floor — operationally indistinguishable from the
benign mismatches. Living with C requires either a growing exclusion
list (collapses to "A with inverted polarity") or tolerating noise.

### D — Refactor: eliminate the duplication

`docs/investigations/pl3-permutations/perm_d_refactor.diff`

`chrome.scripting.executeScript({...})` accepts an `args:` array whose
JSON-serialisable values are passed as parameters to the injected
`func:`. Move the section anchors and selector to constants in
`scraper.js`, import them in `background.js`, pass them through `args:`.
No parity, no lint required.

Caveats:
- The MV3 service worker has to load as an ES module
  (`"background.type": "module"` in `manifest.json`) for `import` to
  work in `background.js`. Verify before committing.
- Regex literals still cannot ride along via `args:`; the existing
  regex-set lint stays.
- ~25 lines edited across two files; one manual reload to verify.

### E — Accept the duplication

Do nothing. Document the gap in `scraper.js`'s leading comment so the
next code review picks it up. Rely on:
- Tests exercising `scraper.js` directly.
- Manual review of changes to `background.js`'s inline `doScrape`.
- The existing regex-set lint catching most parsing-shape changes
  (any new section anchor likely also appears in a regex alternation).

## Grading

| Permutation                                       | False positives | False negatives                  | Maintenance               | Catches PL-3 drift     | Implementation cost                                              |
|---------------------------------------------------|-----------------|----------------------------------|---------------------------|------------------------|------------------------------------------------------------------|
| **A** — Allowlist                                 | 0               | Anchors not added to the list    | Update on every new anchor | Yes, deterministically | ~80 lines, lives next to existing lint                          |
| **B** — Heuristic filter                          | 1 (selector)    | Single-word anchors              | Heuristic stacking         | Yes, modulo heuristic  | ~90 lines, plus tuning                                          |
| **C** — Full diff                                 | 6+ (and growing) | None in principle               | Exclusion list grows       | Yes, in the noise      | ~70 lines, plus exclusion churn                                 |
| **D** — Refactor via `args:`                       | n/a (no lint)   | n/a                              | None ongoing               | n/a (gap eliminated)   | ~25-line code change + 1 manual verify; possible manifest edit  |
| **E** — Accept                                    | n/a             | All drift on the missed strings  | None                       | No                     | 1 comment edit                                                  |

A few cross-cutting observations from running the implementations:

- **Slice tuning matters more than algorithm.** Both B and C only
  behaved sensibly after `_extract_inline_scrape` was narrowed from
  the existing lint's `parseResetMinutes → fetchUsage` window down to
  just the inner `function doScrape()` body. With the wider slice B
  and C report 5 and 15 noise items respectively (mostly
  `scrapeAndPost`'s `console.warn` strings). The existing
  regex-literal lint tolerated the wider slice because regex
  extraction is naturally selective; once we include string literals,
  the slice has to be much tighter or the noise floor swamps signal.

- **A and D are the only two that fail closed.** A reports a concrete
  missing anchor with the diff; D removes the source of drift
  entirely. B and C report a probabilistic divergence that humans
  have to triage — and the triage burden grows as the codebase does.

- **The real population is two strings.** This isn't a wide-surface
  parity problem (cf. the pacing lint, which compares ~30 numeric
  literals across four pairs). It's literally
  `'Plan usage limits'` and `'Extra usage'`. The selector is
  single-sided so it isn't a parity question. An allowlist of two
  entries is not a maintenance burden.

## Recommendation

**Pick A** — hand-maintained allowlist.

Reasons:
1. Real parity gap is narrow (2 strings). The maintenance cost of an
   allowlist is one line per anchor, paid maybe once a year when
   Anthropic renames a section heading.
2. Fails closed with a precise diagnostic (`"Plan usage limit" missing
   in scraper.js`), not a probabilistic diff for a human to triage.
3. Composes naturally with the existing regex-set lint in
   `check_scraper_parity()` — add ~30 lines to that function, no
   structural refactor.
4. The single-sided DOM-selector pin gives us a cheap "selector still
   present in background.js" assertion. If the next claude.ai redesign
   moves the toggle off `[role="switch"][aria-label="Extra usage"]`,
   the lint at least confirms the selector was changed deliberately
   rather than typo'd away.

**Defer D** until either:
- A second cross-file string contract appears (e.g. a new selector
  scraper.js needs to know about), at which point the cost of
  centralising compounds favourably, or
- We're already touching MV3 module wiring for another reason.

D is the architecturally cleaner answer, but the
ROI today is dominated by manifest-edit risk + an extension reload
to verify. Worth a follow-up TODO once two more strings show up.

**Reject B and C.** Slice fragility and growing exclusion lists make
them strictly worse than A for the same coverage. C's "catches
everything" property is illusory once you account for the noise floor
that humans learn to ignore.

**Reject E.** The duplication is small but the failure mode
(silent typo in a literal-equality match → "locale_or_layout"
partial scrape with no clear cause) is exactly the kind of slow-burn
bug the parity lint was created to prevent.

## Concrete next step (if A is approved)

Add a `check_anchor_strings()` function to
`scripts/lint-scraper-parity.py` based on `perm_a_allowlist.py`, wire
it into `main()` alongside the existing checks, no Taskfile change
needed (the existing `lint-scraper-parity` task runs `main()`).

Add a regression note to `chrome-extension/scraper.js`'s leading
comment pointing at the lint.

No source changes to `scraper.js` or `background.js`.
