const SESSION_KEY = "safesight_session";
const IDLE_LIMIT_MS = 30 * 60 * 1000;

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
  if (session && typeof USE_MOCK !== "undefined" && !USE_MOCK) {
    fetch(API_URL + "/api/auth/logout", {
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

const ROLE_PERMISSIONS = {
  project_manager: ["view_stats", "view_alerts", "view_users", "view_reports"],
  hse: ["view_stats", "view_alerts", "check_image", "view_reports"],
  site_engineer: ["view_stats", "view_alerts", "check_image"],
  hr_manager: ["view_stats", "view_users"],
};

function hasPermission(permission) {
  const session = getSession();
  if (!session) return false;
  const permissions =
    session.user.permissions || ROLE_PERMISSIONS[session.user.role] || [];
  return permissions.includes(permission);
}

function requireAuth() {
  const session = getSession();
  if (!session) {
    window.location.replace("index.html");
    return null;
  }
  saveSession(session);
  document.querySelectorAll("[data-permission]").forEach(function (el) {
    el.hidden = !hasPermission(el.dataset.permission);
  });
  return session;
}

function protectFromBackButton() {
  window.addEventListener("pageshow", function (e) {
    if (e.persisted && !getSession()) window.location.replace("index.html");
  });
}
