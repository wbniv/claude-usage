# A5 — dist/ Cleanup

**Date:** 2026-05-17  
**Status:** Complete  
**Triggered by:** A5 from pass-6/7 review backlog

## Context

`dist/` had 17 accumulated local build artifacts (0.9.1–0.10.7 `.deb` + two Chrome zips). All gitignored and local-only — only v0.10.6 was ever uploaded to GitHub. Going forward, `task release` deletes dist artifacts after the tag push so CI-uploaded copies are the canonical ones.

## Changes

| File | Change |
|------|--------|
| `dist/` | Deleted 15 stale artifacts (kept `claude-usage_0.10.7_all.deb` and `claude-usage-chrome-0.10.6.zip`) |
| `Taskfile.yml` | Added `rm -f dist/*.deb dist/*.zip` as final step of `task release` |

## Outcome

`dist/` reduced from 17 files to 2. Future releases auto-prune after tag push.
