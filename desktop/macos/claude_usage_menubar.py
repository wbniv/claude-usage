#!/usr/bin/env python3
"""Claude Usage — macOS menu-bar indicator.

The macOS analog of desktop/gnome/extension.js: an NSStatusItem that shows the
selected meter's `%` (colour-coded by pacing) next to the Anthropic star, and a
dropdown NSMenu with the full per-meter breakdown (coloured pacing bars + reset
countdowns), an "Open Usage Page" link, and a panel-metric selector.

Pure reader, exactly like the GNOME extension: the browser extension + the local
HTTP server (usage-server.py, its own LaunchAgent) produce the cache; this app
only reads ~/.cache/claude-usage/usage.json and renders it. The pacing / colour /
tier MATH is imported from server/usage_core.py — the single source of truth
shared with the GNOME renderer — so there is no third copy to keep in sync.

Requires PyObjC (macOS only). Never imported on the Linux build; the Linux CI
only syntax-checks it.
"""
import json
import os
import sys
import time
import objc
from pathlib import Path

# server/ holds the shared core (usage_core, tooltip). In the .app bundle it's
# copied alongside this module's parent; in a dev checkout it's ../../server.
_HERE = Path(__file__).resolve().parent
# py2app exports RESOURCEPATH = Contents/Resources; the bundled server modules,
# gschema XML, and icons live under there. Dev checkout falls back to ../../server.
_server_dirs = []
if os.environ.get('RESOURCEPATH'):
    _server_dirs.append(Path(os.environ['RESOURCEPATH']) / 'server')
_server_dirs += [_HERE / 'server', _HERE.parent.parent / 'server', _HERE.parent / 'server']
for _cand in _server_dirs:
    if (_cand / 'usage_core.py').exists() or (_cand / 'usage-server.py').exists():
        sys.path.insert(0, str(_cand))
        # In the .app bundle schema_defaults.py is zipped and can't find the
        # gschema XML via __file__; point it at the bundled copy. setdefault so
        # a dev checkout (XML found relative to the repo) is left untouched.
        _schemas = _cand / 'schemas'
        if _schemas.is_dir():
            os.environ.setdefault('CLAUDE_USAGE_SCHEMA_DIR', str(_schemas))
        break

import usage_core
import tooltip
import statusbar_image
import prefs

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSStatusBar,
    NSVariableStatusItemLength, NSMenu, NSMenuItem, NSColor, NSFont, NSWorkspace,
    NSImageLeft, NSEvent, NSEventMaskScrollWheel,
    # Attributed-string key constants live in AppKit, NOT Foundation (PyObjC) —
    # importing them from Foundation raises ImportError on real macOS.
    NSForegroundColorAttributeName, NSFontAttributeName,
)
from Foundation import (
    NSObject, NSTimer, NSAttributedString, NSMutableAttributedString, NSURL,
    NSUserNotification, NSUserNotificationCenter,
)

CACHE_DIR = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'claude-usage'
CACHE_FILE = CACHE_DIR / 'usage.json'
METRIC_FILE = CACHE_DIR / 'panel-metric'          # persisted scroll/click selection
NOTIF_TS_FILE = CACHE_DIR / 'notif-ts'            # broken-tier toast rate-limit
NOTIF_CRIT_TS_FILE = CACHE_DIR / 'notif-crit-ts'  # critical-pacing toast rate-limit
USAGE_URL = 'https://claude.ai/settings/usage'
STATUS_URL = 'https://status.claude.com/'
CACHE_SCHEMA = 1
POLL_SECONDS = 2.0      # cache mtime poll + tier/countdown re-evaluation
FLASH_SECONDS = 0.5     # critical-pacing blink cadence
NOTIFY_THROTTLE_MS = 5 * 60 * 1000


# ── pure display helpers (mirror desktop/gnome/extension.js) ─────────────────

def live_remaining(meter, ts):
    rm = meter.get('reset_minutes') if meter else None
    if not isinstance(rm, (int, float)) or isinstance(rm, bool):
        return None
    elapsed = max(0, int((time.time() - ts) / 60)) if ts else 0
    return max(0, rm - elapsed)


def fmt_countdown(mins):
    if mins >= 24 * 60:
        d = mins // 1440
        h = (mins % 1440) // 60
        return f'⏱{d}d {h}h'
    return f'⏱{mins // 60}:{mins % 60:02d}'


def fmt_age(mins):
    if mins < 60:
        return f'{mins} min'
    h, m = divmod(mins, 60)
    return f'{h} h {m} min' if m else f'{h} h'


def reset_hint(meter, ts):
    """Right-side reset text for a meter row — mirrors extension.js formatRows
    post-bar logic (live countdown when reset_minutes is known, else the parsed
    reset string, else the session "(not started)" placeholder)."""
    live = live_remaining(meter, ts)
    if live is not None:
        return f'  resets in {fmt_countdown(live)}'
    reset = meter.get('reset')
    if reset:
        r = tooltip.parse_reset(reset, reset_minutes=meter.get('reset_minutes'), anchor_ts=ts)
        if r:
            return f'  resets in ⏱{r[1]}' if r[0] else f'  resets {r[1]}'
        return f'  {reset}'
    if (meter.get('pct') or 0) == 0 and 'session' in (meter.get('label') or '').lower():
        return '  (not started)'
    return ''


def is_selectable(m):
    """Eligible to be the panel metric. Mirrors extension.js _isSelectable:
    structural eligibility minus the Sonnet-0% hide rule."""
    label = (m.get('label') or '').lower()
    if 'sonnet' in label and (m.get('pct') or 0) == 0:
        return False
    return m.get('pct') is not None or (
        m.get('count') is not None and m.get('total') is not None and (m.get('total') or 0) > 0)


def visible_meters(meters):
    return [m for m in meters
            if not ('sonnet' in (m.get('label') or '').lower() and (m.get('pct') or 0) == 0)]


def get_primary(meters, selected_label):
    """Mirror extension.js _getPrimary: explicit selection → an 'all' meter →
    first selectable → first."""
    if selected_label:
        found = next((m for m in meters
                      if m.get('label') == selected_label and is_selectable(m)), None)
        if found:
            return found
    import re
    return (next((m for m in meters if re.search(r'all', m.get('label') or '', re.I) and is_selectable(m)), None)
            or next((m for m in meters if is_selectable(m)), None)
            or (meters[0] if meters else None))


def _nscolor(hexstr):
    h = hexstr.lstrip('#')
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


def _ui_cfg():
    """Map the snake_case config (usage_core.load_ui_config) into the short keys
    color_for()/the renderer expect. DR-1 parity: clamp tCrit > tWarn."""
    c = usage_core.load_ui_config()
    t_warn = c['threshold_warning']
    t_crit = max(c['threshold_critical'], t_warn + 1)
    return {
        'tWarn': t_warn, 'tCrit': t_crit,
        'popupNorm': c['popup_color_normal'],
        'popupWarn': c['popup_color_warning'],
        'popupCrit': c['popup_color_critical'],
        'panelNorm': c['panel_color_normal'],
        'panelWarn': c['panel_color_warning'],
        'panelCrit': c['panel_color_critical'],
        'barWidth': c['bar_width'],
        'popupFont': c['popup_font_family'],
        'popupSize': c['popup_font_size'],
    }


def _read_metric():
    try:
        return METRIC_FILE.read_text().strip()
    except OSError:
        return ''


def _write_metric(label):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = METRIC_FILE.with_suffix(f'.{os.getpid()}.tmp')
        tmp.write_text(label or '')
        tmp.replace(METRIC_FILE)
    except OSError:
        pass


def _read_ts(path):
    try:
        return int(path.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def _write_ts(path, value):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value))
    except OSError:
        pass


def _notify(title, body):
    n = NSUserNotification.alloc().init()
    n.setTitle_(title)
    n.setInformativeText_(body)
    NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(n)


# ── controller ───────────────────────────────────────────────────────────────

class ClaudeUsageController(NSObject):

    def init(self):
        self = objc.super(ClaudeUsageController, self).init()
        if self is None:
            return None
        self._data = None
        self._prefs = None      # lazily-created preferences window controller
        self._mtime = 0
        self._lastTier = 'normal'
        self._lastMenuFp = None
        self._anyCrit = False
        self._flashSuppressed = False
        self._flashTimer = None
        self._flashVisible = False
        self._lastNotifyTs = _read_ts(NOTIF_TS_FILE)
        self._lastCritNotifyTs = _read_ts(NOTIF_CRIT_TS_FILE)
        self._schemaWarned = False

        bar = NSStatusBar.systemStatusBar()
        self._item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = self._item.button()
        button.setImagePosition_(NSImageLeft)

        self._menu = NSMenu.alloc().init()
        self._menu.setDelegate_(self)
        self._item.setMenu_(self._menu)

        # Scroll-to-cycle: a scroll event whose window is the status button's
        # window is one delivered over our item — the reliable "pointer is over
        # us" signal without a custom status view. Mirrors extension.js scroll.
        self._scrollMonitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskScrollWheel, self._onScroll)

        self._loadData()
        self._refresh()
        self._pollTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            POLL_SECONDS, self, b'tick:', None, True)
        return self

    # ── data ──
    @objc.python_method
    def _loadData(self):
        try:
            st = CACHE_FILE.stat()
        except OSError:
            return False
        if st.st_mtime == self._mtime:
            return False
        self._mtime = st.st_mtime
        try:
            self._data = json.loads(CACHE_FILE.read_text())
            sv = self._data.get('_schema')
            if sv is not None and sv != CACHE_SCHEMA and not self._schemaWarned:
                print(f'ClaudeUsage: cache _schema={sv} but app expects {CACHE_SCHEMA}; '
                      f'fields may be misread', file=sys.stderr, flush=True)
                self._schemaWarned = True
        except (OSError, json.JSONDecodeError) as e:
            print(f'ClaudeUsage: failed to read cache: {e}', file=sys.stderr, flush=True)
            return False
        return True

    def tick_(self, _timer):
        self._loadData()
        self._refresh()

    # ── render ──
    @objc.python_method
    def _refresh(self):
        button = self._item.button()
        d = self._data
        cfg = _ui_cfg()

        if not d or not d.get('meters'):
            button.setImage_(statusbar_image.status_image('normal'))
            button.setAttributedTitle_(self._attr(' --', cfg['panelNorm'], self._labelFont()))
            self._setMenuLoading()
            return

        meters = d['meters']
        period_lens = d.get('_period_lengths') or {}
        primary = get_primary(meters, _read_metric())
        pct = (primary.get('pct') if primary else 0)
        if pct is None and primary and primary.get('total'):
            pct = round(primary['count'] / primary['total'] * 100)
        pct = pct or 0

        # pacing drives COLOUR; raw pct drives the displayed number.
        panel_pacing = usage_core.pacing_pct(primary, period_lens) if primary else pct
        any_crit = any(usage_core.pacing_pct(m, period_lens) >= cfg['tCrit'] for m in meters)
        if any_crit:
            label_color = cfg['panelCrit']
        elif panel_pacing >= cfg['tCrit']:
            label_color = cfg['panelCrit']
        elif panel_pacing >= cfg['tWarn']:
            label_color = cfg['panelWarn']
        else:
            label_color = cfg['panelNorm']

        # 100% → live ⏱countdown for the soonest-resetting maxed meter.
        ts = d.get('_timestamp')
        maxed = [m for m in meters
                 if (m.get('pct') or 0) >= 100 and isinstance(m.get('reset_minutes'), (int, float))
                 and not isinstance(m.get('reset_minutes'), bool)]
        if maxed:
            maxed.sort(key=lambda m: live_remaining(m, ts) or 0)
            label_text = ' ' + fmt_countdown(live_remaining(maxed[0], ts) or 0)
        else:
            label_text = f' {pct}%'

        tier, reason, want_link = self._deriveTier(d)
        button.setImage_(statusbar_image.status_image(tier))
        button.setAttributedTitle_(self._attr(label_text, label_color, self._labelFont()))

        self._handleNotifications(d, cfg, meters, period_lens, tier, reason, any_crit)
        self._handleFlash(any_crit)

        # Rebuild the menu only when something visible changed (avoids flicker
        # while the menu is open) — mirrors extension.js _lastMenuFp / UX-1.
        fp = self._menuFingerprint(d, cfg, tier, primary, meters)
        if fp != self._lastMenuFp:
            self._lastMenuFp = fp
            self._buildMenu(d, cfg, meters, period_lens, primary, tier, reason, want_link)

    @objc.python_method
    def _deriveTier(self, d):
        """Highest-confidence active failure signal. Cache-encoded signals come
        from usage_core.derive_tier; the time-based stale/broken thresholds are
        the frontend's job (mirror extension.js lines ~569-595)."""
        astat = d.get('_anthropic_status') or {}
        sfc = d.get('_scrape_fail_count') or 0
        age = None
        if d.get('_timestamp'):
            age = max(0, round((time.time() - d['_timestamp']) / 60))
        if astat.get('indicator') and astat['indicator'] != 'none':
            return 'broken', f"⚠ Anthropic reports: {astat.get('description') or astat['indicator']}", True
        comp = astat.get('claude_ai_component_status')
        if comp and comp != 'operational':
            return 'broken', f'⚠ claude.ai status: {comp}', True
        if isinstance(sfc, int) and not isinstance(sfc, bool) and sfc >= 2:
            return 'broken', f'⚠ {sfc} scrape attempts failed · run claude-usage-status', False
        if age is not None and age > 20:
            return 'broken', f'⚠ No data in {fmt_age(age)} · run claude-usage-status', False
        if age is not None and age > 15:
            return 'stale', f'🕐 No update in {fmt_age(age)}', False
        return 'normal', None, False

    # ── menu ──
    @objc.python_method
    def _setMenuLoading(self):
        self._menu.removeAllItems()
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('No data yet', None, '')
        item.setEnabled_(False)
        self._menu.addItem_(item)
        self._addFooter()

    @objc.python_method
    def _buildMenu(self, d, cfg, meters, period_lens, primary, tier, reason, want_link):
        self._menu.removeAllItems()
        plan = d.get('plan') or 'Claude'
        age = None
        if d.get('_timestamp'):
            age = max(0, round((time.time() - d['_timestamp']) / 60))
        age_str = f" · {'<1' if age is not None and age < 1 else age}m ago" if age is not None else ''
        status_text = (reason or f'{plan}{age_str}') + (' ↗' if want_link else '')

        status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(status_text, None, '')
        if want_link:
            status_item.setTarget_(self)
            status_item.setAction_(b'openStatus:')
        else:
            status_item.setEnabled_(False)
        self._menu.addItem_(status_item)
        self._menu.addItem_(NSMenuItem.separatorItem())

        ts = d.get('_timestamp')
        font = self._popupFont(cfg)
        vis = visible_meters(meters)
        max_label = max((len(m.get('label') or '') for m in vis), default=0)
        max_col2 = max([4] + [
            len(f"{m['count']}/{m['total']}" if m.get('count') is not None and m.get('total') is not None
                else f"{m.get('pct') or 0}%") for m in vis])

        sub_color = cfg['popupNorm']
        saw_extra = False
        for m in vis:
            is_extra = m.get('spent') is not None or m.get('balance') is not None
            if is_extra and not saw_extra:
                self._menu.addItem_(NSMenuItem.separatorItem())
                saw_extra = True
            self._menu.addItem_(self._meterItem(m, cfg, period_lens, ts, primary,
                                                max_label, max_col2, font))
            # extra-usage sub-row (spent · balance)
            if is_extra:
                parts = []
                if m.get('spent'):
                    parts.append(f"{m['spent']} spent")
                if m.get('balance'):
                    parts.append(f"{m['balance']} balance")
                if parts:
                    sub = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('', None, '')
                    sub.setAttributedTitle_(self._attr('    ' + ' · '.join(parts), sub_color, font))
                    sub.setEnabled_(False)
                    self._menu.addItem_(sub)

        self._addFooter()

    @objc.python_method
    def _meterItem(self, m, cfg, period_lens, ts, primary, max_label, max_col2, font):
        label = (m.get('label') or '').ljust(max_label)
        is_count = m.get('count') is not None and m.get('total') is not None
        col2 = (f"{m['count']}/{m['total']}" if is_count else f"{m.get('pct') or 0}%").rjust(max_col2)
        prefix = '✴ ' if (m is primary) else '  '
        pacing = usage_core.pacing_pct(m, period_lens)
        row_color = usage_core.color_for('empty', pacing, cfg)

        attr = NSMutableAttributedString.alloc().init()
        attr.appendAttributedString_(self._attr(f'{prefix}{label}  {col2}  ', row_color, font))
        if is_count:
            attr.appendAttributedString_(self._attr(' ' * cfg['barWidth'], row_color, font))
        else:
            ef = usage_core.elapsed_fraction(m, period_lens)
            for ch, role in usage_core.pacing_segments(m.get('pct') or 0, ef, cfg['barWidth']):
                attr.appendAttributedString_(self._attr(ch, usage_core.color_for(role, pacing, cfg), font))
            attr.appendAttributedString_(self._attr(reset_hint(m, ts), row_color, font))

        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('', None, '')
        item.setAttributedTitle_(attr)
        if not is_count or True:  # selectable rows get the click-to-pin action
            if is_selectable(m):
                item.setTarget_(self)
                item.setAction_(b'selectMetric:')
                item.setRepresentedObject_(m.get('label'))
            else:
                item.setEnabled_(False)
        return item

    @objc.python_method
    def _addFooter(self):
        self._menu.addItem_(NSMenuItem.separatorItem())
        prefs_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            'Preferences…', b'openPrefs:', ',')
        prefs_item.setTarget_(self)
        self._menu.addItem_(prefs_item)
        open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            'Open Usage Page', b'openUsage:', '')
        open_item.setTarget_(self)
        self._menu.addItem_(open_item)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            'Quit Claude Usage', b'terminate:', 'q')
        quit_item.setTarget_(NSApplication.sharedApplication())
        self._menu.addItem_(quit_item)

    @objc.python_method
    def _menuFingerprint(self, d, cfg, tier, primary, meters):
        return json.dumps({
            'ts': d.get('_timestamp'), 'tier': tier, 'bw': cfg['barWidth'],
            'norm': cfg['popupNorm'], 'warn': cfg['popupWarn'], 'crit': cfg['popupCrit'],
            'tWarn': cfg['tWarn'], 'tCrit': cfg['tCrit'],
            'primary': (primary or {}).get('label', ''),
            'meters': [f"{m.get('label')}:{m.get('pct')}:{m.get('reset_minutes')}:"
                       f"{m.get('count')}/{m.get('total')}:{m.get('spent')}:{m.get('balance')}"
                       for m in meters],
        }, sort_keys=True)

    # ── notifications + flash ──
    @objc.python_method
    def _handleNotifications(self, d, cfg, meters, period_lens, tier, reason, any_crit):
        now_ms = int(time.time() * 1000)
        if any_crit and not self._anyCrit:
            if now_ms - self._lastCritNotifyTs > NOTIFY_THROTTLE_MS:
                crit_pacing, crit_label = 0, ''
                for m in meters:
                    p = usage_core.pacing_pct(m, period_lens)
                    if p >= cfg['tCrit']:
                        crit_pacing, crit_label = p, m.get('label')
                        break
                disp = '>200' if crit_pacing > 200 else round(crit_pacing)
                _notify('Claude Usage', f'⚠ {crit_label} on pace for {disp}% by reset')
                self._lastCritNotifyTs = now_ms
                _write_ts(NOTIF_CRIT_TS_FILE, now_ms)

        if tier == 'broken' and self._lastTier != 'broken':
            if now_ms - self._lastNotifyTs > NOTIFY_THROTTLE_MS:
                _notify('Claude Usage', reason or 'Service disruption detected')
                self._lastNotifyTs = now_ms
                _write_ts(NOTIF_TS_FILE, now_ms)
        self._lastTier = tier

    @objc.python_method
    def _handleFlash(self, any_crit):
        if not any_crit:
            if self._anyCrit:
                self._stopFlash()
                self._flashSuppressed = False
        elif not self._anyCrit:
            if not self._flashSuppressed:
                self._startFlash()
        self._anyCrit = any_crit

    @objc.python_method
    def _startFlash(self):
        self._stopFlash()
        self._flashVisible = False
        self._flashTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            FLASH_SECONDS, self, b'flash:', None, True)

    def flash_(self, _timer):
        self._item.button().setAlphaValue_(1.0 if self._flashVisible else 0.3)
        self._flashVisible = not self._flashVisible

    @objc.python_method
    def _stopFlash(self):
        if self._flashTimer is not None:
            self._flashTimer.invalidate()
            self._flashTimer = None
        self._item.button().setAlphaValue_(1.0)

    # ── attributed-string helpers ──
    @objc.python_method
    def _labelFont(self):
        return NSFont.menuBarFontOfSize_(0)

    @objc.python_method
    def _popupFont(self, cfg):
        return (NSFont.fontWithName_size_(cfg['popupFont'], cfg['popupSize'])
                or NSFont.monospacedSystemFontOfSize_weight_(cfg['popupSize'], 0))

    @objc.python_method
    def _attr(self, text, hexcolor, font):
        return NSAttributedString.alloc().initWithString_attributes_(
            text, {NSForegroundColorAttributeName: _nscolor(hexcolor), NSFontAttributeName: font})

    # ── actions / events ──
    @objc.python_method
    def _onScroll(self, event):
        try:
            if event.window() is self._item.button().window() and self._data:
                self._cycleMetric(1 if event.deltaY() < 0 else -1)
                return None  # consume
        except Exception:
            pass
        return event

    @objc.python_method
    def _cycleMetric(self, delta):
        eligible = [m for m in (self._data.get('meters') or []) if is_selectable(m)]
        if len(eligible) < 2:
            return
        cur = _read_metric()
        idx = next((i for i, m in enumerate(eligible) if m.get('label') == cur), 0)
        _write_metric(eligible[(idx + delta) % len(eligible)].get('label'))
        self._refresh()

    def selectMetric_(self, sender):
        _write_metric(sender.representedObject())
        self._refresh()

    def openPrefs_(self, _sender):
        if self._prefs is None:
            self._prefs = prefs.PrefsController.alloc().init()
        self._prefs.show()

    def openUsage_(self, _sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(USAGE_URL))

    def openStatus_(self, _sender):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(STATUS_URL))

    # ── NSMenu delegate: stop flashing once the user is looking ──
    def menuWillOpen_(self, _menu):
        self._stopFlash()
        self._flashSuppressed = True


def _start_server_thread():
    """Run the local HTTP server (usage-server.py) in-process, in a daemon
    thread, so a single LaunchAgent covers both the data server and the
    menu-bar UI — the Linux split (systemd server + GNOME shell) collapsed into
    one macOS agent. The server needs only the stdlib + tooltip.py on macOS
    (the cairo/PIL dock-icon path is disabled there)."""
    import importlib.util
    import threading
    for cand in (_HERE / 'server', _HERE.parent.parent / 'server', _HERE.parent / 'server'):
        sp = cand / 'usage-server.py'
        if sp.exists():
            spec = importlib.util.spec_from_file_location('usage_server', sp)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            threading.Thread(target=mod.serve_forever, daemon=True).start()
            return
    print('ClaudeUsage: usage-server.py not found; running UI without a local server',
          file=sys.stderr, flush=True)


def main():
    _start_server_thread()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # menu-bar only
    controller = ClaudeUsageController.alloc().init()
    app._controller = controller  # retain
    app.run()


if __name__ == '__main__':
    main()
