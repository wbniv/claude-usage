---
name: user-email-preference
description: "Will's preferred public-facing email is will@biohack.net (not wbnorris@gmail.com)"
metadata: 
  node_type: memory
  type: user
  originSessionId: 7903bd6c-8def-464e-9dc3-fc7eddac5c87
---

For any user-facing email field (package Maintainer, contact info in docs, PRIVACY.md, copyright lines, etc.), use **`will@biohack.net`**.

`wbnorris@gmail.com` is his personal Gmail and should not be used for new project artifacts. Existing references should be migrated when noticed.

**How to apply:** Default to `will@biohack.net` for any new email reference. When editing files that already contain `wbnorris@gmail.com`, replace it. Don't change git commit author email or shell-history references — those are historical.
