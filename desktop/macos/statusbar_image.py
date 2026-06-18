"""Menu-bar status image for the macOS port.

The GNOME panel uses a fixed brand star bitmap (claude-22.png normal,
claude-22-red.png on the broken tier) plus a colour-coded `%` text label —
NOT the concentric dock rings (those are a Dock concept; see the v1 scope note
in docs/plans/2026-06-18-macos-port.md). The menu bar mirrors that exactly:

  normal  → orange star, full opacity
  stale   → orange star, ~40% opacity (ghosted)
  broken  → red-tinted star, full opacity

These are loaded from the same PNGs the GNOME extension ships
(desktop/gnome/icons/), so there is no separate macOS art to keep in sync.
Importing this module requires PyObjC (macOS only); it is never imported on
the Linux build.
"""
import os
from pathlib import Path

from AppKit import NSImage, NSCompositingOperationSourceOver
from Foundation import NSMakeSize, NSMakeRect

_HERE = Path(__file__).resolve().parent
# In the .app bundle the icons land in Contents/Resources/icons (py2app exports
# RESOURCEPATH). Dev checkout falls back to desktop/gnome/icons/ so running
# straight from a clone needs no art copying.
_ICON_DIRS = []
if os.environ.get('RESOURCEPATH'):
    _ICON_DIRS.append(Path(os.environ['RESOURCEPATH']) / 'icons')
_ICON_DIRS += [_HERE / 'icons', _HERE.parent / 'gnome' / 'icons']

# Menu-bar items render at ~18 pt; the system scales for Retina from the
# bitmap's native resolution, so we hand NSImage the high-res source and let
# it down-sample. claude-64 is the largest brand bitmap available.
_MENUBAR_PT = 18.0


def _icon_path(name):
    for d in _ICON_DIRS:
        p = d / name
        if p.exists():
            return p
    return None


def _load(name):
    p = _icon_path(name)
    if p is None:
        return None
    img = NSImage.alloc().initWithContentsOfFile_(str(p))
    if img is not None:
        img.setSize_(NSMakeSize(_MENUBAR_PT, _MENUBAR_PT))
    return img


def _dimmed(img, alpha):
    """Return a copy of `img` drawn at `alpha` opacity (for the stale tier)."""
    if img is None:
        return None
    size = img.size()
    out = NSImage.alloc().initWithSize_(size)
    out.lockFocus()
    img.drawAtPoint_fromRect_operation_fraction_(
        (0, 0), NSMakeRect(0, 0, size.width, size.height),
        NSCompositingOperationSourceOver, alpha)
    out.unlockFocus()
    return out


def status_image(tier):
    """NSImage for the menu-bar button given the current tier.

    Returns None if the brand PNGs can't be found (caller falls back to a text
    glyph) — defensive, mirroring the GNOME preview's `icon or '✴'` fallback."""
    if tier == 'broken':
        return _load('claude-22-red.png') or _load('claude-22.png')
    img = _load('claude-22.png')
    if tier == 'stale':
        return _dimmed(img, 0.4)   # ~40% — matches extension.js opacity = 100/255
    return img
