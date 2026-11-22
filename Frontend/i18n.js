// الترجمة عربي / إنجليزي
// أي عنصر في الصفحة عليه data-i18n="key" بيتكتب فيه النص بتاع المفتاح ده.
// أسماء الكلاسات (no_helmet, vest, ...) نفس الأسماء اللي في prepared/titan_v1/data.yaml
const translations = {
  ar: {
    langBtn: "English",
    tagline: "اكتشف المخاطر. اضمن السلامة.",
    loginTitle: "سجّل دخولك للمتابعة",
    email: "الإيميل",
    emailPlaceholder: "name@company.com",
    password: "الباسورد",
    login: "تسجيل الدخول",
    signingIn: "جاري تسجيل الدخول...",
    emailRequired: "اكتب الإيميل الأول",
    emailInvalid: "الإيميل مكتوب غلط",
    passwordRequired: "اكتب الباسورد",
    invalidCredentials: "الإيميل أو الباسورد غلط",
    show: "إظهار",
    hide: "إخفاء",
    forgotPassword: "نسيت الباسورد؟",
    demoHint: "وضع تجربة: حسابات التجربة موجودة في MOCK_USERS في ملف api.js",
    resetTitle: "استرجاع الباسورد",
    resetIntro: "اكتب إيميلك وهنبعتلك لينك تعمل بيه باسورد جديد.",
    sendResetLink: "ابعت اللينك",
    sending: "جاري الإرسال...",
    resetSent: "لو الإيميل ده عليه حساب، هيوصلك لينك استرجاع الباسورد خلال دقايق.",
    backToLogin: "رجوع لتسجيل الدخول",
    newPasswordTitle: "اعمل باسورد جديد",
    newPassword: "الباسورد الجديد",
    confirmPassword: "اكتب الباسورد تاني",
    savePassword: "احفظ الباسورد",
    passwordChanged: "الباسورد اتغيّر. سجّل دخول بالباسورد الجديد.",
    passwordTooShort: "الباسورد لازم يبقى 8 حروف على الأقل",
    passwordsDontMatch: "الباسوردين مش زي بعض",
    resetLinkInvalid: "اللينك ده مش صالح أو انتهى. اطلب لينك جديد.",
    users: "المستخدمين",
    reports: "تقارير المخالفات",
    biReport: "تقرير Power BI",
    openFullScreen: "فتح بملء الشاشة",
    loading: "جاري التحميل...",
    biNotExported: "لسه مفيش تقرير. صدّر التقرير من Power BI (File ← Export ← Export to PDF) واحفظه في powerbi/AI_SafeSight_CHV.pdf",
    reportsIntro: "بيتعمل تقرير تلقائي لكل صورة فيها مخالفة. اضغط PDF عشان تفتحه باللغة الحالية.",
    reportNo: "رقم التقرير",
    dateTime: "التاريخ والوقت",
    downloadPdf: "PDF",
    noReports: "مفيش تقارير لسه",
    name: "الاسم",
    role: "الصلاحية",
    role_project_manager: "مدير المشروع",
    role_hse: "مسؤول السلامة HSE",
    role_site_engineer: "مهندس الموقع",
    role_hr_manager: "مدير الموارد البشرية",
    logout: "تسجيل الخروج",
    cameras: "الكاميرات",
    violationsToday: "مخالفات اليوم",
    compliance: "نسبة الالتزام",
    checkImage: "فحص صورة",
    analyzing: "جاري الفحص...",
    chooseImage: "اختار صورة عشان تتفحص",
    detected: "عدد المخالفات المكتشفة: ",
    apiError: "حصل خطأ في الاتصال بالسيرفر",
    noAlerts: "مفيش تنبيهات لسه",
    demoModel: "النموذج الشغال دلوقتي مش متدرب على معدات السلامة، فمش هيكشف مخالفات لحد ما يتدرب",
    recentAlerts: "آخر التنبيهات",
    time: "الوقت",
    camera: "كاميرا",
    violation: "المخالفة",
    severity: "الخطورة",
    high: "عالية",
    medium: "متوسطة",
    low: "منخفضة",
    // كلاسات النموذج
    person: "شخص",
    helmet: "خوذة",
    no_helmet: "بدون خوذة",
    vest: "جاكت",
    no_vest: "بدون جاكت",
    wheelbarrow: "عربية يد",
    mixer_truck: "خلاطة",
    vehicle_other: "مركبة",
    chain_closed: "سلسلة مقفولة",
    chain_open: "سلسلة مفتوحة"
  },
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

// اللغة المحفوظة من آخر مرة (أو عربي لو أول مرة)
let currentLang = "ar";
try {
  currentLang = localStorage.getItem("lang") || "ar";
} catch (e) {}

// بترجع النص بتاع المفتاح باللغة الحالية
function t(key) {
  return translations[currentLang][key] || key;
}

function setLang(lang) {
  currentLang = lang;
  try {
    localStorage.setItem("lang", lang);
  } catch (e) {}
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";

  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });

  // بيبلّغ الصفحة إن اللغة اتغيرت عشان تعيد رسم الجدول
  document.dispatchEvent(new Event("langchange"));
}

function toggleLang() {
  setLang(currentLang === "ar" ? "en" : "ar");
}

setLang(currentLang);
