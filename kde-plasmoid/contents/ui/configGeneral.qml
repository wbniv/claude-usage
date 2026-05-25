import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    id: page

    // The Plasma config system binds these cfg_<EntryName> properties to the
    // matching KConfigXT entries in config/main.xml (generated from the gschema).
    property alias cfg_thresholdWarning: warnSpin.value
    property alias cfg_thresholdCritical: critSpin.value
    property alias cfg_barWidth: barSpin.value
    property alias cfg_panelFontSize: panelFontSpin.value
    property alias cfg_popupFontSize: popupFontSpin.value
    property alias cfg_panelIconSize: panelIconSpin.value
    property alias cfg_panelLabelSpacing: spacingSpin.value
    property alias cfg_popupFontFamily: fontFamilyField.text
    property alias cfg_weeklyColorGreen: greenField.text
    property alias cfg_weeklyColorAmber: amberField.text
    property alias cfg_weeklyColorRed: redField.text
    property alias cfg_sonnetColor: sonnetField.text
    property alias cfg_popupColorNormal: popupNormalField.text
    property alias cfg_popupColorWarning: popupWarningField.text
    property alias cfg_popupColorCritical: popupCriticalField.text
    property alias cfg_panelColorNormal: panelNormalField.text
    property alias cfg_panelColorWarning: panelWarningField.text
    property alias cfg_panelColorCritical: panelCriticalField.text

    QQC2.SpinBox {
        id: warnSpin
        Kirigami.FormData.label: "Warning pacing threshold (%):"
        from: 1; to: 500
    }
    QQC2.SpinBox {
        id: critSpin
        Kirigami.FormData.label: "Critical pacing threshold (%):"
        from: 1; to: 500
    }

    Item { Kirigami.FormData.isSection: true }

    RowLayout {
        Kirigami.FormData.label: "Ring — under warning:"
        QQC2.TextField { id: greenField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(greenField.text) ? greenField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Ring — at warning:"
        QQC2.TextField { id: amberField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(amberField.text) ? amberField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Ring — at critical:"
        QQC2.TextField { id: redField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(redField.text) ? redField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Sonnet (inner) ring:"
        QQC2.TextField { id: sonnetField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(sonnetField.text) ? sonnetField.text : "transparent" }
    }

    Item { Kirigami.FormData.isSection: true }

    RowLayout {
        Kirigami.FormData.label: "Popup text — normal:"
        QQC2.TextField { id: popupNormalField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(popupNormalField.text) ? popupNormalField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Popup text — warning:"
        QQC2.TextField { id: popupWarningField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(popupWarningField.text) ? popupWarningField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Popup text — critical:"
        QQC2.TextField { id: popupCriticalField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(popupCriticalField.text) ? popupCriticalField.text : "transparent" }
    }

    Item { Kirigami.FormData.isSection: true }

    RowLayout {
        Kirigami.FormData.label: "Panel label — normal:"
        QQC2.TextField { id: panelNormalField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(panelNormalField.text) ? panelNormalField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Panel label — warning:"
        QQC2.TextField { id: panelWarningField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(panelWarningField.text) ? panelWarningField.text : "transparent" }
    }
    RowLayout {
        Kirigami.FormData.label: "Panel label — critical:"
        QQC2.TextField { id: panelCriticalField; inputMask: "\\#HHHHHH"; implicitWidth: Kirigami.Units.gridUnit * 6 }
        Rectangle { implicitWidth: Kirigami.Units.gridUnit; implicitHeight: Kirigami.Units.gridUnit
                    radius: 2; border.width: 1; border.color: Kirigami.Theme.disabledTextColor
                    color: /^#[0-9a-fA-F]{6}$/.test(panelCriticalField.text) ? panelCriticalField.text : "transparent" }
    }

    Item { Kirigami.FormData.isSection: true }

    QQC2.SpinBox { id: barSpin; Kirigami.FormData.label: "Usage bar width (chars):"; from: 1; to: 20 }
    QQC2.SpinBox { id: panelFontSpin; Kirigami.FormData.label: "Panel font size (px):"; from: 8; to: 20 }
    QQC2.SpinBox { id: popupFontSpin; Kirigami.FormData.label: "Popup font size (px):"; from: 8; to: 20 }
    QQC2.SpinBox { id: panelIconSpin; Kirigami.FormData.label: "Panel icon size (px):"; from: 8; to: 32 }
    QQC2.SpinBox { id: spacingSpin; Kirigami.FormData.label: "Icon-label gap (px):"; from: 0; to: 20 }
    QQC2.TextField { id: fontFamilyField; Kirigami.FormData.label: "Popup font family:"; implicitWidth: Kirigami.Units.gridUnit * 8 }
}
