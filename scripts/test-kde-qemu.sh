#!/usr/bin/env bash
# Live KDE plasmoid verification: boot the Foundry Linux Plasma 6 ISO in QEMU,
# inject the plasmoid + a synthetic usage.json, load it into the running shell,
# and assert it renders without QML errors. Closes step 10 [live] of
# docs/plans/2026-05-30-code-review-fixes.md (no Plasma on the GNOME dev box).
#
# This caught two runtime-fatal bugs that every static check passed:
#   - CompactRepresentation.qml assigned read-only Image.implicitWidth/Height
#   - main.qml read usage.json via file:// XMLHttpRequest, which never reaches
#     readyState DONE inside the Plasma 6 plasmoid sandbox (→ data never loads)
#
# Usage:
#   bash scripts/test-kde-qemu.sh [ISO]
#   ISO defaults to the newest foundry-anvil-*.iso in ../foundrylinux.org/foundry-iso/dist/
#
# Requires (host): qemu-system-x86_64, ovmf, sshpass, /dev/kvm, an active display.
# The Foundry ISO must be built with hook 1200-live-ssh (sshd on forwarded :2222).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

ISO="${1:-}"
if [[ -z "$ISO" ]]; then
  ISO="$(ls -t "$REPO"/../foundrylinux.org/foundry-iso/dist/foundry-anvil-*.iso 2>/dev/null | head -1 || true)"
fi
[[ -f "$ISO" ]] || { echo "ERROR: ISO not found: ${ISO:-<none>}" >&2; exit 1; }

for bin in qemu-system-x86_64 sshpass; do
  command -v "$bin" >/dev/null || { echo "ERROR: missing $bin" >&2; exit 1; }
done
OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
[[ -f "$OVMF_CODE" ]] || { echo "ERROR: OVMF not found ($OVMF_CODE) — install ovmf" >&2; exit 1; }

PORT=2222
VARS=$(mktemp /tmp/cu-kde-vars.XXXX.fd)
cp /usr/share/OVMF/OVMF_VARS_4M.fd "$VARS"
SERIAL=$(mktemp /tmp/cu-kde-serial.XXXX.log)
FIX=$(mktemp /tmp/cu-usage-fixture.XXXX.json)
SHOTDIR="$REPO/docs/plans/screenshots"; mkdir -p "$SHOTDIR"

# Synthetic usage.json — fields drawn from scripts/lint-kde-parity.py allowlists.
# _timestamp is stamped at injection time so the status line reads sensibly.
cat > "$FIX" <<'JSON'
{
  "plan": "Max 20x",
  "_timestamp": 0,
  "_anthropic_status": { "indicator": "none", "claude_ai_component_status": "operational" },
  "_period_lengths": { "Sonnet 4.6": 10080, "Opus 4.8": 10080, "Weekly (all models)": 10080 },
  "meters": [
    { "label": "Sonnet 4.6", "pct": 72, "reset_minutes": 2880 },
    { "label": "Opus 4.8", "pct": 31, "reset_minutes": 600 },
    { "label": "Weekly (all models)", "pct": 88, "reset_minutes": 7320 }
  ]
}
JSON

KVM=(); [[ -w /dev/kvm ]] && KVM=(-enable-kvm -cpu host)
echo "=== Booting $ISO ==="
qemu-system-x86_64 -m "${QEMU_MEM:-4096}" "${KVM[@]}" \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$VARS" \
  -drive file="$ISO",media=cdrom,format=raw,readonly=on \
  -boot order=d -device virtio-vga-gl,xres="${QEMU_XRES:-1280}",yres="${QEMU_YRES:-800}" -display gtk,gl=on \
  -serial file:"$SERIAL" -no-reboot \
  -device virtio-net,netdev=n0 -netdev user,id=n0,hostfwd=tcp::${PORT}-:22 &
QEMU_PID=$!
cleanup() { kill "$QEMU_PID" 2>/dev/null || true; rm -f "$VARS" "$SERIAL" "$FIX"; }
trap cleanup EXIT

# ssh helpers. The live 'user' account password is unreliable across casper
# builds, so reset it from root (root:foundry is set by hook 1200-live-ssh).
SSHC="-p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=6"
asroot() { sshpass -p foundry ssh $SSHC root@localhost "$@"; }
asuser() { sshpass -p live   ssh $SSHC user@localhost "$@"; }
cpuser() { sshpass -p live   scp -P $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PreferredAuthentications=password -o PubkeyAuthentication=no "$@"; }
# Run a command inside the live user's Plasma/Wayland session (env not inherited over ssh).
ENV='export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus WAYLAND_DISPLAY=wayland-0 QT_QPA_PLATFORM=wayland;'
insession() { asuser "bash -lc '$ENV $*'"; }

echo "=== Waiting for sshd on :$PORT (live Plasma boot, up to 5 min) ==="
for i in $(seq 1 100); do
  if asroot true 2>/dev/null; then echo "  sshd up after ~$((i*3))s"; break; fi
  kill -0 "$QEMU_PID" 2>/dev/null || { echo "ERROR: QEMU died" >&2; exit 1; }
  sleep 3
  [[ $i == 100 ]] && { echo "ERROR: timed out waiting for sshd" >&2; exit 1; }
done
asroot "echo 'user:live' | chpasswd"   # make the live user ssh-able

echo "=== Injecting plasmoid + server assets + fixture ==="
asuser 'mkdir -p ~/.local/share/plasma/plasmoids ~/.cache/claude-usage ~/.config/claude-usage ~/server/schemas ~/.local/share/gnome-shell/extensions/claude-usage@indri.studio/icons'
cpuser -r "$REPO/desktop/kde" user@localhost:'~/.local/share/plasma/plasmoids/org.indri.claude-usage'
cpuser "$REPO"/server/{generate-icon.py,schema_defaults.py,tooltip.py,usage-server.py} user@localhost:'~/server/'
cpuser "$REPO/desktop/gnome/schemas/org.indri.claude-usage.gschema.xml" user@localhost:'~/server/schemas/'
cpuser "$REPO/desktop/gnome/icons/claude-64.png" user@localhost:'~/.local/share/gnome-shell/extensions/claude-usage@indri.studio/icons/claude-64.png'
cpuser "$FIX" user@localhost:'~/.cache/claude-usage/usage.json'
asuser 'python3 -c "import json,time,os;p=os.path.expanduser(\"~/.cache/claude-usage/usage.json\");d=json.load(open(p));d[\"_timestamp\"]=int(time.time())-120;json.dump(d,open(p,\"w\"))"'

echo "=== Set display to >=1024x768 (default virtio-gpu mode is a cramped 640x480) ==="
# The virtio-vga-gl xres/yres device hint is ignored by the guest, so bump the
# mode with kscreen-doctor. Done ONCE, early (before screenshots) so the buffer
# repaints cleanly. Prefer 1280x1024, fall back through to 1024x768.
insession 'out=$(kscreen-doctor -o 2>/dev/null | grep -oE "Output:[[:space:]]+[0-9]+[[:space:]]+[^[:space:]]+" | awk "{print \$3}" | head -1);
  for res in 1280x1024 1280x768 1024x768; do
    id=$(kscreen-doctor -o 2>/dev/null | grep -oE "[0-9]+:${res}@[0-9.]+" | head -1 | cut -d: -f1);
    [ -n "$id" ] && { kscreen-doctor output.$out.mode.$id 2>/dev/null && echo "set $out -> $res (mode $id)"; break; };
  done' || true
sleep 2

echo "=== Loading plasmoid into the running shell ==="
# Mark the journal cursor BEFORE the restart so the error-check below only sees
# errors from this load — not stale ones from earlier in the boot.
MARK=$(asuser 'date "+%Y-%m-%d %H:%M:%S"')
insession 'systemctl --user restart plasma-plasmashell; for i in $(seq 1 20); do qdbus6 org.kde.plasmashell >/dev/null 2>&1 && break; sleep 1; done'
# Add to BOTH a panel and the desktop on purpose: exercises the compact (panel)
# and full (desktop) representations in one run. So a live run shows TWO
# instances/popups rendering identical data — intentional coverage, not a
# duplication bug. (Panel-only? drop the desktops()[0].addWidget call.)
insession 'qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "panels()[0].addWidget(\"org.indri.claude-usage\"); desktops()[0].addWidget(\"org.indri.claude-usage\");"'
sleep 4

echo "=== Assert: no QML errors loading the plasmoid (since $MARK) ==="
ERRS=$(asuser "journalctl --user --no-pager --since '$MARK' 2>/dev/null | grep -iE 'claude-usage|StandardPaths|ReferenceError' | grep -iE 'error|unavailable|Invalid|ReferenceError' | grep -v 'does not match requested format' || true")
if [[ -n "$ERRS" ]]; then echo "FAIL — QML errors:"; echo "$ERRS"; exit 1; fi
echo "  PASS — no QML load errors"

echo "=== Assert: config QML compiles clean against real Plasma modules (qmllint) ==="
# The config page's QML errors surface only when the config dialog opens, which
# we can't trigger headlessly — so qmllint it against the guest's real Plasma
# modules instead (the GNOME dev box lacks them). Catches unresolved imports/
# types AND the Plasma-5 lowercase `plasmoid.` idiom that silently drops the page.
asroot 'command -v /usr/lib/qt6/bin/qmllint >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq qt6-declarative-dev-tools >/dev/null 2>&1' || true
QL=$(asuser 'Q=/usr/lib/x86_64-linux-gnu/qt6/qml; P="$HOME/.local/share/plasma/plasmoids/org.indri.claude-usage/contents/ui"; for f in "$P"/config/*.qml; do /usr/lib/qt6/bin/qmllint -I "$Q" -I "$P" "$f" 2>&1; done | grep -iE "Error:|plasmoid\." || true')
if [[ -n "$QL" ]]; then echo "FAIL — config QML qmllint issues:"; echo "$QL"; exit 1; fi
echo "  PASS — config QML qmllint-clean (no errors, no unqualified plasmoid)"

echo "=== Screenshot → $SHOTDIR/kde-plasmoid-live.png ==="
insession 'spectacle -b -n -f -o /tmp/cu-final.png 2>/dev/null' || true
cpuser user@localhost:/tmp/cu-final.png "$SHOTDIR/kde-plasmoid-live.png" 2>/dev/null && echo "  saved" || echo "  (screenshot unavailable)"

echo "=== Config round-trip: plasmoid writes config.json → generate-icon.py consumes it ==="
CFG='{"weekly_color_green":"#11aa22","weekly_color_amber":"#ccaa00","weekly_color_red":"#dd0000","sonnet_color":"#3366ff","popup_color_normal":"#ffffff","popup_color_warning":"#ffaa00","popup_color_critical":"#ff0000","threshold_warning":42,"threshold_critical":77,"popup_font_family":"monospace"}'
B64=$(printf %s "$CFG" | base64 -w0)
asuser "printf %s '$B64' | base64 -d > ~/.config/claude-usage/config.json"   # exact plasmoid mechanism
ICON_OUT=$(asuser 'cd ~/server && python3 generate-icon.py 2>&1' || true)
echo "$ICON_OUT" | grep -qi "falling through to GSettings\|GSettings load failed" \
  && { echo "FAIL — generate-icon.py fell through to GSettings (config.json not consumed)"; exit 1; }
echo "$ICON_OUT" | grep -q "^Icon:" \
  && echo "  PASS — generate-icon.py read config.json (no GSettings fallthrough): $(echo "$ICON_OUT" | grep '^Icon:')" \
  || { echo "FAIL — generate-icon.py did not produce an icon:"; echo "$ICON_OUT"; exit 1; }

echo
echo "=== ALL CHECKS PASSED — KDE plasmoid verified live on Plasma 6 ==="
echo "    Screenshot: $SHOTDIR/kde-plasmoid-live.png"
echo "    (close the QEMU window to tear down the VM)"
