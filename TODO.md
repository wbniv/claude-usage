# TODO

## Fixes
- [ ] **Pass-15 Low + Info findings → 0.11.13.** HM‑2 (Content-Length ValueError), SC‑2 (textContent ↔ innerText), I‑2 (Wayland enable messaging), SC‑3 (scraper parity lint), PR‑1 (postUpdate 5xx-with-signature), L‑3 (PORT_CACHE_TTL_MS 1h → 24h), CI‑4 (weekly docker-cache bust). Plan: [`docs/plans/2026-05-19-fix-pass-15-low-info-findings-0-11-13.md`](docs/plans/2026-05-19-fix-pass-15-low-info-findings-0-11-13.md).

## Deferred
- [ ] **TF‑1 — bundle with next icon-rendering refactor.** `.desktop` Icon= holds a per-nanosecond absolute path; `rm -rf ~/.cache/claude-usage` leaves the dock launcher with a missing-icon glyph until next regen (≤ 60 s). Self-heals; not urgent. Pass-15 §10: "Don't do solo." Sketch: stable `Icon=claude-usage` + symlink at `~/.cache/claude-usage/icon-current.png` → latest timestamped PNG.

## Done
- [x] 2026-05-19 — Pass-15 H+M findings → 0.11.12 (U‑1 deploy gap, TS‑1 timestamp bound, T‑8 parser parity). [Plan](docs/plans/2026-05-19-fix-pass-15-high-medium-findings-0-11-12.md). Commits: `ef3a852`, `574c32c`.
