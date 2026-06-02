import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents3

RowLayout {
    id: compactRoot
    spacing: 4

    // KQ-1 (pass-29): wheel-to-cycle must live on the compact representation —
    // the item actually placed in the panel. A MouseArea on the root
    // PlasmoidItem (the previous home) receives no panel wheel events in
    // Plasma 6, so scroll-to-cycle was dead. WheelHandler doesn't participate
    // in the layout (no anchors conflict) and leaves click-to-expand to the
    // framework.
    WheelHandler {
        onWheel: (event) => root.cycleMeter(event.angleDelta.y > 0 ? -1 : 1)
    }

    // Icon
    Image {
        id: icon
        source: Qt.resolvedUrl("../icons/claude-22.png")
        // Image.implicitWidth/implicitHeight are read-only in Qt 6 (derived from
        // sourceSize) — size it through the layout + sourceSize instead.
        readonly property int px: Plasmoid.configuration.panelIconSize || 16
        Layout.preferredWidth: px
        Layout.preferredHeight: px
        sourceSize.width: px
        sourceSize.height: px
        Layout.alignment: Qt.AlignVCenter
        fillMode: Image.PreserveAspectFit

        // Fall back to a text "C" if icon file absent
        visible: status === Image.Ready
    }
    PlasmaComponents3.Label {
        visible: icon.status !== Image.Ready
        text: "C"
        font.bold: true
        Layout.alignment: Qt.AlignVCenter
    }

    PlasmaComponents3.Label {
        id: label
        Layout.alignment: Qt.AlignVCenter
        text: {
            var _ = root.nowTick  // force re-eval on each 30 s tick
            const maxed = root.maxedMeter()
            if (maxed !== null) {
                const rem = root.liveRemaining(maxed)
                return root.fmtCountdown(rem !== null ? rem : 0)
            }
            const m = root.currentMeter()
            return m ? Math.round(m.pct) + "%" : "—"
        }
        color: root.pacingColor(root.currentMeter(),
                                Plasmoid.configuration.panelColorNormal,
                                Plasmoid.configuration.panelColorWarning,
                                Plasmoid.configuration.panelColorCritical)
        font.pixelSize: Plasmoid.configuration.panelFontSize || 11
    }
}