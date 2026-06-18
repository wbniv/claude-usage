"""macOS preferences window for the menu-bar app.

A native PyObjC window (built programmatically, no nib) of NSColorWell colour
wells + NSStepper steppers that round-trip the SAME ~/.config/claude-usage/
config.json the app polls (and that generate-icon / the KDE plasmoid read) —
the macOS analog of GNOME's prefs.js and KDE's ConfigGeneral.qml. Writes land
via usage_core.write_ui_config; the app's 2 s poll re-renders within a couple
seconds (the macOS equivalent of GNOME settings applying instantly).

Requires PyObjC (macOS only). Never imported on the Linux build; CI / the Linux
smoke only syntax-check + stub-import it.
"""
from AppKit import (
    NSApplication, NSBackingStoreBuffered, NSColor, NSColorSpace, NSColorWell,
    NSStepper, NSTextField, NSWindow, NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSMakeRect

import usage_core

# (key, kind, label). Only the keys the macOS menu bar actually honours — the
# dock-ring colours (weekly_*/sonnet) render nothing here, and panel font/size/
# spacing are GNOME-panel concepts the status item doesn't use. See
# docs/plans/2026-06-19-macos-prefs-window.md.
FIELDS = [
    ('threshold_warning',    'int',   'Warning threshold (pacing %)'),
    ('threshold_critical',   'int',   'Critical threshold (pacing %)'),
    ('bar_width',            'int',   'Popup bar width'),
    ('popup_font_size',      'int',   'Popup font size (pt)'),
    ('panel_color_normal',   'color', 'Menu-bar %  —  normal'),
    ('panel_color_warning',  'color', 'Menu-bar %  —  warning'),
    ('panel_color_critical', 'color', 'Menu-bar %  —  critical'),
    ('popup_color_normal',   'color', 'Popup  —  normal'),
    ('popup_color_warning',  'color', 'Popup  —  warning'),
    ('popup_color_critical', 'color', 'Popup  —  critical'),
]

W = 460
ROW_H = 36
TOP = 16
BOTTOM = 16


def _nscolor(hexstr):
    h = hexstr.lstrip('#')
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)


def _to_hex(color):
    c = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
    if c is None:
        return None
    r = int(round(c.redComponent() * 255))
    g = int(round(c.greenComponent() * 255))
    b = int(round(c.blueComponent() * 255))
    return f'#{r:02x}{g:02x}{b:02x}'


class PrefsController(NSObject):
    """Methods are exactly: init (designated initializer), show (0-arg), and the
    two `*_` action selectors. No arg-taking helper is a method — they'd become
    Obj-C selectors and trip BadPrototypeError (see the macOS-port plan)."""

    def init(self):
        self = super().init()
        if self is None:
            return None
        self._valueFields = {}
        cfg = usage_core.load_ui_config()
        n = len(FIELDS)
        height = TOP + BOTTOM + ROW_H * n
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, height), style, NSBackingStoreBuffered, False)
        win.setTitle_('Claude Usage — Preferences')
        win.setReleasedWhenClosed_(False)   # retained by the app; reuse on reopen
        win.center()
        content = win.contentView()

        for i, (key, kind, label) in enumerate(FIELDS):
            y = height - TOP - (i + 1) * ROW_H
            lab = NSTextField.labelWithString_(label)
            lab.setFrame_(NSMakeRect(20, y + 6, 230, 20))
            content.addSubview_(lab)
            if kind == 'color':
                well = NSColorWell.alloc().initWithFrame_(NSMakeRect(260, y + 4, 64, 24))
                well.setColor_(_nscolor(cfg[key]))
                well.setTag_(i)
                well.setTarget_(self)
                well.setAction_(b'colorChanged:')
                content.addSubview_(well)
            else:  # int → value label + stepper
                lo, hi = usage_core._SCHEMA_RANGES.get(key, (0, 999))
                vfield = NSTextField.labelWithString_(str(cfg[key]))
                vfield.setFrame_(NSMakeRect(260, y + 6, 44, 20))
                content.addSubview_(vfield)
                self._valueFields[i] = vfield
                stepper = NSStepper.alloc().initWithFrame_(NSMakeRect(310, y + 2, 19, 27))
                stepper.setMinValue_(float(lo))
                stepper.setMaxValue_(float(hi))
                stepper.setIncrement_(1.0)
                stepper.setValueWraps_(False)
                stepper.setIntValue_(int(cfg[key]))
                stepper.setTag_(i)
                stepper.setTarget_(self)
                stepper.setAction_(b'stepperChanged:')
                content.addSubview_(stepper)

        self._window = win
        return self

    def show(self):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._window.makeKeyAndOrderFront_(None)

    def colorChanged_(self, sender):
        key = FIELDS[sender.tag()][0]
        hexv = _to_hex(sender.color())
        if hexv:
            usage_core.write_ui_config({key: hexv})

    def stepperChanged_(self, sender):
        i = sender.tag()
        key = FIELDS[i][0]
        v = int(sender.intValue())
        field = self._valueFields.get(i)
        if field is not None:
            field.setStringValue_(str(v))
        usage_core.write_ui_config({key: v})
