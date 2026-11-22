// طبقة البيانات: المكان الوحيد اللي الصفحات بتجيب منه داتا.
// USE_MOCK = true بيرجّع بيانات وهمية (لو عايز تشتغل على الشكل من غير ما تشغّل الـ API).
// USE_MOCK = false بيكلم الـ Python API الحقيقي (api/main.py) اللي بيشغّل YOLO.
const USE_MOCK = false; // خليها true لو عايز تشتغل على الشكل من غير ما تشغّل الـ API
const API_URL = "http://127.0.0.1:8000";

// الكلاسات اللي تعتبر مخالفة (من prepared/titan_v1/data.yaml)
const VIOLATION_CLASSES = ["no_helmet", "no_vest", "chain_open"];

// بيبعت الطلب للـ API، ومعاه التوكن بتاع المستخدم لو مسجل دخول (auth.js)
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

// ---------- تسجيل الدخول ----------
// مستخدمين تجربة للوضع الوهمي بس. لما الـ API يجهز، المستخدمين هيبقوا في قاعدة البيانات
// والباسوردات متشفرة هناك، ومش هيبقى فيه أي باسورد في كود الفرونت.
const MOCK_USERS = [
  {
    email: "ziad@safesight.test",
    password: "ziad2026",
    name: "Ziad",
    role: "project_manager",
  },
  {
    email: "hse@safesight.test",
    password: "Hse#2026",
    name: "Mona HSE",
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
    password: "Hr#2026",
    name: "Omar HR",
    role: "hr_manager",
  },
];

// بترجع { token, user: { name, email, role } } أو بترمي خطأ code = "invalidCredentials"
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

// بيرجع نجاح دايمًا حتى لو الإيميل مش موجود، عشان محدش يعرف مين عنده حساب
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

// من صفحة reset-password.html (اللينك فيه token)
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

// لـ Project Manager و HR Manager (صلاحية view_users)
async function getUsers() {
  if (USE_MOCK) {
    return MOCK_USERS.map(function (u) {
      return { name: u.name, email: u.email, role: u.role };
    });
  }
  return getJson("/users");
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

// ---------- تقارير المخالفات (PDF) ----------
// كل صورة فيها مخالفة بيتعملها تقرير في الـ API (صلاحية view_reports)
async function getIncidents() {
  if (USE_MOCK) {
    return [
      { id: 2, date: "2026-11-22", time: "10:32", camera: 1, severity: "medium", violations: 1, types: { no_vest: 1 } },
      { id: 1, date: "2026-11-22", time: "09:41", camera: 1, severity: "high", violations: 2, types: { no_helmet: 1, no_vest: 1 } },
    ];
  }
  return getJson("/incidents");
}

// بيجيب ملف الـ PDF باللغة اللي المستخدم مختارها ويفتحه في تاب جديدة.
// بنجيبه بـ fetch (مش لينك عادي) عشان لازم نبعت التوكن مع الطلب.
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

// تقرير Power BI (متصدّر PDF). بيرجع لينك مؤقت للملف، أو null لو لسه ماتصدّرش.
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

// بيقول أنهي نموذج شغال، وهل هو النموذج المدرّب على معدات السلامة ولا لأ
async function getHealth() {
  if (USE_MOCK) return { weights: "mock", ppe_model: true };
  return getJson("/health");
}

// box = [x1, y1, x2, y2] بالبكسل في الصورة الأصلية
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
