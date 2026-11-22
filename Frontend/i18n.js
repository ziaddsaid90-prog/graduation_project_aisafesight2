// الترجمة عربي / إنجليزي
// الكلام بيتكتب بالإنجليزي بس هنا. العربي بيترجمه نموذج ترجمة (MarianMT) شغال في الـ API (POST /translate)،
// والترجمات الغلط بتتصلح في api/translation_fixes.json.
// أي عنصر في الصفحة عليه data-i18n="key" بيتكتب فيه النص بتاع المفتاح ده.
const translations = {
  en: {
    langBtn: "العربية",
    tagline: "See risks. Ensure safety.",
    loginTitle: "Sign in to continue",
    email: "Email",
    emailPlaceholder: "name@company.com",
    password: "Password",
    login: "Sign in",
    signingIn: "Signing in...",
    emailRequired: "Please enter your email",
    emailInvalid: "That email doesn't look right",
    passwordRequired: "Please enter your password",
    invalidCredentials: "Wrong email or password",
    show: "Show",
    hide: "Hide",
    forgotPassword: "Forgot password?",
    demoHint: "Demo mode: test accounts are in MOCK_USERS in api.js",
    resetTitle: "Reset your password",
    resetIntro: "Enter your email and we'll send you a link to set a new password.",
    sendResetLink: "Send link",
    sending: "Sending...",
    resetSent: "If an account exists for that email, a reset link will arrive in a few minutes.",
    backToLogin: "Back to sign in",
    newPasswordTitle: "Set a new password",
    newPassword: "New password",
    confirmPassword: "Repeat the password",
    savePassword: "Save password",
    passwordChanged: "Your password was changed. Sign in with the new one.",
    passwordTooShort: "The password must be at least 8 characters",
    passwordsDontMatch: "The passwords don't match",
    resetLinkInvalid: "This link is invalid or expired. Request a new one.",
    users: "Users",
    reports: "Violation reports",
    biReport: "Power BI report",
    openFullScreen: "Open full screen",
    loading: "Loading...",
    biNotExported: "No report yet. Export it from Power BI (File > Export > Export to PDF) and save it as powerbi/AI_SafeSight_CHV.pdf",
    reportsIntro: "A report is created automatically for every image with a violation. Click PDF to open it in the current language.",
    reportNo: "Report No.",
    dateTime: "Date & time",
    downloadPdf: "PDF",
    noReports: "No reports yet",
    name: "Name",
    role: "Role",
    role_project_manager: "Project Manager",
    role_hse: "HSE Officer",
    role_site_engineer: "Site Engineer",
    role_hr_manager: "HR Manager",
    logout: "Log out",
    cameras: "Cameras",
    violationsToday: "Violations today",
    compliance: "Compliance rate",
    checkImage: "Check an image",
    analyzing: "Analyzing...",
    chooseImage: "Choose an image to analyze",
    detected: "Violations detected: ",
    apiError: "Could not reach the server",
    noAlerts: "No alerts yet",
    demoModel: "The current model is not trained on safety equipment, so it won't detect violations until it is trained",
    recentAlerts: "Recent alerts",
    time: "Time",
    camera: "Camera",
    violation: "Violation",
    severity: "Severity",
    high: "High",
    medium: "Medium",
    low: "Low",
    // model classes
    person: "Person",
    helmet: "Helmet",
    no_helmet: "No helmet",
    vest: "Vest",
    no_vest: "No vest",
    wheelbarrow: "Wheelbarrow",
    mixer_truck: "Mixer truck",
    vehicle_other: "Vehicle",
    chain_closed: "Chain closed",
    chain_open: "Chain open"
  }
};

// حاجات مابتتترجمش (اسم اللغة التانية، أمثلة، اختصارات)
const FIXED = {
  ar: { langBtn: "English", emailPlaceholder: "name@company.com", downloadPdf: "PDF" },
  en: {},
};

const I18N_DEFAULT_API = "http://127.0.0.1:8000";
const CACHE_KEY = "i18n_cache_ar_v1"; // الترجمات اللي جت من النموذج، عشان ماتتطلبش كل مرة

let arCache = {};
try {
  arCache = JSON.parse(localStorage.getItem(CACHE_KEY)) || {};
} catch (e) {}

// اللغة المحفوظة من آخر مرة (أو عربي لو أول مرة)
let currentLang = "ar";
try {
  currentLang = localStorage.getItem("lang") || "ar";
} catch (e) {}

// بترجع النص بتاع المفتاح باللغة الحالية. لو الترجمة لسه ماوصلتش، بيرجع الإنجليزي.
function t(key) {
  if (FIXED[currentLang][key] !== undefined) return FIXED[currentLang][key];
  const english = translations.en[key];
  if (english === undefined) return key;
  if (currentLang === "en") return english;
  return arCache[english] || english;
}

// بيترجم أي نصوص (مثلًا داتا جاية من قاعدة البيانات) بالنموذج
async function translateTexts(texts, target, source) {
  const apiUrl = typeof API_URL !== "undefined" ? API_URL : I18N_DEFAULT_API;
  const res = await fetch(apiUrl + "/translate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texts: texts, target: target || "ar", source: source || "en" }),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return (await res.json()).translations;
}

// بيجيب ترجمة كل الكلام الإنجليزي اللي لسه مالوش ترجمة محفوظة
async function loadArabic() {
  const missing = Object.keys(translations.en)
    .filter(function (key) {
      return FIXED.ar[key] === undefined && !arCache[translations.en[key]];
    })
    .map(function (key) {
      return translations.en[key];
    });
  if (missing.length === 0) return false;
  const result = await translateTexts(missing, "ar", "en");
  missing.forEach(function (text, i) {
    arCache[text] = result[i];
  });
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(arCache));
  } catch (e) {}
  return true;
}

function applyTexts() {
  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  // بيبلّغ الصفحة إن الكلام اتغير عشان تعيد رسم الجداول
  document.dispatchEvent(new Event("langchange"));
}

function setLang(lang) {
  currentLang = lang;
  try {
    localStorage.setItem("lang", lang);
  } catch (e) {}
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  applyTexts(); // على طول بالمحفوظ (أو بالإنجليزي لو لسه مفيش ترجمة)

  if (lang === "ar") {
    // بعد ما باقي ملفات الصفحة تتحمّل، نجيب أي ترجمة ناقصة من النموذج
    setTimeout(function () {
      loadArabic()
        .then(function (changed) {
          if (changed && currentLang === "ar") applyTexts();
        })
        .catch(function () {
          // الـ API مش شغال: الكلام اللي مالوش ترجمة محفوظة بيفضل إنجليزي
        });
    }, 0);
  }
}

function toggleLang() {
  setLang(currentLang === "ar" ? "en" : "ar");
}

setLang(currentLang);
