import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami
import org.kde.kquickcontrols as KQuickControls
import org.kde.plasma.plasma5support as Plasma5Support

Kirigami.ScrollablePage {
    id: configPage

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => disconnectSource(sourceName)
    }

    // Persist the dock-icon-relevant config to ~/.config/claude-usage/config.json
    // so server/generate-icon.py picks up KDE colour/threshold/font choices.
    // QML can't write files directly, so shell out via the executable engine;
    // base64-pipe the payload so colour/font values can't break the command.
    function saveConfigJson() {
        const cfg = {
            weekly_color_green:   cfg_weeklyColorGreen.color.toString(),
            weekly_color_amber:   cfg_weeklyColorAmber.color.toString(),
            weekly_color_red:     cfg_weeklyColorRed.color.toString(),
            sonnet_color:         cfg_sonnetColor.color.toString(),
            popup_color_normal:   cfg_popupColorNormal.color.toString(),
            popup_color_warning:  cfg_popupColorWarning.color.toString(),
            popup_color_critical: cfg_popupColorCritical.color.toString(),
            threshold_warning:    cfg_thresholdWarning.value,
            threshold_critical:   cfg_thresholdCritical.value,
            popup_font_family:    plasmoid.configuration.popupFontFamily,
        }
        const b64 = Qt.btoa(JSON.stringify(cfg))
        executable.connectSource(
            'mkdir -p "$HOME/.config/claude-usage" && ' +
            "printf %s '" + b64 + "' | base64 -d > \"$HOME/.config/claude-usage/config.json\"")
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        // ── Dock Icon Colors ─────────────────────────────────────────────────
        Kirigami.FormLayout {
            Layout.fillWidth: true
            Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Dock Icon Colors" }

            KQuickControls.ColorButton {
                id: cfg_weeklyColorGreen
                Kirigami.FormData.label: "Weekly — low:"
                color: plasmoid.configuration.weeklyColorGreen
                onAccepted: { plasmoid.configuration.weeklyColorGreen = color.toString(); saveConfigJson() }
            }
            KQuickControls.ColorButton {
                id: cfg_weeklyColorAmber
                Kirigami.FormData.label: "Weekly — mid:"
                color: plasmoid.configuration.weeklyColorAmber
                onAccepted: { plasmoid.configuration.weeklyColorAmber = color.toString(); saveConfigJson() }
            }
            KQuickControls.ColorButton {
                id: cfg_weeklyColorRed
                Kirigami.FormData.label: "Weekly — high:"
                color: plasmoid.configuration.weeklyColorRed
                onAccepted: { plasmoid.configuration.weeklyColorRed = color.toString(); saveConfigJson() }
            }
            KQuickControls.ColorButton {
                id: cfg_sonnetColor
                Kirigami.FormData.label: "Sonnet ring:"
                color: plasmoid.configuration.sonnetColor
                onAccepted: { plasmoid.configuration.sonnetColor = color.toString(); saveConfigJson() }
            }
        }

        // ── Popup Colors ─────────────────────────────────────────────────────
        Kirigami.FormLayout {
            Layout.fillWidth: true
            Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Popup Colors" }

            KQuickControls.ColorButton {
                id: cfg_popupColorNormal
                Kirigami.FormData.label: "Normal:"
                color: plasmoid.configuration.popupColorNormal
                onAccepted: { plasmoid.configuration.popupColorNormal = color.toString(); saveConfigJson() }
            }
            KQuickControls.ColorButton {
                id: cfg_popupColorWarning
                Kirigami.FormData.label: "Warning:"
                color: plasmoid.configuration.popupColorWarning
                onAccepted: { plasmoid.configuration.popupColorWarning = color.toString(); saveConfigJson() }
            }
            KQuickControls.ColorButton {
                id: cfg_popupColorCritical
                Kirigami.FormData.label: "Critical:"
                color: plasmoid.configuration.popupColorCritical
                onAccepted: { plasmoid.configuration.popupColorCritical = color.toString(); saveConfigJson() }
            }
        }

        // ── Thresholds ────────────────────────────────────────────────────────
        Kirigami.FormLayout {
            Layout.fillWidth: true
            Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Thresholds" }

            QQC2.SpinBox {
                id: cfg_thresholdWarning
                Kirigami.FormData.label: "Warning (%):"
                from: 1; to: 499
                value: plasmoid.configuration.thresholdWarning
                onValueModified: {
                    if (value >= cfg_thresholdCritical.value)
                        cfg_thresholdCritical.value = value + 1
                    plasmoid.configuration.thresholdWarning = value
                    saveConfigJson()
                }
            }
            QQC2.SpinBox {
                id: cfg_thresholdCritical
                Kirigami.FormData.label: "Critical (%):"
                from: 2; to: 500
                value: plasmoid.configuration.thresholdCritical
                onValueModified: {
                    if (value <= cfg_thresholdWarning.value)
                        cfg_thresholdWarning.value = value - 1
                    plasmoid.configuration.thresholdCritical = value
                    saveConfigJson()
                }
            }
        }

        // ── Font ──────────────────────────────────────────────────────────────
        Kirigami.FormLayout {
            Layout.fillWidth: true
            Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Popup Font" }

            RowLayout {
                Kirigami.FormData.label: "Font family:"
                QQC2.Button {
                    id: fontBtn
                    text: plasmoid.configuration.popupFontFamily || "monospace"
                    onClicked: fontDialog.open()
                }
                FontDialog {
                    id: fontDialog
                    title: "Choose popup font family"
                    onAccepted: {
                        plasmoid.configuration.popupFontFamily = selectedFont.family
                        fontBtn.text = selectedFont.family
                        saveConfigJson()
                    }
                }
            }
        }

        // ── Sizes ─────────────────────────────────────────────────────────────
        Kirigami.FormLayout {
            Layout.fillWidth: true
            Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Sizes" }

            QQC2.SpinBox {
                Kirigami.FormData.label: "Panel icon (px):"
                from: 8; to: 64
                value: plasmoid.configuration.panelIconSize
                onValueModified: plasmoid.configuration.panelIconSize = value
            }
            QQC2.SpinBox {
                Kirigami.FormData.label: "Panel font (px):"
                from: 6; to: 48
                value: plasmoid.configuration.panelFontSize
                onValueModified: plasmoid.configuration.panelFontSize = value
            }
            QQC2.SpinBox {
                Kirigami.FormData.label: "Popup font (px):"
                from: 6; to: 48
                value: plasmoid.configuration.popupFontSize
                onValueModified: plasmoid.configuration.popupFontSize = value
            }
            QQC2.SpinBox {
                Kirigami.FormData.label: "Bar segments:"
                from: 4; to: 40
                value: plasmoid.configuration.barWidth
                onValueModified: plasmoid.configuration.barWidth = value
            }
        }

        // ── Panel Colors ──────────────────────────────────────────────────────
        Kirigami.FormLayout {
            Layout.fillWidth: true
            Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Panel Label Colors" }

            KQuickControls.ColorButton {
                Kirigami.FormData.label: "Normal:"
                color: plasmoid.configuration.panelColorNormal
                onAccepted: plasmoid.configuration.panelColorNormal = color.toString()
            }
            KQuickControls.ColorButton {
                Kirigami.FormData.label: "Warning:"
                color: plasmoid.configuration.panelColorWarning
                onAccepted: plasmoid.configuration.panelColorWarning = color.toString()
            }
            KQuickControls.ColorButton {
                Kirigami.FormData.label: "Critical:"
                color: plasmoid.configuration.panelColorCritical
                onAccepted: plasmoid.configuration.panelColorCritical = color.toString()
            }
        }
    }
}
