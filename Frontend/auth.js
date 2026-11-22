// الجلسة: مين مسجل دخول دلوقتي.
// بنحفظها في sessionStorage، وده بيتمسح لوحده لما تقفل التاب أو المتصفح،
// فأول ما ترجع للموقع لازم تسجل دخول تاني.
const SESSION_KEY = "safesight_session";
// احتياطي: بعض المتصفحات بترجّع التابات القديمة بالـ sessionStorage بتاعها لما تفتحها تاني،
// فلو مافيش أي نشاط بقاله المدة دي، الجلسة بتعتبر منتهية.
const IDLE_LIMIT_MS = 30 * 60 * 1000; // 30 دقيقة

// تنضيف: نسخ قديمة من الموقع كانت بتحفظ الجلسة في localStorage ("افتكرني")
try {
  localStorage.removeItem(SESSION_KEY);
} catch (e) {}

function getSession() {
  try {
    const session = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    if (!session) return null;
    if (Date.now() - (session.lastActive || 0) > IDLE_LIMIT_MS) {
      sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    return session;
  } catch (e) {
    return null;
  }
}

function saveSession(session) {
  session.lastActive = Date.now();
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch (e) {}
}

// بنحدّث وقت آخر نشاط كل ما المستخدم يعمل حاجة (مرة كل دقيقة بالكتير)
function touchSession() {
  const session = getSession();
  if (session && Date.now() - session.lastActive > 60 * 1000)
    saveSession(session);
}
["click", "keydown", "scroll"].forEach(function (evt) {
  window.addEventListener(evt, touchSession, { passive: true });
});

function logout() {
  const session = getSession();
  // نقول للـ API ينهي الجلسة كمان (لو شغالين على الـ API الحقيقي)، من غير ما نستنى الرد
  if (session && typeof USE_MOCK !== "undefined" && !USE_MOCK) {
    fetch(API_URL + "/auth/logout", {
      method: "POST",
      headers: { Authorization: "Bearer " + session.token },
      keepalive: true,
    }).catch(function () {});
  }
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch (e) {}
  window.location.replace("index.html");
}

// ---------- الصلاحيات ----------
// مع الـ API الحقيقي: الصلاحيات بتيجي من السيرفر مع تسجيل الدخول (ROLE_PERMISSIONS في api/auth.py)،
// والسيرفر هو اللي بيرفض أي طلب مش من صلاحيتك.
// الجدول ده للوضع الوهمي بس (USE_MOCK = true)، فلو غيّرت صلاحية غيّرها في الملفين.
//   view_stats   كروت الإحصائيات (الكاميرات، مخالفات اليوم، نسبة الالتزام)
//   view_alerts  جدول التنبيهات بالتفاصيل (الوقت، الكاميرا، المخالفة)
//   check_image  رفع صورة وفحصها بالنموذج
//   view_users   جدول المستخدمين
//   view_reports تقارير المخالفات (PDF)
const ROLE_PERMISSIONS = {
  project_manager: ["view_stats", "view_alerts", "view_users", "view_reports"],
  hse: ["view_stats", "view_alerts", "check_image", "view_reports"],
  site_engineer: ["view_stats", "view_alerts", "check_image"],
  hr_manager: ["view_stats", "view_users"],
};

function hasPermission(permission) {
  const session = getSession();
  if (!session) return false;
  const permissions = session.user.permissions || ROLE_PERMISSIONS[session.user.role] || [];
  return permissions.includes(permission);
}

// تتنادي أول الصفحة المحمية: لو مش مسجل دخول يرجع لصفحة الدخول.
// ملحوظة: ده بيخفي الصفحة بس. الحماية الحقيقية لازم تبقى في الـ API (بيرفض أي طلب من غير توكن صحيح).
function requireAuth() {
  const session = getSession();
  if (!session) {
    window.location.replace("index.html");
    return null;
  }
  saveSession(session); // فتح الصفحة نفسه نشاط
  // أي عنصر عليه data-permission="..." بيظهر بس لو دورك عنده الصلاحية دي
  document.querySelectorAll("[data-permission]").forEach(function (el) {
    el.hidden = !hasPermission(el.dataset.permission);
  });
  return session;
}

// لو رجعت بزرار Back بعد تسجيل الخروج، المتصفح ممكن يعرض نسخة محفوظة من الصفحة.
// الصفحات المحمية بتنادي protectFromBackButton() عشان ترجع لصفحة الدخول في الحالة دي.
function protectFromBackButton() {
  window.addEventListener("pageshow", function (e) {
    if (e.persisted && !getSession()) window.location.replace("index.html");
  });
}
