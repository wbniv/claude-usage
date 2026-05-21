---
name: feedback-semver-patch-bumps
description: "Use semver patch bumps (0.9 → 0.9.1) for small fixes, not minor bumps (0.10)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7903bd6c-8def-464e-9dc3-fc7eddac5c87
---

For small changes — bug fixes, cleanups, refactors, file-layout consolidations — bump the **patch** component (0.9 → 0.9.1), not the minor.

**Why:** User explicitly corrected a 0.9 → 0.10 bump I made for a cache-layout reorganization. They follow standard semver: minor bumps imply user-facing feature changes; patch bumps are for everything else.

**How to apply:** Default to `X.Y.Z+1` for any bump unless the change introduces a new feature or breaking change. If the current version is two-component (`0.9`), extend to three (`0.9.1`). Touches [[project-version-locations]] — bump both `packaging/control` and `chrome-extension/manifest.json` together.
