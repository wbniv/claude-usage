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
    // so usageData would stay null forever. The executable engine is the same
    // mechanism ConfigGeneral.qml uses to write config.json.
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

    // Pacing fraction (0–1+): mirrors gnome-extension/extension.js:pacingPct
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
        if (pacing >= Plasmoid.configuration.thresholdCritical / 100) return cCritical
        if (pacing >= Plasmoid.configuration.thresholdWarning / 100) return cWarning
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

    Component.onCompleted: root.loadData()

    // Scroll cycles through meters
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        onWheel: function(wheel) {
            if (!usageData || !usageData.meters) return
            const n = usageData.meters.length
            if (n <= 1) return
            if (wheel.angleDelta.y > 0)
                activeMeterIndex = (activeMeterIndex - 1 + n) % n
            else
                activeMeterIndex = (activeMeterIndex + 1) % n
            Plasmoid.configuration.panelMetric = usageData.meters[activeMeterIndex].label
        }
    }
}
