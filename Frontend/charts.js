const CHART_COLORS = {
  navy: "#0f172a",
  orange: "#f59e0b",
  red: "#dc2626",
  amber: "#d97706",
  green: "#16a34a",
  muted: "#64748b",
  grid: "#e2e8f0",
};
const TYPE_COLORS = { no_helmet: CHART_COLORS.red, no_vest: CHART_COLORS.orange, chain_open: CHART_COLORS.navy };

const charts = {};
let chartDays = 7;

function chartLocale() {
  return currentLang === "ar" ? "ar-EG-u-nu-latn" : "en-GB";
}

function dayLabel(iso) {
  return new Date(iso + "T00:00").toLocaleDateString(chartLocale(), { weekday: "short", day: "numeric" });
}

function hourLabel(h) {
  return String(h).padStart(2, "0") + ":00";
}

function baseOptions(extra) {
  const rtl = currentLang === "ar";
  return Object.assign(
    {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: { display: false, rtl: rtl, labels: { font: { family: "Segoe UI, Tahoma, Arial" } } },
        tooltip: { rtl: rtl, textDirection: rtl ? "rtl" : "ltr" },
      },
      scales: {
        x: { reverse: rtl, grid: { display: false }, ticks: { color: CHART_COLORS.muted } },
        y: { beginAtZero: true, ticks: { color: CHART_COLORS.muted, precision: 0 }, grid: { color: CHART_COLORS.grid } },
      },
    },
    extra || {},
  );
}

function upsertChart(id, config) {
  const existing = charts[id];
  if (existing && existing.config.type === config.type) {
    existing.data = config.data;
    existing.options = config.options;
    existing.update();
    return;
  }
  if (existing) existing.destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

async function renderCharts() {
  if (!hasPermission("view_stats") || typeof Chart === "undefined") return;
  const empty = document.getElementById("chartsEmpty");
  let data;
  try {
    data = await getAnalytics(chartDays);
  } catch (e) {
    if (e.status === 401) return logout();
    empty.textContent = t("apiError");
    empty.hidden = false;
    return;
  }

  const total = data.violationsByDay.reduce(function (a, b) { return a + b; }, 0);
  empty.textContent = t("noChartData");
  empty.hidden = total > 0;

  upsertChart("chartHour", {
    type: "line",
    data: {
      labels: data.hours.map(hourLabel),
      datasets: [{
        label: t("violation"),
        data: data.violationsByHour,
        borderColor: CHART_COLORS.orange,
        backgroundColor: "rgba(245, 158, 11, 0.15)",
        fill: true,
        tension: 0.35,
        cubicInterpolationMode: "monotone",
        pointRadius: 2,
      }],
    },
    options: baseOptions(),
  });

  upsertChart("chartDay", {
    type: "bar",
    data: {
      labels: data.days.map(dayLabel),
      datasets: [{
        label: t("violation"),
        data: data.violationsByDay,
        backgroundColor: CHART_COLORS.navy,
        borderRadius: 6,
      }],
    },
    options: baseOptions(),
  });

  const types = Object.keys(data.violationsByType);
  upsertChart("chartType", {
    type: "doughnut",
    data: {
      labels: types.map(function (k) { return t(k); }),
      datasets: [{
        data: types.map(function (k) { return data.violationsByType[k]; }),
        backgroundColor: types.map(function (k) { return TYPE_COLORS[k] || CHART_COLORS.muted; }),
        borderWidth: 0,
      }],
    },
    options: baseOptions({
      cutout: "62%",
      scales: {},
      plugins: {
        legend: { display: true, position: "bottom", rtl: currentLang === "ar" },
        tooltip: { rtl: currentLang === "ar" },
      },
    }),
  });

  upsertChart("chartCompliance", {
    type: "line",
    data: {
      labels: data.days.map(dayLabel),
      datasets: [{
        label: t("compliance"),
        data: data.complianceByDay,
        borderColor: CHART_COLORS.green,
        backgroundColor: "rgba(22, 163, 74, 0.12)",
        fill: true,
        tension: 0.35,
        cubicInterpolationMode: "monotone",
        spanGaps: true,
        pointRadius: 3,
      }],
    },
    options: baseOptions({
      scales: {
        x: { reverse: currentLang === "ar", grid: { display: false }, ticks: { color: CHART_COLORS.muted } },
        y: {
          min: 0,
          max: 100,
          ticks: { color: CHART_COLORS.muted, callback: function (v) { return v + "%"; } },
          grid: { color: CHART_COLORS.grid },
        },
      },
    }),
  });
}

document.addEventListener("DOMContentLoaded", function () {
  const select = document.getElementById("chartDays");
  if (!select) return;
  select.addEventListener("change", function () {
    chartDays = Number(select.value);
    renderCharts();
  });
});
