import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents3

RowLayout {
    id: compactRoot
    spacing: 4

    // Icon
    Image {
        id: icon
        source: Qt.resolvedUrl("../icons/claude-22.png")
        implicitWidth: Plasmoid.configuration.panelIconSize || 16
        implicitHeight: implicitWidth
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
