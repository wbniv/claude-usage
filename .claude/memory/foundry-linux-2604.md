---
name: foundry-linux-2604
description: "Foundry Linux (~/SRC/foundrylinux.org) is Will's Ubuntu 26.04 + KDE Plasma 6 distro — dogfood it whenever a 26.04 / Plasma-6 environment is needed"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fc0f1fc4-7923-421e-9ed2-4ef49eeeb7e8
---

Foundry Linux lives at `~/SRC/foundrylinux.org` (i.e. `../foundrylinux.org/` from
`~/SRC/claude-usage`). It is Will's own Ubuntu **26.04**-based distro shipping **KDE
Plasma 6** and the full org.kde.plasma.* / Kirigami QML module stack. The
`claude-usage` KDE live-test harness (`scripts/test-kde-qemu.sh`) already boots a
Foundry ISO in QEMU.

**Why:** When a task needs a 26.04 box or a real Plasma-6 environment (e.g. running
`qmllint` so it resolves `PlasmoidItem`/`Plasma5Support`/`cfg_*` aliases instead of
emitting unresolved-type/-alias noise, or any 26.04-only dependency), Foundry is the
canonical, owned, reproducible source — don't reach for `ubuntu:25.xx`/`26.04`
generic images and hand-install Plasma modules.

**How to apply:** Prefer a Foundry-based container/image (or the QEMU ISO for live
desktop tests) over stock Ubuntu when 26.04 or Plasma 6 is required. Dogfood it.
Related: [[cross-desktop-rename]] CI work that surfaced this (lint-qml needs the
Plasma QML modules present to type-check the plasmoid).
