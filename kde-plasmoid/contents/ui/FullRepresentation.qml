import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: fullRoot
    spacing: Kirigami.Units.smallSpacing
    width: implicitWidth
    implicitWidth: Kirigami.Units.gridUnit * 18

    // Status bar
    PlasmaComponents3.Label {
        id: statusLabel
        Layout.fillWidth: true
        text: {
            if (!root.usageData) return "No data — waiting for Chrome extension"
            if (root.usageData.status && root.usageData.status !== "ok")
                return "⚠ Anthropic service degraded"
            if (root.usageData.last_update) {
                const ageSecs = Date.now() / 1000 - root.usageData.last_update
                const ageMin = Math.round(ageSecs / 60)
                return "Updated " + (ageMin < 1 ? "just now" : ageMin + "m ago")
            }
            return ""
        }
        font.pixelSize: 10
        opacity: 0.7
        wrapMode: Text.WordWrap
    }

    Kirigami.Separator { Layout.fillWidth: true }

    // Meter rows
    Repeater {
        model: root.usageData ? root.usageData.meters : []

        MeterRow {
            Layout.fillWidth: true
            meter: modelData
            meterColor: root.popupPacingColor(modelData)
            barWidth: Plasmoid.configuration.barWidth || 10
            fontFamily: Plasmoid.configuration.popupFontFamily || "monospace"
            fontSize: Plasmoid.configuration.popupFontSize || 10
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    // Panel metric selector
    ColumnLayout {
        spacing: 2
        visible: root.usageData && root.usageData.meters && root.usageData.meters.length > 1

        PlasmaComponents3.Label {
            text: "Panel metric"
            font.pixelSize: 9
            opacity: 0.6
        }

        Repeater {
            model: root.usageData ? root.usageData.meters : []
            QQC2.RadioButton {
                text: modelData.label
                checked: root.activeMeterIndex === index
                onClicked: {
                    root.activeMeterIndex = index
                    Plasmoid.configuration.panelMetric = modelData.label
                }
                font.pixelSize: 10
            }
        }
    }

    // Open usage page link
    PlasmaComponents3.Label {
        Layout.alignment: Qt.AlignHCenter
        text: "<a href='https://claude.ai/settings/usage'>Open Usage Page</a>"
        font.pixelSize: 10
        onLinkActivated: link => Qt.openUrlExternally(link)
        linkColor: Kirigami.Theme.linkColor
    }
}
