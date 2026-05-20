// AUTO-GENERATED from gnome-extension/schemas/org.gnome.shell.extensions.claude-usage.gschema.xml
// DO NOT HAND-EDIT — regenerate with `task gen-js-defaults`.
//
// JS-1 (pass-18, option b chosen post-pass-21): extension.js's `safeColor`
// fallbacks needed a single-source-of-truth check against the gschema
// without copy-paste drift. Python consumers read schema_defaults.py;
// JS consumers read this file. CI runs lint-js-defaults to assert both
// stay synced to the schema XML.


export const DEFAULTS = Object.freeze({
    bar_width: 10,
    panel_color_critical: "#e03030",
    panel_color_normal: "#ffffff",
    panel_color_warning: "#d07000",
    panel_font_size: 11,
    panel_icon_size: 16,
    panel_label_spacing: 6,
    panel_metric: "",
    popup_color_critical: "#e03030",
    popup_color_normal: "#2a9a2a",
    popup_color_warning: "#d07000",
    popup_font_family: "monospace",
    popup_font_size: 10,
    sonnet_color: "#4dbfff",
    threshold_critical: 90,
    threshold_warning: 70,
    weekly_color_amber: "#ffe033",
    weekly_color_green: "#8cff8c",
    weekly_color_red: "#ff5933",
});
