#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Paths
GNOME_EXT_DIR="$HOME/.local/share/gnome-shell/extensions/claude-usage@wbnorris.gmail.com"
CHROME_EXT_SRC="$REPO_DIR/chrome-extension"
SERVER_DIR="$HOME/.local/share/claude-usage"
SYSTEMD_DIR="$HOME/.config/systemd/user"

usage() {
    echo "Usage: $0 [--uninstall]"
    echo ""
    echo "Installs the Claude Usage panel indicator."
    echo "  --uninstall  Remove all installed files and services"
    exit 0
}

uninstall() {
    echo "Uninstalling Claude Usage..."
    systemctl --user stop claude-usage-fetch.service 2>/dev/null || true
    systemctl --user disable claude-usage-fetch.service 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/claude-usage-fetch.service"
    systemctl --user daemon-reload
    rm -rf "$GNOME_EXT_DIR"
    rm -rf "$SERVER_DIR"
    rm -f "$HOME/.cache/claude-usage.json"
    rm -f "$HOME/.local/share/applications/claude-usage.desktop"
    update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
    echo "Done. Log out and back in to remove the panel indicator."
    exit 0
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
[[ "${1:-}" == "--uninstall" ]] && uninstall

echo "Installing Claude Usage..."

# 1. GNOME Shell extension
mkdir -p "$GNOME_EXT_DIR/schemas" "$GNOME_EXT_DIR/icons"
cp "$REPO_DIR/gnome-extension/extension.js" "$GNOME_EXT_DIR/"
cp "$REPO_DIR/gnome-extension/metadata.json" "$GNOME_EXT_DIR/"
cp "$REPO_DIR/gnome-extension/prefs.js" "$GNOME_EXT_DIR/"
cp "$REPO_DIR/gnome-extension/schemas/"*.xml "$GNOME_EXT_DIR/schemas/"
cp "$REPO_DIR/gnome-extension/icons/"* "$GNOME_EXT_DIR/icons/" 2>/dev/null || true
glib-compile-schemas "$GNOME_EXT_DIR/schemas/"
echo "  ✓ GNOME extension installed"

# 2. Local data server
mkdir -p "$SERVER_DIR"
cp "$REPO_DIR/server/usage-server.py" "$SERVER_DIR/"
chmod +x "$SERVER_DIR/usage-server.py"
echo "  ✓ Usage server installed"

# 3. Systemd service
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_DIR/systemd/claude-usage-fetch.service" "$SYSTEMD_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now claude-usage-fetch.service
echo "  ✓ Systemd service enabled and started"

# 4. Dock launcher entry
mkdir -p "$HOME/.local/share/applications"
sed "s|%HOME%|$HOME|g" "$REPO_DIR/desktop/claude-usage.desktop" \
    > "$HOME/.local/share/applications/claude-usage.desktop"
update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
echo "  ✓ Dock entry installed — find 'Claude Usage' in the app grid, right-click → Add to Favorites"

# 5. Enable GNOME extension (may fail until after re-login)
gnome-extensions enable claude-usage@wbnorris.gmail.com 2>/dev/null \
    && echo "  ✓ GNOME extension enabled" \
    || echo "  ℹ  GNOME extension registered — log out and back in to activate it"

echo ""
echo "Next step: load the Chrome extension"
echo "  1. Open chrome://extensions"
echo "  2. Enable Developer mode"
echo "  3. Click 'Load unpacked' and select: $CHROME_EXT_SRC"
echo ""
echo "The Chrome extension fetches usage data every 15 minutes."
echo "Click its toolbar icon to force an immediate refresh."
