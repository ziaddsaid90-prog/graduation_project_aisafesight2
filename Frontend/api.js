const USE_MOCK = false;
const API_URL = "http://127.0.0.1:8000";
const API_BASE = API_URL + "/api"; // REST paths follow docs/api_contracts.md

const VIOLATION_CLASSES = ["no_helmet", "no_vest", "no_helmet_no_vest", "chain_open"];

async function getJson(path, options) {
  options = options || {};
  const session = typeof getSession === "function" ? getSession() : null;
  if (session) {
    options.headers = Object.assign(
      { Authorization: "Bearer " + session.token },
      options.headers,
    );
  }
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) {
    const err = new Error("HTTP " + res.status);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

function wait(ms) {
  return new Promise(function (r) {
    setTimeout(r, ms);
  });
}

const MOCK_USERS = [
  {
    email: "ziad@safesight.test",
    password: "ziad2026",
    name: "Ziad",
    role: "project_manager",
  },
  {
    email: "anna@safesight.test",
    password: "anna2026",
    name: "Anna HSE",
    role: "hse",
  },
  {
    email: "supervisor@safesight.test",
    password: "george2026",
    name: "George",
    role: "site_engineer",
  },
  {
    email: "hr@safesight.test",
    password: "omar2026",
    name: "Omar HR",
    role: "hr_manager",
  },
];

async function login(email, password) {
  if (USE_MOCK) {
    await wait(500);
    const user = MOCK_USERS.find(function (u) {
      return u.email === email.trim().toLowerCase() && u.password === password;
    });
    if (!user) {
      const err = new Error("invalid credentials");
      err.code = "invalidCredentials";
      throw err;
    }
    return {
      token: "mock-" + user.role,
      user: { name: user.name, email: user.email, role: user.role },
    };
  }
  try {
    return await getJson("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: password }),
    });
  } catch (e) {
    if (e.status === 401) e.code = "invalidCredentials";
    throw e;
  }
}

async function requestPasswordReset(email) {
  if (USE_MOCK) {
    await wait(700);
    return { ok: true };
  }
  return getJson("/auth/forgot-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email }),
  });
}

async function resetPassword(token, password) {
  if (USE_MOCK) {
    await wait(500);
    return { ok: true };
  }
  return getJson("/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: token, password: password }),
  });
}

async function getUsers() {
  if (USE_MOCK) {
    return MOCK_USERS.map(function (u) {
      return { name: u.name, email: u.email, role: u.role };
    });
  }
  return getJson("/users");
}

async function getAnalytics(days) {
  if (USE_MOCK) {
    const dayList = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(Date.now() - i * 86400000);
      dayList.push(d.toISOString().slice(0, 10));
    }
    return {
      hours: Array.from({ length: 24 }, function (_, h) { return h; }),
      violationsByHour: [0, 0, 0, 0, 0, 0, 1, 4, 7, 9, 6, 5, 3, 4, 6, 5, 3, 1, 0, 0, 0, 0, 0, 0],
      days: dayList,
      violationsByDay: dayList.map(function (_, i) { return 8 + ((i * 7) % 11); }),
      complianceByDay: dayList.map(function (_, i) { return 70 + ((i * 5) % 20); }),
      violationsByType: { no_helmet: 26, no_vest: 18, no_helmet_no_vest: 3 },
    };
  }
  return getJson("/analytics?days=" + days);
}

// Today's statistics: persons_seen, helmet/vest compliance and safety_index (0-1), violations,
// by_violation, active_alerts (not acknowledged), alerts_sent
async function getStatistics(from, to) {
  if (USE_MOCK) {
    return { persons_seen: 40, helmet_compliance: 0.85, vest_compliance: 0.9, safety_index: 0.8625, violations: 12,
             by_violation: { no_helmet: 6, no_vest: 4, no_helmet_no_vest: 2 }, active_alerts: 3, alerts_sent: 12 };
  }
  const q = [];
  if (from) q.push("from=" + encodeURIComponent(from));
  if (to) q.push("to=" + encodeURIComponent(to));
  return getJson("/statistics" + (q.length ? "?" + q.join("&") : ""));
}

async function getCameras() {
  if (USE_MOCK) {
    return [1, 2, 3, 4].map(function (n) {
      return { id: "cam" + n, name: "Camera " + n, location: null, active: true, last_seen: null, online: n < 4,
               last_snapshot_url: null };
    });
  }
  return getJson("/cameras");
}

async function getAlerts(acknowledged) {
  if (USE_MOCK) {
    const now = Date.now();
    return [
      { alert_id: "a1", camera_id: "cam1", violation: "no_helmet", severity: "high", ts: new Date(now - 6e5).toISOString(),
        end_ts: null, acknowledged: false, snapshot_url: null },
      { alert_id: "a2", camera_id: "cam3", violation: "no_vest", severity: "medium", ts: new Date(now - 2e6).toISOString(),
        end_ts: new Date(now - 1.9e6).toISOString(), acknowledged: true, snapshot_url: null },
    ];
  }
  return getJson("/alerts?limit=50" + (acknowledged === undefined ? "" : "&acknowledged=" + acknowledged));
}

async function ackAlert(alertId) {
  if (USE_MOCK) return { alert_id: alertId, acknowledged: true };
  return getJson("/alerts/" + encodeURIComponent(alertId) + "/ack", { method: "POST" });
}

async function getIncidents() {
  if (USE_MOCK) {
    return [
      { id: 2, date: "2026-11-22", time: "10:32", camera: 1, severity: "medium", violations: 1, types: { no_vest: 1 } },
      { id: 1, date: "2026-11-22", time: "09:41", camera: 1, severity: "high", violations: 2, types: { no_helmet: 1, no_vest: 1 } },
    ];
  }
  return getJson("/incidents");
}

async function openIncidentReport(id, lang) {
  if (USE_MOCK) {
    alert("PDF reports need the real API (USE_MOCK = false)");
    return;
  }
  const session = getSession();
  const res = await fetch(API_BASE + "/incidents/" + id + "/report.pdf?lang=" + lang, {
    headers: { Authorization: "Bearer " + session.token },
  });
  if (!res.ok) {
    const err = new Error("HTTP " + res.status);
    err.status = res.status;
    throw err;
  }
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank");
  setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
}

async function getBiReportUrl() {
  if (USE_MOCK) return null;
  const session = getSession();
  const res = await fetch(API_BASE + "/bi-report", {
    headers: { Authorization: "Bearer " + session.token },
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    const err = new Error("HTTP " + res.status);
    err.status = res.status;
    throw err;
  }
  return URL.createObjectURL(await res.blob());
}

async function getHealth() {
  if (USE_MOCK) return { weights: "mock", ppe_model: true };
  return getJson("/health");
}

async function detectImage(file) {
  if (USE_MOCK) {
    await new Promise(function (r) {
      setTimeout(r, 800);
    });
    return {
      detections: [
        { label: "person", confidence: 0.95, box: [40, 40, 220, 400] },
        { label: "no_helmet", confidence: 0.91, box: [90, 70, 170, 130] },
        { label: "vest", confidence: 0.88, box: [60, 120, 200, 260] },
      ],
    };
  }
  const form = new FormData();
  form.append("file", file);
  return getJson("/detect", { method: "POST", body: form });
}

// Live messages over the WebSocket /ws/alerts (docs/api_contracts.md): onMessage gets
// {type: "violation", alert_id, ...}, {type: "event_end", ...}, {type: "stats", ...} or {type: "ack", ...};
// onExpired runs when the session is no longer valid; onStatus(true/false) says whether the live
// connection is up. Reconnects by itself (1s, 2s, 4s ... up to 30s).
function connectAlerts(onMessage, onExpired, onStatus) {
  onStatus = onStatus || function () {};
  if (USE_MOCK) return onStatus(true);
  const session = getSession();
  if (!session) return;
  const url = API_URL.replace(/^http/, "ws") + "/ws/alerts";
  let retry = 1000;
  function open() {
    const ws = new WebSocket(url);
    ws.onopen = function () {
      ws.send(JSON.stringify({ token: session.token }));
    };
    ws.onmessage = function (e) {
      const msg = JSON.parse(e.data);
      if (msg.type === "ready") {
        retry = 1000;
        onStatus(true);
      } else onMessage(msg);
    };
    ws.onclose = function (e) {
      onStatus(false);
      if (e.code === 4401) return onExpired();
      if (e.code === 4403) return;
      setTimeout(open, retry);
      retry = Math.min(retry * 2, 30000);
    };
  }
  open();
}

// A snapshot (snapshot_url from the API, e.g. "/api/snapshots/....jpg") as an object URL for <img src>.
// The request needs the login token, so it can't be a plain <img src>. Cached because lists redraw often.
const snapshotCache = new Map();
async function getSnapshotUrl(snapshotUrl) {
  if (snapshotCache.has(snapshotUrl)) return snapshotCache.get(snapshotUrl);
  const res = await fetch(API_URL + snapshotUrl, {
    headers: { Authorization: "Bearer " + getSession().token },
  });
  if (!res.ok) {
    const err = new Error("HTTP " + res.status);
    err.status = res.status;
    throw err;
  }
  const url = URL.createObjectURL(await res.blob());
  snapshotCache.set(snapshotUrl, url);
  return url;
}
