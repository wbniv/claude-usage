#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $(basename "$0") [no arguments]
Builds the Chrome extension zip for Chrome Web Store upload and writes it to dist/.
EOF
    exit 0
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(python3 -c "import json; print(json.load(open('$REPO_DIR/chrome-extension/manifest.json'))['version'])")"
OUT="$REPO_DIR/dist/claude-usage-chrome-${VERSION}.zip"

mkdir -p "$REPO_DIR/dist"
cd "$REPO_DIR/chrome-extension"
zip -r "$OUT" . -x "*.DS_Store" -x "__pycache__/*" -x "*.pyc" -x "test/*" -x "chrome-compat.js"
echo "Built: dist/claude-usage-chrome-${VERSION}.zip"
echo ""
echo "Upload this zip at: https://chrome.google.com/webstore/devconsole"
