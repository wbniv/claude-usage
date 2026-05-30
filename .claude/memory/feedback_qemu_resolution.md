---
name: feedback_qemu_resolution
description: All QEMU runs must use at least 1024x768 resolution (prefer 1280x800)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 821bba45-f69d-474c-8c8f-8289605fc32d
---

For every QEMU run (KDE plasmoid testing, ISO smoke tests, any VM boot), set the
display resolution to **at least 1024x768** — default virtio-gpu modes come up
too small and screenshots/inspection are hard to read.

**Why:** The default `-device virtio-vga-gl -display gtk,gl=on` boots Plasma at a
cramped resolution (~1024x768 or smaller); the user explicitly wants ≥1024x768.

**How to apply:** Add an initial-mode hint to the virtio GPU, e.g.
`-device virtio-vga-gl,xres=1280,yres=800` (QEMU ≥6.1 honours xres/yres). If the
guest ignores it, set it post-boot with `kscreen-doctor output.<name>.mode.1280x800`.
Bake this into `scripts/test-kde-qemu.sh` and any ISO boot harness. Relates to
[[feedback_popup_preview_render]].
