/* Watchdesk front end. Reads /api/data; never talks to Zabbix, Dataverse or
   DeskPro directly -- those credentials stay on the Python side. */

var SEV_COLOUR = {0:"#97AAB3",1:"#7499FF",2:"#FFC859",3:"#FFA059",4:"#E97659",5:"#E45959"};
var DAY_LABELS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
var severityFilter = null;   // null until we see the first payload
var lastFetch = 0;

function el(tag, cls, text) {
  var node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return seconds + "s";
  var m = Math.floor(seconds / 60);
  if (m < 60) return m + "m";
  var h = Math.floor(m / 60);
  if (h < 24) return h + "h " + String(m % 60).padStart(2, "0") + "m";
  return Math.floor(h / 24) + "d " + (h % 24) + "h";
}

function setHealth(key, entry) {
  var dot = document.getElementById(key + "-health");
  var meta = document.getElementById(key + "-meta");
  var count = document.getElementById(key + "-count");

  if (entry.ok === null) {
    dot.className = "health off";
    meta.textContent = "disabled";
    count.textContent = "—";
  } else if (entry.ok) {
    dot.className = "health";
    count.textContent = entry.items.length;
  } else {
    dot.className = "health bad";
    meta.textContent = "connection failed";
    count.textContent = "!";
  }
}

function failPanel(entry) {
  var box = el("div", "fail");
  box.appendChild(el("p", "fail-h", "Cannot reach this source"));
  box.appendChild(el("p", "fail-b", entry.error || "Unknown error"));
  if (entry.meta && entry.meta.detail) {
    box.appendChild(el("pre", "fail-d", entry.meta.detail));
  }
  return box;
}

/* ---------- Zabbix ---------- */

function renderZabbix(entry) {
  var panel = document.getElementById("zabbix-panel");
  panel.textContent = "";
  setHealth("zabbix", entry);
  if (entry.ok === null) { panel.appendChild(el("p", "empty", "Set zabbix.enabled to true in config.json.")); return; }
  if (!entry.ok) { panel.appendChild(failPanel(entry)); return; }

  document.getElementById("zabbix-meta").textContent =
    "v" + (entry.meta.version || "?") + " · " + entry.meta.unacknowledged + " unacked";

  var present = {};
  entry.items.forEach(function (a) { present[a.severity] = true; });
  if (severityFilter === null) { severityFilter = {}; Object.keys(present).forEach(function (s) { severityFilter[s] = true; }); }

  var levels = Object.keys(present).sort(function (a, b) { return b - a; });
  if (levels.length) {
    var bar = el("div", "filters");
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "Filter by severity");
    levels.forEach(function (sev) {
      var on = severityFilter[sev] !== false;
      var b = el("button", "filter");
      b.type = "button";
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.style.setProperty("--sev", SEV_COLOUR[sev]);
      b.appendChild(el("span", "swatch"));
      b.appendChild(document.createTextNode(
        (entry.items.filter(function (i) { return String(i.severity) === sev; })[0] || {}).severity_name || sev));
      b.addEventListener("click", function () {
        severityFilter[sev] = !(severityFilter[sev] !== false);
        renderZabbix(entry);
      });
      bar.appendChild(b);
    });
    panel.appendChild(bar);
  }

  var shown = entry.items.filter(function (a) { return severityFilter[a.severity] !== false; });

  if (!shown.length) {
    panel.appendChild(el("p", "empty", entry.items.length
      ? "No problems at the selected severities."
      : "No unresolved problems. "));
  }

  shown.forEach(function (a) {
    var row = el("article", "row alert");
    row.style.setProperty("--sev", a.colour || SEV_COLOUR[a.severity]);
    row.appendChild(el("span", "stripe"));
    row.appendChild(el("p", "row-title", a.name));

    var meta = el("div", "row-meta");
    meta.appendChild(el("span", "sev-pill", a.severity_name));
    meta.appendChild(el("span", "host", a.host));
    meta.appendChild(el("span", "sep", "/"));
    meta.appendChild(el("span", null, ago(a.age_seconds)));
    meta.appendChild(el("span", a.acknowledged ? "ack" : "ack no",
                        a.acknowledged ? "Acked" : "Unacked"));
    row.appendChild(meta);
    panel.appendChild(row);
  });

  panel.appendChild(el("div", "panel-foot",
    entry.meta.label + " · " + shown.length + " of " + entry.items.length + " shown"));
}

/* ---------- Planner ---------- */

function renderPlanner(entry) {
  var panel = document.getElementById("planner-panel");
  panel.textContent = "";
  setHealth("planner", entry);
  if (entry.ok === null) { panel.appendChild(el("p", "empty", "Set planner.enabled to true in config.json.")); return; }
  if (!entry.ok) { panel.appendChild(failPanel(entry)); return; }

  document.getElementById("planner-meta").textContent =
    entry.meta.week_start + " → " + entry.meta.week_end;

  var start = new Date(entry.meta.week_start + "T00:00:00");
  var today = new Date().toISOString().slice(0, 10);
  var strip = el("div", "weekstrip");
  strip.setAttribute("aria-label", "Tasks due per day this week");
  for (var i = 0; i < 7; i++) {
    var date = new Date(start.getTime() + i * 86400000);
    var iso = date.toISOString().slice(0, 10);
    var n = entry.meta.per_day[iso] || 0;
    var day = el("div", "day" + (iso === today ? " today" : ""));
    day.appendChild(el("span", "day-l", DAY_LABELS[(start.getDay() + i + 6) % 7]));
    day.appendChild(el("span", "day-n" + (n ? "" : " zero"), n));
    strip.appendChild(day);
  }
  panel.appendChild(strip);

  if (!entry.items.length) {
    panel.appendChild(el("p", "empty", "Nothing scheduled for this week."));
  }

  entry.items.forEach(function (t) {
    var row = el("article", "row");
    row.appendChild(el("p", "row-title", t.title));

    var meta = el("div", "row-meta");
    if (t.bucket) meta.appendChild(el("span", "bucket", t.bucket));
    var due = t.due_date
      ? (t.due_date === today ? "Due today" : "Due " + t.due_date)
      : "No due date";
    meta.appendChild(el("span", t.overdue ? "overdue" : null,
                        t.overdue ? due + " · overdue" : due));
    row.appendChild(meta);

    var prog = el("div", "prog");
    var track = el("span", "track");
    var fill = el("span", "fill" + (t.percent >= 100 ? " done" : ""));
    fill.style.width = Math.max(0, Math.min(100, t.percent)) + "%";
    track.appendChild(fill);
    prog.appendChild(track);
    prog.appendChild(el("span", "pct", t.percent + "%"));
    row.appendChild(prog);

    panel.appendChild(row);
  });

  panel.appendChild(el("div", "panel-foot",
    entry.meta.overdue + " overdue · " + entry.meta.due_today + " due today"));
}

/* ---------- DeskPro ---------- */

function renderDeskpro(entry) {
  var panel = document.getElementById("deskpro-panel");
  panel.textContent = "";
  setHealth("deskpro", entry);
  if (entry.ok === null) { panel.appendChild(el("p", "empty", "Set deskpro.enabled to true in config.json.")); return; }
  if (!entry.ok) { panel.appendChild(failPanel(entry)); return; }

  document.getElementById("deskpro-meta").textContent =
    entry.meta.scope + " · " + entry.meta.total + " total";

  if (!entry.items.length) {
    panel.appendChild(el("p", "empty", "No open tickets."));
  }

  entry.items.forEach(function (t) {
    var row = el("article", "row");
    row.appendChild(el("p", "row-title", t.subject));

    var meta = el("div", "row-meta");
    meta.appendChild(el("span", "ref", t.ref));
    meta.appendChild(el("span", "status" + (t.on_us ? " agent" : ""), t.status_label));
    if (t.urgency) {
      meta.appendChild(el("span", "urg" + (t.urgency >= 7 ? " hi" : ""), "U" + t.urgency));
    }
    meta.appendChild(el("span", "sep", "/"));
    meta.appendChild(el("span", null, ago(t.age_seconds)));
    row.appendChild(meta);
    panel.appendChild(row);
  });

  panel.appendChild(el("div", "panel-foot",
    entry.meta.awaiting_agent + " awaiting agent"));
}

/* ---------- wiring ---------- */

function render(payload) {
  renderZabbix(payload.sources.zabbix);
  renderPlanner(payload.sources.planner);
  renderDeskpro(payload.sources.deskpro);
  lastFetch = Date.now();
  tick();
}

function tick() {
  if (!lastFetch) return;
  document.getElementById("synced").textContent =
    "synced " + ago(Math.round((Date.now() - lastFetch) / 1000)) + " ago";
}

function load(force) {
  return fetch(force ? "/api/refresh" : "/api/data")
    .then(function (r) { return r.json(); })
    .then(render)
    .catch(function (err) {
      document.getElementById("synced").textContent = "dashboard offline — is run.py still running?";
      console.error(err);
    });
}

document.getElementById("refresh").addEventListener("click", function () {
  var btn = this;
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  load(true).then(function () { btn.disabled = false; btn.textContent = "Refresh"; });
});

setInterval(tick, 1000);
setInterval(function () { load(false); }, 15000);
load(false);
