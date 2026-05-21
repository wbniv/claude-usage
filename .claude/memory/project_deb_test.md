---
name: project_deb_test
description: Next session pick-up — fresh .deb install test after logout/login
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f8083c1-5f09-4b8d-93b0-c60713b01f07
---

After building v0.9 .deb and uninstalling the source install, the user logged out to test a clean .deb installation.

**Why:** Testing the full .deb install path (BUG-P3-3, BUG-P3-5 fixes) and the new selectable panel metric feature (panel-metric GSettings key) in a clean environment.

**How to apply:** On next session start, remind the user to install the .deb if they haven't already:

```bash
sudo dpkg -i ~/SRC/claude-usage/dist/claude-usage_0.9_all.deb
sudo apt-get install -f
claude-usage-setup
```

Then load the Chrome extension from `/usr/share/claude-usage/chrome-extension/` and verify:
1. Panel indicator appears after login
2. Popup rows are clickable — clicking a row changes the panel metric
3. Scroll on panel label cycles through eligible meters
4. `gsettings get org.gnome.shell.extensions.claude-usage panel-metric` works without GSETTINGS_SCHEMA_DIR (BUG-P3-5 check)
5. Dock icon has rounded corners and updates after first Chrome fetch
