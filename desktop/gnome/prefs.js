import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Pango from 'gi://Pango';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

// Source install puts generate-icon.py under ~/.local/share; .deb under /usr/share.
// Mirrors the candidate-list probe in server/generate-icon.py.
const _ICON_SCRIPT_CANDIDATES = [
    GLib.get_home_dir() + '/.local/share/claude-usage/generate-icon.py',
    '/usr/share/claude-usage/generate-icon.py',
];
const ICON_SCRIPT = _ICON_SCRIPT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || _ICON_SCRIPT_CANDIDATES[0];

// Same probe for the Chrome-extension load-unpacked dir — the prefs window
// surfaces this path so the user can paste it into chrome://extensions.
// Hardcoding ~/.local/share/ misled .deb-installed users to a non-existent path.
const _CHROME_EXT_CANDIDATES = [
    GLib.get_home_dir() + '/.local/share/claude-usage/chrome-extension',
    '/usr/share/claude-usage/chrome-extension',
];
const CHROME_EXT_PATH = _CHROME_EXT_CANDIDATES.find(
    p => GLib.file_test(p, GLib.FileTest.EXISTS)
) || _CHROME_EXT_CANDIDATES[0];

function regenIcon() {
    try {
        Gio.Subprocess.new(
            ['python3', ICON_SCRIPT],
            Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
        );
    } catch (_) {}
}

// L-5 (pass-17): `_regenTimer` used to live at module scope, which leaked
// state across prefs-window close→reopen. Now it's threaded through
// addSpinRow via a per-window holder set up in fillPreferencesWindow.
function addColorRow(group, settings, key, title, subtitle, isDockColor = false) {
    const row = new Adw.ActionRow({title, subtitle});
    const dialog = new Gtk.ColorDialog({title, modal: true});
    const btn = new Gtk.ColorDialogButton({dialog, valign: Gtk.Align.CENTER});
    const rgba = new Gdk.RGBA();
    rgba.parse(settings.get_string(key));
    btn.set_rgba(rgba);
    btn.connect('notify::rgba', () => {
        const c = btn.get_rgba();
        const hex = '#' + [c.red, c.green, c.blue]
            .map(v => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
        settings.set_string(key, hex);
        if (isDockColor) regenIcon();
    });
    row.add_suffix(btn);
    row.set_activatable_widget(btn);
    group.add(row);
}

// Pull <range min/max> from the gschema for `key` so spinner bounds can't
// drift from the schema. Closes pass-17 PR-1 (prefs upper-bound stuck at 99
// after 0.11.19 widened the schema to 500): one source of truth.
//
// PRECONDITION: `key` has an explicit `<range>` element in the gschema.
// Throws a clear error otherwise (PR-2, PR-3 pass-18). PR-4 (pass-19):
// the rejection is "non-`<range>`-typed key" — strictly broader than
// "non-numeric key". A uint key with `<choices>` (no `<range>`) would
// also be rejected. Today only ranged keys are passed.
function schemaRange(settings, key) {
    const k = settings.settings_schema.get_key(key);
    if (!k)
        throw new Error(`schemaRange: key '${key}' not in schema — typo or missing gschema entry`);
    const rangeVariant = k.get_range();              // GVariant '(sv)'
    const [type, inner] = rangeVariant.deepUnpack();
    if (type !== 'range')
        throw new Error(`schemaRange: key '${key}' has no <range> (type=${type}) — call only on numeric ranged keys`);
    const [lo, hi] = inner.deepUnpack();
    return [lo, hi];
}

function addFontRow(group, settings, key, title, subtitle) {
    const row = new Adw.ActionRow({title, subtitle});
    const dialog = new Gtk.FontDialog({title, modal: true});
    const btn = new Gtk.FontDialogButton({
        dialog,
        valign: Gtk.Align.CENTER,
    });
    btn.set_font_desc(Pango.FontDescription.from_string(settings.get_string(key)));
    btn.connect('notify::font-desc', () => {
        const family = btn.get_font_desc().get_family();
        if (family) settings.set_string(key, family);
    });
    row.add_suffix(btn);
    row.set_activatable_widget(btn);
    group.add(row);
}

function addSpinRow(group, settings, key, title, subtitle, regen = false, holder = null) {
    const [lower, upper] = schemaRange(settings, key);
    const adj = new Gtk.Adjustment({lower, upper, step_increment: 1, value: settings.get_uint(key)});
    const row = new Adw.SpinRow({title, subtitle, adjustment: adj});
    // L-4 (pass-17): debounce the GSettings write itself, not just the icon
    // regen. Click-and-hold on the spinner used to fire set_uint per step
    // (10+/sec), and each set_uint dispatches 'changed' synchronously to the
    // main process, which re-runs the full popup _updateDisplay every step.
    // 120 ms means held-down still feels responsive but each "stop spinning"
    // is a single render.
    //
    // PT-1 (pass-18): writeTimer is per-row (so concurrent multi-row writes
    // don't clobber each other) but registered with holder.pendingTimers so
    // the window close-request can drain it before the SpinRow is disposed.
    // PT-2 (pass-19): short-circuit if the window has begun closing — Adw
    // can fire late `value-changed` for committed values during teardown.
    let writeTimer = null;
    adj.connect('value-changed', () => {
        if (holder?.closed) return;
        if (writeTimer) {
            clearTimeout(writeTimer);
            holder?.pendingTimers.delete(writeTimer);
        }
        writeTimer = setTimeout(() => {
            holder?.pendingTimers.delete(writeTimer);
            writeTimer = null;
            settings.set_uint(key, Math.round(adj.get_value()));
        }, 120);
        holder?.pendingTimers.add(writeTimer);
        if (regen && holder) {
            if (holder.regenTimer) clearTimeout(holder.regenTimer);
            holder.regenTimer = setTimeout(() => {
                holder.regenTimer = null;
                regenIcon();
            }, 300);
        }
    });
    group.add(row);
    return adj;
}

export default class ClaudeUsagePreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        // L-5 (pass-17): per-window timer holder. Doesn't survive close/reopen.
        // PT-1 (pass-18, hardened pass-19 PT-2): a Set of pending setTimeout
        // IDs + a `closed` guard flag. Drained on close-request. The flag
        // matters because Adw can emit `value-changed` during widget teardown
        // for committed values — without the flag, the per-row closure would
        // pass its `if (writeTimer)` check, schedule a fresh setTimeout, and
        // call adj.get_value() on a disposed SpinRow. With the flag, the
        // callback short-circuits before re-populating the just-cleared Set.
        const holder = {regenTimer: null, pendingTimers: new Set(), closed: false};
        window.connect('close-request', () => {
            holder.closed = true;
            if (holder.regenTimer) { clearTimeout(holder.regenTimer); holder.regenTimer = null; }
            for (const id of holder.pendingTimers) clearTimeout(id);
            holder.pendingTimers.clear();
            return false;  // don't suppress the close
        });

        const page = new Adw.PreferencesPage({
            title: 'Claude Usage',
            icon_name: 'preferences-system-symbolic',
        });

        // ── Dock Icon Colors ─────────────────────────────────────────────────
        const dockGroup = new Adw.PreferencesGroup({
            title: 'Dock Icon Colors',
            description: 'Ring colors on the dock/taskbar icon',
        });
        page.add(dockGroup);
        addColorRow(dockGroup, settings, 'weekly-color-green', 'Weekly — low',
            'Outer ring · below warning threshold', true);
        addColorRow(dockGroup, settings, 'weekly-color-amber', 'Weekly — mid',
            'Outer ring · at or above warning threshold', true);
        addColorRow(dockGroup, settings, 'weekly-color-red',   'Weekly — high',
            'Outer ring · at or above critical threshold', true);
        addColorRow(dockGroup, settings, 'sonnet-color',       'Sonnet ring',
            'Inner ring', true);

        // ── Popup Colors ─────────────────────────────────────────────────────
        const popupColorGroup = new Adw.PreferencesGroup({
            title: 'Popup Colors',
            description: 'Meter text colors in the panel popup',
        });
        page.add(popupColorGroup);
        addColorRow(popupColorGroup, settings, 'popup-color-normal',
            'Normal',   'Below warning threshold');
        addColorRow(popupColorGroup, settings, 'popup-color-warning',
            'Warning',  'At or above warning threshold');
        addColorRow(popupColorGroup, settings, 'popup-color-critical',
            'Critical', 'At or above critical threshold');

        // ── Popup Display ────────────────────────────────────────────────────
        const popupDisplayGroup = new Adw.PreferencesGroup({title: 'Popup Display'});
        page.add(popupDisplayGroup);
        const warningAdj  = addSpinRow(popupDisplayGroup, settings, 'threshold-warning',
            'Warning threshold',  'Pacing % at which color flips to warning (must be below Critical)', true, holder);
        const criticalAdj = addSpinRow(popupDisplayGroup, settings, 'threshold-critical',
            'Critical threshold', 'Pacing % at which color flips to critical (must exceed Warning)', true, holder);
        warningAdj.connect('value-changed', () => {
            if (Math.round(warningAdj.get_value()) >= Math.round(criticalAdj.get_value()))
                criticalAdj.set_value(Math.round(warningAdj.get_value()) + 1);
        });
        criticalAdj.connect('value-changed', () => {
            if (Math.round(criticalAdj.get_value()) <= Math.round(warningAdj.get_value()))
                warningAdj.set_value(Math.round(criticalAdj.get_value()) - 1);
        });
        addSpinRow(popupDisplayGroup, settings, 'bar-width',
            'Bar width', 'Character count of the █░ usage bar');
        addSpinRow(popupDisplayGroup, settings, 'popup-font-size',
            'Font size', 'Popup meter row font size (px)');

        // ── Popup Font ───────────────────────────────────────────────────────
        const popupFontGroup = new Adw.PreferencesGroup({title: 'Popup Font'});
        page.add(popupFontGroup);
        addFontRow(popupFontGroup, settings, 'popup-font-family',
            'Font family', 'CSS font family used in the popup meter rows');

        // ── Panel ────────────────────────────────────────────────────────────
        const panelGroup = new Adw.PreferencesGroup({title: 'Panel'});
        page.add(panelGroup);
        addColorRow(panelGroup, settings, 'panel-color-normal',   'Label — normal',   'Label color below warning threshold');
        addColorRow(panelGroup, settings, 'panel-color-warning',  'Label — warning',  'Label color at or above warning threshold');
        addColorRow(panelGroup, settings, 'panel-color-critical', 'Label — critical', 'Label color at or above critical threshold');
        addSpinRow(panelGroup, settings, 'panel-font-size',
            'Label font size', 'Panel percentage label font size (px)');
        addSpinRow(panelGroup, settings, 'panel-label-spacing',
            'Icon–label gap', 'Pixels between the icon and the percentage label');
        addSpinRow(panelGroup, settings, 'panel-icon-size',
            'Icon size', 'Panel icon pixel size');

        // ── Setup ────────────────────────────────────────────────────────────
        const infoGroup = new Adw.PreferencesGroup({title: 'Setup'});
        page.add(infoGroup);
        infoGroup.add(new Adw.ActionRow({
            title: 'Chrome extension',
            subtitle: `Load unpacked from: ${CHROME_EXT_PATH}`,
        }));
        infoGroup.add(new Adw.ActionRow({
            title: 'Settings via CLI',
            subtitle: 'gsettings set org.indri.claude-usage …',
        }));

        window.add(page);
    }
}
