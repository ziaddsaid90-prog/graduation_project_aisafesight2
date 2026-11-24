const CHART_COLORS = {
  blue: "#3b82f6",
  orange: "#f59e0b",
  red: "#ef4444",
  purple: "#a855f7",
  green: "#22c55e",
  muted: "#94a3b8",
  grid: "rgba(148, 163, 184, 0.14)",
};
const TYPE_COLORS = { no_helmet: CHART_COLORS.blue, no_vest: CHART_COLORS.orange, no_helmet_no_vest: CHART_COLORS.red,
                      chain_open: CHART_COLORS.purple };
if (typeof Chart !== "undefined") {
  Chart.defaults.color = CHART_COLORS.muted;
  Chart.defaults.font.family = "Segoe UI, Tahoma, Arial";
}

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
  const empty = document.getElementById("chartsEmpty") || document.createElement("p");
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
        backgroundColor: CHART_COLORS.blue,
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
        legend: { display: true, position: "bottom", rtl: currentLang === "ar", labels: { color: CHART_COLORS.muted } },
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
        backgroundColor: "rgba(34, 197, 94, 0.12)",
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

  renderOverviewCharts(data);
}

function average(values) {
  const nums = values.filter(function (v) { return v !== null && v !== undefined; });
  return nums.length ? nums.reduce(function (a, b) { return a + b; }, 0) / nums.length : null;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

// Small line in a KPI card (SVG, no Chart.js): the series scaled to the box
function drawSpark(id, values) {
  const svg = document.getElementById(id);
  if (!svg) return;
  const nums = values.map(function (v) { return v === null || v === undefined ? NaN : v; });
  const valid = nums.filter(function (v) { return !isNaN(v); });
  if (valid.length < 2) {
    svg.innerHTML = "";
    return;
  }
  const min = Math.min.apply(null, valid), max = Math.max.apply(null, valid);
  const step = 100 / (nums.length - 1);
  const rtl = currentLang === "ar";
  const points = [];
  nums.forEach(function (v, i) {
    if (isNaN(v)) return;
    const x = rtl ? 100 - i * step : i * step;
    const y = max === min ? 16 : 29 - ((v - min) / (max - min)) * 26;
    points.push(x.toFixed(1) + "," + y.toFixed(1));
  });
  svg.innerHTML = '<polyline fill="none" stroke-width="2" vector-effect="non-scaling-stroke" points="' + points.join(" ") + '"/>';
}

// The overview page: trend chart, safety score ring, top violations, site statistics
function renderOverviewCharts(data) {
  const avgCompliance = average(data.complianceByDay);
  const todayCompliance = data.complianceByDay[data.complianceByDay.length - 1];
  const score = todayCompliance !== null && todayCompliance !== undefined ? todayCompliance : avgCompliance;
  const ring = document.getElementById("scoreRing");
  if (ring) {
    ring.style.setProperty("--pct", score === null ? 0 : score);
    setText("scoreValue", score === null ? "-" : Math.round(score) + "%");
  }
  drawSpark("sparkAlerts", data.violationsByDay);
  drawSpark("sparkCompliance", data.complianceByDay);

  const rtl = currentLang === "ar";
  if (document.getElementById("chartTrend")) {
    upsertChart("chartTrend", {
      type: "line",
      data: {
        labels: data.days.map(dayLabel),
        datasets: [
          {
            label: t("violationsLabel"),
            data: data.violationsByDay,
            borderColor: CHART_COLORS.orange,
            backgroundColor: "rgba(245, 158, 11, 0.14)",
            fill: true,
            tension: 0.35,
            cubicInterpolationMode: "monotone",
            pointRadius: 3,
            yAxisID: "y",
          },
          {
            label: t("safetyScore"),
            data: data.complianceByDay,
            borderColor: CHART_COLORS.blue,
            backgroundColor: CHART_COLORS.blue,
            tension: 0.35,
            cubicInterpolationMode: "monotone",
            spanGaps: true,
            pointRadius: 3,
            yAxisID: "y2",
          },
        ],
      },
      options: baseOptions({
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: true, position: "top", align: "end", rtl: rtl,
                    labels: { boxWidth: 8, boxHeight: 8, usePointStyle: true, color: CHART_COLORS.muted } },
          tooltip: { rtl: rtl, textDirection: rtl ? "rtl" : "ltr" },
        },
        scales: {
          x: { reverse: rtl, grid: { display: false }, ticks: { color: CHART_COLORS.muted } },
          y: { beginAtZero: true, position: rtl ? "right" : "left", ticks: { color: CHART_COLORS.muted, precision: 0 },
               grid: { color: CHART_COLORS.grid } },
          y2: { min: 0, max: 100, position: rtl ? "left" : "right", grid: { display: false },
                ticks: { color: CHART_COLORS.muted, callback: function (v) { return v + "%"; } } },
        },
      }),
    });
  }

  const types = Object.keys(data.violationsByType);
  const total = types.reduce(function (a, k) { return a + data.violationsByType[k]; }, 0);
  if (document.getElementById("chartTop")) {
    upsertChart("chartTop", {
      type: "doughnut",
      data: {
        labels: types.map(function (k) { return t(k); }),
        datasets: [{
          data: total ? types.map(function (k) { return data.violationsByType[k]; }) : [1],
          backgroundColor: total ? types.map(function (k) { return TYPE_COLORS[k] || CHART_COLORS.muted; }) : [CHART_COLORS.grid],
          borderWidth: 0,
        }],
      },
      options: baseOptions({ cutout: "58%", scales: {},
                             plugins: { legend: { display: false }, tooltip: { enabled: total > 0, rtl: rtl } } }),
    });
    document.getElementById("topLegend").innerHTML = types.map(function (k) {
      const pct = total ? Math.round((100 * data.violationsByType[k]) / total) : 0;
      return '<li><i style="background:' + (TYPE_COLORS[k] || CHART_COLORS.muted) + '"></i><span>' + t(k) +
             "</span><b>" + pct + "%</b></li>";
    }).join("");
  }

  setText("siteTotal", data.violationsByDay.reduce(function (a, b) { return a + b; }, 0));
  setText("siteCompliance", avgCompliance === null ? "-" : Math.round(avgCompliance) + "%");
  const peak = Math.max.apply(null, data.violationsByHour);
  setText("sitePeak", peak > 0 ? hourLabel(data.violationsByHour.indexOf(peak)) : "-");
  const common = types.filter(function (k) { return data.violationsByType[k] > 0; })
    .sort(function (a, b) { return data.violationsByType[b] - data.violationsByType[a]; })[0];
  setText("siteCommon", common ? t(common) : "-");
}

document.addEventListener("DOMContentLoaded", function () {
  const selects = document.querySelectorAll(".chart-range");
  selects.forEach(function (select) {
    select.addEventListener("change", function () {
      chartDays = Number(select.value);
      selects.forEach(function (s) { s.value = select.value; });
      renderCharts();
    });
  });
});

