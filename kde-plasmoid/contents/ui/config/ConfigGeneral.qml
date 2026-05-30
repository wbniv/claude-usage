// Plasma 6 config page. Uses the cfg_<key> auto-binding convention (the
// framework loads/saves cfg_<key> ↔ KConfig from main.xml on OK/Apply/Defaults);
// the cfg_ property names MUST match the <entry name> values in
// contents/config/main.xml exactly.
//
// NB: do NOT access `plasmoid.configuration` here — in Plasma 6 the config page
// has no lowercase `plasmoid` context, so that throws at load and Plasma
// silently drops the page (showing only Keyboard Shortcuts + About). The
// dock-icon side-effect (writing ~/.config/claude-usage/config.json for
// generate-icon.py) lives in main.qml, which watches Plasmoid.configuration.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

KCM.SimpleKCM {
    id: root

    // Dock icon ring colours
    property alias cfg_weeklyColorGreen: weeklyGreen.colorString
    property alias cfg_weeklyColorAmber: weeklyAmber.colorString
    property alias cfg_weeklyColorRed: weeklyRed.colorString
    property alias cfg_sonnetColor: sonnetColor.colorString
    // Popup meter colours
    property alias cfg_popupColorNormal: popupNormal.colorString
    property alias cfg_popupColorWarning: popupWarning.colorString
    property alias cfg_popupColorCritical: popupCritical.colorString
    // Panel label colours
    property alias cfg_panelColorNormal: panelNormal.colorString
    property alias cfg_panelColorWarning: panelWarning.colorString
    property alias cfg_panelColorCritical: panelCritical.colorString
    // Thresholds
    property alias cfg_thresholdWarning: warningSpin.value
    property alias cfg_thresholdCritical: criticalSpin.value
    // Popup font family
    property alias cfg_popupFontFamily: fontCombo.editText
    // Sizes
    property alias cfg_barWidth: barSpin.value
    property alias cfg_panelFontSize: panelFontSpin.value
    property alias cfg_popupFontSize: popupFontSpin.value
    property alias cfg_panelIconSize: panelIconSpin.value

    Kirigami.FormLayout {

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Dock Icon Colors" }
        ColorField { id: weeklyGreen;  Kirigami.FormData.label: "Weekly — low:" }
        ColorField { id: weeklyAmber;  Kirigami.FormData.label: "Weekly — mid:" }
        ColorField { id: weeklyRed;    Kirigami.FormData.label: "Weekly — high:" }
        ColorField { id: sonnetColor;  Kirigami.FormData.label: "Sonnet ring:" }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Popup Colors" }
        ColorField { id: popupNormal;   Kirigami.FormData.label: "Normal:" }
        ColorField { id: popupWarning;  Kirigami.FormData.label: "Warning:" }
        ColorField { id: popupCritical; Kirigami.FormData.label: "Critical:" }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Panel Label Colors" }
        ColorField { id: panelNormal;   Kirigami.FormData.label: "Normal:" }
        ColorField { id: panelWarning;  Kirigami.FormData.label: "Warning:" }
        ColorField { id: panelCritical; Kirigami.FormData.label: "Critical:" }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Thresholds" }
        QQC2.SpinBox {
            id: warningSpin
            Kirigami.FormData.label: "Warning (%):"
            from: 1; to: 499
            onValueModified: if (value >= criticalSpin.value) criticalSpin.value = value + 1
        }
        QQC2.SpinBox {
            id: criticalSpin
            Kirigami.FormData.label: "Critical (%):"
            from: 2; to: 500
            onValueModified: if (value <= warningSpin.value) warningSpin.value = value - 1
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Popup Font" }
        QQC2.ComboBox {
            id: fontCombo
            Kirigami.FormData.label: "Font family:"
            editable: true
            model: Qt.fontFamilies()
            // Reflect the loaded cfg value in the dropdown selection too.
            Component.onCompleted: { var i = find(editText); if (i >= 0) currentIndex = i }
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true; Kirigami.FormData.label: "Sizes" }
        QQC2.SpinBox { id: panelIconSpin; Kirigami.FormData.label: "Panel icon (px):"; from: 8; to: 64 }
        QQC2.SpinBox { id: panelFontSpin; Kirigami.FormData.label: "Panel font (px):"; from: 6; to: 48 }
        QQC2.SpinBox { id: popupFontSpin; Kirigami.FormData.label: "Popup font (px):"; from: 6; to: 48 }
        QQC2.SpinBox { id: barSpin;       Kirigami.FormData.label: "Bar segments:";    from: 4; to: 40 }
    }
}
