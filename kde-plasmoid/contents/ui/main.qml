import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore

PlasmoidItem {
    id: root

    property var usageData: null
    property int activeMeterIndex: 0

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

    // Pacing color: matches extension.js pacing formula
    function pacingColor(meter) {
        if (!meter) return Plasmoid.configuration.panelColorNormal
        const now = Date.now() / 1000
        const periodSecs = meter.period_secs || 604800
        const resetTs = meter.reset_ts || (now - periodSecs)
        const elapsed = Math.max(now - resetTs, 1)
        const periodFrac = Math.min(elapsed / periodSecs, 1)
        const pacing = periodFrac > 0 ? (meter.pct / 100) / periodFrac : 0
        const warn = Plasmoid.configuration.thresholdWarning / 100
        const crit = Plasmoid.configuration.thresholdCritical / 100
        if (pacing >= crit) return Plasmoid.configuration.panelColorCritical
        if (pacing >= warn) return Plasmoid.configuration.panelColorWarning
        return Plasmoid.configuration.panelColorNormal
    }

    function popupPacingColor(meter) {
        if (!meter) return Plasmoid.configuration.popupColorNormal
        const now = Date.now() / 1000
        const periodSecs = meter.period_secs || 604800
        const resetTs = meter.reset_ts || (now - periodSecs)
        const elapsed = Math.max(now - resetTs, 1)
        const periodFrac = Math.min(elapsed / periodSecs, 1)
        const pacing = periodFrac > 0 ? (meter.pct / 100) / periodFrac : 0
        const warn = Plasmoid.configuration.thresholdWarning / 100
        const crit = Plasmoid.configuration.thresholdCritical / 100
        if (pacing >= crit) return Plasmoid.configuration.popupColorCritical
        if (pacing >= warn) return Plasmoid.configuration.popupColorWarning
        return Plasmoid.configuration.popupColorNormal
    }

    function loadData() {
        const path = StandardPaths.standardLocations(StandardPaths.CacheLocation)[0]
            .toString().replace(/^file:\/\//, '')
            .replace(/\/claude-usage.*$/, '') + '/claude-usage/usage.json'
        const xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status === 0 && xhr.responseText) {
                try {
                    usageData = JSON.parse(xhr.responseText)
                    resolveActiveMeter()
                } catch(e) {
                    console.warn("claude-usage: failed to parse usage.json:", e)
                }
            }
        }
        xhr.open("GET", "file://" + StandardPaths.writableLocation(StandardPaths.HomeLocation)
                  + "/.cache/claude-usage/usage.json")
        xhr.send()
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
    Plasmoid.onActivated: { }

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
