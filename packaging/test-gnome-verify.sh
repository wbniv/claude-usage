#!/usr/bin/env bash
# Smoke-test the GNOME extension without a running GNOME session.
#
# Tests:
#   - GNOME Shell version detection
#   - Schema compilation artifact
#   - All standalone GI namespaces used by extension.js / prefs.js
#
# Shell-internal namespaces (St, Clutter) and resource:/// imports require a
# running gnome-shell and cannot be tested here — that's a live session test.
# Full runtime (extension renders in panel) requires a real GNOME session.
set -euo pipefail

PASS=0
FAIL=0

ok()   { echo "  PASS  $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL  $*"; FAIL=$((FAIL+1)); }
info() { echo "  INFO  $*"; }

EXT=/root/.local/share/gnome-shell/extensions/claude-usage@indri.studio
META="$EXT/metadata.json"

echo "=== GNOME extension smoke test ==="
echo

# 1. Confirm GNOME Shell version
version=$(gnome-shell --version)
major=$(echo "$version" | grep -oP '\d+' | head -1)
echo "Shell: $version"
if [ -n "$major" ]; then
    ok "gnome-shell --version returns major=$major"
else
    fail "could not parse GNOME Shell major version"
fi

# 2. Extension metadata: uuid matches install path
uuid=$(grep -oP '"uuid"\s*:\s*"\K[^"]+' "$META" || true)
if [ "$uuid" = "claude-usage@indri.studio" ]; then
    ok "metadata.json uuid matches extension directory"
else
    fail "metadata.json uuid mismatch: got '$uuid'"
fi

# 3. Schema compilation artifact present (compiled in Dockerfile RUN step)
if [ -f "$EXT/schemas/gschemas.compiled" ]; then
    ok "gschemas.compiled present"
else
    fail "gschemas.compiled missing"
fi

# 4. Standalone GI namespaces used by extension.js / prefs.js
#    St and Clutter are gnome-shell-internal — only importable inside a
#    running shell process — so we skip them here.
echo
echo "Standalone GI namespace checks:"
for ns in GLib GObject Gio Adw Gtk Gdk; do
    if gjs -c "const x = imports.gi.$ns; print('ok')" 2>/dev/null | grep -q ok; then
        ok "imports.gi.$ns"
    else
        fail "imports.gi.$ns — import failed (removed or renamed in GNOME $major?)"
    fi
done
info "St, Clutter skipped — shell-internal, require running gnome-shell"

# 5. Shell-version status (informational — does not affect PASS/FAIL)
echo
if grep -q "\"$major\"" "$META"; then
    info "shell-version already includes $major"
else
    info "shell-version does not yet include $major — add it after this test passes"
fi

echo
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
    echo "OVERALL: FAIL — do not add $major to shell-version"
    exit 1
fi
echo "OVERALL: PASS — safe to add \"$major\" to desktop/gnome/metadata.json shell-version"
