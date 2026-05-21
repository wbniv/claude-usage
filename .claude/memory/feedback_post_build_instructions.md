---
name: feedback-post-build-instructions
description: "After building a .deb package, always print the correct install command with ./ prefix"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 61aab3c3-874f-4a0e-bfef-be5640f77b1d
---

After `task build` or any .deb build, always show the installation command immediately:

```
sudo dpkg -i ./dist/claude-usage_<VERSION>_all.deb
```

**Why:** `apt-get install dist/...` (without `./`) fails — apt interprets it as a package name, not a file path. The `./` prefix is required. User was burned by the build output's suggested command not having it.

**How to apply:** Whenever a .deb build completes successfully, follow up with the exact install command including `./`.
