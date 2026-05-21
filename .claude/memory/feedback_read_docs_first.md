---
name: feedback-read-docs-first
description: "Read project docs before debugging — don't assume architecture from code alone"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fb7b89dd-fb43-4c64-ae33-17e66633e4c4
---

Always read the project's README, MANUAL, and any other docs before diagnosing issues or making assumptions about how the system works.

**Why:** I wasted significant time chasing Unity LauncherEntry signals as the dock ring mechanism, when README.md and MANUAL.md clearly document that the rings are baked into a PNG by `generate-icon.py`. Reading the docs first would have avoided the entire wrong detour.

**How to apply:** For this project specifically: README.md describes the full architecture and data flow; MANUAL.md describes what each visual component does and how it works. Read both before touching anything. This applies generally too — docs exist for a reason.
