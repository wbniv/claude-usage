---
name: feedback-logout-disruption
description: Logging out/in is very disruptive; exhaust all static and runtime checks before recommending it
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fb7b89dd-fb43-4c64-ae33-17e66633e4c4
---

Never suggest "log out and back in" as a first or easy option. It is very disruptive to the user.

**Why:** User explicitly stated this and pushed back when it was recommended.

**How to apply:** For GNOME extension work (and any other session-restart scenarios), first exhaust all statically verifiable checks: syntax validation, schema loading via `gsettings`/`GSETTINGS_SCHEMA_DIR`, metadata JSON inspection, compiled binary string checks, XML validation, D-Bus queries. Only recommend logout after all checkable preconditions pass and you've confirmed no remaining alternative (e.g., `gdbus` reload, `gnome-extensions disable/enable`, worktree isolation). When a logout is ultimately unavoidable, say so explicitly with the evidence that all static checks passed.
