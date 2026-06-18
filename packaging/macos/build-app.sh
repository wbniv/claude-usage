#!/usr/bin/env bash
set -euo pipefail
#
# build-app.sh — package the macOS menu-bar indicator as a self-contained
# py2app bundle (PyObjC + the shared server modules baked in), ad-hoc signed so
# it launches on Apple Silicon. Output: dist/claude-usage.app. Distributed via
# the Homebrew cask (packaging/macos/Casks/claude-usage.rb).
#
# Must run on macOS with py2app available (`pip3 install py2app`).
# See docs/plans/2026-06-18-macos-port.md. Live-validated on a Mac ([verify]).

usage() {
    cat <<EOF
Usage: packaging/macos/build-app.sh [-h]

Builds dist/claude-usage.app from desktop/macos/ + server/ via py2app, then
ad-hoc codesigns it. Reads the version from packaging/control (single source).
EOF
}
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$REPO_DIR/dist"

# 0. Environment sanity — abort early (CLAUDE.md) rather than fail deep in py2app.
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "build-app.sh: macOS only (got $(uname -s))" >&2
    exit 1
fi
if ! python3 -c 'import py2app' 2>/dev/null; then
    echo "build-app.sh: py2app not installed — run: pip3 install py2app pyobjc" >&2
    exit 1
fi

# 1. Version — single source of truth, same as task bump.
VERSION="$(grep '^Version:' "$REPO_DIR/packaging/control" | awk '{print $2}')"
[[ -n "$VERSION" ]] || { echo "build-app.sh: no Version: in packaging/control" >&2; exit 1; }
echo "Building claude-usage.app v$VERSION"

# 2. Stage a flat build tree so py2app's modulegraph picks up the shared modules
#    as direct imports, and the runtime data lands under Contents/Resources/.
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/server/schemas" "$BUILD/icons"

cp "$REPO_DIR/desktop/macos/claude_usage_menubar.py" "$BUILD/"
cp "$REPO_DIR/desktop/macos/statusbar_image.py"      "$BUILD/"
# Shared server modules: importable twins (usage_core/tooltip/schema_defaults)
# + usage-server.py (loaded via importlib at runtime) + the gschema XML.
cp "$REPO_DIR/server/usage_core.py" \
   "$REPO_DIR/server/tooltip.py" \
   "$REPO_DIR/server/schema_defaults.py" \
   "$REPO_DIR/server/usage-server.py" \
   "$BUILD/server/"
cp "$REPO_DIR/desktop/gnome/schemas/org.indri.claude-usage.gschema.xml" "$BUILD/server/schemas/"
cp "$REPO_DIR/desktop/gnome/icons/claude-22.png" \
   "$REPO_DIR/desktop/gnome/icons/claude-22-red.png" \
   "$REPO_DIR/desktop/gnome/icons/claude-64.png" "$BUILD/icons/"
# LaunchAgent plist ships inside the bundle (Contents/Resources/) so the cask's
# postflight can copy it into ~/Library/LaunchAgents and bootstrap it.
cp "$REPO_DIR/packaging/macos/studio.indri.claude-usage.plist" "$BUILD/"

# 3. App icon (.icns) from the 64px brand bitmap, best-effort (iconutil is macOS-only).
ICNS=""
if command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
    ICONSET="$BUILD/claude-usage.iconset"
    mkdir -p "$ICONSET"
    for sz in 16 32 128 256 512; do
        sips -z "$sz" "$sz"     "$BUILD/icons/claude-64.png" --out "$ICONSET/icon_${sz}x${sz}.png"   >/dev/null
        sips -z "$((sz*2))" "$((sz*2))" "$BUILD/icons/claude-64.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$BUILD/claude-usage.icns" && ICNS="$BUILD/claude-usage.icns"
fi

# 4. Info.plist with the version substituted in.
sed "s/@VERSION@/$VERSION/g" "$REPO_DIR/desktop/macos/Info.plist.in" > "$BUILD/Info.plist"

# 5. py2app setup.py.
cat > "$BUILD/setup.py" <<'SETUP'
import pathlib
import plistlib
from setuptools import setup

plist = plistlib.loads(pathlib.Path('Info.plist').read_bytes())
opts = {
    'plist': plist,
    'includes': ['usage_core', 'tooltip', 'schema_defaults', 'statusbar_image'],
    'packages': ['objc', 'Foundation', 'AppKit'],
    'arch': 'universal2',
}
if pathlib.Path('claude-usage.icns').exists():
    opts['iconfile'] = 'claude-usage.icns'

setup(
    app=['claude_usage_menubar.py'],
    data_files=[
        ('', ['studio.indri.claude-usage.plist']),
        ('server', ['server/usage_core.py', 'server/tooltip.py',
                    'server/schema_defaults.py', 'server/usage-server.py']),
        ('server/schemas', ['server/schemas/org.indri.claude-usage.gschema.xml']),
        ('icons', ['icons/claude-22.png', 'icons/claude-22-red.png', 'icons/claude-64.png']),
    ],
    options={'py2app': opts},
    setup_requires=['py2app'],
)
SETUP

# 6. Build.
( cd "$BUILD" && python3 setup.py py2app >/dev/null )

# 7. Move into dist/ and ad-hoc sign (required for an unsigned bundle to launch
#    at all on Apple Silicon; the cask clears quarantine post-install).
mkdir -p "$DIST"
APP="$DIST/claude-usage.app"
rm -rf "$APP"
mv "$BUILD/dist/"*.app "$APP"
codesign -s - --deep --force --timestamp=none "$APP"

echo "Built $APP (v$VERSION)"
echo "  arch:   $(lipo -archs "$APP/Contents/MacOS/"* 2>/dev/null | head -1 || echo '?')"
echo "  signed: $(codesign -dv "$APP" 2>&1 | grep -c 'Signature=adhoc' || true) (ad-hoc)"
echo "Zip for release:  ditto -c -k --keepParent '$APP' '$DIST/claude-usage-macos-$VERSION.zip'"
