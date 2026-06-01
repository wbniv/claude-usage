import QtQuick
import QtQuick.Layouts
import QtCore
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    property var usageData: null
    property int activeMeterIndex: 0

    // Read usage.json via the executable engine, NOT XMLHttpRequest: a file://
    // XHR never reaches readyState DONE inside the Plasma 6 plasmoid QML
    // sandbox (verified live on Plasma 6 / Qt 6.8 — it hangs at readyState 1),
    // so usageData would stay null forever.
    Plasma5Support.DataSource {
        id: reader
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source)   // one-shot per poll
            const out = (data && data["stdout"] ? data["stdout"] : "").trim()
            if (!out) return
            try {
                usageData = JSON.parse(out)
                resolveActiveMeter()
            } catch(e) {
                console.warn("claude-usage: failed to parse usage.json:", e)
            }
        }
    }

    // Mirror dock-icon-relevant config to ~/.config/claude-usage/config.json so
    // server/generate-icon.py picks up KDE colour/threshold/font choices (KConfig
    // is invisible to it). This lives here — not in the config page — because the
    // page can't reliably write files, and watching Plasmoid.configuration fires
    // on every change (dialog OK, scroll, defaults reset), not just a dialog save.
    Plasma5Support.DataSource {
        id: writer
        engine: "executable"
        connectedSources: []
        onNewData: (source) => disconnectSource(source)
    }

    function writeConfigJson() {
        const c = Plasmoid.configuration
        const cfg = {
            weekly_color_green:   c.weeklyColorGreen,
            weekly_color_amber:   c.weeklyColorAmber,
            weekly_color_red:     c.weeklyColorRed,
            sonnet_color:         c.sonnetColor,
            popup_color_normal:   c.popupColorNormal,
            popup_color_warning:  c.popupColorWarning,
            popup_color_critical: c.popupColorCritical,
            threshold_warning:    c.thresholdWarning,
            threshold_critical:   c.thresholdCritical,
            popup_font_family:    c.popupFontFamily,
        }
        // base64-pipe the payload so colour/font values can't break the command.
        const b64 = Qt.btoa(JSON.stringify(cfg))
        writer.connectSource(
            'mkdir -p "$HOME/.config/claude-usage" && ' +
            "printf %s '" + b64 + "' | base64 -d > \"$HOME/.config/claude-usage/config.json\"")
    }

    // Recomputes whenever any mirrored key changes → onChanged re-writes the file.
    readonly property string _configSnapshot: [
        Plasmoid.configuration.weeklyColorGreen, Plasmoid.configuration.weeklyColorAmber,
        Plasmoid.configuration.weeklyColorRed, Plasmoid.configuration.sonnetColor,
        Plasmoid.configuration.popupColorNormal, Plasmoid.configuration.popupColorWarning,
        Plasmoid.configuration.popupColorCritical, Plasmoid.configuration.thresholdWarning,
        Plasmoid.configuration.thresholdCritical, Plasmoid.configuration.popupFontFamily
    ].join("")
    on_ConfigSnapshotChanged: writeConfigJson()

    // Derive index from saved panelMetric name, or use 0
    function resolveActiveMeter() {
        if (!usageData || !usageData.meters || usageData.meters.length === 0) return
        const saved = Plasmoid.configuration.panelMetric
        if (!saved) { activeMeterIndex = 0; return }
        const idx = usageData.meters.findIndex(m => m.label === saved)
        activeMeterIndex = idx >= 0 ? idx : 0
    }

    function currentMeter() {
        if (!usageData || !usageData.meters || usageData.meters.length === 0) return null
        return usageData.meters[Math.min(activeMeterIndex, usageData.meters.length - 1)]
    }

    // Cycle the panel metric by `delta` (±1). Called from CompactRepresentation's
    // WheelHandler — see the note where the root MouseArea used to live.
    function cycleMeter(delta) {
        if (!usageData || !usageData.meters) return
        const n = usageData.meters.length
        if (n <= 1) return
        activeMeterIndex = (activeMeterIndex + delta + n) % n
        Plasmoid.configuration.panelMetric = usageData.meters[activeMeterIndex].label
    }

    // Pacing fraction (0–1+): mirrors desktop/gnome/extension.js:pacingPct
    // exactly — raw fraction below the floor, pct ÷ elapsed-fraction above it.
    // Reads the real usage.json schema: meter.reset_minutes (minutes-from-now)
    // and the top-level _period_lengths[label] (minutes). Field names are
    // guarded by scripts/lint-kde-parity.py.
    function pacingFraction(meter) {
        if (!meter || typeof meter.pct !== "number" || meter.pct === 0) return 0
        const periodLens = usageData ? usageData._period_lengths : null
        const rm = meter.reset_minutes
        const period = periodLens ? periodLens[meter.label] : undefined
        if (rm === undefined || rm === null || !period) return meter.pct / 100
        const elapsed = period - rm
        if (elapsed < Math.max(15, period * 0.05)) return meter.pct / 100
        return (meter.pct / 100) / (elapsed / period)
    }

    // One helper for both panel and popup colours (caller passes the trio).
    function pacingColor(meter, cNormal, cWarning, cCritical) {
        if (!meter) return cNormal
        const pacing = pacingFraction(meter)
        const tWarn = Plasmoid.configuration.thresholdWarning
        // KQ-4 (pass-29): clamp critical > warning even if persisted out of order
        // (kwriteconfig6 / a config migration bypass the SpinBox interlock, which
        // only fires on user edits). Mirrors extension.js's DR-1 — without it the
        // colour ladder inverts: critical fires first and warning is unreachable.
        const tCrit = Math.max(Plasmoid.configuration.thresholdCritical, tWarn + 1)
        if (pacing >= tCrit / 100) return cCritical
        if (pacing >= tWarn / 100) return cWarning
        return cNormal
    }

    function loadData() {
        // GenericCacheLocation = $XDG_CACHE_HOME or ~/.cache (no app-name
        // suffix) — exactly where usage-server.py writes usage.json. Qt6 QML
        // may return a file:// url or a bare path; normalise both.
        var base = StandardPaths.writableLocation(StandardPaths.GenericCacheLocation).toString()
        base = base.replace(/^file:\/\//, "")
        const path = base + "/claude-usage/usage.json"
        // Single-quote the path for the shell; cache paths never contain quotes.
        reader.connectSource("cat '" + path + "' 2>/dev/null")
    }

    compactRepresentation: CompactRepresentation { }
    fullRepresentation: FullRepresentation { }

    Timer {
        interval: 30000
        repeat: true
        running: true
        onTriggered: root.loadData()
    }

    Component.onCompleted: { root.loadData(); root.writeConfigJson() }
}
