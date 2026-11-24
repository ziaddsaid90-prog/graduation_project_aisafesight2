const USE_MOCK = false;
const API_URL = "http://127.0.0.1:8000";

const VIOLATION_CLASSES = ["no_helmet", "no_vest", "chain_open"];

async function getJson(path, options) {
  options = options || {};
  const session = typeof getSession === "function" ? getSession() : null;
  if (session) {
    options.headers = Object.assign(
      { Authorization: "Bearer " + session.token },
      options.headers,
    );
  }
  const res = await fetch(API_URL + path, options);
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
      violationsByType: { no_helmet: 26, no_vest: 18, chain_open: 3 },
    };
  }
  return getJson("/analytics?days=" + days);
}

async function getStats() {
  if (USE_MOCK) return { cameras: 4, violationsToday: 12, compliance: 87 };
  return getJson("/stats");
}

async function getAlerts() {
  if (USE_MOCK) {
    return [
      { time: "10:15", camera: 1, violation: "no_helmet", level: "high" },
      { time: "10:32", camera: 3, violation: "no_vest", level: "medium" },
      { time: "11:05", camera: 2, violation: "chain_open", level: "high" },
    ];
  }
  return getJson("/alerts");
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
  const res = await fetch(API_URL + "/incidents/" + id + "/report.pdf?lang=" + lang, {
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
  const res = await fetch(API_URL + "/bi-report", {
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

// Live alerts over WebSocket. onMessage gets {type: "detections", camera, alerts: [...]} every time
// /detect saves something; onExpired runs when the session is no longer valid.
// Reconnects by itself (1s, 2s, 4s ... up to 30s) if the API restarts.
function connectAlerts(onMessage, onExpired) {
  if (USE_MOCK) return;
  const session = getSession();
  if (!session) return;
  const url = API_URL.replace(/^http/, "ws") + "/ws/alert";
  let retry = 1000;
  function open() {
    const ws = new WebSocket(url);
    ws.onopen = function () {
      ws.send(JSON.stringify({ token: session.token }));
    };
    ws.onmessage = function (e) {
      const msg = JSON.parse(e.data);
      if (msg.type === "ready") retry = 1000;
      else onMessage(msg);
    };
    ws.onclose = function (e) {
      if (e.code === 4401) return onExpired();
      if (e.code === 4403) return;
      setTimeout(open, retry);
      retry = Math.min(retry * 2, 30000);
    };
  }
  open();
}

// The violation frame (camera image with boxes) of one alert, as an object URL for <img src>.
// Cached per alert because the alerts table is redrawn on every refresh.
const alertFrameCache = new Map();
async function getAlertFrameUrl(id) {
  if (alertFrameCache.has(id)) return alertFrameCache.get(id);
  const res = await fetch(API_URL + "/alerts/" + id + "/frame.jpg", {
    headers: { Authorization: "Bearer " + getSession().token },
  });
  if (!res.ok) {
    const err = new Error("HTTP " + res.status);
    err.status = res.status;
    throw err;
  }
  const url = URL.createObjectURL(await res.blob());
  alertFrameCache.set(id, url);
  return url;
}
