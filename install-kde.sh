#!/usr/bin/env bash
# KDE Plasma 6 installer. The GNOME path lives in install.sh (which hard-requires
# glib-compile-schemas and enables a GNOME Shell extension — neither applies on
# KDE). This installs the Plasma plasmoid plus the shared backend (local server,
# systemd user service, Chrome extension copy).
#
# Deliberately NOT installed on KDE:
#   • the GNOME Shell extension + gschema compile — KDE config lives in the
#     plasmoid's KConfigXT (contents/config/main.xml, generated from the gschema).
#   • server/generate-icon.py — that renders the GNOME dock-icon PNG and reads
#     live colours via GSettings. The plasmoid paints its own rings in QML, so
#     KDE needs neither the script nor its pycairo/pillow/PyGObject deps.
set -euo pipefail

# rsync is used for the transactional chrome-extension copy (matches install.sh).
if ! command -v rsync >/dev/null 2>&1; then
    echo "install-kde.sh: rsync not found — install it (e.g. 'sudo apt install rsync') and re-run." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# XDG base directories (with spec defaults) — same conventions as install.sh.
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

PLASMOID_ID="studio.indri.claudeusage"
PLASMOID_DIR="$XDG_DATA_HOME/plasma/plasmoids/$PLASMOID_ID"
SERVER_DIR="$XDG_DATA_HOME/claude-usage"
SYSTEMD_DIR="$XDG_CONFIG_HOME/systemd/user"

usage() {
    cat <<EOF
Usage: ./install-kde.sh [--uninstall] [--help]

Installs the Claude Usage KDE Plasma 6 plasmoid + backend service.
After install: right-click your panel → Add Widgets → search "Claude Usage".

  --uninstall   Remove the plasmoid, service, and server files.
  --help        Show this message.
EOF
}

uninstall() {
    echo "Uninstalling Claude Usage (KDE)…"
    systemctl --user stop claude-usage-fetch.service 2>/dev/null || true
    systemctl --user disable claude-usage-fetch.service 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/claude-usage-fetch.service"
    systemctl --user daemon-reload 2>/dev/null || true
    rm -rf "$PLASMOID_DIR"
    rm -rf "$SERVER_DIR"
    rm -f "$HOME/.local/bin/claude-usage-status"
    echo "  ✓ Removed plasmoid, service, and server files."
    echo "  ℹ  Restart Plasma (or log out/in) to drop the widget from any panel."
    echo "  ℹ  Cache left intact at \${XDG_CACHE_HOME:-~/.cache}/claude-usage — 'rm -rf' it to fully reset."
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --uninstall) uninstall; exit 0 ;;
    "") ;;
    *) echo "install-kde.sh: unknown argument '$1'" >&2; usage; exit 2 ;;
esac

# Pre-flight: warn (don't fail) if this doesn't look like a Plasma session — the
# files install fine but the widget only appears once a Plasma shell is running.
if ! command -v plasmashell >/dev/null 2>&1; then
    echo "install-kde.sh: 'plasmashell' not found — this may not be a KDE Plasma system." >&2
    echo "                Installing anyway; the widget will appear once Plasma is running." >&2
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "install-kde.sh: python3 not found — required for the data-fetch server." >&2
    exit 1
fi
if ! systemctl --user --version >/dev/null 2>&1; then
    echo "install-kde.sh: 'systemctl --user' unavailable — required for the fetch service." >&2
    exit 1
fi

echo "Installing Claude Usage (KDE Plasma 6)…"

# 1. Plasmoid. Regenerate the KConfigXT schema from the gschema first (same SOT
#    discipline as install.sh's gen-js-defaults call) so the installed widget
#    carries current defaults even if the checked-in artifact drifted.
python3 "$REPO_DIR/scripts/gen-kde-config.py"
rm -rf "$PLASMOID_DIR"
mkdir -p "$(dirname "$PLASMOID_DIR")"
cp -r "$REPO_DIR/kde-plasmoid/." "$PLASMOID_DIR/"
echo "  ✓ Plasmoid installed to $PLASMOID_DIR"

# 2. Local data server + diagnostics (shared with the GNOME install, minus
#    generate-icon.py). schema_defaults.py parses the gschema XML at import, so
#    ship a sibling schemas/ copy — same as install.sh / build-deb.sh.
rm -rf "$SERVER_DIR/usage-server.py" "$SERVER_DIR/tooltip.py" \
       "$SERVER_DIR/schema_defaults.py" "$SERVER_DIR/claude-usage-status" \
       "$SERVER_DIR/chrome-extension"
mkdir -p "$SERVER_DIR/schemas"
cp "$REPO_DIR/server/usage-server.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/tooltip.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/schema_defaults.py" "$SERVER_DIR/"
cp "$REPO_DIR/gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml" \
   "$SERVER_DIR/schemas/"
chmod +x "$SERVER_DIR/usage-server.py"
cp "$REPO_DIR/scripts/claude-usage-status.py" "$SERVER_DIR/claude-usage-status"
chmod +x "$SERVER_DIR/claude-usage-status"
mkdir -p "$HOME/.local/bin"
ln -sf "$SERVER_DIR/claude-usage-status" "$HOME/.local/bin/claude-usage-status"
echo "  ✓ Usage server + diagnostics installed (run 'claude-usage-status' to check health)"

# 3. Chrome extension install copy (Chrome loads unpacked from this path).
#    Mirrors install.sh §2b — transactional rsync, drops dev-only test/.
mkdir -p "$SERVER_DIR/chrome-extension"
rsync -a --delete \
    --exclude='test/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    "$REPO_DIR/chrome-extension/" \
    "$SERVER_DIR/chrome-extension/"
echo "  ✓ Chrome extension files synced to $SERVER_DIR/chrome-extension"

# 4. Systemd user service (identical to install.sh §4).
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_DIR/systemd/claude-usage-fetch.service" "$SYSTEMD_DIR/"
systemctl --user daemon-reload
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable claude-usage-fetch.service
systemctl --user restart claude-usage-fetch.service
echo "  ✓ Systemd service enabled and (re)started"

# 5. Reload Plasma so it rescans the plasmoids dir (best effort — harmless if
#    Plasma isn't running, e.g. a staged install before logging into KDE).
if command -v kquitapp6 >/dev/null 2>&1 && command -v kstart >/dev/null 2>&1; then
    if kquitapp6 plasmashell >/dev/null 2>&1; then
        kstart plasmashell >/dev/null 2>&1 || true
        echo "  ✓ Reloaded plasmashell"
    fi
fi

echo
echo "Done. Add the widget: right-click your panel → Add Widgets → search \"Claude Usage\"."
echo "Then install the Chrome extension (unpacked) from: $SERVER_DIR/chrome-extension"
echo "Configure thresholds/colours via the widget's settings (right-click → Configure)."
