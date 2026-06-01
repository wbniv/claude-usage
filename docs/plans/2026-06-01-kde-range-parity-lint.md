# 2026-06-01 — KDE config range-parity lint

## Context

A stale local branch `kde-plasma-support` (2026-05-25) held a first-draft KDE
plasmoid plus a config **generator** (`scripts/gen-kde-config.py`) that emitted
`main.xml` (KConfigXT) from the GNOME gschema, with a `--check` mode as a drift
guard. The plasmoid was later reimplemented directly on `main` under
`desktop/kde/` (2026-05-28) and hardened through ~30 review passes. The branch
is superseded and will be retired.

The only idea worth salvaging from it was the gschema↔`main.xml` single-source-
of-truth guarantee. On inspection, `main` already enforces that:
`scripts/lint-kde-parity.py::check_config_parity` (KDE-5) asserts every
`main.xml` **default** equals the gschema default via an explicit `KEY_MAP`.

So porting the generator was rejected:
- **A (faithful port)** would regenerate `main.xml` and regress reviewed choices
  (colors as `String` not `Color`; grouping comments not `<label>`s; deliberate
  reordering; omission of `panel-label-spacing`; size-field ranges left to QML).
- **C (curated port)** would hard-code all of that layout into the generator —
  a brittle re-encoding of the file it's meant to generate, buying a guarantee
  that already exists.

## Decision — option B

The one real gap in the existing lint: it checks **defaults** but not **ranges**.
The gschema declares `<range>` on seven keys; `main.xml` carries `<min>/<max>`
on only `thresholdWarning`/`thresholdCritical` (the size fields delegate bounds
to their QML SpinBoxes — a deliberate choice we will not undo).

Add `check_range_parity()` to `lint-kde-parity.py`:
- Compare `min`/`max` **only for keys that declare a range on BOTH sides**
  (today: the two thresholds, both `1–500`). One-sided ranges are out of scope
  by design, so no reviewed content changes.
- Future-proof: any range later added to `main.xml` is automatically pinned to
  the gschema.

## Scope

- `scripts/lint-kde-parity.py`: two helpers (`_gschema_ranges`, `_kcfg_ranges`),
  one check (`check_range_parity`), wired into `main()`; docstring item 6.
- No change to `main.xml`, the QML, the gschema, or the Taskfile (the existing
  `lint-kde-parity` target already runs the whole module).

## Verification

- `python3 scripts/lint-kde-parity.py` exits 0 (thresholds match → pass).
- Negative check: temporarily perturb a `main.xml` threshold `<max>` → the lint
  reports `range drift` and exits 1; revert.
