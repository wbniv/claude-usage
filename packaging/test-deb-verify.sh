#!/usr/bin/env bash
# Verify a freshly-installed claude-usage .deb inside a container.
# Runs file-presence checks, syntax sanity, then apt-removes and confirms
# postrm cleaned the system-wide GSettings schema.
#
# Shared between `task test-deb` (cold/clean Ubuntu) and `task test-deb-fast`
# (prebaked image) — keep both paths exercising the same checks.
set -euo pipefail

# Shipped binaries
test -x /usr/bin/claude-usage-setup
test -x /usr/bin/claude-usage-status
# Shipped server
test -f /usr/share/claude-usage/generate-icon.py
test -f /usr/share/claude-usage/usage-server.py
test -f /usr/share/claude-usage/tooltip.py
# VD-1 (pass-18): schema_defaults.py and its sibling schemas/ XML must be
# shipped together — generate-icon.py imports schema_defaults at module
# load and the import crashes if the XML is missing. py_compile below
# doesn't catch this (it parses but doesn't execute imports).
test -f /usr/share/claude-usage/schema_defaults.py
test -f /usr/share/claude-usage/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
# Extension + compiled schema in both locations
test -f /usr/share/gnome-shell/extensions/claude-usage@indri.studio/extension.js
test -f /usr/share/gnome-shell/extensions/claude-usage@indri.studio/schemas/gschemas.compiled
test -f /usr/share/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
# Desktop entry, icons, systemd unit
test -f /usr/share/applications/claude-usage.desktop
test -f /usr/share/pixmaps/claude-usage.png
test -f /usr/share/icons/hicolor/64x64/apps/claude-usage.png
test -f /usr/lib/systemd/user/claude-usage-fetch.service
# CLI smoke + script-syntax sanity
/usr/bin/claude-usage-status -h >/dev/null
python3 -m py_compile /usr/share/claude-usage/generate-icon.py
python3 -m py_compile /usr/share/claude-usage/usage-server.py
python3 -m py_compile /usr/share/claude-usage/tooltip.py
python3 -m py_compile /usr/share/claude-usage/schema_defaults.py
# VD-1: py_compile parses but doesn't execute imports. Actually load
# schema_defaults so a missing/malformed schema XML fails CI loudly here,
# not at first icon-render on a user's box.
# VD-2 (pass-19): assertion messages + a specific key check so a CI failure
# tells you which guarantee broke. threshold_warning has historically been
# the canary key (pass-17 DG-1 was an out-of-sync value for it).
python3 -c "
import sys; sys.path.insert(0, '/usr/share/claude-usage')
import schema_defaults
assert schema_defaults.DEFAULTS, 'schema_defaults.DEFAULTS empty — XML parsed but produced no keys'
assert 'threshold_warning' in schema_defaults.DEFAULTS, \
    'threshold_warning missing from schema_defaults.DEFAULTS — schema XML drift?'
"
bash -n /usr/bin/claude-usage-setup
python3 -m py_compile /usr/bin/claude-usage-status
# Removal must clear the system-wide schema (postrm)
DEBIAN_FRONTEND=noninteractive apt-get remove -y claude-usage
test ! -f /usr/share/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
echo OK
