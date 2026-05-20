# TODO

## Fixes

## Deferred

## Done
- [x] 2026-05-20 — Pacing parity lint: extended `scripts/lint-scraper-parity.py` to compare numeric constants in `pacingPct` (extension.js) vs `pacing_pct` (generate-icon.py); catches constant drift on `15`, `0.05`, etc.
- [x] 2026-05-20 — Pacing-aware threshold range → 0.11.19 (`<range max>` 99 → 500 on threshold-warning + threshold-critical; pacing is uncapped, schema cap was stale from pre-pacing semantics). [Plan](docs/plans/2026-05-20-pacing-threshold-range-0-11-19.md).
- [x] 2026-05-19 — Pass-16 L+I findings + TF‑1 → 0.11.18 (R‑1 autoscrape race, WP‑1 period-scaled pacing floor, D‑1/TF‑1 stable Icon=claude-usage via icon-theme dir, D‑2 startup icon refresh, N‑1 toast reword, I‑1 nuke-and-recreate install dirs; 3 new pacing tests). [Plan](docs/plans/2026-05-19-fix-pass-16-medium-bugs-0-11-17.md). Commit: `095c3e1`.
- [x] 2026-05-19 — Pass-16 M findings → 0.11.17 (TH‑1 stale-threshold drift, V‑2 top-level filter, PL‑1 eviction guard, V‑3 empty-string labels; 6 new tests). [Plan](docs/plans/2026-05-19-fix-pass-16-medium-bugs-0-11-17.md). Commit: `35bbb91`.
- [x] 2026-05-19 — Pacing early-period false-critical → 0.11.16 (15-min time-based floor in pacingPct + pacing_pct; 13-case pytest regression). [Plan](docs/plans/2026-05-19-pacing-early-period-fix-0-11-14.md). Commits: `1eacc51` (fix), tag `v0.11.14` (failed CI: missing cairo), `c9f7075` + tag `v0.11.15` (failed CI: BASE_ICON discovery), `<next>` (XDG stub + bump 0.11.16).
- [x] 2026-05-19 — Pass-15 L+I findings → 0.11.13 (HM‑2, SC‑2, I‑2, SC‑3, PR‑1, L‑3, CI‑4). [Plan](docs/plans/2026-05-19-fix-pass-15-low-info-findings-0-11-13.md). Commit: `ea28b71`.
- [x] 2026-05-19 — Pass-15 H+M findings → 0.11.12 (U‑1 deploy gap, TS‑1 timestamp bound, T‑8 parser parity). [Plan](docs/plans/2026-05-19-fix-pass-15-high-medium-findings-0-11-12.md). Commits: `ef3a852`, `574c32c`.
