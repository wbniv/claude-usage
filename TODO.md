# TODO

## Fixes

## Deferred
- [ ] **TF‑1 — bundle with next icon-rendering refactor.** `.desktop` Icon= holds a per-nanosecond absolute path; `rm -rf ~/.cache/claude-usage` leaves the dock launcher with a missing-icon glyph until next regen (≤ 60 s). Self-heals; not urgent. Pass-15 §10: "Don't do solo." Sketch: stable `Icon=claude-usage` + symlink at `~/.cache/claude-usage/icon-current.png` → latest timestamped PNG.

## Done
- [x] 2026-05-19 — Pass-15 L+I findings → 0.11.13 (HM‑2, SC‑2, I‑2, SC‑3, PR‑1, L‑3, CI‑4). [Plan](docs/plans/2026-05-19-fix-pass-15-low-info-findings-0-11-13.md). Commit: `ea28b71`.
- [x] 2026-05-19 — Pass-15 H+M findings → 0.11.12 (U‑1 deploy gap, TS‑1 timestamp bound, T‑8 parser parity). [Plan](docs/plans/2026-05-19-fix-pass-15-high-medium-findings-0-11-12.md). Commits: `ef3a852`, `574c32c`.
