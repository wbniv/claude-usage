#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# XDG base directories (with spec defaults)
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

# Paths
GNOME_EXT_DIR="$XDG_DATA_HOME/gnome-shell/extensions/claude-usage@indri.studio"
CHROME_EXT_SRC="$REPO_DIR/chrome-extension"
SERVER_DIR="$XDG_DATA_HOME/claude-usage"
SYSTEMD_DIR="$XDG_CONFIG_HOME/systemd/user"

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
    # Remove any claude-usage@* extension dir (current and historical UUIDs)
    rm -rf "$XDG_DATA_HOME/gnome-shell/extensions/"claude-usage@*
    rm -f "$XDG_DATA_HOME/glib-2.0/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml"
    glib-compile-schemas "$XDG_DATA_HOME/glib-2.0/schemas/" 2>/dev/null || true
    # Drop any claude-usage@* entries from the enabled/disabled lists
    for key in enabled-extensions disabled-extensions; do
        current=$(gsettings get org.gnome.shell "$key" 2>/dev/null || echo "@as []")
        cleaned=$(python3 -c "import ast,sys; v=ast.literal_eval(sys.argv[1].replace('@as ','')); print(str([x for x in v if not x.startswith('claude-usage@')]))" "$current" 2>/dev/null || echo "")
        [ -n "$cleaned" ] && gsettings set org.gnome.shell "$key" "$cleaned" 2>/dev/null || true
    done
    rm -f "$HOME/.local/bin/claude-usage-status"
    rm -rf "$SERVER_DIR"
    rm -rf "$XDG_CONFIG_HOME/claude-usage"
    rm -rf "$XDG_CACHE_HOME/claude-usage"
    rm -f "$XDG_DATA_HOME/applications/claude-usage.desktop"
    update-desktop-database "$XDG_DATA_HOME/applications/" 2>/dev/null || true
    echo "Done. Log out and back in to remove the panel indicator."
    exit 0
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
[[ "${1:-}" == "--uninstall" ]] && uninstall

echo "Installing Claude Usage..."

# 0. Python dependencies (pycairo, pillow — used by the dock icon generator)
_missing=()
python3 -c "import cairo" 2>/dev/null || _missing+=(python3-cairo)
python3 -c "import PIL"   2>/dev/null || _missing+=(python3-pil)
if [ ${#_missing[@]} -gt 0 ]; then
    echo "  Installing Python dependencies: ${_missing[*]}"
    sudo apt-get install -y "${_missing[@]}"
fi
echo "  ✓ Python dependencies OK"

# 1. GNOME Shell extension
mkdir -p "$GNOME_EXT_DIR/schemas" "$GNOME_EXT_DIR/icons"
cp "$REPO_DIR/gnome-extension/extension.js" "$GNOME_EXT_DIR/"
cp "$REPO_DIR/gnome-extension/metadata.json" "$GNOME_EXT_DIR/"
cp "$REPO_DIR/gnome-extension/prefs.js" "$GNOME_EXT_DIR/"
cp "$REPO_DIR/gnome-extension/schemas/"*.xml "$GNOME_EXT_DIR/schemas/"
cp "$REPO_DIR/gnome-extension/icons/"* "$GNOME_EXT_DIR/icons/" 2>/dev/null || true
glib-compile-schemas "$GNOME_EXT_DIR/schemas/"
# Also install schema to user glib path so plain `gsettings` works without GSETTINGS_SCHEMA_DIR
GLIB_SCHEMA_DIR="$XDG_DATA_HOME/glib-2.0/schemas"
mkdir -p "$GLIB_SCHEMA_DIR"
cp "$REPO_DIR/gnome-extension/schemas/"*.xml "$GLIB_SCHEMA_DIR/"
glib-compile-schemas "$GLIB_SCHEMA_DIR/"
echo "  ✓ GNOME extension installed"

# 2. Local data server + diagnostics
mkdir -p "$SERVER_DIR"
cp "$REPO_DIR/server/usage-server.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/generate-icon.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/tooltip.py" "$SERVER_DIR/"
chmod +x "$SERVER_DIR/usage-server.py" "$SERVER_DIR/generate-icon.py"
cp "$REPO_DIR/scripts/claude-usage-status.py" "$SERVER_DIR/claude-usage-status"
chmod +x "$SERVER_DIR/claude-usage-status"
mkdir -p "$HOME/.local/bin"
ln -sf "$SERVER_DIR/claude-usage-status" "$HOME/.local/bin/claude-usage-status"
echo "  ✓ Usage server installed"
echo "  ✓ Diagnostics installed — run 'claude-usage-status' to check service health"

# 2b. Chrome extension install copy (Chrome loads unpacked from this path)
mkdir -p "$SERVER_DIR/chrome-extension"
cp "$REPO_DIR/chrome-extension/"* "$SERVER_DIR/chrome-extension/"
echo "  ✓ Chrome extension files synced to $SERVER_DIR/chrome-extension"

# 3. Generate initial dock icon (0% rings until first data fetch)
# Settings are stored in GSettings (dconf) with built-in defaults.
# To customise: gnome-extensions prefs claude-usage@indri.studio
python3 "$SERVER_DIR/generate-icon.py" 2>/dev/null || true

# 4. Systemd service
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_DIR/systemd/claude-usage-fetch.service" "$SYSTEMD_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now claude-usage-fetch.service
echo "  ✓ Systemd service enabled and started"

# 5. Dock launcher entry
mkdir -p "$XDG_DATA_HOME/applications"
sed "s|%HOME%|$HOME|g" "$REPO_DIR/desktop/claude-usage.desktop" \
    > "$XDG_DATA_HOME/applications/claude-usage.desktop"
update-desktop-database "$XDG_DATA_HOME/applications/" 2>/dev/null || true
echo "  ✓ Dock entry installed — find 'Claude Usage' in the app grid, right-click → Add to Favorites"

# 6. Enable GNOME extension (may fail until after re-login)
gnome-extensions enable claude-usage@indri.studio 2>/dev/null \
    && echo "  ✓ GNOME extension enabled" \
    || echo "  ℹ  GNOME extension registered — log out and back in to activate it"

echo ""
echo "Next step: load the Chrome extension"
echo "  1. Open chrome://extensions"
echo "  2. Enable Developer mode"
echo "  3. Click 'Load unpacked' and select: $CHROME_EXT_SRC"
echo ""
echo "The Chrome extension fetches usage data every 7 minutes."
echo "Click its toolbar icon to force an immediate refresh."
