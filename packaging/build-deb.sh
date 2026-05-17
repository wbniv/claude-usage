#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep '^Version:' "$REPO_DIR/packaging/control" | awk '{print $2}')"
DEB_NAME="claude-usage_${VERSION}_all.deb"
BUILD_DIR="$(mktemp -d)"

trap 'rm -rf "$BUILD_DIR"' EXIT

echo "Building $DEB_NAME..."

PKG="$BUILD_DIR/claude-usage"

# Directory structure
mkdir -p \
    "$PKG/DEBIAN" \
    "$PKG/usr/share/gnome-shell/extensions/claude-usage@indri.studio" \
    "$PKG/usr/share/claude-usage" \
    "$PKG/usr/share/applications" \
    "$PKG/usr/share/pixmaps" \
    "$PKG/usr/share/icons/hicolor/64x64/apps" \
    "$PKG/usr/lib/systemd/user" \
    "$PKG/usr/bin"

# GNOME extension
cp -r "$REPO_DIR/gnome-extension/." \
    "$PKG/usr/share/gnome-shell/extensions/claude-usage@indri.studio/"

# Python server
cp "$REPO_DIR/server/usage-server.py" \
   "$REPO_DIR/server/generate-icon.py" \
   "$REPO_DIR/server/tooltip.py" \
   "$PKG/usr/share/claude-usage/"

# Chrome extension (for load-unpacked until CWS listing is live)
cp -r "$REPO_DIR/chrome-extension" "$PKG/usr/share/claude-usage/"

# Systemd user unit — rewrite path from %h/.local/share to /usr/share
sed 's|%h/.local/share/claude-usage|/usr/share/claude-usage|g' \
    "$REPO_DIR/systemd/claude-usage-fetch.service" \
    > "$PKG/usr/lib/systemd/user/claude-usage-fetch.service"

# System .desktop (static icon — setup script installs user-level dynamic one)
cat > "$PKG/usr/share/applications/claude-usage.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Claude Usage
Comment=Claude.ai weekly usage meter
Exec=xdg-open https://claude.ai/settings/usage
Icon=claude-usage
StartupWMClass=claude-usage
Categories=Utility;
NoDisplay=false
EOF

# System icon — bake the rounded-rect + orange + star placeholder (no rings)
# so the dock looks consistent before any usage data has been fetched.
# Falls back to the raw star PNG if cairo/PIL aren't on the build host.
BAKED_ICON="$BUILD_DIR/claude-usage-baseline.png"
if python3 "$REPO_DIR/server/generate-icon.py" --baseline "$BAKED_ICON" 2>/dev/null \
   && [[ -s "$BAKED_ICON" ]]; then
    cp "$BAKED_ICON" "$PKG/usr/share/pixmaps/claude-usage.png"
    cp "$BAKED_ICON" "$PKG/usr/share/icons/hicolor/64x64/apps/claude-usage.png"
else
    echo "  ⚠  Baseline icon bake failed; shipping raw star PNG" >&2
    cp "$REPO_DIR/gnome-extension/icons/claude-64.png" \
        "$PKG/usr/share/pixmaps/claude-usage.png"
    cp "$REPO_DIR/gnome-extension/icons/claude-64.png" \
        "$PKG/usr/share/icons/hicolor/64x64/apps/claude-usage.png"
fi

# User setup script + diagnostics script
cp "$REPO_DIR/packaging/claude-usage-setup" "$PKG/usr/bin/"
install -m 755 "$REPO_DIR/scripts/claude-usage-status.sh" "$PKG/usr/bin/claude-usage-status"

# DEBIAN control files
cp "$REPO_DIR/packaging/control"  "$PKG/DEBIAN/"
cp "$REPO_DIR/packaging/postinst" "$PKG/DEBIAN/"
cp "$REPO_DIR/packaging/postrm"   "$PKG/DEBIAN/"

# Permissions
find "$PKG/usr" -type f              -exec chmod 644 {} \;
find "$PKG/usr/bin"                  -exec chmod 755 {} \;
find "$PKG/usr/share/claude-usage" -name "*.py" -exec chmod 755 {} \;
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

# Build
mkdir -p "$REPO_DIR/dist"
dpkg-deb --root-owner-group --build "$PKG" "$REPO_DIR/dist/$DEB_NAME"
echo "Built: dist/$DEB_NAME"
echo ""
echo "Install with:"
echo "  sudo dpkg -i dist/$DEB_NAME"
echo "  sudo apt-get install -f   # if deps are missing"
