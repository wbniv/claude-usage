import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {ExtensionPreferences} from 'resource:///org/gnome/shell/extensions/prefs.js';

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
function schemaRange(settings, key) {
    const k = settings.settings_schema.get_key(key);
    const rangeVariant = k.get_range();              // GVariant '(sv)'
    const [, inner] = rangeVariant.deepUnpack();     // [type, GVariant<(uu)>]
    const [lo, hi] = inner.deepUnpack();             // [min, max]
    return [lo, hi];
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
    let writeTimer = null;
    adj.connect('value-changed', () => {
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
        // PT-1 (pass-18): a Set of pending setTimeout IDs (per-row write
        // debounces + the shared regen debounce). Drained on close-request
        // so no callback fires against the disposed SpinRow widgets. Per-row
        // tracking matters because the user might touch row A then row B
        // within 120 ms — a single shared writeTimer would lose A's value.
        const holder = {regenTimer: null, pendingTimers: new Set()};
        window.connect('close-request', () => {
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
        const fontRow = new Adw.EntryRow({
            title: 'Font family',
            text: settings.get_string('popup-font-family'),
        });
        fontRow.connect('notify::text', () =>
            settings.set_string('popup-font-family', fontRow.get_text()));
        popupFontGroup.add(fontRow);

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
            subtitle: 'gsettings set org.gnome.shell.extensions.claude-usage …',
        }));

        window.add(page);
    }
}
