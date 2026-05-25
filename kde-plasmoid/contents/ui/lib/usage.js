// Shared usage math for the KDE plasmoid — a faithful port of the parity'd
// helpers in gnome-extension/extension.js (pacingPct, elapsedFraction,
// pacingSegments, colorFor, formatReset, bar, tier derivation, meter
// selection). Kept in sync BY HAND with extension.js / generate-icon.py /
// tooltip.py; the lint-kde-parity check in scripts/lint-scraper-parity.py
// asserts pacingPct, elapsedFraction, pacingSegments, bar, and fmtAge match
// extension.js's literals.
//
// .pragma library: stateless, evaluated once, shared across importers. Only
// pure functions live here — no QML types, no plasmoid.configuration reads.
// Callers pass a `cfg` object {tWarn,tCrit,popupNorm,popupWarn,popupCrit,...}.
.pragma library

// QColor (from KConfigXT Color entries) or a plain "#rrggbb" string -> "#rrggbb".
// QML exposes a color's channels as 0..1 floats; build the hex ourselves so we
// never depend on QColor.toString()'s "#aarrggbb"-when-alpha quirk.
function toHex(c) {
    if (c === undefined || c === null) return "#000000";
    if (typeof c === "string") return c;
    var to2 = function (x) {
        var h = Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16);
        return h.length < 2 ? "0" + h : h;
    };
    return "#" + to2(c.r) + to2(c.g) + to2(c.b);
}

// pacing_pct = pct / fraction_elapsed — uncapped. 100 = on pace, > 100 = over.
// Falls back to raw pct when reset_minutes/period unknown or too few minutes
// have elapsed. Used only for COLOR decisions; displayed numbers stay raw.
// Kept in sync by hand with extension.js:pacingPct / generate-icon.py:pacing_pct.
function pacingPct(meter, periodLens) {
    if (!meter) return 0;
    var pct = meter.pct;
    if (typeof pct !== "number" || pct === 0) return pct || 0;
    var rm = meter.reset_minutes;
    var period = periodLens ? periodLens[meter.label] : undefined;
    if (rm === null || rm === undefined || !period) return pct;
    var elapsed = period - rm;
    // Floor = max(15 min, 5% of period). WP-1 (pass-16 §6): flat 15-min was
    // right for the 5h session bucket but for 7d weekly buckets meant any
    // usage > ~0.14% in the first 16 min paced > critical.
    if (elapsed < Math.max(15, period * 0.05)) return pct;
    return pct / (elapsed / period);
}

function elapsedFraction(meter, periodLens) {
    if (!meter) return null;
    var rm = meter.reset_minutes;
    var period = periodLens ? periodLens[meter.label] : undefined;
    if (rm === null || rm === undefined || !period) return null;
    var elapsed = period - rm;
    if (elapsed < Math.max(15, period * 0.05)) return null;
    return elapsed / period;
}

// PVS-1 (pass-26): decide over-pace on raw fractions BEFORE rounding.
function pacingSegments(pct, elapsedFrac, width) {
    pct = Math.max(0, Math.min(100, pct || 0));
    var fillFrac = pct / 100;
    var overPaceRaw = elapsedFrac !== null && elapsedFrac !== undefined && fillFrac > elapsedFrac;
    var fill = Math.round(fillFrac * width);
    var elapsedPos = (elapsedFrac !== null && elapsedFrac !== undefined)
        ? Math.min(Math.round(elapsedFrac * width), width)
        : null;
    var segs = [];
    for (var i = 0; i < width; i++) {
        if (i < fill) {
            var overHere = overPaceRaw &&
                (elapsedPos === null || fill === elapsedPos || i >= elapsedPos);
            segs.push({ c: "█", role: overHere ? "over_pace" : "on_pace" });
        } else {
            if (!overPaceRaw && elapsedPos !== null && i === elapsedPos && fill <= elapsedPos) {
                segs.push({ c: "┊", role: "tick" });
            } else {
                segs.push({ c: "░", role: "empty" });
            }
        }
    }
    return segs;
}

function colorFor(role, pacing, cfg) {
    if (role === "on_pace") return cfg.popupNorm;
    if (role === "over_pace") return pacing >= cfg.tCrit ? cfg.popupCrit : cfg.popupWarn;
    if (role === "tick") return "#888888";
    if (pacing >= cfg.tCrit) return cfg.popupCrit;
    if (pacing >= cfg.tWarn) return cfg.popupWarn;
    return cfg.popupNorm;
}

function bar(pct, width) {
    if (width === undefined) width = 10;
    var filled = Math.max(0, Math.min(width, Math.round((pct / 100) * width)));
    return repeat("█", filled) + repeat("░", width - filled);
}

function repeat(s, n) {
    var out = "";
    for (var i = 0; i < n; i++) out += s;
    return out;
}

function fmtAge(min) {
    if (min < 60) return min + " min";
    var h = Math.floor(min / 60);
    var m = min % 60;
    return m > 0 ? (h + " h " + m + " min") : (h + " h");
}

// Port of extension.js:formatReset — collapses "Resets in 3 hr 47 min" to a
// "⏱h:mm" countdown, and "Resets Tue 5:00 PM" to a countdown when < 12h
// away or a "Tue 17:00" day/time otherwise.
function formatReset(reset) {
    if (!reset || typeof reset !== "string") return "";
    var m;
    m = reset.match(/[Rr]esets? in (\d+) hr (\d+) min/);
    if (m) return "resets in ⏱" + m[1] + ":" + pad2(m[2]);
    m = reset.match(/[Rr]esets? in (\d+) min/);
    if (m) return "resets in ⏱0:" + pad2(m[1]);
    m = reset.match(/[Rr]esets? (\w{3}) (\d+):(\d+) (AM|PM)/);
    if (m) {
        var day = m[1], h = parseInt(m[2], 10), mn = parseInt(m[3], 10), ap = m[4];
        if (ap === "PM" && h !== 12) h += 12;
        else if (ap === "AM" && h === 12) h = 0;
        var now = new Date();
        var wdMap = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
        if (!(day in wdMap)) return reset;
        var ahead = (wdMap[day] - now.getDay() + 7) % 7;
        if (ahead === 0) {
            var candidate = new Date(now);
            candidate.setHours(h, mn, 0, 0);
            if (candidate <= now) ahead = 7;
        }
        var target = new Date(now);
        target.setDate(now.getDate() + ahead);
        target.setHours(h, mn, 0, 0);
        var mins = Math.floor((target - now) / 60000);
        if (mins < 12 * 60)
            return "resets in ⏱" + Math.floor(mins / 60) + ":" + pad2(mins % 60);
        return "resets " + day + " " + pad2(h) + ":" + pad2(mn);
    }
    return reset;
}

function pad2(v) {
    var s = "" + v;
    return s.length < 2 ? "0" + s : s;
}

function isEligible(m) {
    return m.pct !== undefined ||
        (m.count !== undefined && m.total !== undefined && m.total > 0);
}

// Layers the Sonnet-0% popup-hide rule on top of structural eligibility.
function isSelectable(m) {
    if (m.label && m.label.toLowerCase().indexOf("sonnet") !== -1 && (m.pct || 0) === 0)
        return false;
    return isEligible(m);
}

function isSonnetHidden(m) {
    return m.label && m.label.toLowerCase().indexOf("sonnet") !== -1 && (m.pct || 0) === 0;
}

function visibleMeters(meters) {
    return (meters || []).filter(function (m) { return !isSonnetHidden(m); });
}

// Returns the primary meter for the panel. `panelMetric` is the saved label
// ("" = auto). Unlike extension.js this has NO side effect — the QML layer
// clears a stale panelMetric config value itself.
function getPrimary(meters, panelMetric) {
    if (!meters || meters.length === 0) return null;
    if (panelMetric) {
        for (var i = 0; i < meters.length; i++)
            if (meters[i].label === panelMetric && isSelectable(meters[i])) return meters[i];
    }
    for (var j = 0; j < meters.length; j++)
        if (/all/i.test(meters[j].label || "") && isSelectable(meters[j])) return meters[j];
    for (var k = 0; k < meters.length; k++)
        if (isSelectable(meters[k])) return meters[k];
    return meters[0];
}

// Merge of extension.js's time-based tier and generate-icon.py:derive_tier's
// cache-based signals. Returns {tier, reason}.
//   broken — Anthropic outage, OR scrape-fail >= 2, OR age > 20 min
//   stale  — age > 15 min
//   normal — otherwise
function deriveTier(data) {
    if (!data) return { tier: "normal", reason: null };
    var astat = data._anthropic_status || {};
    var sfc = data._scrape_fail_count || 0;
    var age = (typeof data._timestamp === "number")
        ? Math.round((Date.now() / 1000 - data._timestamp) / 60) : null;
    var indicator = astat.indicator || "none";
    var component = astat.claude_ai_component_status || "operational";
    if (indicator !== "none")
        return { tier: "broken", reason: "⚠ Anthropic reports: " + (astat.description || indicator) };
    if (component !== "operational")
        return { tier: "broken", reason: "⚠ claude.ai status: " + component };
    if (typeof sfc === "number" && sfc >= 2)
        return { tier: "broken", reason: "⚠ " + sfc + " scrape attempts failed · run claude-usage-status" };
    if (age !== null && age > 20)
        return { tier: "broken", reason: "⚠ No data in " + fmtAge(age) + " · run claude-usage-status" };
    if (age !== null && age > 15)
        return { tier: "stale", reason: "🕐 No update in " + fmtAge(age) };
    return { tier: "normal", reason: null };
}

// Tooltip text — port of tooltip.py:format_tooltip (the "current | all | sonnet"
// one-liner). Returns "" when no recognisable meters.
function tooltipSummary(meters) {
    var find = function (kw) {
        return (meters || []).filter(function (m) {
            return (m.label || "").toLowerCase().indexOf(kw) !== -1;
        })[0];
    };
    var current = find("session") || find("current");
    var allM = find("all");
    var sonnet = find("sonnet");
    var parts = [];
    var rows = [["current", current], ["all", allM], ["sonnet", sonnet]];
    for (var i = 0; i < rows.length; i++) {
        var key = rows[i][0], meter = rows[i][1];
        if (!meter) continue;
        var pct = meter.pct || 0;
        if (key === "sonnet" && pct === 0) continue;
        var part = key + " " + pct + "%";
        var r = formatReset(meter.reset);
        if (r) part += "  " + r;
        parts.push(part);
    }
    return parts.join("   |   ");
}
