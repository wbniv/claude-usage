// usage-api.js — map the claude.ai usage API response to the meters[] shape the
// local server + desktop consumers already expect, so switching the extension
// from DOM-scraping to the JSON API (GET /api/organizations/{org}/usage) needs
// no downstream changes.
//
// Loaded into the extension background as a CLASSIC script (Firefox:
// background.scripts; Chrome SW: importScripts) — its top-level functions become
// globals that background.js calls. Tested via vm (see test/usage-api.test.js),
// so there's no ES-module export and no scraper.js-style inline duplication.
//
// API buckets -> the exact label STRING consumers match on (case-insensitive
// substring: "session"/"current", "all", "opus", "sonnet"):
var USAGE_BUCKETS = [
  { key: 'five_hour',        label: 'Current session' },
  { key: 'seven_day',        label: 'All models' },
  { key: 'seven_day_opus',   label: 'Opus' },
  { key: 'seven_day_sonnet', label: 'Sonnet only' },
];

var _RESET_DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
var RESET_CAP_MIN = 60 * 24 * 31;  // 31 days — matches the server's reset_minutes bound

function _clampPct(u) {
  var n = Math.round(Number(u));
  if (!isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

// reset_minutes (minutes-from-now) from an ISO `resets_at`, clamped like the
// scraper/server. nowMs is injected for testability.
function resetMinutesFrom(resetsAtIso, nowMs) {
  if (!resetsAtIso) return null;
  var t = Date.parse(resetsAtIso);
  if (isNaN(t)) return null;
  var mins = Math.round((t - nowMs) / 60000);
  return Math.max(0, Math.min(RESET_CAP_MIN, mins));
}

// Human reset string replicating the DOM-scraper's formats so tooltip.py and
// extension.js render identically:
//   < 60 min  -> "Resets in M min"
//   < 24 h    -> "Resets in H hr M min"
//   otherwise -> "Resets {Day} {h}:{mm} {AM/PM}" in LOCAL time
function formatReset(resetMinutes, resetsAtIso, nowMs) {
  if (resetMinutes == null) return null;
  if (resetMinutes < 24 * 60) {
    if (resetMinutes < 60) return 'Resets in ' + resetMinutes + ' min';
    return 'Resets in ' + Math.floor(resetMinutes / 60) + ' hr ' + (resetMinutes % 60) + ' min';
  }
  var d = new Date(Date.parse(resetsAtIso));
  var hr = d.getHours();
  var ampm = hr >= 12 ? 'PM' : 'AM';
  var h12 = hr % 12;
  if (h12 === 0) h12 = 12;
  var mm = String(d.getMinutes()).padStart(2, '0');
  return 'Resets ' + _RESET_DAYS[d.getDay()] + ' ' + h12 + ':' + mm + ' ' + ampm;
}

// Map the usage API JSON -> meters[]. Null/absent buckets are skipped; the
// extra-usage bucket is mapped only when enabled. Returns [] on a bad shape so
// the caller treats it like an empty scrape (server records the failure).
function mapUsageResponse(api, nowMs) {
  if (!api || typeof api !== 'object') return [];
  var meters = [];
  for (var i = 0; i < USAGE_BUCKETS.length; i++) {
    var b = api[USAGE_BUCKETS[i].key];
    if (!b || b.utilization == null) continue;
    var rm = resetMinutesFrom(b.resets_at, nowMs);
    meters.push({
      pct: _clampPct(b.utilization),
      label: USAGE_BUCKETS[i].label,
      reset: formatReset(rm, b.resets_at, nowMs),
      reset_minutes: rm,
    });
  }
  // Extra usage (pay-as-you-go credits). Field shapes are best-effort until a
  // live capture with extra_usage enabled confirms units/format.
  var ex = api.extra_usage;
  if (ex && ex.is_enabled) {
    meters.push({
      label: 'Extra usage',
      pct: ex.utilization != null ? _clampPct(ex.utilization) : 0,
      reset: null,
      reset_minutes: null,
      spent: ex.used_credits != null ? ('$' + ex.used_credits) : null,
      balance: ex.monthly_limit != null ? ('$' + ex.monthly_limit) : null,
    });
  }
  return meters;
}
