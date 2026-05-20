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
    # Pass-17 I-1: generate-icon.py emits at 48/64/96/128/256 (commit da6a2ac).
    # Glob over all of them so the source-install uninstall matches MANUAL.md's
    # cleanup recipe. Also clear the user-local icon-theme.cache.
    rm -f "$XDG_DATA_HOME"/icons/hicolor/*/apps/claude-usage.png
    rm -f "$XDG_DATA_HOME/icons/hicolor/icon-theme.cache"
    gtk-update-icon-cache -f "$XDG_DATA_HOME/icons/hicolor/" 2>/dev/null || true
    update-desktop-database "$XDG_DATA_HOME/applications/" 2>/dev/null || true
    echo "Done. Log out and back in to remove the panel indicator."
    exit 0
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
[[ "${1:-}" == "--uninstall" ]] && uninstall

echo "Installing Claude Usage..."

# 0. Python dependencies (pycairo, pillow — used by the dock icon generator).
# Per-distro package names differ; detect the host's package manager and use
# the matching ones, or print actionable instructions and abort.
_need_cairo=0; _need_pil=0
python3 -c "import cairo" 2>/dev/null || _need_cairo=1
python3 -c "import PIL"   2>/dev/null || _need_pil=1
if [ $_need_cairo -eq 1 ] || [ $_need_pil -eq 1 ]; then
    if command -v apt-get >/dev/null; then
        _pkgs=()
        [ $_need_cairo -eq 1 ] && _pkgs+=(python3-cairo)
        [ $_need_pil -eq 1 ]   && _pkgs+=(python3-pil)
        echo "  Installing Python dependencies via apt: ${_pkgs[*]}"
        sudo apt-get install -y "${_pkgs[@]}"
    elif command -v dnf >/dev/null; then
        _pkgs=()
        [ $_need_cairo -eq 1 ] && _pkgs+=(python3-cairo)
        [ $_need_pil -eq 1 ]   && _pkgs+=(python3-pillow)
        echo "  Installing Python dependencies via dnf: ${_pkgs[*]}"
        sudo dnf install -y "${_pkgs[@]}"
    elif command -v pacman >/dev/null; then
        _pkgs=()
        [ $_need_cairo -eq 1 ] && _pkgs+=(python-cairo)
        [ $_need_pil -eq 1 ]   && _pkgs+=(python-pillow)
        echo "  Installing Python dependencies via pacman: ${_pkgs[*]}"
        sudo pacman -S --noconfirm "${_pkgs[@]}"
    else
        echo "  ✗ Unknown package manager — install the Python pycairo and pillow bindings manually:" >&2
        [ $_need_cairo -eq 1 ] && echo "      pycairo  (Debian/Ubuntu: python3-cairo · Fedora: python3-cairo · Arch: python-cairo)" >&2
        [ $_need_pil -eq 1 ]   && echo "      pillow   (Debian/Ubuntu: python3-pil · Fedora: python3-pillow · Arch: python-pillow)" >&2
        exit 1
    fi
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
# I-1 (pass-16 §11): nuke and recreate the install.sh-owned subtrees so a
# file removed in a new version doesn't linger from a previous install.
# Only touches paths install.sh entirely owns (server scripts + chrome-ext
# copy). Cache (~/.cache/claude-usage) and gsettings (dconf) live elsewhere
# and are left alone.
rm -rf "$SERVER_DIR/usage-server.py" "$SERVER_DIR/generate-icon.py" "$SERVER_DIR/tooltip.py" \
       "$SERVER_DIR/claude-usage-status" "$SERVER_DIR/chrome-extension"
mkdir -p "$SERVER_DIR"
cp "$REPO_DIR/server/usage-server.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/generate-icon.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/tooltip.py" "$SERVER_DIR/"
cp "$REPO_DIR/server/schema_defaults.py" "$SERVER_DIR/"
# schema_defaults.py parses the gschema XML at import time; copy a sibling
# `schemas/` so the installed module can find it. Same idea as build-deb.sh.
mkdir -p "$SERVER_DIR/schemas"
cp "$REPO_DIR/gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml" \
   "$SERVER_DIR/schemas/"
chmod +x "$SERVER_DIR/usage-server.py" "$SERVER_DIR/generate-icon.py"
cp "$REPO_DIR/scripts/claude-usage-status.py" "$SERVER_DIR/claude-usage-status"
chmod +x "$SERVER_DIR/claude-usage-status"
mkdir -p "$HOME/.local/bin"
ln -sf "$SERVER_DIR/claude-usage-status" "$HOME/.local/bin/claude-usage-status"
echo "  ✓ Usage server installed"
echo "  ✓ Diagnostics installed — run 'claude-usage-status' to check service health"

# 2b. Chrome extension install copy (Chrome loads unpacked from this path).
# Use `cp -r` so the manifest, scripts, and icons all land — but explicitly
# drop the test/ subdirectory so dev-only artifacts don't ship to end-users
# (CWS zip already excludes via build-chrome-zip.sh). P-1 (pass-17): rsync
# --exclude does this in one transactional op — no cp-then-rm window where
# test/ briefly exists at the destination.
mkdir -p "$SERVER_DIR/chrome-extension"
rsync -a --delete --exclude='test/' "$REPO_DIR/chrome-extension/" \
    "$SERVER_DIR/chrome-extension/"
echo "  ✓ Chrome extension files synced to $SERVER_DIR/chrome-extension"

# 2c. Icon-theme baseline for source installs (TF-1, pass-16 §13).
# The .desktop file uses `Icon=claude-usage` (name, not path) — GNOME's XDG
# icon-theme lookup resolves that name to whichever file is present. For
# source installs the user-theme dir is the only candidate (the .deb path
# also installs /usr/share/pixmaps/claude-usage.png as a system fallback).
# Without this seed, `Icon=claude-usage` doesn't resolve until the first
# generate-icon.py run writes the dynamic version.
mkdir -p "$XDG_DATA_HOME/icons/hicolor/64x64/apps"
cp "$REPO_DIR/gnome-extension/icons/claude-64.png" \
    "$XDG_DATA_HOME/icons/hicolor/64x64/apps/claude-usage.png"
gtk-update-icon-cache -f "$XDG_DATA_HOME/icons/hicolor/" 2>/dev/null || true
echo "  ✓ Icon-theme baseline installed"

# 3. Generate initial dock icon (0% rings until first data fetch)
# Settings are stored in GSettings (dconf) with built-in defaults.
# To customise: gnome-extensions prefs claude-usage@indri.studio
python3 "$SERVER_DIR/generate-icon.py" 2>/dev/null || true

# 4. Systemd service
mkdir -p "$SYSTEMD_DIR"
cp "$REPO_DIR/systemd/claude-usage-fetch.service" "$SYSTEMD_DIR/"
systemctl --user daemon-reload
# Clear any failed/auto-restart state from a previous broken version so the
# enable/restart pair below actually progresses the unit rather than refusing
# because StartLimitBurst was already exhausted.
systemctl --user reset-failed claude-usage-fetch.service 2>/dev/null || true
systemctl --user enable claude-usage-fetch.service
# `restart` works whether the service is running (re-execs new code) or stopped
# (equivalent to `start`). `enable --now` would be a no-op against an already-
# running unit, leaving upgraded users on stale code — the same running ≠ disk
# drift class as pass-14's V-2, one step further along the deploy pipeline.
systemctl --user restart claude-usage-fetch.service
echo "  ✓ Systemd service enabled and (re)started"

# 5. Dock launcher entry
mkdir -p "$XDG_DATA_HOME/applications"
sed "s|%HOME%|$HOME|g" "$REPO_DIR/desktop/claude-usage.desktop" \
    > "$XDG_DATA_HOME/applications/claude-usage.desktop"
update-desktop-database "$XDG_DATA_HOME/applications/" 2>/dev/null || true
echo "  ✓ Dock entry installed — find 'Claude Usage' in the app grid, right-click → Add to Favorites"

# 6. Enable GNOME extension (may fail until after re-login)
# I-2 (pass-15 §7): `enable` returns 0 on Wayland even though the extension
# code only loads after logout — gnome-shell can't be restarted in-place on
# Wayland. Always mention the log-out fallback so the success message is
# accurate on both X11 (where it self-activates) and Wayland (where it
# doesn't appear until next session).
gnome-extensions enable claude-usage@indri.studio 2>/dev/null \
    && echo "  ✓ GNOME extension enabled (log out and back in if the panel indicator isn't visible)" \
    || echo "  ℹ  GNOME extension registered — log out and back in to activate it"

echo ""
echo "Next step: load the Chrome extension"
echo "  1. Open chrome://extensions"
echo "  2. Enable Developer mode"
echo "  3. Click 'Load unpacked' and select: $CHROME_EXT_SRC"
echo ""
echo "The Chrome extension fetches usage data every 7 minutes."
echo "Click its toolbar icon to force an immediate refresh."
