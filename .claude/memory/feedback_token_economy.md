---
name: feedback-token-economy
description: "Keep responses and exploration minimal — one sentence summaries, targeted lookups not broad exploration"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 807b349c-f413-4b58-b847-3ad316efca29
---

End-of-turn summaries: **1 sentence max**, not 2.

Before spawning broad exploration (Agent/Explore/multi-tool fan-out), ask: could a single `grep` or `find` answer this? Use targeted lookups first; only escalate if the first shot misses.

**Why:** Over-exploring burns 30%+ of a session's tokens on questions a focused search resolves in a few thousand.

**How to apply:** Default to the smallest-scope tool that could work — a `grep` over spawning an Explore agent, a single `Read` over reading the whole tree. Reserve broad exploration for genuinely unknown codebases or when the first targeted attempt fails.
