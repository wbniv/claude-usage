#!/usr/bin/env bash
# Headless smoke test for the KDE Plasma 6 plasmoid. Mirrors
# packaging/test-gnome-verify.sh: validate the package metadata, make the
# plasmoid discoverable, then load it via plasmoidviewer on the offscreen Qt
# platform and fail on any QML diagnostic. Per project policy (SV-1), KDE
# support is only claimed after this passes.
#
# We copy the plasmoid into the local plasmoids dir (KPackage discovers applets
# by scanning $XDG_DATA dirs) rather than using kpackagetool6, which Ubuntu
# doesn't ship as a standalone CLI. The offscreen QPA platform instantiates the
# full QML scene — surfacing import/type/binding errors — without needing an X
# server or libxcb-cursor0.
set -euo pipefail

SRC="${1:-/plasmoid}"
ID="studio.indri.claudeusage"
fail=0

echo "=== KDE plasmoid smoke test ==="
echo "Plasma: plasma-workspace $(dpkg-query -W -f='${Version}' plasma-workspace 2>/dev/null || echo '?')"
echo

# 1. metadata.json — valid JSON, Id + Plasma 6 API marker present.
if python3 - "$SRC/metadata.json" "$ID" <<'PY'
import json, sys
path, want_id = sys.argv[1], sys.argv[2]
d = json.load(open(path))
assert d["KPlugin"]["Id"] == want_id, f"Id mismatch: {d['KPlugin']['Id']}"
assert d.get("X-Plasma-API-Minimum-Version", "").startswith("6"), "missing Plasma 6 API marker"
PY
then echo "  PASS  metadata.json valid (Id=$ID, Plasma 6 API)"
else echo "  FAIL  metadata.json"; fail=1
fi

# 2. make the applet discoverable by copying into the local plasmoids dir.
DEST="$HOME/.local/share/plasma/plasmoids/$ID"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -r "$SRC" "$DEST"
# Inject a load marker into the COPY only (production QML stays log-free). Its
# presence in the viewer log below proves the applet's root actually executed.
sed -i 's/^\(\s*id: root\)$/\1\n    Component.onCompleted: console.log("CLAUDE_USAGE_MAIN_LOADED")/' \
    "$DEST/contents/ui/main.qml"
if [ -f "$DEST/metadata.json" ] && grep -q CLAUDE_USAGE_MAIN_LOADED "$DEST/contents/ui/main.qml"; then
    echo "  PASS  installed to $DEST (load marker injected)"
else
    echo "  FAIL  install copy incomplete or marker injection failed"; fail=1
fi

# 3. headless load — instantiate the applet under a virtual X server (Xvfb +
#    Qt's xcb platform; the offscreen platform can't build a plasmoid scene) and
#    a private D-Bus session for ~16s. The plasmoid logs CLAUDE_USAGE_MAIN_LOADED
#    from its root Component.onCompleted, so we can prove the QML actually
#    executed — a missing marker means the applet never loaded (a blind pass).
#    timeout SIGTERMs the still-open viewer (exit 124), the expected clean path.
unset QT_QPA_PLATFORM
xvfb-run -a dbus-run-session -- timeout 16 plasmoidviewer --applet "$ID" >/tmp/view.log 2>&1 || true

ERRPAT='is not a type|ReferenceError|Unable to assign|Cannot assign|TypeError:|SyntaxError|is not installed|is not a function|Expected token|Unexpected token|file:.*:[0-9]+:[0-9]+:|Binding loop'
# Scope diagnostics to OUR plasmoid's files. plasmoidviewer's own desktop
# containment emits unrelated noise (e.g. Corona::isScreenUiReady) when run
# outside a real plasmashell — those reference org.kde.desktopcontainment, not
# our $ID, so the path filter excludes them while still catching anything in
# our main.qml / representations / usage.js.
OUR_ERRORS="$(grep -iE "$ERRPAT" /tmp/view.log | grep -F "$ID" || true)"
if ! grep -q "CLAUDE_USAGE_MAIN_LOADED" /tmp/view.log; then
    echo "  FAIL  applet never loaded (no load marker) — viewer log tail:"
    grep -ivE "QML debugging|Detected locale|switched to|reconfigure|locale\(1\)" /tmp/view.log | tail -20 | sed 's/^/        /'
    fail=1
elif [ -n "$OUR_ERRORS" ]; then
    echo "  FAIL  plasmoidviewer reported QML diagnostics in the plasmoid:"
    echo "$OUR_ERRORS" | head -30 | sed 's/^/        /'
    fail=1
else
    echo "  PASS  applet loaded (marker present) with no QML errors"
fi

echo
echo "=== Results: $([ $fail -eq 0 ] && echo PASS || echo FAIL) ==="
exit $fail
