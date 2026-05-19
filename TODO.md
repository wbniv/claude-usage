# TODO

## Fixes

## Deferred
- [ ] **Pacing parity lint (post-0.11.14).** `pacingPct` in `gnome-extension/extension.js` and `pacing_pct` in `server/generate-icon.py` are hand-synced. Generalise `scripts/lint-scraper-parity.py` to cover this function pair (or unify via a single source of truth). Trigger: next time one drifts.
- [ ] **TF‑1 — bundle with next icon-rendering refactor.** `.desktop` Icon= holds a per-nanosecond absolute path; `rm -rf ~/.cache/claude-usage` leaves the dock launcher with a missing-icon glyph until next regen (≤ 60 s). Self-heals; not urgent. Pass-15 §10: "Don't do solo." Sketch: stable `Icon=claude-usage` + symlink at `~/.cache/claude-usage/icon-current.png` → latest timestamped PNG.

## Done
- [x] 2026-05-19 — Pass-16 M findings → 0.11.17 (TH‑1 stale-threshold drift, V‑2 top-level filter, PL‑1 eviction guard, V‑3 empty-string labels; 6 new tests). [Plan](docs/plans/2026-05-19-fix-pass-16-medium-bugs-0-11-17.md).
- [x] 2026-05-19 — Pacing early-period false-critical → 0.11.16 (15-min time-based floor in pacingPct + pacing_pct; 13-case pytest regression). [Plan](docs/plans/2026-05-19-pacing-early-period-fix-0-11-14.md). Commits: `1eacc51` (fix), tag `v0.11.14` (failed CI: missing cairo), `c9f7075` + tag `v0.11.15` (failed CI: BASE_ICON discovery), `<next>` (XDG stub + bump 0.11.16).
- [x] 2026-05-19 — Pass-15 L+I findings → 0.11.13 (HM‑2, SC‑2, I‑2, SC‑3, PR‑1, L‑3, CI‑4). [Plan](docs/plans/2026-05-19-fix-pass-15-low-info-findings-0-11-13.md). Commit: `ea28b71`.
- [x] 2026-05-19 — Pass-15 H+M findings → 0.11.12 (U‑1 deploy gap, TS‑1 timestamp bound, T‑8 parser parity). [Plan](docs/plans/2026-05-19-fix-pass-15-high-medium-findings-0-11-12.md). Commits: `ef3a852`, `574c32c`.
