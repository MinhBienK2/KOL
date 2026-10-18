/* KOL Pipeline Supervisor - dependency-free dashboard frontend.
 * Consumes the frozen dashboard API:
 *   GET /api/health
 *   GET /api/runs
 *   GET /api/runs/{run_id}                     (view model)
 *   GET /api/runs/{run_id}/events?since=&limit=
 *   GET /api/runs/{run_id}/stream?since=       (SSE)
 *   GET /api/runs/{run_id}/file?path=
 *   GET /api/runs/{run_id}/artifact?name=
 * run_id contains "/" so the raw value is used as a path segment; only query
 * values are percent-encoded.
 */
(function () {
  "use strict";

  var TOTAL_STAGES = 8;
  var STAGE_TITLES = {
    1: "Competitor Research & Strategic Creative Briefing",
    2: "Multi-Archetype High-Conversion Scriptwriting",
    3: "DramaClaw Spatial Storyboard & OpenMontage Slideshow Risk Gate",
    4: "KOL Identity Locking & Clean Keyframe Staging",
    5: "Genuine Video Diffusion Generation (Hailuo-2.3)",
    6: "Neural TTS Audio & Lip-Sync Alignment",
    7: "Final FFmpeg Multi-Track Composition & Audio Ducking",
    8: "Independent Quality Verification Gates & Packaging"
  };
  var STAGE_KEYS = {
    1: "research_briefing", 2: "scriptwriting", 3: "storyboard_staging", 4: "identity_keyframes",
    5: "video_diffusion", 6: "audio_lip_sync", 7: "composition", 8: "verification_publish"
  };
  var STAGE_SHORT = {
    1: "Research", 2: "Script", 3: "Storyboard", 4: "Keyframes",
    5: "Video", 6: "Audio", 7: "Compose", 8: "Verify"
  };
  var ARTIFACT_FILES = [
    ["brief.json", "brief"], ["competitor_research.json", "research"],
    ["creative_concept.json", "concept"], ["script.json", "script"],
    ["scene_plan.json", "scene_plan"], ["asset_manifest.json", "asset_manifest"],
    ["edit_decisions.json", "edit_decisions"], ["render_report.json", "render_report"],
    ["publish_log.json", "publish_log"]
  ];
  var CHANGE_TYPES = {
    run_start: 1, run_complete: 1, run_failed: 1, stage_start: 1, stage_progress: 1,
    stage_message: 1, stage_complete: 1, stage_failed: 1, stage_skipped: 1,
    artifact: 1, prompt: 1, api_call: 1, note: 1
  };
  var MAX_BUFFERED_EVENTS = 5000;
  var MAX_FEED_ROWS = 600;

  var state = {
    runId: null,
    runs: [],
    view: null,
    health: null,
    banner: null,
    filter: "",
    feedLevel: "all",
    autoscroll: true,
    tab: "all",
    events: [],
    lastSeq: 0,
    seen: {},
    live: null,
    promptIndex: {},
    apiCache: { runId: null, events: null },
    es: null,
    esRunId: null,
    streamStarted: false,
    reconnectTimer: null,
    refreshTimer: null,
    pollTimer: null,
    runTimer: null,
    runListError: null
  };

  /* ------------------------------------------------------------------ utils */

  function $(id) { return document.getElementById(id); }

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function txt(value) {
    if (value === null || value === undefined || value === "") return "--";
    return esc(value);
  }

  function isObj(v) { return !!v && typeof v === "object" && !Array.isArray(v); }
  function asList(v) { if (!v) return []; return Array.isArray(v) ? v : [v]; }

  function fmtAny(v) {
    if (v === null || v === undefined || v === "") return "--";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function fmtTime(iso) {
    if (!iso) return "--";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    var now = new Date();
    var prefix = d.toDateString() === now.toDateString() ? "" : (pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) + " ");
    return prefix + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
  }

  function fmtDur(sec) {
    if (sec === null || sec === undefined || sec === "" || isNaN(Number(sec))) return "--";
    var s = Number(sec);
    if (s < 0) s = 0;
    if (s < 60) return (s < 10 ? s.toFixed(1) : s.toFixed(0)) + "s";
    var m = Math.floor(s / 60), r = Math.round(s % 60);
    if (m < 60) return m + "m " + pad2(r) + "s";
    return Math.floor(m / 60) + "h " + pad2(m % 60) + "m";
  }

  function fmtBytes(b) {
    if (b === null || b === undefined || b === "" || isNaN(Number(b))) return "--";
    var n = Number(b), units = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i === 0 ? n.toFixed(0) : n.toFixed(n < 10 ? 1 : 0)) + " " + units[i];
  }

  function fmtPct(p) {
    if (p === null || p === undefined || p === "" || isNaN(Number(p))) return "--";
    var n = Number(p);
    return (n > 0 && n < 1 ? n.toFixed(1) : String(Math.round(n))) + "%";
  }

  function tc(sec) {
    var s = Math.max(0, Number(sec) || 0);
    return Math.floor(s / 60) + ":" + pad2(Math.floor(s % 60)) + "." + Math.floor((s % 1) * 10);
  }

  function basename(p) {
    if (!p) return "";
    var parts = String(p).split(/[\\/]/);
    return parts[parts.length - 1] || String(p);
  }

  function kindOf(p) {
    var m = String(p || "").toLowerCase().match(/\.([a-z0-9]+)(?:[?#]|$)/);
    var e = m ? m[1] : "";
    if (e === "json") return "json";
    if (e === "mp4" || e === "mov" || e === "webm" || e === "mkv" || e === "avi") return "video";
    if (e === "jpg" || e === "jpeg" || e === "png" || e === "webp" || e === "bmp") return "image";
    if (e === "wav" || e === "mp3" || e === "m4a" || e === "aac" || e === "flac" || e === "ogg") return "audio";
    if (e === "txt" || e === "srt" || e === "log" || e === "csv" || e === "md") return "text";
    return "file";
  }

  function statusClass(s) {
    s = String(s || "unknown").toLowerCase();
    if (s === "running") return "s-running";
    if (s === "completed" || s === "complete" || s === "ok" || s === "passed") return "s-completed";
    if (s === "failed" || s === "error") return "s-failed";
    if (s === "skipped") return "s-skipped";
    if (s === "pending") return "s-pending";
    return "s-unknown";
  }

  function badge(text, cls) { return '<span class="badge ' + esc(cls || "s-unknown") + '">' + esc(text === null || text === undefined || text === "" ? "unknown" : text) + '</span>'; }
  function statusBadge(s) { return badge(s || "unknown", statusClass(s)); }

  function levelClass(l) {
    l = String(l || "info").toLowerCase();
    if (l === "error" || l === "critical") return "lvl-error";
    if (l === "warning" || l === "warn") return "lvl-warning";
    return "lvl-info";
  }

  function normLevel(l) {
    l = String(l || "info").toLowerCase();
    if (l === "warn" || l === "warning") return "warning";
    if (l === "error" || l === "critical") return "error";
    return "info";
  }

  function stageEq(a, b) { return a === b || String(a) === String(b); }
  function stageMatches(evStage, stage) {
    if (stage === null || stage === undefined) return true;
    if (evStage === null || evStage === undefined) return false;
    return stageEq(evStage, stage);
  }

  /* -------------------------------------------------------------------- api */

  function encQ(v) { return encodeURIComponent(v === null || v === undefined ? "" : String(v)); }

  function runApi(runId, suffix) { return "/api/runs/" + (runId || "") + (suffix || ""); }
  function fileUrl(relPath) { return runApi(state.runId, "/file") + "?path=" + encQ(relPath); }
  function artifactUrl(name, runId) { return runApi(runId || state.runId, "/artifact") + "?name=" + encQ(name); }

  function refOf(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "string") {
      return { label: basename(value), rel_path: value, url: fileUrl(value), kind: kindOf(value), size_bytes: null, exists: null };
    }
    if (typeof value === "object") {
      var out = {}, k;
      for (k in value) if (Object.prototype.hasOwnProperty.call(value, k)) out[k] = value[k];
      if (!out.url && out.rel_path) out.url = fileUrl(out.rel_path);
      if (!out.kind) out.kind = kindOf(out.rel_path || out.label || "");
      if (!out.label) out.label = basename(out.rel_path || "");
      return out;
    }
    return null;
  }

  /* A path that may be absolute or outside the run root: map it onto the run-root
   * relative form the /file endpoint accepts when possible, otherwise keep it as a
   * label (never a broken <img>) with url null. */
  function refFromPath(p) {
    if (!p) return null;
    var s = String(p);
    if (s.charAt(0) !== "/") return refOf(s);
    var root = String(viewRun().root || "");
    if (root && s.indexOf(root + "/") === 0) return refOf(s.slice(root.length + 1));
    var idx = s.lastIndexOf("/output/");
    if (idx >= 0) return refOf("output" + s.slice(idx + 7));
    return { label: basename(s), rel_path: null, url: null, kind: kindOf(s), size_bytes: null, exists: false, abs_path: s };
  }

  function refUrl(ref) {
    if (!ref) return null;
    if (ref.url) return ref.url;
    if (ref.rel_path) return fileUrl(ref.rel_path);
    return null;
  }

  function isServable(ref) {
    if (!ref) return false;
    if (ref.exists === false) return false;
    return !!refUrl(ref);
  }

  function refChip(value, prefix) {
    var r = refOf(value);
    if (!r) return "";
    var label = r.label || basename(r.rel_path || "") || "(unnamed)";
    var text = "[" + (r.kind || kindOf(r.rel_path)) + "] " + label +
      (r.size_bytes !== null && r.size_bytes !== undefined ? "  " + fmtBytes(r.size_bytes) : "");
    if (prefix) text = prefix + " " + text;
    var title = esc(r.rel_path || r.abs_path || label);
    if (!isServable(r)) {
      return '<span class="chip chip-dead" title="' + title + '">' + esc(text) + ' <span class="muted">-- not servable --</span></span>';
    }
    return '<a class="chip kind-' + esc(r.kind || "file") + '" href="' + esc(refUrl(r)) + '" target="_blank" rel="noopener" title="' + title + '">' + esc(text) + '</a>';
  }

  function chiplist(refs, prefix) {
    var list = asList(refs).map(function (r) { return refChip(r, prefix); }).filter(Boolean);
    if (!list.length) return '<div class="muted">--</div>';
    return '<div class="chip-row">' + list.join("") + '</div>';
  }

  function miniChip(value) {
    var r = refOf(value);
    if (!r) return "";
    var label = basename(r.rel_path || r.label || "") || "(file)";
    if (!isServable(r)) {
      return '<span class="chip chip-dead" title="' + esc(r.rel_path || r.abs_path || label) + '">' + esc(label) + '</span>';
    }
    return '<a class="chip" href="' + esc(refUrl(r)) + '" target="_blank" rel="noopener" title="' + esc(r.rel_path || label) +
      '">' + esc(label) + '</a>';
  }

  function miniChips(refs, max) {
    var list = asList(refs);
    if (!list.length) return '<span class="muted">no artifacts</span>';
    var head = list.slice(0, max || 3).map(miniChip).filter(Boolean).join("");
    var rest = list.length - (max || 3);
    return '<span class="chip-row chip-row-mini">' + head + (rest > 0 ? '<span class="chip chip-more">+' + rest + '</span>' : "") + '</span>';
  }

  function fetchJson(url) {
    return fetch(url, { headers: { "Accept": "application/json" }, cache: "no-store" }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status + " " + url);
      return res.json();
    });
  }

  /* ------------------------------------------------------------- html atoms */

  function barHtml(percent, cls) {
    var p = (percent === null || percent === undefined || percent === "" || isNaN(Number(percent))) ? null : Number(percent);
    if (p !== null) p = Math.max(0, Math.min(100, p));
    return '<div class="bar ' + esc(cls || "") + '"><span style="width:' + (p === null ? 0 : p) + '%"></span></div>';
  }

  function progText(progress) {
    if (!isObj(progress)) return "";
    var cur = progress.current, tot = progress.total;
    if (cur === null || cur === undefined) return "";
    var unit = progress.unit ? " " + progress.unit : "";
    return esc(cur + "/" + (tot === null || tot === undefined ? "?" : tot) + unit) +
      (progress.label ? ' <span class="muted">' + esc(progress.label) + '</span>' : "");
  }

  function kvHtml(pairs) {
    var rows = [];
    asList(pairs).forEach(function (p) {
      if (!p) return;
      var v = p[1];
      if (v === null || v === undefined || v === "") return;
      rows.push('<div class="kv-k">' + esc(p[0]) + '</div><div class="kv-v">' + v + '</div>');
    });
    if (!rows.length) return '<div class="muted">--</div>';
    return '<div class="kv">' + rows.join("") + '</div>';
  }

  function listHtml(items, cls) {
    var a = asList(items).filter(function (x) { return x !== null && x !== undefined && x !== ""; });
    if (!a.length) return '<div class="muted">--</div>';
    return '<ul class="list ' + esc(cls || "") + '">' + a.map(function (t) {
      return '<li>' + (typeof t === "string" ? esc(t) : esc(fmtAny(t))) + '</li>';
    }).join("") + '</ul>';
  }

  function tableHtml(headers, rows, cls) {
    if (!rows || !rows.length) return '<div class="muted">--</div>';
    var head = '<tr>' + headers.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join("") + '</tr>';
    var body = rows.map(function (r) {
      return '<tr>' + r.map(function (c) {
        return '<td>' + (c === null || c === undefined || c === "" ? '<span class="muted">--</span>' : c) + '</td>';
      }).join("") + '</tr>';
    }).join("");
    return '<table class="tbl ' + esc(cls || "") + '"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  }

  function jsonHtml(obj, label, open) {
    if (obj === null || obj === undefined) return '<div class="muted">--</div>';
    return '<details class="details"' + (open ? " open" : "") + '><summary>' + esc(label || "json") + '</summary><pre class="json">' +
      esc(JSON.stringify(obj, null, 2)) + '</pre></details>';
  }

  function sec(title, body, extraClass) {
    return '<section class="card ' + esc(extraClass || "") + '"><div class="card-head"><span class="card-title">' + esc(title) +
      '</span></div><div class="card-body">' + body + '</div></section>';
  }

  function mediaHtml(ref, kind) {
    if (kind === "video") return videoHtml(ref);
    if (kind === "audio") return audioHtml(ref);
    if (kind === "image") return imgHtml(ref);
    return "";
  }

  function videoHtml(ref, label, preload) {
    var r = refOf(ref);
    if (!r) return "";
    if (!isServable(r)) return '<div class="muted small">' + esc((label ? label + ": " : "") + (r.label || "") + " -- not servable --") + '</div>';
    return '<figure class="media-fig"><video class="player" controls playsinline preload="' + esc(preload || "none") + '" src="' + esc(refUrl(r)) + '" onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{className:\'muted small\',textContent:\'video unavailable\'}))"></video>' +
      '<figcaption class="small muted">' + esc(label ? label + " - " : "") + esc(r.label || "") +
      (r.size_bytes ? " - " + fmtBytes(r.size_bytes) : "") + '</figcaption></figure>';
  }

  function audioHtml(ref, label) {
    var r = refOf(ref);
    if (!r) return "";
    if (!isServable(r)) return '<div class="muted small">' + esc((label ? label + ": " : "") + (r.label || "") + " -- not servable --") + '</div>';
    return '<figure class="media-fig"><audio class="player audio" controls preload="none" src="' + esc(refUrl(r)) + '" onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{className:\'muted small\',textContent:\'audio unavailable\'}))"></audio>' +
      '<figcaption class="small muted">' + esc(label ? label + " - " : "") + esc(r.label || "") +
      (r.size_bytes ? " - " + fmtBytes(r.size_bytes) : "") + '</figcaption></figure>';
  }

  function imgHtml(ref, label) {
    var r = refOf(ref);
    if (!r) return "";
    if (!isServable(r)) {
      return '<figure class="media-fig"><div class="img-missing small muted">' + esc(r.label || label || "image") + '<br>-- not servable --</div>' +
        '<figcaption class="small muted">' + esc(label || r.label || "") + '</figcaption></figure>';
    }
    return '<figure class="media-fig"><a href="' + esc(refUrl(r)) + '" target="_blank" rel="noopener"><img class="thumb" loading="lazy" alt="' +
      esc(label || r.label || "image") + '" src="' + esc(refUrl(r)) + '" onerror="this.classList.add(\'img-error\');this.alt=\'image unavailable\';this.removeAttribute(\'src\')"></a>' +
      '<figcaption class="small muted">' + esc(label || r.label || "") + '</figcaption></figure>';
  }

  function promptBlock(text, id, title) {
    if (!text) return '<div class="muted">-- no prompt recorded --</div>';
    var head = '<div class="prompt-head"><span class="small muted">' + esc(title || "exact generation prompt") + '</span>' +
      '<span class="prompt-actions">' +
      '<button class="btn small" type="button" data-copy-prompt="' + esc(id) + '">copy</button>' +
      '<button class="btn small" type="button" data-open-prompt="' + esc(id) + '">open</button>' +
      '</span></div>';
    return head + '<pre class="prompt" data-prompt-id="' + esc(id) + '">' + esc(text) + '</pre>';
  }

  function segmentsHtml(segments) {
    var a = asList(segments).filter(function (s) { return isObj(s); });
    if (!a.length) return "";
    return '<div class="segments">' + a.map(function (s) {
      return '<div class="segment"><span class="seg-label">' + esc(s.label || "segment") + '</span>' +
        '<span class="seg-text">' + esc(s.text || "") + '</span></div>';
    }).join("") + '</div>';
  }

  /* --------------------------------------------------------------- api calls */

  function apiRows(stage) {
    var rows = [], seen = {};
    function add(record) {
      if (!isObj(record)) return;
      var r = {};
      for (var k in record) if (Object.prototype.hasOwnProperty.call(record, k)) r[k] = record[k];
      var key = [r.name, r.ts, r.endpoint, r.status, r.shot_id].join("|");
      if (seen[key]) {
        var ex = seen[key];
        if (!ex.request && r.request) ex.request = r.request;
        if (!ex.response && r.response) ex.response = r.response;
        if (!ex.duration_seconds && r.duration_seconds) ex.duration_seconds = r.duration_seconds;
        return;
      }
      seen[key] = r;
      rows.push(r);
    }
    asList(state.events).forEach(function (ev) {
      if (ev && ev.type === "api_call" && stageMatches(ev.stage, stage)) {
        var payload = isObj(ev.payload) ? ev.payload : {};
        var merged = { ts: ev.ts, text: ev.text };
        for (var k in payload) if (Object.prototype.hasOwnProperty.call(payload, k)) merged[k] = payload[k];
        add(merged);
      }
    });
    var v = state.view || {};
    asList(v.api_calls).forEach(function (c) { if (stageMatches(c && c.stage, stage)) add(c); });
    asList(v.prompts).forEach(function (p) {
      if (!p) return;
      if (!(stage === null || stage === undefined || !p.stage || stageEq(p.stage, stage))) return;
      asList(p.api_calls).forEach(function (c) {
        if (!isObj(c)) return;
        var merged = {};
        for (var k in c) if (Object.prototype.hasOwnProperty.call(c, k)) merged[k] = c[k];
        if (merged.stage === undefined || merged.stage === null) merged.stage = p.stage;
        if (merged.shot_id === undefined || merged.shot_id === null) merged.shot_id = p.shot_id;
        add(merged);
      });
    });
    rows.sort(function (a, b) { return String(a.ts || "").localeCompare(String(b.ts || "")); });
    return rows;
  }

  function apiTableHtml(rows) {
    var body = rows.map(function (r) {
      var reqResp = "";
      if (r.request || r.response) {
        reqResp = '<details class="details"><summary>payload</summary>' +
          (r.request ? '<div class="small muted">request</div><pre class="json">' + esc(JSON.stringify(r.request, null, 2)) + '</pre>' : "") +
          (r.response ? '<div class="small muted">response</div><pre class="json">' + esc(JSON.stringify(r.response, null, 2)) + '</pre>' : "") +
          '</details>';
      } else if (r.text) {
        reqResp = '<span class="muted small">' + esc(r.text) + '</span>';
      }
      var ok = r.ok === null || r.ok === undefined ? "" : (r.ok ? badge("ok", "s-completed") : badge("failed", "s-failed"));
      return [
        fmtTime(r.ts),
        esc(r.name || "--"),
        esc((r.method || "") + " " + (r.endpoint || "")),
        esc(r.status === null || r.status === undefined ? "--" : r.status) + " " + ok,
        r.duration_seconds === null || r.duration_seconds === undefined ? "--" : esc(Number(r.duration_seconds).toFixed(2)) + "s",
        txt(r.shot_id),
        reqResp
      ];
    });
    return tableHtml(["time", "name", "endpoint", "status", "duration", "shot", "payload"], body, "tbl-api");
  }

  function ensureApiEventCache() {
    if (!state.runId) return Promise.resolve();
    if (state.apiCache.runId === state.runId && state.apiCache.events) return Promise.resolve();
    var rid = state.runId;
    return fetchJson(runApi(rid, "/events") + "?since=0&limit=2000").then(function (res) {
      var events = asList(res && res.events);
      asList(events).forEach(function (ev) { ingestEvent(ev, true); });
      state.apiCache = { runId: rid, events: events };
    }).catch(function () {
      state.apiCache = { runId: rid, events: [] };
    });
  }

  function apiSectionHtml(stage) {
    var rows = apiRows(stage);
    if (rows.length) return sec("API / LLM calls", apiTableHtml(rows));
    return sec("API / LLM calls", '<div id="api-log-slot" class="muted">loading API call log&hellip;</div>');
  }

  function fillApiLog(stage) {
    var slot = $("api-log-slot");
    if (!slot) return;
    ensureApiEventCache().then(function () {
      var slot2 = $("api-log-slot");
      if (!slot2) return;
      var rows = apiRows(stage);
      slot2.outerHTML = rows.length ? apiTableHtml(rows) : '<div class="muted">-- no API calls recorded for this stage --</div>';
    });
  }

  /* ------------------------------------------------------------ view helpers */

  function viewRun() { return (state.view && state.view.run) || {}; }

  function rawStage(n) {
    var stages = asList(state.view && state.view.stages);
    for (var i = 0; i < stages.length; i++) if (stages[i] && stageEq(stages[i].stage, n)) return stages[i];
    return null;
  }

  function allStages() {
    var out = [];
    for (var n = 1; n <= TOTAL_STAGES; n++) {
      var s = rawStage(n);
      if (!s) {
        s = {
          stage: n, key: STAGE_KEYS[n], title: STAGE_TITLES[n], status: "pending",
          started_at: null, finished_at: null, duration_seconds: null, progress: null,
          message: null, error: null, artifacts: [], items: []
        };
      }
      out.push(s);
    }
    return out;
  }

  function artifactsForStage(n) {
    var out = [], seen = {};
    function push(value) {
      var r = refOf(value);
      if (!r) return;
      var key = r.rel_path || r.abs_path || r.label || JSON.stringify(r);
      if (seen[key]) return;
      seen[key] = 1;
      out.push(r);
    }
    var st = rawStage(n);
    if (st) asList(st.artifacts).forEach(push);
    asList(state.view && state.view.artifacts).forEach(function (a) {
      if (isObj(a) && a.stage !== null && a.stage !== undefined && stageEq(a.stage, n)) push(a);
    });
    asList(state.view && state.view.media).forEach(function (m) {
      if (isObj(m) && stageEq(m.stage, n)) push(m);
    });
    return out;
  }

  function stageItems(n) {
    var st = rawStage(n);
    var items = asList(st && st.items);
    var map = {};
    items.forEach(function (it) {
      if (isObj(it) && it.id !== undefined && it.id !== null) map[String(it.id)] = it;
    });
    return { list: items, map: map };
  }

  function shotList() { return asList(state.view && state.view.shots).filter(isObj); }

  function shotMap() {
    var map = {};
    shotList().forEach(function (s) { if (s.shot_id) map[String(s.shot_id)] = s; });
    return map;
  }

  function promptRecords(stage) {
    return asList(state.view && state.view.prompts).filter(function (p) {
      if (!isObj(p)) return false;
      if (stage === null || stage === undefined) return true;
      return !p.stage || stageEq(p.stage, stage);
    });
  }

  function promptMap(stage) {
    var map = {};
    promptRecords(stage).forEach(function (p) { if (p.shot_id) map[String(p.shot_id)] = p; });
    return map;
  }

  function shotEntries(stage) {
    var shots = shotMap(), prompts = promptMap(stage), keys = [], seen = {};
    shotList().forEach(function (s) { var k = String(s.shot_id); if (!seen[k]) { seen[k] = 1; keys.push(k); } });
    Object.keys(prompts).forEach(function (k) { if (!seen[k]) { seen[k] = 1; keys.push(k); } });
    return keys.map(function (k) { return { shot_id: k, shot: shots[k] || null, prompt: prompts[k] || null }; });
  }

  function registerPrompt(id, text, label) {
    state.promptIndex[id] = { text: text, label: label || "Prompt" };
  }

  function shotPromptHtml(entry, stage) {
    var prompt = entry.prompt;
    var text = (prompt && prompt.prompt) || (entry.shot && entry.shot.prompt) || null;
    if (!text) return '<div class="muted">-- no prompt recorded --</div>';
    var id = "p" + stage + "-" + entry.shot_id;
    registerPrompt(id, text, "Shot " + entry.shot_id + " - exact generation prompt");
    var segs = (prompt && prompt.segments) || (entry.shot && entry.shot.segments);
    return segmentsHtml(segs) + promptBlock(text, id, "exact generation prompt");
  }

  /* ---------------------------------------------------------------- sidebar */

  function renderHealth() {
    var line = $("health-line");
    if (state.health) {
      line.textContent = "base_dir: " + (state.health.base_dir || "--") + "  |  runs: " +
        (state.health.runs === undefined ? "--" : state.health.runs);
    } else if (state.runListError) {
      line.textContent = state.runListError;
    } else {
      line.textContent = "connecting...";
    }
  }

  function runRowHtml(r) {
    var sel = r.run_id === state.runId ? " selected" : "";
    var completed = asList(r.completed_stages).map(String);
    var pips = "";
    for (var i = 1; i <= TOTAL_STAGES; i++) {
      var cls = "pip";
      if (completed.indexOf(String(i)) >= 0) cls += " done";
      if (stageEq(r.current_stage, i)) cls += (String(r.status) === "failed" ? " failed" : " active");
      pips += '<span class="' + cls + '" title="Stage ' + i + ' ' + esc(STAGE_SHORT[i]) + '"></span>';
    }
    var foot = '<span class="small">' + fmtPct(r.progress_percent) + '</span>' +
      '<span class="small">' + fmtDur(r.elapsed_seconds) + '</span>' +
      (r.master_exists ? '<span class="small ok-text">master</span>' : '') +
      (r.has_telemetry === false ? '<span class="small muted">no telemetry</span>' : '');
    return '<div class="run-row' + sel + '" data-run-id="' + esc(r.run_id) + '" role="button" tabindex="0">' +
      '<div class="run-top"><span class="run-id mono">' + txt(r.project_id || r.run_id) + '</span>' + statusBadge(r.status) + '</div>' +
      '<div class="run-topic">' + txt(r.topic || (r.product_name || "")) + '</div>' +
      '<div class="run-pips">' + pips + '</div>' +
      '<div class="run-foot">' + foot + '</div>' +
      '</div>';
  }

  function renderRuns() {
    var box = $("run-list");
    var list = asList(state.runs);
    var f = (state.filter || "").toLowerCase();
    if (f) {
      list = list.filter(function (r) {
        return [r.run_id, r.project_id, r.topic, r.product_name, r.status, r.campaign_id]
          .map(function (x) { return String(x === null || x === undefined ? "" : x).toLowerCase(); })
          .join(" ").indexOf(f) >= 0;
      });
    }
    if (!list.length) {
      box.innerHTML = '<div class="muted pad">' + (asList(state.runs).length ? "No runs match the filter." : "No runs found.") + '</div>';
      return;
    }
    box.innerHTML = list.map(runRowHtml).join("");
  }

  function loadRuns() {
    return fetchJson("/api/health").then(function (h) {
      state.health = h;
      renderHealth();
    }).catch(function () {
      state.health = null;
      state.runListError = "health unavailable";
      renderHealth();
    }).then(function () {
      return fetchJson("/api/runs");
    }).then(function (res) {
      state.runs = asList(res && res.runs);
      state.runListError = null;
      renderRuns();
      if (!state.runId && state.runs.length) {
        var running = state.runs.filter(function (r) { return String(r.status) === "running"; })[0];
        selectRun((running || state.runs[0]).run_id, { silentHash: false });
      }
    }).catch(function (err) {
      state.runListError = "run list unavailable";
      renderHealth();
      if (!state.runs.length) {
        $("run-list").innerHTML = '<div class="muted pad">Failed to load runs: ' + esc(err.message) + '</div>';
      }
    });
  }

  /* ----------------------------------------------------------------- header */

  function renderBanner() {
    var box = $("banner");
    if (!state.banner) { box.className = "banner hidden"; box.innerHTML = ""; return; }
    box.className = "banner " + (state.banner.kind === "error" ? "banner-error" : "banner-warn");
    box.innerHTML = esc(state.banner.text);
  }

  function setBanner(text, kind) {
    state.banner = text ? { text: text, kind: kind || "warn" } : null;
    renderBanner();
  }

  function liveFromView() {
    var v = state.view;
    if (!v) return null;
    var run = viewRun();
    var cs = run.current_stage;
    var st = cs === null || cs === undefined ? null : rawStage(cs);
    var stageMessage = st ? st.message : null;
    return {
      stage: cs === null || cs === undefined ? null : cs,
      title: st ? (st.title || STAGE_TITLES[cs]) : null,
      progress: st ? st.progress : null,
      message: run.message || stageMessage || null,
      stageMessage: stageMessage
    };
  }

  function renderLive() {
    var box = $("live");
    var v = state.view;
    if (!v) { box.innerHTML = '<span class="muted">No run selected.</span>'; return; }
    var live = state.live || liveFromView() || {};
    var run = viewRun();
    var stageNo = live.stage;
    var title = live.title || (stageNo ? STAGE_TITLES[stageNo] : null);
    var html = '<div class="live-line">';
    if (stageNo) {
      html += '<span class="live-tag">STAGE ' + esc(stageNo) + '</span><span class="live-title">' + txt(title) + '</span>';
    } else if (String(run.status) === "completed") {
      html += '<span class="live-tag s-completed">COMPLETED</span><span class="live-title">Run finished</span>';
    } else if (String(run.status) === "failed") {
      html += '<span class="live-tag s-failed">FAILED</span><span class="live-title">Run stopped</span>';
    } else {
      html += '<span class="live-tag s-unknown">IDLE</span><span class="live-title">Waiting for a stage</span>';
    }
    html += '</div><div class="live-sub">';
    if (isObj(live.progress) && live.progress.current !== null && live.progress.current !== undefined) {
      html += '<span class="live-progress">' + progText(live.progress) +
        (live.progress.percent === null || live.progress.percent === undefined ? "" : " (" + fmtPct(live.progress.percent) + ")") + '</span>';
    }
    html += '<span class="live-message">' + txt(live.message || "no activity yet") + '</span>';
    if (live.stageMessage && live.stageMessage !== live.message) {
      html += '<span class="live-stage-msg">stage: ' + txt(live.stageMessage) + '</span>';
    }
    html += '</div>';
    box.innerHTML = html;
  }

  function renderHeader() {
    var v = state.view;
    var product = $("hdr-product"), meta = $("hdr-meta"), stats = $("hdr-stats"), prog = $("hdr-progress");
    if (!v) {
      product.textContent = "No run selected";
      meta.innerHTML = 'Select a run from the sidebar, or open <span class="mono">/?run=&lt;run_id&gt;</span>';
      stats.innerHTML = "";
      prog.innerHTML = "";
      renderLive();
      return;
    }
    var run = viewRun();
    product.textContent = run.product_name || run.project_id || run.run_id || "Run";
    meta.innerHTML = [
      'run <span class="mono">' + txt(run.run_id) + '</span>',
      'campaign ' + txt(run.campaign_id),
      'archetype ' + txt(run.archetype),
      'mode ' + txt(run.video_mode),
      'layout ' + txt(run.layout),
      'source ' + txt(run.source),
      run.resume_from_stage ? 'resume from stage ' + esc(run.resume_from_stage) : null
    ].filter(Boolean).join(' <span class="sep">|</span> ');

    var events = isObj(v.events) ? v.events : {};
    stats.innerHTML = [
      statusBadge(run.status),
      '<span class="stat"><span class="stat-k">stage</span>' + txt(run.current_stage ? (run.current_stage + " " + STAGE_SHORT[run.current_stage]) : null) + '</span>',
      '<span class="stat"><span class="stat-k">started</span>' + fmtTime(run.started_at) + '</span>',
      '<span class="stat"><span class="stat-k">finished</span>' + fmtTime(run.finished_at) + '</span>',
      '<span class="stat"><span class="stat-k">elapsed</span>' + fmtDur(run.elapsed_seconds) + '</span>',
      '<span class="stat"><span class="stat-k">events</span>' + txt(events.count) + '</span>',
      '<span class="stat"><span class="stat-k">master</span>' + (run.master_video_path ? "yes" : "no") + '</span>',
      '<span class="stat"><span class="stat-k">telemetry</span>' + (run.has_telemetry === false ? "artifacts only" : "yes") + '</span>'
    ].join("");

    var pct = run.progress_percent;
    var completed = asList(run.completed_stages).length;
    prog.innerHTML = '<div class="prog-row">' + barHtml(pct) +
      '<span class="prog-label">' + fmtPct(pct) + ' - ' + completed + '/' + TOTAL_STAGES + ' stages completed</span></div>';
    renderLive();
  }

  /* ---------------------------------------------------------------- stepper */

  function stageCardHtml(st) {
    var n = st.stage;
    var selected = String(state.tab) === String(n);
    var arts = artifactsForStage(n);
    var prog = st.progress;
    return '<div class="stage-card ' + statusClass(st.status) + (selected ? " selected" : "") + '" data-stage="' + esc(n) + '" role="button" tabindex="0">' +
      '<div class="stage-head"><span class="stage-num">' + esc(n) + '</span>' +
      '<span class="stage-title">' + txt(st.title || STAGE_TITLES[n]) + '</span>' + statusBadge(st.status) + '</div>' +
      '<div class="stage-meta"><span class="mono small">' + esc(st.key || STAGE_KEYS[n] || "") + '</span>' +
      '<span class="small">' + fmtDur(st.duration_seconds) + '</span></div>' +
      barHtml(isObj(prog) ? prog.percent : null) +
      '<div class="stage-prog small">' + (progText(prog) || '<span class="muted">no progress</span>') + '</div>' +
      '<div class="stage-msg small">' + txt(st.message) + '</div>' +
      (st.error ? '<div class="stage-err small">' + esc(st.error) + '</div>' : '') +
      '<div class="stage-arts small">' + miniChips(arts, 3) + '</div>' +
      '</div>';
  }

  function renderStepper() {
    var box = $("stepper");
    if (!state.view) { box.innerHTML = ""; return; }
    box.innerHTML = allStages().map(stageCardHtml).join("");
  }

  function renderTabs() {
    var box = $("tabs");
    if (!state.view) { box.innerHTML = ""; return; }
    var tabs = ['<button class="tab' + (state.tab === "all" ? " active" : "") + '" data-tab="all" type="button">All</button>'];
    allStages().forEach(function (st) {
      var n = st.stage;
      tabs.push('<button class="tab ' + statusClass(st.status) + (String(state.tab) === String(n) ? " active" : "") +
        '" data-tab="' + esc(n) + '" type="button"><span class="tab-num">' + esc(n) + '</span>' + esc(STAGE_SHORT[n]) + '</button>');
    });
    box.innerHTML = tabs.join("");
  }

  /* ----------------------------------------------------- detail: all stages */

  function renderAllPanel() {
    var v = state.view, run = viewRun();
    var out = [];
    out.push(sec("Run", kvHtml([
      ["run_id", txt(run.run_id)],
      ["project_id", txt(run.project_id)],
      ["topic", txt(run.topic)],
      ["campaign_id", txt(run.campaign_id)],
      ["product_name", txt(run.product_name)],
      ["archetype", txt(run.archetype)],
      ["video_mode", txt(run.video_mode)],
      ["layout / source", esc(run.layout + " / " + run.source)],
      ["status", statusBadge(run.status)],
      ["current_stage", run.current_stage ? esc(run.current_stage) : null],
      ["resume_from_stage", run.resume_from_stage === null || run.resume_from_stage === undefined ? null : esc(run.resume_from_stage)],
      ["started_at", fmtTime(run.started_at)],
      ["finished_at", fmtTime(run.finished_at)],
      ["elapsed", fmtDur(run.elapsed_seconds)],
      ["progress", fmtPct(run.progress_percent)],
      ["root", '<span class="mono small">' + txt(run.root) + '</span>'],
      ["artifacts_dir", '<span class="mono small">' + txt(run.artifacts_dir) + '</span>'],
      ["master_video", refChip(run.master_video_path ? refFromPath(run.master_video_path) : null) || txt(run.master_video_path)],
      ["thumbnail", refChip(run.thumbnail_path ? refFromPath(run.thumbnail_path) : null) || txt(run.thumbnail_path)],
      ["message", txt(run.message)]
    ])));

    var stageRows = allStages().map(function (st) {
      var arts = artifactsForStage(st.stage);
      return [
        esc(st.stage),
        txt(st.title || STAGE_TITLES[st.stage]),
        statusBadge(st.status),
        fmtDur(st.duration_seconds),
        (isObj(st.progress) ? (progText(st.progress) + " " + fmtPct(st.progress.percent)) : "--"),
        txt(st.message),
        st.error ? '<span class="err-text">' + esc(st.error) + '</span>' : "--",
        arts.length ? chiplist(arts) : "--"
      ];
    });
    out.push(sec("Stages", tableHtml(["#", "title", "status", "duration", "progress", "message", "error", "artifacts"], stageRows, "tbl-stages")));

    var prompts = asList(v.prompts);
    if (prompts.length) {
      var rows = prompts.map(function (p, i) {
        var id = "all-" + (p.shot_id || i);
        registerPrompt(id, p.prompt || "", "Shot " + (p.shot_id || i) + " - exact generation prompt");
        return [
          txt(p.shot_id),
          p.stage === null || p.stage === undefined ? "--" : esc(p.stage),
          txt(p.mode),
          txt(p.model),
          p.attempts === null || p.attempts === undefined ? "--" : esc(p.attempts),
          txt(p.task_id),
          '<span class="preview mono">' + esc(String(p.prompt || "").slice(0, 220)) + '</span>' +
          '<button class="btn small" type="button" data-open-prompt="' + esc(id) + '">open</button>' +
          '<button class="btn small" type="button" data-copy-prompt="' + esc(id) + '">copy</button>'
        ];
      });
      out.push(sec("Prompt ledger (" + prompts.length + " shots)", tableHtml(["shot", "stage", "mode", "model", "attempts", "task_id", "prompt"], rows, "tbl-prompts")));
    }

    var artifacts = asList(v.artifacts);
    if (artifacts.length) {
      var arows = artifacts.map(function (a) {
        return [txt(a.kind), txt(a.label), a.stage === null || a.stage === undefined ? "--" : esc(a.stage),
          a.size_bytes === null || a.size_bytes === undefined ? "--" : esc(fmtBytes(a.size_bytes)),
          fmtTime(a.written_at), refChip(a)];
      });
      out.push(sec("Artifacts (" + artifacts.length + ")", tableHtml(["kind", "label", "stage", "size", "written", "link"], arows, "tbl-artifacts")));
    }

    var mediaItems = asList(v.media).filter(function (m) { return isObj(m) && (m.kind === "video" || m.kind === "audio" || m.kind === "image"); });
    if (mediaItems.length) {
      out.push(sec("Media", '<div class="media-grid">' + mediaItems.map(function (m) {
        return mediaHtml(m, m.kind) || refChip(m);
      }).join("") + '</div>'));
    }

    var gates = asList(v.gates);
    if (gates.length) {
      out.push(sec("Verification gates", tableHtml(["gate", "passed", "error"], gates.map(function (g) {
        return [txt(g.gate_name), g.passed ? badge("passed", "s-completed") : badge("failed", "s-failed"), txt(g.error_message)];
      }), "tbl-gates")));
    }

    out.push(sec("Parsed artifacts", '<div class="chip-row">' + ARTIFACT_FILES.map(function (pair) {
      return '<a class="chip" href="' + esc(artifactUrl(pair[0])) + '" target="_blank" rel="noopener">' + esc(pair[1] + " (" + pair[0] + ")") + '</a>';
    }).join("") + '</div>' + jsonHtml({ brief: v.brief, research: v.research, concept: v.concept, script: v.script, scene_plan_summary: v.scene_plan_summary, edit_decisions: v.edit_decisions, render_report: v.render_report, publish_log: v.publish_log }, "raw parsed artifacts")));

    if (isObj(v.events)) {
      out.push(sec("Events", kvHtml([["count", esc(v.events.count)], ["last_seq", esc(v.events.last_seq)]])));
    }
    return out.join("");
  }

  /* ------------------------------------------------------------- detail: 1-8 */

  function renderStage1() {
    var v = state.view;
    var b = isObj(v.brief) ? v.brief : {};
    var r = isObj(v.research) ? v.research : {};
    var c = isObj(v.concept) ? v.concept : {};
    var out = [];

    out.push(sec("Brief", kvHtml([
      ["product_name", txt(b.product_name || viewRun().product_name)],
      ["campaign_id", txt(b.campaign_id || viewRun().campaign_id)],
      ["archetype", txt(b.archetype || viewRun().archetype)],
      ["category", txt(b.category)],
      ["character_role", txt(b.character_role)],
      ["audio_strategy", txt(b.target_audio_strategy)],
      ["visual_tone", txt(b.visual_tone)],
      ["aspect_ratio", txt(b.aspect_ratio)],
      ["presenter", isObj(b.presenter) ? esc([b.presenter.name, b.presenter.role, b.presenter.character_tag].filter(Boolean).join(" - ")) : txt(b.presenter)]
    ]) +
      '<div class="sub"><div class="sub-title">Target persona</div><div>' + txt(b.target_persona) + '</div></div>' +
      '<div class="sub"><div class="sub-title">Pain points</div>' + listHtml(b.pain_points) + '</div>' +
      '<div class="sub"><div class="sub-title">Unique selling points</div>' + listHtml(b.usps) + '</div>'));

    var intel = isObj(r.product_intel) ? r.product_intel : {};
    var pricing = isObj(intel.pricing) ? intel.pricing : {};
    var objections = asList(intel.objection_matrix).map(function (o) {
      return [txt(o && o.objection), txt(o && o.counter_evidence), txt(o && o.demonstration_technique)];
    });
    var researchBody = kvHtml([
      ["primary_persona", txt(r.primary_persona)],
      ["price_anchor_strategy", txt(r.price_anchor_strategy)],
      ["product_url", r.product_url ? '<a href="' + esc(r.product_url) + '" target="_blank" rel="noopener">' + esc(r.product_url) + '</a>' : null],
      ["title", txt(intel.title)],
      ["brand", txt(intel.brand)],
      ["category", txt(intel.category)],
      ["awareness_level", txt(intel.awareness_level)],
      ["price", pricing.current_price === undefined ? null : esc(fmtAny(pricing.current_price) + " " + fmtAny(pricing.currency))],
      ["original_price", pricing.original_price === undefined ? null : esc(fmtAny(pricing.original_price) + " " + fmtAny(pricing.currency))],
      ["discount", pricing.discount_percent === undefined ? null : esc(pricing.discount_percent + "%")],
      ["price_tier", txt(pricing.price_tier)]
    ]) +
      '<div class="sub"><div class="sub-title">Features</div>' + listHtml(intel.features) + '</div>' +
      '<div class="sub"><div class="sub-title">Dramatic benefits</div>' + listHtml(intel.dramatic_benefits) + '</div>' +
      '<div class="sub"><div class="sub-title">Target personas</div>' + listHtml(intel.target_personas) + '</div>' +
      '<div class="sub"><div class="sub-title">Sensory anchors</div>' + listHtml(intel.sensory_anchors) + '</div>' +
      '<div class="sub"><div class="sub-title">Objection matrix</div>' +
      tableHtml(["objection", "counter evidence", "demonstration technique"], objections) + '</div>';
    out.push(sec("Research / product intel", researchBody));

    var landscape = isObj(r.competitor_landscape) ? r.competitor_landscape : {};
    out.push(sec("Competitor landscape",
      '<div class="sub"><div class="sub-title">Saturated angles</div>' + listHtml(landscape.saturated_angles) + '</div>' +
      '<div class="sub"><div class="sub-title">Competitor weaknesses</div>' + listHtml(landscape.competitor_weaknesses) + '</div>' +
      '<div class="sub"><div class="sub-title">Whitespace opportunities</div>' + listHtml(landscape.whitespace_opportunities) + '</div>' +
      (landscape.competitor_examples ? '<div class="sub"><div class="sub-title">Competitor examples</div>' + jsonHtml(landscape.competitor_examples, "examples") + '</div>' : "")));

    var winning = isObj(c.winning_concept) ? c.winning_concept : {};
    var options = asList(c.concept_options);
    var selected = null;
    options.forEach(function (o) { if (o && winning.selected_angle_id && String(o.angle_id) === String(winning.selected_angle_id)) selected = o; });
    if (!selected && options.length) selected = options[0];
    var hook = selected && isObj(selected.hook_strategy) ? selected.hook_strategy : {};
    var angleBody = kvHtml([
      ["selected_angle_id", txt(winning.selected_angle_id)],
      ["title", txt(selected && selected.title)],
      ["angle_archetype", txt(selected && selected.angle_archetype)],
      ["target_segment", txt(selected && selected.target_audience_segment)],
      ["character_role", txt(selected && selected.character_role)],
      ["audio_strategy", txt(selected && selected.audio_strategy)],
      ["projected_retention_score", selected && selected.projected_retention_score !== undefined ? esc(selected.projected_retention_score) : null],
      ["projected_conversion_score", selected && selected.projected_conversion_score !== undefined ? esc(selected.projected_conversion_score) : null],
      ["confidence_score", winning.confidence_score === undefined ? null : esc(winning.confidence_score)],
      ["selection_rationale", txt(winning.selection_rationale)]
    ]) +
      '<div class="sub"><div class="sub-title">Hook strategy</div>' + kvHtml([
        ["spoken_hook", txt(hook.spoken_hook)],
        ["visual_hook", txt(hook.visual_hook)],
        ["on_screen_text", txt(hook.on_screen_text)],
        ["retention_trigger", txt(hook.retention_trigger)]
      ]) + '</div>' +
      '<div class="sub"><div class="sub-title">Narrative arc</div>' + listHtml(selected && selected.narrative_arc) + '</div>' +
      '<div class="sub"><div class="sub-title">Conversion thesis</div><div>' + txt(selected && selected.conversion_thesis) + '</div></div>';
    out.push(sec("Winning creative angle", angleBody));

    if (options.length) {
      var rows = options.map(function (o) {
        return [txt(o.angle_id), txt(o.title), txt(o.angle_archetype), txt(o.character_role), txt(o.audio_strategy),
          o.projected_retention_score === undefined ? "--" : esc(o.projected_retention_score),
          o.projected_conversion_score === undefined ? "--" : esc(o.projected_conversion_score),
          String(o.angle_id) === String(winning.selected_angle_id) ? badge("selected", "s-completed") : ""];
      });
      out.push(sec("Angle scoreboard", tableHtml(["angle_id", "title", "archetype", "role", "audio", "retention", "conversion", ""], rows, "tbl-angles")));
    }

    var hooks = asList(r.viral_hook_library);
    if (hooks.length) {
      var hrows = hooks.map(function (h) {
        return [txt(h && h.hook_type), txt(h && h.spoken_line), txt(h && h.visual_action), txt(h && h.on_screen_text),
          txt(h && h.retention_mechanism),
          h && h.projected_retention_score !== undefined ? esc(h.projected_retention_score) : "--"];
      });
      out.push(sec("Hook library (" + hooks.length + ")", tableHtml(["type", "spoken line", "visual action", "on-screen text", "retention mechanism", "score"], hrows, "tbl-hooks")));
    }

    out.push(apiSectionHtml(1));
    out.push(sec("Raw stage 1 artifacts",
      jsonHtml({ brief: v.brief, research: v.research, concept: v.concept }, "brief / research / concept")));
    return out.join("");
  }

  function renderStage2() {
    var v = state.view;
    var script = isObj(v.script) ? v.script : {};
    var beats = asList(script.beats);
    var acc = 0;
    var rows = beats.map(function (bt, i) {
      var dur = Number(bt && bt.estimated_duration) || 0;
      var window = tc(acc) + " - " + tc(acc + dur);
      acc += dur;
      return [
        esc(i + 1),
        '<span class="mono small">' + window + '</span>',
        esc(dur ? dur.toFixed(2) + "s" : "--"),
        txt(bt && (bt.beat_type || bt.archetype)),
        txt(bt && bt.spoken_text),
        txt(bt && bt.on_screen_text),
        txt(bt && bt.visual_cue),
        txt(bt && bt.character_role),
        txt(bt && bt.audio_strategy),
        txt(bt && bt.camera_choreography),
        txt(bt && bt.lighting_contract),
        txt(bt && bt.narrative_purpose)
      ];
    });
    var out = [];
    out.push(sec("Script", kvHtml([
      ["target_duration", script.target_duration === undefined ? null : esc(fmtAny(script.target_duration) + "s")],
      ["archetype", txt(script.archetype || viewRun().archetype)],
      ["beats", beats.length ? esc(beats.length) : null]
    ])));
    out.push(sec("Beats", tableHtml(["#", "timecode", "duration", "beat_type", "spoken_text", "on_screen_text", "visual_cue", "character_role", "audio_strategy", "camera_choreography", "lighting_contract", "narrative_purpose"], rows, "tbl-beats")));
    out.push(apiSectionHtml(2));
    out.push(sec("Raw stage 2 artifact", jsonHtml(v.script, "script.json")));
    return out.join("");
  }

  function renderStage3() {
    var v = state.view;
    var summary = isObj(v.scene_plan_summary) ? v.scene_plan_summary : {};
    var plan = isObj(v.scene_plan) ? v.scene_plan : {};
    var risk = isObj(summary.slideshow_risk) ? summary.slideshow_risk : (isObj(plan.slideshow_risk) ? plan.slideshow_risk : null);
    var contactSheet = summary.contact_sheet || plan.storyboard_contact_sheet;
    var out = [];

    out.push(sec("Scene plan", kvHtml([
      ["shot_count", summary.shot_count === undefined ? (asList(plan.shots).length || null) : esc(summary.shot_count)],
      ["spatial_staging_contract", txt(summary.spatial_staging_contract || plan.spatial_staging_contract)],
      ["campaign_id", txt(plan.campaign_id)]
    ]) + '<div class="media-grid">' + imgHtml(contactSheet, "storyboard contact sheet") + '</div>'));

    if (risk) {
      var dims = isObj(risk.dimensions) ? risk.dimensions : {};
      var drows = Object.keys(dims).map(function (k) {
        var d = isObj(dims[k]) ? dims[k] : {};
        return [esc(k), d.score === undefined || d.score === null ? "--" : esc(d.score), txt(d.verdict), txt(d.reason), listHtml(d.flagged_shots)];
      });
      out.push(sec("Slideshow risk",
        kvHtml([
          ["average_score", risk.average_score === undefined ? null : esc(risk.average_score)],
          ["verdict", txt(risk.verdict)],
          ["passed", risk.passed === undefined || risk.passed === null ? null : (risk.passed ? badge("passed", "s-completed") : badge("failed", "s-failed"))]
        ]) +
        '<div class="sub"><div class="sub-title">Dimensions</div>' +
        tableHtml(["dimension", "score", "verdict", "reason", "flagged shots"], drows, "tbl-risk") + '</div>' +
        '<div class="sub"><div class="sub-title">Hard rejects</div>' + listHtml(risk.hard_reject_reasons, "list-hard") + '</div>' +
        '<div class="sub"><div class="sub-title">Recommendations</div>' + listHtml(risk.recommendations) + '</div>'));
    }

    var entries = shotEntries(3);
    if (entries.length) {
      out.push(sec("Storyboard shots (" + entries.length + ")", '<div class="cards">' + entries.map(function (entry) {
        var s = entry.shot || {};
        var keyframeSource = s.keyframe_source || null;
        return '<div class="card inner">' +
          '<div class="card-head"><span class="card-title mono">' + txt(entry.shot_id) + '</span>' +
          '<span class="badges">' + (s.is_hero_moment ? badge("hero moment", "s-running") : "") +
          badge(txt(s.shot_type), "s-unknown") + badge(txt(s.angle), "s-unknown") + badge(txt(s.camera_motion), "s-unknown") + '</span></div>' +
          '<div class="card-body">' + kvHtml([
            ["scene_id", txt(s.scene_id)],
            ["beat_type", txt(s.beat_type)],
            ["shot_type", txt(s.shot_type)],
            ["angle", txt(s.angle)],
            ["camera_motion", txt(s.camera_motion)],
            ["camera_choreography", txt(s.camera_choreography)],
            ["lighting", txt(s.lighting)],
            ["lighting_contract", txt(s.lighting_contract)],
            ["color_temp_kelvin", s.color_temp_kelvin === undefined || s.color_temp_kelvin === null ? null : esc(s.color_temp_kelvin + " K")],
            ["character", esc([s.character_tag, s.character_role].filter(Boolean).join(" / ")) || null],
            ["estimated_duration", s.estimated_duration === undefined ? null : esc(fmtAny(s.estimated_duration) + "s")],
            ["narrative_purpose", txt(s.narrative_purpose)],
            ["reference_expression", txt(s.reference_expression)]
          ]) +
          '<div class="sub"><div class="sub-title">Scene description</div><div>' + txt(s.scene_description) + '</div></div>' +
          '<div class="sub"><div class="sub-title">Identity lock directive</div><div class="mono small">' + txt(s.identity_lock_directive) + '</div></div>' +
          '<div class="sub"><div class="sub-title">Style constraints</div><div class="mono small">' + txt(s.style_constraints) + '</div></div>' +
          (isServable(refOf(keyframeSource)) ? '<div class="sub"><div class="sub-title">Reference expression image</div><div class="media-grid">' + imgHtml(keyframeSource, "reference expression") + '</div></div>' : "") +
          '<div class="sub"><div class="sub-title">Exact generation prompt</div>' + shotPromptHtml(entry, 3) + '</div>' +
          '</div></div>';
      }).join("") + '</div>'));
    } else {
      out.push(sec("Storyboard shots", '<div class="muted">-- no shots in the view model --</div>'));
    }

    var arts = artifactsForStage(3);
    if (arts.length) out.push(sec("Stage artifacts", chiplist(arts)));
    out.push(apiSectionHtml(3));
    out.push(sec("Raw stage 3 artifact", jsonHtml(v.scene_plan, "scene_plan.json")));
    return out.join("");
  }

  function renderStage4() {
    var items = stageItems(4);
    var entries = shotEntries(4);
    var out = [];
    var byId = {}, order = [];
    function addKey(key) { if (key && order.indexOf(key) < 0) order.push(key); }
    entries.forEach(function (entry) { var k = String(entry.shot_id); byId[k] = entry; addKey(k); });
    items.list.forEach(function (it, idx) {
      var k = it && it.id !== undefined && it.id !== null ? String(it.id) : "(item " + (idx + 1) + ")";
      addKey(k);
      if (!byId[k]) byId[k] = { shot_id: k, shot: null, prompt: null };
    });
    if (!order.length) {
      out.push(sec("Keyframes", '<div class="muted">-- no keyframe information available --</div>'));
    } else {
      out.push(sec("Keyframe gallery (" + order.length + " shots)",
        '<div class="cards">' + order.map(function (key) {
          var entry = byId[key];
          var s = entry.shot || {};
          var item = items.map[key] || {};
          var cleaned = s.keyframe || item.cleaned_image || null;
          var anchor = s.keyframe_source || item.source_image || null;
          var w = item.width, h = item.height;
          var badges = [];
          if (item.watermark_removed) badges.push(badge("watermark removed", "s-completed"));
          if (item.fallback_reference) badges.push(badge("fallback reference", "s-running"));
          if (item.status) badges.push(badge(item.status, "s-unknown"));
          if (w && h) badges.push(badge(w + "x" + h, "s-unknown"));
          return '<div class="card inner"><div class="card-head"><span class="card-title mono">' + txt(entry.shot_id) + '</span>' +
            '<span class="badges">' + badges.join("") + '</span></div>' +
            '<div class="card-body"><div class="two-col">' +
            '<div class="sub"><div class="sub-title">Identity anchor</div>' + (anchor ? imgHtml(anchor, "identity anchor") : '<div class="muted small">-- no anchor recorded --</div>') + '</div>' +
            '<div class="sub"><div class="sub-title">Clean 9:16 keyframe</div>' + (cleaned ? imgHtml(cleaned, "clean 9:16 keyframe") : '<div class="muted small">-- no keyframe recorded --</div>') + '</div>' +
            '</div>' + kvHtml([
              ["source_image", txt(item.source_image)],
              ["cleaned_image", txt(item.cleaned_image)],
              ["watermark_removed", item.watermark_removed === undefined ? null : esc(String(item.watermark_removed))],
              ["dimensions", w && h ? esc(w + " x " + h) : null],
              ["fallback_reference", item.fallback_reference === undefined ? null : esc(String(item.fallback_reference))],
              ["anchor ref", anchor ? refChip(anchor) : null],
              ["keyframe ref", cleaned ? refChip(cleaned) : null]
            ]) + '</div></div>';
        }).join("") + '</div>'));
    }
    var arts = artifactsForStage(4);
    if (arts.length) out.push(sec("Stage artifacts", chiplist(arts)));
    if (items.list.length) out.push(sec("Stage 4 items", jsonHtml(items.list, "items")));
    out.push(jsonHtml(state.view.asset_manifest, "asset_manifest.json"));
    return out.join("");
  }

  function renderStage5() {
    var entries = shotEntries(5);
    var out = [];
    if (!entries.length) out.push(sec("Renders", '<div class="muted">-- no shot renders recorded --</div>'));
    entries.forEach(function (entry) {
      var p = entry.prompt || {};
      var s = entry.shot || {};
      var clip = p.output_url || p.output_rel_path ? { label: basename(p.output_rel_path || "render"), rel_path: p.output_rel_path, url: p.output_url } : (s.clip || s.render || null);
      var firstFrame = p.first_frame_url || p.first_frame_rel ? { label: basename(p.first_frame_rel || "first frame"), rel_path: p.first_frame_rel, url: p.first_frame_url } : (p.first_frame ? p.first_frame : null);
      var calls = asList(p.api_calls);
      out.push(sec("Shot " + (entry.shot_id || "?"), 
        kvHtml([
          ["mode", txt(p.mode)],
          ["model", txt(p.model)],
          ["aspect_ratio", txt(p.aspect_ratio)],
          ["duration_requested", p.duration_requested === undefined || p.duration_requested === null ? null : esc(p.duration_requested + "s")],
          ["attempts", p.attempts === undefined || p.attempts === null ? null : esc(p.attempts)],
          ["task_id", '<span class="mono small">' + txt(p.task_id) + '</span>'],
          ["first_frame", txt(p.first_frame_rel)],
          ["output", txt(p.output_rel_path)],
          ["output size", p.size_bytes === undefined || p.size_bytes === null ? (clip && clip.size_bytes ? esc(fmtBytes(clip.size_bytes)) : null) : esc(fmtBytes(p.size_bytes))],
          ["updated_at", fmtTime(p.updated_at)]
        ]) +
        '<div class="sub"><div class="sub-title">Prompt sent to the video model</div>' + shotPromptHtml(entry, 5) + '</div>' +
        '<div class="two-col">' +
        '<div class="sub"><div class="sub-title">First frame</div>' + (firstFrame ? (isServable(refOf(firstFrame)) ? '<div class="media-grid">' + imgHtml(firstFrame, "first frame") + '</div>' : refChip(firstFrame)) : '<div class="muted small">-- none --</div>') + '</div>' +
        '<div class="sub"><div class="sub-title">Rendered clip</div>' + (clip ? (videoHtml(clip) || refChip(clip)) : '<div class="muted small">-- none --</div>') + '</div>' +
        '</div>' +
        '<div class="sub"><div class="sub-title">API / poll calls (' + calls.length + ')</div>' + (calls.length ? apiTableHtml(calls) : '<div class="muted small">-- none recorded --</div>') + '</div>',
        "card-shot"));
    });
    var arts = artifactsForStage(5);
    if (arts.length) out.push(sec("Stage artifacts", chiplist(arts)));
    return out.join("");
  }

  function renderStage6() {
    var entries = shotEntries(6);
    var out = [];
    var speech = [];
    var b = isObj(state.view.brief) ? state.view.brief : {};
    if (b.target_audio_strategy) speech.push("target_audio_strategy: " + b.target_audio_strategy);
    var st = rawStage(6);
    if (st && st.message) speech.push("stage message: " + st.message);
    if (st && isObj(st.progress) && st.progress.label) {
      speech.push("progress: " + st.progress.current + "/" + (st.progress.total === null || st.progress.total === undefined ? "?" : st.progress.total) +
        " - " + st.progress.label);
    }

    if (speech.length || (st && st.items && st.items.length)) {
      out.push(sec("Speech profile notes",
        listHtml(speech) + (st && st.items && st.items.length ? jsonHtml(st.items, "stage items") : "")));
    }
    if (!entries.length) out.push(sec("Audio / lip-sync", '<div class="muted">-- no per-shot audio information --</div>'));
    entries.forEach(function (entry) {
      var s = entry.shot || {};
      var voice = s.voice || null;
      var synced = s.synced || null;
      if (!voice && !synced) return;
      out.push(sec("Shot " + (entry.shot_id || "?"),
        '<div class="two-col">' +
        '<div class="sub"><div class="sub-title">Voice stem</div>' + (voice ? (audioHtml(voice) || refChip(voice)) : '<div class="muted small">-- none --</div>') + '</div>' +
        '<div class="sub"><div class="sub-title">Synced clip</div>' + (synced ? (videoHtml(synced) || refChip(synced)) : '<div class="muted small">-- none --</div>') + '</div>' +
        '</div>' +
        '<div class="sub"><div class="sub-title">Spoken text</div><div>' + txt(s.spoken_text) + '</div></div>' +
        '<div class="sub"><div class="sub-title">Audio strategy</div><div>' + txt(s.audio_strategy) + '</div></div>',
        "card-shot"));
    });
    var arts = artifactsForStage(6);
    if (arts.length) {
      var audioArts = arts.filter(function (a) { return a.kind === "audio" || a.kind === "video"; });
      var otherArts = arts.filter(function (a) { return a.kind !== "audio" && a.kind !== "video"; });
      if (audioArts.length) out.push(sec("Stage media", '<div class="media-grid">' + audioArts.map(function (a) { return mediaHtml(a, a.kind) || refChip(a); }).join("") + '</div>'));
      if (otherArts.length) out.push(sec("Stage artifacts", chiplist(otherArts)));
    }
    out.push(apiSectionHtml(6));
    return out.join("");
  }

  function renderStage7() {
    var e = isObj(state.view.edit_decisions) ? state.view.edit_decisions : {};
    var out = [];
    var clips = asList(e.timeline_clips);
    out.push(sec("Edit decisions", kvHtml([
      ["render_runtime", txt(e.render_runtime)],
      ["target_aspect_ratio", txt(e.target_aspect_ratio)],
      ["output_master_path", '<span class="mono small">' + txt(e.output_master_path) + '</span>'],
      ["clips", clips.length ? esc(clips.length) : null]
    ])));

    if (clips.length) {
      out.push(sec("Timeline clip order", tableHtml(["#", "clip"], clips.map(function (c, i) {
        return [esc(i + 1), '<span class="mono small">' + esc(fmtAny(c)) + '</span>'];
      }), "tbl-timeline")));
    }

    var transitions = asList(e.transitions);
    if (transitions.length) {
      out.push(sec("Transitions", tableHtml(["type", "duration"], transitions.map(function (t) {
        return [txt(t && t.type), t && t.duration !== undefined && t.duration !== null ? esc(t.duration + "s") : "--"];
      }), "tbl-transitions")));
    }

    var captions = asList(e.captions);
    out.push(sec("Captions", captions.length ? jsonHtml(captions, captions.length + " caption entries") : '<div class="muted">-- no captions --</div>'));

    var tracks = asList(e.audio_tracks);
    if (tracks.length) {
      out.push(sec("Audio tracks", tableHtml(["track_id", "type", "file", "target LUFS", "ducking dB"], tracks.map(function (t) {
        return [txt(t && t.track_id), txt(t && t.type), '<span class="mono small">' + txt(t && t.file_path) + '</span>',
          t && t.target_lufs === null || t && t.target_lufs === undefined ? "--" : esc(t.target_lufs),
          t && t.ducking_attenuation_db === null || t && t.ducking_attenuation_db === undefined ? "--" : esc(t.ducking_attenuation_db)];
      }), "tbl-audio-tracks")));
    }

    var master = masterRef();
    out.push(sec("Master video", master ? (videoHtml(master, "master", "metadata") + downloadLinks([master])) : '<div class="muted">-- master not available --</div>'));
    var arts = artifactsForStage(7);
    if (arts.length) out.push(sec("Stage artifacts", chiplist(arts)));
    out.push(sec("Raw stage 7 artifact", jsonHtml(state.view.edit_decisions, "edit_decisions.json")));
    return out.join("");
  }

  function gateDetailsHtml(details) {
    if (!isObj(details)) return jsonHtml(details, "details");
    var simple = [], complex = {};
    Object.keys(details).forEach(function (k) {
      var val = details[k];
      if (val === null || val === undefined || typeof val === "object") complex[k] = val;
      else simple.push([k, esc(fmtAny(val))]);
    });
    return kvHtml(simple) + (Object.keys(complex).length ? jsonHtml(complex, "nested details") : "");
  }

  function masterRef() {
    var v = state.view || {};
    var run = viewRun();
    var candidates = [];
    asList(v.media).forEach(function (m) { if (isObj(m) && m.kind === "video") candidates.push(m); });
    [7, 8].forEach(function (n) {
      asList(artifactsForStage(n)).forEach(function (a) { if (a.kind === "video" && candidates.indexOf(a) < 0) candidates.push(a); });
    });
    asList(v.artifacts).forEach(function (a) {
      if (isObj(a) && a.kind === "video" && candidates.indexOf(a) < 0) candidates.push(a);
    });
    var named = null;
    candidates.forEach(function (c) {
      if (named) return;
      if (/master/i.test(String(c.label || "") + " " + String(c.rel_path || ""))) named = c;
    });
    if (named) return refOf(named);
    var staged = candidates.filter(function (c) { return c.stage === 7 || c.stage === 8 || c.stage === undefined; });
    if (staged.length) return refOf(staged[0]);
    if (run.master_video_path) return refFromPath(run.master_video_path);
    return candidates.length ? refOf(candidates[0]) : null;
  }

  function thumbnailRef() {
    var v = state.view || {};
    var run = viewRun();
    var candidates = [];
    asList(v.media).forEach(function (m) { if (isObj(m) && m.kind === "image") candidates.push(m); });
    asList(v.artifacts).forEach(function (a) { if (isObj(a) && a.kind === "image") candidates.push(a); });
    var named = null;
    candidates.forEach(function (c) {
      if (named) return;
      if (/thumbnail|master|cover|poster/i.test(String(c.label || "") + " " + String(c.rel_path || ""))) named = c;
    });
    if (named) return refOf(named);
    if (run.thumbnail_path) return refFromPath(run.thumbnail_path);
    return null;
  }

  function downloadLinks(refs) {
    var out = [];
    asList(refs).forEach(function (value) {
      var r = refOf(value);
      if (!isServable(r)) return;
      out.push('<a class="btn small" href="' + esc(refUrl(r)) + '" download>download ' + esc(basename(r.rel_path || r.label || "file")) + '</a>');
    });
    return out.length ? '<div class="btn-row">' + out.join("") + '</div>' : "";
  }

  function renderStage8() {
    var out = [];
    var gates = asList(state.view && state.view.gates);
    var rows = gates.map(function (g) {
      return [txt(g && g.gate_name), g && g.passed ? badge("passed", "s-completed") : badge("failed", "s-failed"),
        txt(g && g.error_message), gateDetailsHtml(g && g.details)];
    });
    out.push(sec("Verification gates", tableHtml(["gate_name", "passed", "error", "details"], rows, "tbl-gates")));

    var rr = isObj(state.view && state.view.render_report) ? state.view.render_report : {};
    out.push(sec("Render report", kvHtml([
      ["overall_status", txt(rr.overall_status)],
      ["video_codec", txt(rr.video_codec)],
      ["audio_codec", txt(rr.audio_codec)],
      ["resolution", rr.width && rr.height ? esc(rr.width + " x " + rr.height) : null],
      ["aspect_ratio", txt(rr.aspect_ratio)],
      ["duration_seconds", rr.duration_seconds === undefined || rr.duration_seconds === null ? null : esc(rr.duration_seconds + "s")],
      ["file_size", rr.file_size_bytes === undefined || rr.file_size_bytes === null ? null : esc(fmtBytes(rr.file_size_bytes))],
      ["master_video_path", '<span class="mono small">' + txt(rr.master_video_path) + '</span>']
    ]) + jsonHtml(state.view && state.view.render_report, "render_report.json")));

    var pl = isObj(state.view && state.view.publish_log) ? state.view.publish_log : {};
    var hashtags = asList(pl.hashtags);
    out.push(sec("Publish log", kvHtml([
      ["title", txt(pl.title)],
      ["description", txt(pl.description)],
      ["hashtags", hashtags.length ? esc(hashtags.join(" ")) : null],
      ["published_at", fmtTime(pl.published_at)],
      ["master_video_path", '<span class="mono small">' + txt(pl.master_video_path) + '</span>'],
      ["thumbnail_path", '<span class="mono small">' + txt(pl.thumbnail_path) + '</span>']
    ])));

    var master = masterRef();
    var thumb = thumbnailRef();
    out.push(sec("Final master", 
      (master ? videoHtml(master, "master", "metadata") : '<div class="muted">-- master video not available --</div>') +
      downloadLinks([master, thumb].filter(Boolean)) +
      '<div class="media-grid">' + imgHtml(thumb, "thumbnail") + '</div>'));

    var arts = artifactsForStage(8);
    if (arts.length) out.push(sec("Stage artifacts", chiplist(arts)));
    return out.join("");
  }

  function renderDetail() {
    var box = $("detail-panel");
    if (!state.view) { box.innerHTML = '<div class="muted pad">Select a run to inspect its stages.</div>'; return; }
    state.promptIndex = {};
    var html;
    if (state.tab === "all") html = renderAllPanel();
    else {
      var n = Number(state.tab);
      if (n === 1) html = renderStage1();
      else if (n === 2) html = renderStage2();
      else if (n === 3) html = renderStage3();
      else if (n === 4) html = renderStage4();
      else if (n === 5) html = renderStage5();
      else if (n === 6) html = renderStage6();
      else if (n === 7) html = renderStage7();
      else if (n === 8) html = renderStage8();
      else html = renderAllPanel();
    }
    var header = '<div class="panel-head"><span class="mono small">' + txt(viewRun().run_id) + '</span>' +
      '<span class="badges">' + statusBadge(viewRun().status) + badge(state.tab === "all" ? "overview" : ("stage " + state.tab + " - " + STAGE_SHORT[state.tab]), "s-unknown") + '</span>' +
      '</div>';
    box.innerHTML = header + html;
    if (state.tab !== "all") fillApiLog(Number(state.tab));
  }

  /* -------------------------------------------------------------- event feed */

  function levelPass(ev) {
    if (state.feedLevel === "all") return true;
    return normLevel(ev && ev.level) === state.feedLevel;
  }

  function feedRowHtml(ev) {
    var lv = normLevel(ev && ev.level);
    var stageTag = ev && ev.stage !== null && ev.stage !== undefined ? "S" + ev.stage : "--";
    return '<div class="feed-row ' + levelClass(lv) + '">' +
      '<span class="ts">' + esc(fmtTime(ev && ev.ts)) + '</span>' +
      '<span class="stage-tag">' + esc(stageTag) + '</span>' +
      '<span class="lvl">' + esc(lv) + '</span>' +
      '<span class="txt">' + esc((ev && (ev.text || ev.type)) || "") + '</span></div>';
  }

  function feedEmpty() {
    var rows = $("feed-rows");
    rows.innerHTML = '<div class="muted pad">' + (state.runId ? (state.view && state.view.run && state.view.run.has_telemetry === false ? "No telemetry for this run (derived from artifacts)." : "No events yet.") : "No run selected.") + '</div>';
  }

  function renderFeedRows() {
    var rows = $("feed-rows");
    var filtered = state.events.filter(levelPass).slice(-MAX_FEED_ROWS);
    if (!filtered.length) { feedEmpty(); return; }
    rows.innerHTML = filtered.map(feedRowHtml).join("");
    if (state.autoscroll) rows.scrollTop = rows.scrollHeight;
  }

  function appendFeedRow(ev) {
    var rows = $("feed-rows");
    if (!levelPass(ev)) return;
    if (rows.querySelector(".muted.pad")) rows.innerHTML = "";
    rows.insertAdjacentHTML("beforeend", feedRowHtml(ev));
    while (rows.childElementCount > MAX_FEED_ROWS) rows.removeChild(rows.firstChild);
    if (state.autoscroll) rows.scrollTop = rows.scrollHeight;
  }

  function ingestEvent(ev, skipFeed) {
    if (!isObj(ev)) return;
    var seq = ev.seq;
    if (seq !== null && seq !== undefined) {
      var key = String(seq);
      if (state.seen[key]) return;
      state.seen[key] = 1;
      if (Number(seq) > state.lastSeq) state.lastSeq = Number(seq);
      if (Object.keys(state.seen).length > 20000) state.seen = {};
    }
    state.events.push(ev);
    if (state.events.length > MAX_BUFFERED_EVENTS) state.events = state.events.slice(-MAX_BUFFERED_EVENTS);
    applyEventToLive(ev);
    if (!skipFeed) appendFeedRow(ev);
  }

  function applyEventToLive(ev) {
    if (!isObj(ev)) return;
    if (!state.live) state.live = liveFromView() || { stage: null, title: null, progress: null, message: null };
    var type = ev.type;
    if (type === "stage_start" || type === "stage_progress" || type === "stage_message" || type === "stage_complete" ||
      type === "stage_failed" || type === "stage_skipped") {
      if (ev.stage !== null && ev.stage !== undefined) {
        state.live.stage = ev.stage;
        state.live.title = STAGE_TITLES[ev.stage] || rawStage(ev.stage) && rawStage(ev.stage).title;
      }
    }
    if (type === "stage_progress") {
      var p = isObj(ev.payload) ? ev.payload : {};
      state.live.progress = {
        current: p.current === undefined ? null : p.current,
        total: p.total === undefined ? null : p.total,
        percent: p.percent === undefined ? null : p.percent,
        unit: p.unit === undefined ? null : p.unit,
        label: p.label === undefined ? null : p.label
      };
      if (ev.text) state.live.message = ev.text;
    } else if (type === "stage_start" || type === "stage_message") {
      state.live.progress = null;
      if (ev.text) state.live.message = ev.text;
    } else if (type === "log" || type === "note") {
      if (ev.text) state.live.message = ev.text;
    } else if (type === "stage_complete" || type === "stage_failed" || type === "stage_skipped") {
      if (ev.text) state.live.message = ev.text;
      state.live.progress = null;
    } else if (type === "run_start") {
      state.live = liveFromView();
    }
    renderLive();
  }

  function setConn(text, cls) {
    var c = $("feed-conn");
    if (!c) return;
    c.textContent = text;
    c.className = "conn " + cls;
  }

  function stopStream() {
    if (state.reconnectTimer) { clearTimeout(state.reconnectTimer); state.reconnectTimer = null; }
    if (state.es) {
      try { state.es.close(); } catch (e) { /* ignore */ }
      state.es = null;
    }
  }

  function scheduleStreamReconnect() {
    if (state.reconnectTimer) return;
    if (!state.runId) return;
    var rid = state.runId;
    state.reconnectTimer = setTimeout(function () {
      state.reconnectTimer = null;
      if (state.runId !== rid) return;
      startStream();
    }, 2000);
  }

  function startStream() {
    stopStream();
    if (!state.runId) return;
    var run = viewRun();
    if (run.has_telemetry === false) { setConn("no telemetry", "conn-idle"); return; }
    if (typeof EventSource === "undefined") { setConn("unsupported", "conn-err"); return; }
    var url = runApi(state.runId, "/stream") + "?since=" + encQ(state.lastSeq || 0);
    var es;
    try { es = new EventSource(url); } catch (e) { setConn("unavailable", "conn-err"); return; }
    state.es = es;
    state.esRunId = state.runId;
    setConn("connecting", "conn-connecting");
    es.onopen = function () { setConn("live", "conn-live"); };
    es.onmessage = function (msg) {
      var ev = null;
      try { ev = JSON.parse(msg.data); } catch (e) { ev = null; }
      if (!ev) return;
      ingestEvent(ev, false);
      if (CHANGE_TYPES[ev.type]) scheduleViewRefresh();
      if (ev.type === "run_complete" || ev.type === "run_failed") loadView(true);
    };
    es.onerror = function () {
      setConn("reconnecting", "conn-warn");
      var wasOpen = state.es;
      stopStream();
      if (wasOpen) scheduleStreamReconnect();
    };
  }

  function primeEventsThenStream() {
    if (state.streamStarted && state.esRunId === state.runId) return;
    var rid = state.runId;
    var run = viewRun();
    state.streamStarted = true;
    if (run.has_telemetry === false) { setConn("no telemetry", "conn-idle"); renderFeedRows(); return; }
    fetchJson(runApi(rid, "/events") + "?since=0&limit=500").then(function (res) {
      if (state.runId !== rid) return;
      asList(res && res.events).forEach(function (ev) { ingestEvent(ev, true); });
      renderFeedRows();
      startStream();
    }).catch(function () {
      if (state.runId !== rid) return;
      renderFeedRows();
      startStream();
    });
  }

  function feedText() {
    return state.events.filter(levelPass).map(function (ev) {
      var stageTag = ev.stage === null || ev.stage === undefined ? "--" : "S" + ev.stage;
      return "[" + (ev.ts || "") + "] [" + stageTag + "] " + normLevel(ev.level) + " " + (ev.text || ev.type || "");
    }).join("\n");
  }

  /* ----------------------------------------------------------------- modal */

  function openModal(id) {
    var entry = state.promptIndex[id];
    if (!entry) return;
    $("modal-title").textContent = entry.label || "Prompt";
    $("modal-body").textContent = entry.text || "";
    $("modal").classList.remove("hidden");
    state.modalId = id;
  }

  function closeModal() {
    $("modal").classList.add("hidden");
    state.modalId = null;
  }

  function copyText(text, btn) {
    function done() {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = "copied";
      setTimeout(function () { btn.textContent = old; }, 1200);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text || "").then(done).catch(function () { fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text || "";
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); if (done) done(); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
  }

  /* ------------------------------------------------------------------ shell */

  function updateHash() {
    if (!state.runId) return;
    var hash = "run=" + encodeURIComponent(state.runId) + (state.tab && state.tab !== "all" ? "&stage=" + encQ(state.tab) : "");
    if (location.hash.replace(/^#/, "") === hash) return;
    location.hash = hash;
  }

  function parseTarget() {
    var out = { runId: null, tab: "all" };
    var search = location.search.replace(/^\?/, "");
    if (search) {
      search.split("&").forEach(function (pair) {
        var idx = pair.indexOf("=");
        if (idx < 0) return;
        var k = decodeURIComponent(pair.slice(0, idx));
        var v = decodeURIComponent(pair.slice(idx + 1).replace(/\+/g, " "));
        if (k === "run") out.runId = v;
      });
    }
    var hash = location.hash.replace(/^#/, "");
    if (hash) {
      hash.split("&").forEach(function (pair) {
        var idx = pair.indexOf("=");
        if (idx < 0) return;
        var k = pair.slice(0, idx);
        var v = pair.slice(idx + 1);
        if (k === "run") out.runId = decodeURIComponent(v);
        if (k === "stage") out.tab = decodeURIComponent(v);
      });
    }
    return out;
  }

  function selectRun(runId, opts) {
    opts = opts || {};
    if (!runId) return;
    if (state.runId !== runId) {
      stopStream();
      state.runId = runId;
      state.view = null;
      state.events = [];
      state.lastSeq = 0;
      state.seen = {};
      state.live = null;
      state.apiCache = { runId: null, events: null };
      state.streamStarted = false;
      state.esRunId = null;
      state.tab = opts.tab || "all";
    } else if (opts.tab) {
      state.tab = opts.tab;
    }
    if (!opts.silentHash) updateHash();
    setBanner(null);
    renderRuns();
    renderHeader();
    renderStepper();
    renderTabs();
    renderDetail();
    renderFeedRows();
    loadView(false);
  }

  function loadView(silent) {
    if (!state.runId) return Promise.resolve();
    var rid = state.runId;
    return fetchJson(runApi(rid, "")).then(function (v) {
      if (state.runId !== rid) return;
      state.view = v;
      state.live = liveFromView();
      setBanner(null);
      renderRuns();
      renderHeader();
      renderStepper();
      renderTabs();
      renderDetail();
      updatePoll();
      primeEventsThenStream();
    }).catch(function (err) {
      if (state.runId !== rid) return;
      if (!silent) setBanner("Failed to load run view model: " + err.message, "error");
    });
  }

  function scheduleViewRefresh() {
    if (state.refreshTimer) return;
    state.refreshTimer = setTimeout(function () {
      state.refreshTimer = null;
      loadView(true);
    }, 500);
  }

  function updatePoll() {
    var run = viewRun();
    var running = String(run.status) === "running";
    if (running && !state.pollTimer) {
      state.pollTimer = setInterval(function () {
        var r = viewRun();
        if (String(r.status) !== "running") { updatePoll(); return; }
        loadView(true);
      }, 5000);
    } else if (!running && state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function setTab(tab) {
    if (String(state.tab) === String(tab)) return;
    state.tab = tab;
    updateHash();
    renderStepper();
    renderTabs();
    renderDetail();
    var panel = $("detail-panel");
    if (panel && panel.scrollIntoView) panel.scrollIntoView({ block: "start" });
  }

  /* ------------------------------------------------------------- wiring */

  function wire() {
    $("run-list").addEventListener("click", function (ev) {
      var row = ev.target.closest("[data-run-id]");
      if (row) selectRun(row.getAttribute("data-run-id"));
    });
    $("run-list").addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      var row = ev.target.closest("[data-run-id]");
      if (row) { ev.preventDefault(); selectRun(row.getAttribute("data-run-id")); }
    });

    $("run-filter").addEventListener("input", function (ev) {
      state.filter = ev.target.value || "";
      renderRuns();
    });
    $("btn-refresh-runs").addEventListener("click", function () { loadRuns(); });
    $("btn-reload-view").addEventListener("click", function () { loadView(false); });

    $("stepper").addEventListener("click", function (ev) {
      if (ev.target.closest("a")) return;
      var card = ev.target.closest("[data-stage]");
      if (card) setTab(card.getAttribute("data-stage"));
    });

    $("tabs").addEventListener("click", function (ev) {
      var tab = ev.target.closest("[data-tab]");
      if (tab) setTab(tab.getAttribute("data-tab"));
    });

    $("detail-panel").addEventListener("click", function (ev) {
      var copyBtn = ev.target.closest("[data-copy-prompt]");
      if (copyBtn) {
        var id = copyBtn.getAttribute("data-copy-prompt");
        var entry = state.promptIndex[id];
        copyText(entry ? entry.text : "", copyBtn);
        return;
      }
      var openBtn = ev.target.closest("[data-open-prompt]");
      if (openBtn) { openModal(openBtn.getAttribute("data-open-prompt")); return; }
    });

    $("modal-close").addEventListener("click", closeModal);
    $("modal").addEventListener("click", function (ev) { if (ev.target === $("modal")) closeModal(); });
    $("btn-modal-copy").addEventListener("click", function () {
      var entry = state.promptIndex[state.modalId];
      copyText(entry ? entry.text : $("modal-body").textContent, $("btn-modal-copy"));
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeModal();
    });

    $("feed-level").addEventListener("change", function (ev) {
      state.feedLevel = ev.target.value || "all";
      renderFeedRows();
    });
    $("btn-autoscroll").addEventListener("click", function (ev) {
      state.autoscroll = !state.autoscroll;
      ev.target.textContent = "autoscroll: " + (state.autoscroll ? "on" : "off");
      ev.target.classList.toggle("active", state.autoscroll);
      if (state.autoscroll) { var rows = $("feed-rows"); rows.scrollTop = rows.scrollHeight; }
    });
    $("btn-copy-feed").addEventListener("click", function (ev) { copyText(feedText(), ev.target); });
    $("btn-clear-feed").addEventListener("click", function () {
      state.events = [];
      renderFeedRows();
    });
    $("feed-rows").addEventListener("scroll", function (ev) {
      var el = ev.target;
      var atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      if (atBottom !== state.autoscroll) {
        state.autoscroll = atBottom;
        var btn = $("btn-autoscroll");
        btn.textContent = "autoscroll: " + (atBottom ? "on" : "off");
        btn.classList.toggle("active", atBottom);
      }
    });

    $("btn-feed-toggle").addEventListener("click", function () {
      document.body.classList.toggle("feed-hidden");
    });

    window.addEventListener("hashchange", function () {
      var target = parseTarget();
      if (!target.runId || target.runId === state.runId) {
        if (target.tab && String(target.tab) !== String(state.tab)) setTab(target.tab);
      } else {
        selectRun(target.runId, { tab: target.tab, silentHash: true });
      }
    });
  }

  function init() {
    wire();
    document.body.classList.remove("feed-hidden");
    var target = parseTarget();
    if (target.runId) {
      selectRun(target.runId, { tab: target.tab, silentHash: false });
    }
    loadRuns();
    state.runTimer = setInterval(function () { loadRuns(); }, 5000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
