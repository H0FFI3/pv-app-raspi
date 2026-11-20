"use strict";

const numberFormat = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
const shortDateFormat = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "short", timeZone: "UTC" });

const MIN_DAYS_FOR_HOUR_PROFILE = 5;
const MIN_POTENTIAL_FOR_HOUR_PROFILE = 0.05; // kWh je Stunde über alle Tage; darunter ist das Verhältnis nur Rauschen
const GREEN = "#197459";
const SUN = "#e5ad38";
const ORANGE = "#dc7b52";
const WEATHER_SOURCE_COLORS = {
  archive: "#2f7aa6",
  forecast: "#dc7b52",
};
const WEATHER_SOURCE_BANDS = {
  archive: "rgba(47, 122, 166, 0.16)",
  forecast: "rgba(220, 123, 82, 0.18)",
};
const POTENTIAL_MODEL_PALETTE = [
  "#dc7b52",
  "#2f7aa6",
  "#7c9d3a",
  "#8a57a2",
  "#d66a4d",
  "#4d8a7a",
  "#c77a13",
  "#6a5cc7",
  "#a24f63",
  "#3d7d4b",
];
const HEATMAP_COLORS = [
  { max: 50, color: "#d7634d" },
  { max: 60, color: "#de7d57" },
  { max: 70, color: "#efaf63" },
  { max: 80, color: "#f1d17a" },
  { max: 90, color: "#dce19b" },
  { max: 100, color: "#a7c76b" },
  { max: Infinity, color: "#197459" },
];
const CURTAILED_BAND = "rgba(220, 123, 82, 0.2)";
const CURTAILMENT_REASONS = { limit: "Einspeiselimit erreicht", battery: "Akku voll" };

let records = Array.isArray(window.PV_DAILY_DATA?.records) ? window.PV_DAILY_DATA.records : [];
let activeRange = 30;

const elements = {
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  publicStatus: document.querySelector("#public-status"),
  latestDate: document.querySelector("#latest-date"),
  actualValue: document.querySelector("#actual-value"),
  actualCaption: document.querySelector("#actual-caption"),
  potentialValue: document.querySelector("#potential-value"),
  potentialCaption: document.querySelector("#potential-caption"),
  sunshineValue: document.querySelector("#sunshine-value"),
  specificYieldValue: document.querySelector("#specific-yield-value"),
  performanceRatioValue: document.querySelector("#performance-ratio-value"),
  poaValue: document.querySelector("#poa-value"),
  modelWarning: document.querySelector("#model-provenance-warning"),
  energyCanvas: document.querySelector("#energy-chart"),
  sunshineCanvas: document.querySelector("#sunshine-chart"),
  ratioCanvas: document.querySelector("#ratio-chart"),
  hourlyCanvas: document.querySelector("#hourly-chart"),
  profileCanvas: document.querySelector("#profile-chart"),
  hourlyEmpty: document.querySelector("#hourly-empty"),
  hourlySelect: document.querySelector("#hourly-date"),
  profileEmpty: document.querySelector("#profile-empty"),
  profileEmptyText: document.querySelector("#profile-empty-text"),
  profileNote: document.querySelector("#profile-note"),
  analysisScatter: document.querySelector("#analysis-scatter"),
  analysisScatterEmpty: document.querySelector("#analysis-scatter-empty"),
  analysisResiduals: document.querySelector("#analysis-residuals"),
  analysisResidualsEmpty: document.querySelector("#analysis-residuals-empty"),
  analysisHistogram: document.querySelector("#analysis-histogram"),
  analysisHistogramEmpty: document.querySelector("#analysis-histogram-empty"),
  analysisTrend: document.querySelector("#analysis-trend"),
  analysisTrendEmpty: document.querySelector("#analysis-trend-empty"),
  analysisHeatmap: document.querySelector("#analysis-heatmap"),
  analysisHeatmapEmpty: document.querySelector("#analysis-heatmap-empty"),
  analysisCurtailment: document.querySelector("#analysis-curtailment"),
  analysisCurtailmentEmpty: document.querySelector("#analysis-curtailment-empty"),
  analysisSoc: document.querySelector("#analysis-soc"),
  analysisSocEmpty: document.querySelector("#analysis-soc-empty"),
  analysisMetrics: document.querySelector("#analysis-metrics"),
  analysisReferenceEmpty: document.querySelector("#analysis-reference-empty"),
  analysisReferenceEmptyText: document.querySelector("#analysis-reference-empty-text"),
  analysisReferenceCanvas: document.querySelector("#analysis-reference"),
  regressionNote: document.querySelector("#analysis-regression-note"),
  annualNote: document.querySelector("#analysis-annual-note"),
  anomalies: document.querySelector("#analysis-anomalies"),
  hourlyCurtailmentNote: document.querySelector("#hourly-curtailment-note"),
  hourlyCurtailedLegend: document.querySelector("#hourly-curtailed-legend"),
  energyEmpty: document.querySelector("#energy-empty"),
  sunshineEmpty: document.querySelector("#sunshine-empty"),
  ratioEmpty: document.querySelector("#ratio-empty"),
  historyBody: document.querySelector("#history-body"),
  historyCount: document.querySelector("#history-count"),
  summaryBody: document.querySelector("#summary-body"),
  completenessSection: document.querySelector(".completeness-section"),
  completenessCalendar: document.querySelector("#completeness-calendar"),
  completenessSummary: document.querySelector("#completeness-summary"),
  runHistoryBody: document.querySelector("#run-history-body"),
  sourceNote: document.querySelector("#source-note"),
  exportButton: document.querySelector("#export-button"),
};

/* ------------------------------------------------------------------ Hilfsfunktionen */

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number.isFinite(Number(value)) ? numberFormat.format(Number(value)) : "-";
}

function formatDate(value) {
  return dateFormat.format(new Date(`${value}T12:00:00Z`));
}

function formatShortDate(value) {
  return shortDateFormat.format(new Date(`${value}T12:00:00Z`));
}

function addDays(isoDate, days) {
  const date = new Date(`${isoDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function ratioPercent(actual, potential) {
  if (actual === null || actual === undefined || actual === "" || potential === null || potential === undefined || potential === "") return null;
  const a = Number(actual);
  const p = Number(potential);
  return Number.isFinite(a) && Number.isFinite(p) && p > 0 ? (a / p) * 100 : null;
}

function sumOf(items, key) {
  return items.reduce((total, item) => total + (Number(item[key]) || 0), 0);
}

function visibleRecords() {
  return activeRange === "all" ? records : records.slice(-activeRange);
}

/* ------------------------------------------------------------ Tooltips (Maus, Touch, Tastatur) */

function tooltipFor(canvas) {
  return document.getElementById(canvas.dataset.tooltipId);
}

function hideTooltip(canvas) {
  const tooltip = tooltipFor(canvas);
  if (tooltip) tooltip.hidden = true;
  if (canvas.pvChart) canvas.pvChart.activeIndex = null;
}

function showTooltip(canvas, index, pointerY) {
  const chart = canvas.pvChart;
  const tooltip = tooltipFor(canvas);
  if (!chart || !tooltip || !chart.data.length) return;

  const bounds = canvas.getBoundingClientRect();
  const slotWidth = (bounds.width - chart.left - chart.right) / chart.data.length;
  const safeIndex = Math.max(0, Math.min(chart.data.length - 1, index));
  const item = chart.data[safeIndex];
  chart.activeIndex = safeIndex;

  const lines = chart.tooltipLines
    ? chart.tooltipLines(item)
    : [
        chart.title(item),
        `${chart.label}: ${formatNumber(item[chart.valueKey])} ${chart.unit}`,
        ...(chart.comparisonKey ? [`${chart.comparisonLabel}: ${formatNumber(item[chart.comparisonKey])} ${chart.unit}`] : []),
        ...(chart.extraLine && chart.extraLine(item) ? [chart.extraLine(item)] : []),
      ];
  tooltip.textContent = lines.join("\n");
  tooltip.hidden = false;

  const center = chart.left + slotWidth * (safeIndex + 0.5);
  const halfTooltip = tooltip.offsetWidth / 2;
  const left = Math.max(halfTooltip + 6, Math.min(bounds.width - halfTooltip - 6, center));
  const y = Math.max(tooltip.offsetHeight + 8, pointerY ?? bounds.height * 0.45);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${y}px`;
}

function bindChartInteraction(canvas) {
  if (canvas.dataset.interactionBound) return;
  canvas.dataset.interactionBound = "true";

  canvas.addEventListener("pointermove", (event) => {
    const chart = canvas.pvChart;
    if (!chart?.data.length) return hideTooltip(canvas);
    const bounds = canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    if (x < chart.left || x > bounds.width - chart.right) return hideTooltip(canvas);
    const index = chart.pickIndex
      ? chart.pickIndex(x, event.clientY - bounds.top, bounds)
      : Math.floor((x - chart.left) / ((bounds.width - chart.left - chart.right) / chart.data.length));
    if (index === null || index === undefined || index < 0) return hideTooltip(canvas);
    showTooltip(canvas, index, event.clientY - bounds.top - 10);
  });
  canvas.addEventListener("pointerleave", () => hideTooltip(canvas));
  canvas.addEventListener("blur", () => hideTooltip(canvas));
  canvas.addEventListener("focus", () => {
    const chart = canvas.pvChart;
    if (!chart?.data.length) return;
    let keyboardFocus = true;
    try {
      keyboardFocus = canvas.matches(":focus-visible");
    } catch (error) {
      keyboardFocus = true;
    }
    if (keyboardFocus) showTooltip(canvas, chart.data.length - 1);
  });
  canvas.addEventListener("keydown", (event) => {
    const chart = canvas.pvChart;
    if (!chart?.data.length) return;
    const last = chart.data.length - 1;
    let index = chart.activeIndex ?? last; // erster Tastendruck: zuerst den letzten (jüngsten) Wert zeigen
    if (event.key === "ArrowLeft") index = chart.activeIndex === null ? last : index - 1;
    else if (event.key === "ArrowRight") index = chart.activeIndex === null ? last : index + 1;
    else if (event.key === "Home") index = 0;
    else if (event.key === "End") index = last;
    else if (event.key === "Escape") return hideTooltip(canvas);
    else return;
    event.preventDefault();
    showTooltip(canvas, index);
  });
}

/* ---------------------------------------------------------------------------- Diagramm */

function drawChart(canvas, data, valueKey, color, comparisonKey = null, options = {}) {
  if (!canvas) return;
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height || !data.length) return;

  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);

  const left = 42;
  const right = 10;
  const top = 10;
  const bottom = 28;
  const plotWidth = bounds.width - left - right;
  const plotHeight = bounds.height - top - bottom;

  hideTooltip(canvas); // ein neu gezeichnetes Diagramm hat keinen gültigen Tooltip-Bezug mehr
  canvas.pvChart = {
    data,
    valueKey,
    comparisonKey,
    label: options.label || (valueKey === "sunshine_hours" ? "Sonne" : "Ist-Ertrag"),
    unit: options.unit || (valueKey === "sunshine_hours" ? "h" : "kWh"),
    comparisonLabel: options.comparisonLabel || "Potentieller Ertrag",
    title: options.title || ((item) => formatDate(item.date)),
    extraLine: options.extraLine || null,
    left,
    right,
    activeIndex: null,
  };
  bindChartInteraction(canvas);

  const values = data.flatMap((item) => [Number(item[valueKey]), comparisonKey ? Number(item[comparisonKey]) : 0]);
  const referenceLine = options.referenceLine ?? null;
  const maximum = Math.max(options.minimumMaximum ?? 1, referenceLine ?? 0, ...values.filter(Number.isFinite)) * 1.12;
  const slotWidth = plotWidth / data.length;
  const barWidth = Math.max(2, Math.min(18, slotWidth * (comparisonKey ? 0.5 : 0.62)));
  const yFor = (value) => top + plotHeight - (Math.max(0, Number(value)) / maximum) * plotHeight;

  context.font = "10px Trebuchet MS, sans-serif";
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (let tick = 0; tick <= 4; tick += 1) {
    const y = top + (plotHeight * tick) / 4;
    const value = maximum * (1 - tick / 4);
    context.strokeStyle = "#e8eeea";
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(bounds.width - right, y);
    context.stroke();
    context.fillStyle = "#687872";
    context.fillText(formatNumber(value), left - 7, y);
  }

  if (options.highlight) {
    data.forEach((item, index) => {
      const band = options.highlight(item);
      if (!band) return;
      context.fillStyle = band;
      context.fillRect(left + slotWidth * index, top, slotWidth, plotHeight);
    });
  }

  data.forEach((item, index) => {
    const raw = item[valueKey];
    if (raw === null || raw === undefined || !Number.isFinite(Number(raw))) return;
    const center = left + slotWidth * (index + 0.5);
    const y = yFor(raw);
    context.fillStyle = options.valueColor?.(item) || color;
    context.fillRect(center - barWidth / 2, y, barWidth, top + plotHeight - y);
  });

  if (referenceLine !== null) {
    context.save();
    context.strokeStyle = ORANGE;
    context.lineWidth = 1.5;
    context.setLineDash([5, 4]);
    context.beginPath();
    context.moveTo(left, yFor(referenceLine));
    context.lineTo(bounds.width - right, yFor(referenceLine));
    context.stroke();
    context.restore();
  }

  if (comparisonKey) {
    let previous = null;
    data.forEach((item, index) => {
      const raw = item[comparisonKey];
      if (raw === null || raw === undefined || !Number.isFinite(Number(raw))) {
        previous = null;
        return;
      }
      const point = {
        x: left + slotWidth * (index + 0.5),
        y: yFor(raw),
      };
      const color = options.comparisonColor?.(item) || modelColorForHash(item.config_hash, ORANGE);
      if (previous) {
        context.beginPath();
        context.moveTo(previous.x, previous.y);
        context.lineTo(point.x, point.y);
        context.lineWidth = 2;
        context.strokeStyle = color;
        context.stroke();
      }
      context.beginPath();
      context.arc(point.x, point.y, 2.5, 0, Math.PI * 2);
      context.fillStyle = color;
      context.fill();
      previous = point;
    });
  }

  const xLabel = options.xLabel || ((item) => formatShortDate(item.date));
  const labelStride = Math.max(1, Math.ceil(data.length / 6));
  context.fillStyle = "#687872";
  context.textAlign = "center";
  context.textBaseline = "top";
  data.forEach((item, index) => {
    if (index % labelStride !== 0 && index !== data.length - 1) return;
    context.fillText(xLabel(item), left + slotWidth * (index + 0.5), top + plotHeight + 8);
  });
}

/* ------------------------------------------------------------------------------ Anzeige */

function setEmptyState(hasData) {
  elements.energyEmpty.hidden = hasData;
  elements.sunshineEmpty.hidden = hasData;
  elements.ratioEmpty.hidden = hasData;
  elements.energyCanvas.hidden = !hasData;
  elements.sunshineCanvas.hidden = !hasData;
  elements.ratioCanvas.hidden = !hasData;
}

function renderMetrics() {
  const latest = records.at(-1);
  const installed = Number(window.PV_DAILY_DATA?.installed_kwp);
  if (!latest) {
    elements.actualValue.textContent = "-";
    elements.potentialValue.textContent = "-";
    elements.sunshineValue.textContent = "-";
    elements.latestDate.textContent = "Noch keine Daten";
    elements.actualCaption.textContent = "AlphaESS Tageswert";
    elements.potentialCaption.textContent = "Wetterbasiertes PV-Modell";
    elements.specificYieldValue.textContent = "-";
    elements.performanceRatioValue.textContent = "-";
    elements.poaValue.textContent = "-";
    return;
  }
  const difference = Number(latest.potential_kwh) - Number(latest.actual_kwh);
  const achieved = ratioPercent(latest.actual_kwh, latest.potential_kwh);
  elements.actualValue.textContent = formatNumber(latest.actual_kwh);
  elements.potentialValue.textContent = formatNumber(latest.potential_kwh);
  elements.sunshineValue.textContent = formatNumber(latest.sunshine_hours);
  const specificYield = Number.isFinite(installed) && installed > 0 ? Number(latest.actual_kwh) / installed : null;
  const poa = Number(latest.poa_kwh_m2);
  const performanceRatio = Number.isFinite(specificYield) && Number.isFinite(poa) && poa > 0
    ? (specificYield / poa) * 100
    : null;
  elements.specificYieldValue.textContent = formatNumber(specificYield);
  elements.performanceRatioValue.textContent = formatNumber(performanceRatio);
  elements.poaValue.textContent = formatNumber(latest.poa_kwh_m2);
  elements.latestDate.textContent = formatDate(latest.date);
  elements.actualCaption.textContent = achieved === null ? "AlphaESS Tageswert" : `${formatNumber(achieved)} % des Potenzials`;
  elements.potentialCaption.textContent = `Abstand zum Ist: ${formatNumber(difference)} kWh`;
}

function appendRow(body, values) {
  const row = document.createElement("tr");
  values.forEach((value) => {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.append(cell);
  });
  body.append(row);
  return row;
}

function appendEmptyRow(body, columns, text) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.className = "table-empty";
  cell.textContent = text;
  row.append(cell);
  body.append(row);
}

function curtailmentText(curtailment) {
  if (!curtailment) return "-";
  if (!curtailment.hours) return "keine";
  return `${curtailment.hours} h · ${formatNumber(curtailment.lost_kwh)} kWh`;
}

function combineCurtailment(items) {
  const checked = items.filter((item) => item.curtailment);
  if (!checked.length) return null;
  return {
    hours: checked.reduce((total, item) => total + item.curtailment.hours, 0),
    lost_kwh: checked.reduce((total, item) => total + item.curtailment.lost_kwh, 0),
    lost_kwh_upper: checked.every((item) => Number.isFinite(item.curtailment.lost_kwh_upper))
      ? checked.reduce((total, item) => total + item.curtailment.lost_kwh_upper, 0)
      : null,
  };
}

function hourlyTooltipExtra(item) {
  const lines = [];
  if (item.curtailed) lines.push(`Abregelung wahrscheinlich: ${CURTAILMENT_REASONS[item.curtailed] || "erkannt"}`);
  const signals = [];
  if (Number.isFinite(item.soc_pct)) signals.push(`Akku ${formatNumber(item.soc_pct)} %`);
  if (Number.isFinite(item.feed_in_signed_w)) {
    const power = Math.round(Math.abs(item.feed_in_signed_w));
    const direction = item.feed_in_signed_w > 0 ? "Einspeisung" : item.feed_in_signed_w < 0 ? "Netzbezug" : "Netzleistung";
    signals.push(`${direction} ${power} W`);
  } else if (Number.isFinite(item.feed_in_w)) {
    signals.push(`Netzleistung (Betrag) ${Math.round(item.feed_in_w)} W`);
  }
  if (Number.isFinite(item.feed_in_max_w) && item.feed_in_max_w > 0) {
    signals.push(`Spitze ${Math.round(item.feed_in_max_w)} W`);
  }
  if (signals.length) lines.push(signals.join(" · "));
  return lines.join("\n");
}

function percentText(value) {
  return value === null ? "-" : `${formatNumber(value)} %`;
}

function modelColorForHash(hash, fallback = ORANGE) {
  if (!hash) return fallback;
  let total = 0;
  for (let index = 0; index < hash.length; index += 1) {
    total = (total * 31 + hash.charCodeAt(index)) >>> 0;
  }
  return POTENTIAL_MODEL_PALETTE[total % POTENTIAL_MODEL_PALETTE.length] || fallback;
}

function renderHistory(data) {
  elements.historyBody.replaceChildren();
  elements.historyCount.textContent = `${records.length} ${records.length === 1 ? "Tag" : "Tage"}`;
  if (!data.length) {
    appendEmptyRow(elements.historyBody, 6, "Die Tageshistorie wird nach dem ersten Lauf hier angezeigt.");
    return;
  }
  data
    .slice()
    .reverse()
    .slice(0, 14)
    .forEach((item) => {
      const row = appendRow(elements.historyBody, [
        formatDate(item.date),
        `${formatNumber(item.actual_kwh)} kWh`,
        `${formatNumber(item.potential_kwh)} kWh`,
        `${formatNumber(item.sunshine_hours)} h`,
        percentText(ratioPercent(item.actual_kwh, item.potential_kwh)),
        curtailmentText(item.curtailment),
      ]);
      const flags = item.quality?.flags;
      if (Array.isArray(flags) && flags.length) {
        const dateCell = row.firstElementChild;
        const descriptions = {
          low_coverage: "Geringe Abdeckung der Leistungsproben",
          epv_mismatch: "Stundenintegral weicht vom AlphaESS-Tageswert ab",
          hourly_missing: "Kein Stundenprofil vorhanden",
        };
        dateCell.textContent = `! ${formatDate(item.date)}`;
        dateCell.title = flags.map((flag) => descriptions[flag] || flag).join("; ");
        dateCell.setAttribute("aria-label", `${formatDate(item.date)}. Qualitäts-Hinweis: ${dateCell.title}`);
      }
    });
}

function summaryRows() {
  const latest = records.at(-1);
  if (!latest) return [];
  const month = latest.date.slice(0, 7);
  const weekStart = addDays(latest.date, -6);
  return [
    { label: "Letzte 7 Tage", items: records.filter((item) => item.date >= weekStart) },
    { label: `Laufender Monat (${latest.date.slice(5, 7)}/${latest.date.slice(0, 4)})`, items: records.filter((item) => item.date.startsWith(month)) },
    { label: `Laufendes Jahr (${latest.date.slice(0, 4)})`, items: records.filter((item) => item.date.startsWith(latest.date.slice(0, 4))) },
    { label: "Gesamter Zeitraum", items: records },
  ];
}

function renderSummary() {
  elements.summaryBody.replaceChildren();
  const rows = summaryRows();
  if (!rows.length) {
    appendEmptyRow(elements.summaryBody, 10, "Summen erscheinen nach dem ersten Datensatz.");
    return;
  }
  rows.forEach(({ label, items }) => {
    const actual = sumOf(items, "actual_kwh");
    const potential = sumOf(items, "potential_kwh");
    const installed = Number(window.PV_DAILY_DATA?.installed_kwp);
    const poa = items.reduce((total, item) => total + (Number(item.poa_kwh_m2) || 0), 0);
    const specific = Number.isFinite(installed) && installed > 0 ? actual / installed : null;
    const pr = specific !== null && poa > 0 ? (specific / poa) * 100 : null;
    appendRow(elements.summaryBody, [
      label,
      String(items.length),
      `${formatNumber(actual)} kWh`,
      `${formatNumber(potential)} kWh`,
      percentText(ratioPercent(actual, potential)),
      `${formatNumber(sumOf(items, "sunshine_hours"))} h`,
      formatNumber(specific),
      formatNumber(poa),
      percentText(pr),
      curtailmentText(combineCurtailment(items)),
    ]);
  });
}

function renderSourceNote() {
  const labels = { archive: "Open-Meteo-Archiv (ERA5-Reanalyse)", forecast: "Open-Meteo-Forecast (Modellanalyse)" };
  const counts = {};
  records.forEach((item) => {
    const key = labels[item.weather_source] ? item.weather_source : "unknown";
    counts[key] = (counts[key] || 0) + 1;
  });
  const parts = Object.entries(counts).map(([key, count]) => `${labels[key] || "Quelle nicht vermerkt (ältere Datensätze)"}: ${count} ${count === 1 ? "Tag" : "Tage"}`);
  elements.sourceNote.textContent = parts.length ? `Wetterquelle – ${parts.join("; ")}.` : "";
}

function renderMetricsSummary(data) {
  const pairs = data
    .filter((item) => item.actual_kwh !== null && item.actual_kwh !== undefined && item.potential_kwh !== null && item.potential_kwh !== undefined)
    .map((item) => [Number(item.actual_kwh), Number(item.potential_kwh)])
    .filter(([actual, potential]) => Number.isFinite(actual) && Number.isFinite(potential));
  if (!pairs.length) {
    elements.analysisMetrics.textContent = "MBE, RMSE, rMBD und MAPE erscheinen mit gültigen Ist- und Potenzialwerten.";
    return;
  }
  const errors = pairs.map(([actual, potential]) => potential - actual);
  const mean = (values) => values.reduce((total, value) => total + value, 0) / values.length;
  const mbe = mean(errors);
  const meanActual = mean(pairs.map(([actual]) => actual));
  const rmse = Math.sqrt(mean(errors.map((error) => error * error)));
  const rmbd = meanActual ? (mbe / meanActual) * 100 : null;
  const mapeValues = pairs
    .filter(([actual]) => actual !== 0)
    .map(([actual, potential]) => (Math.abs(potential - actual) / Math.abs(actual)) * 100);
  const mape = mapeValues.length ? mean(mapeValues) : null;
  elements.analysisMetrics.textContent =
    `${pairs.length} Tage im ausgewählten Zeitraum · MBE ${formatNumber(mbe)} kWh/Tag · ` +
    `RMSE ${formatNumber(rmse)} kWh/Tag · rMBD ${percentText(rmbd)} · MAPE ${percentText(mape)}`;
}

function drawReferenceChart() {
  const reference = window.PV_DAILY_DATA?.tmy_reference;
  const monthlyData = reference?.daily_kwh_by_month_day;
  const latest = records.at(-1);
  if (!monthlyData || !Object.keys(monthlyData).length) {
    elements.analysisReferenceEmpty.hidden = false;
    elements.analysisReferenceCanvas.hidden = true;
    elements.analysisReferenceEmptyText.textContent = window.PV_DAILY_DATA?.tmy_reference_stale
      ? "Die PVGIS-TMY-Referenz wurde mit einer anderen Modellkonfiguration berechnet. Bitte mit python analyze_pv.py aktualisieren."
      : "Keine PVGIS-TMY-Referenz vorhanden. Mit python analyze_pv.py lässt sie sich berechnen.";
    return;
  }
  if (!latest) {
    elements.analysisReferenceEmpty.hidden = false;
    elements.analysisReferenceCanvas.hidden = true;
    elements.analysisReferenceEmptyText.textContent = "Für den Soll-Ist-Vergleich werden Tagesdaten benötigt.";
    return;
  }
  elements.analysisReferenceEmpty.hidden = true;
  const monthLabel = new Intl.DateTimeFormat("de-DE", { month: "short", timeZone: "UTC" });
  const monthTitle = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric", timeZone: "UTC" });
  const months = new Map();
  records.forEach((item) => {
    const key = item.date.slice(0, 7);
    const period = months.get(key) || {
      key,
      label: monthLabel.format(new Date(`${key}-01T12:00:00Z`)).replace(/\.$/, ""),
      period: monthTitle.format(new Date(`${key}-01T12:00:00Z`)),
      actual: 0,
      expected: 0,
    };
    period.actual += Number(item.actual_kwh) || 0;
    const monthDay = item.date.slice(5);
    period.expected += Number(monthlyData[monthDay] ?? (monthDay === "02-29" ? monthlyData["02-28"] : 0)) || 0;
    months.set(key, period);
  });
  const data = [...months.values()].sort((a, b) => a.key.localeCompare(b.key));

  elements.analysisReferenceCanvas.hidden = false;
  const frame = beginAnalysisChart(elements.analysisReferenceCanvas, data, {
    title: (item) => item.period,
    tooltipLines: (item) => [
      item.period,
      `Ist-Ertrag: ${formatNumber(item.actual)} kWh`,
      `PVGIS-TMY-Soll: ${formatNumber(item.expected)} kWh`,
    ],
  });
  if (!frame) return;
  const maximum = Math.max(0.1, ...data.flatMap((item) => [item.actual, item.expected])) * 1.15;
  drawAnalysisAxes(frame.context, frame, maximum);
  const slot = frame.plotWidth / data.length;
  const barWidth = Math.min(24, slot * 0.34);
  data.forEach((item, index) => {
    const center = frame.left + slot * (index + 0.5);
    [item.actual, item.expected].forEach((value, seriesIndex) => {
      const height = value / maximum * frame.plotHeight;
      frame.context.fillStyle = seriesIndex === 0 ? GREEN : ORANGE;
      frame.context.fillRect(
        center + (seriesIndex === 0 ? -barWidth : 0),
        frame.top + frame.plotHeight - height,
        barWidth,
        height,
      );
    });
    frame.context.fillStyle = "#687872";
    frame.context.font = "10px Trebuchet MS, sans-serif";
    frame.context.textAlign = "center";
    frame.context.textBaseline = "top";
    frame.context.fillText(item.label, center, frame.top + frame.plotHeight + 5);
  });
}

function renderModelWarning() {
  const hashes = [...new Set(visibleRecords().map((item) => item.config_hash).filter(Boolean))];
  elements.modelWarning.hidden = hashes.length < 2;
  elements.modelWarning.textContent = hashes.length < 2
    ? ""
    : "Im ausgewählten Zeitraum wurden Potenziale mit unterschiedlichen Modellkonfigurationen berechnet. Für einen konsistenten Vergleich kannst du die Werte mit --recompute neu berechnen.";
}

function renderCompleteness() {
  const data = window.PV_DAILY_DATA?.completeness;
  if (!Array.isArray(data) || !data.length) {
    elements.completenessSection.hidden = true;
    return;
  }
  elements.completenessSection.hidden = false;
  elements.completenessCalendar.replaceChildren();
  const summary = window.PV_DAILY_DATA.completeness_summary || {};
  elements.completenessSummary.textContent =
    `${summary.missing || 0} Lücken gesamt · ${summary.outside_backfill || 0} außerhalb des Backfill-Fensters`;
  const months = new Map();
  data.forEach((item) => {
    const key = item.date.slice(0, 7);
    if (!months.has(key)) months.set(key, []);
    months.get(key).push(item);
  });
  const monthFormat = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric", timeZone: "UTC" });
  for (const [month, days] of months) {
    const [year, monthNumber] = month.split("-").map(Number);
    const panel = document.createElement("article");
    panel.className = "completeness-month";
    const heading = document.createElement("h3");
    heading.textContent = monthFormat.format(new Date(Date.UTC(year, monthNumber - 1, 1, 12)));
    panel.append(heading);
    const grid = document.createElement("div");
    grid.className = "completeness-days";
    grid.setAttribute("role", "list");
    const firstWeekday = (new Date(Date.UTC(year, monthNumber - 1, 1, 12)).getUTCDay() + 6) % 7;
    for (let blank = 0; blank < firstWeekday; blank += 1) {
      const spacer = document.createElement("span");
      spacer.className = "completeness-day empty";
      spacer.setAttribute("aria-hidden", "true");
      grid.append(spacer);
    }
    days.forEach((item) => {
      const cell = document.createElement("span");
      const statusClass = item.status === "fehlt"
        ? "missing"
        : item.status === "übersprungen"
          ? "skipped"
          : item.status === "ok" && !(item.flags || []).length
            ? ""
            : "flagged";
      cell.className = `completeness-day ${statusClass}`.trim();
      cell.textContent = String(Number(item.date.slice(-2)));
      const details = [item.status, item.reason, ...(item.flags || [])].filter(Boolean).join("; ");
      cell.title = `${formatDate(item.date)}: ${details}`;
      cell.setAttribute("role", "listitem");
      cell.setAttribute("aria-label", `${formatDate(item.date)}: ${details}`);
      grid.append(cell);
    });
    panel.append(grid);
    elements.completenessCalendar.append(panel);
  }
}

function renderRunHistory() {
  const runs = window.PV_DAILY_DATA?.runs;
  elements.runHistoryBody.replaceChildren();
  if (!Array.isArray(runs) || !runs.length) {
    appendEmptyRow(elements.runHistoryBody, 5, "Laufhistorie ist im Server-Dashboard verfügbar.");
    return;
  }
  const runDateFormat = new Intl.DateTimeFormat("de-DE", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
  runs.slice(0, 20).forEach((run) => {
    const finished = run.finished_at ? new Date(run.finished_at) : null;
    const duration = Number(run.duration_seconds);
    appendRow(elements.runHistoryBody, [
      finished && Number.isFinite(finished.getTime()) ? runDateFormat.format(finished) : "-",
      Number.isFinite(duration) ? `${formatNumber(duration)} s` : "-",
      String(run.days_ok || 0),
      String(run.days_skipped || 0),
      run.ok ? "Erfolgreich" : "Fehlgeschlagen",
    ]);
  });
}

async function pollPublicHealth() {
  if (!elements.publicStatus || !["http:", "https:"].includes(window.location.protocol)) return;
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const health = await response.json();
    const lastSuccess = health.last_success_date ? formatDate(health.last_success_date) : "Noch kein erfolgreicher Lauf";
    const updateTime = window.PV_DAILY_DATA?.update_time;
    const timezone = window.PV_DAILY_DATA?.timezone;
    const next = updateTime ? `Nächste Aktualisierung: täglich um ${updateTime} Uhr${timezone ? ` (${timezone})` : ""}` : "";
    elements.publicStatus.textContent = [
      `Zuletzt aktualisiert: ${lastSuccess}`,
      next,
      health.last_message,
    ].filter(Boolean).join(" · ");
    elements.publicStatus.dataset.state = health.ok ? "ok" : "stale";
    elements.publicStatus.hidden = false;
  } catch (error) {
    elements.publicStatus.hidden = true;
  } finally {
    window.setTimeout(pollPublicHealth, 60000);
  }
}

function describeSeries(name, data, valueText) {
  if (!data.length) return `${name}: keine Daten.`;
  return `${name}, ${data.length} ${data.length === 1 ? "Tag" : "Tage"} von ${formatShortDate(data[0].date)} bis ${formatShortDate(data.at(-1).date)}. ${valueText} Mit Pfeiltasten den Tag wechseln.`;
}

function weatherSourceLabel(source) {
  if (source === "archive") return "Open-Meteo-Archiv";
  if (source === "forecast") return "Open-Meteo-Forecast";
  return null;
}

function weatherSourceOptions() {
  return {
    highlight: (item) => WEATHER_SOURCE_BANDS[item.weather_source] || null,
    extraLine: (item) => {
      const source = weatherSourceLabel(item.weather_source);
      return source ? `Wetterdaten: ${source}` : null;
    },
  };
}

/* --------------------------------------------------------------- Stunden- und Tageszeit-Diagramme */

function daysWithHourly() {
  return records.filter((record) => Array.isArray(record.hourly) && record.hourly.length > 0);
}

function populateHourlySelect() {
  const availableDays = daysWithHourly();
  elements.hourlySelect.replaceChildren();
  if (!availableDays.length) {
    elements.hourlySelect.disabled = true;
    document.querySelector("#hourly-prev").disabled = true;
    document.querySelector("#hourly-next").disabled = true;
    return;
  }
  for (const record of availableDays) {
    const option = document.createElement("option");
    option.value = record.date;
    option.textContent = formatDate(record.date);
    elements.hourlySelect.append(option);
  }
  elements.hourlySelect.value = availableDays.at(-1).date;
  elements.hourlySelect.disabled = false;
  document.querySelector("#hourly-prev").disabled = false;
  document.querySelector("#hourly-next").disabled = false;
}

function stepHourlyDay(direction) {
  const availableDays = daysWithHourly();
  if (!availableDays.length) return;
  const current = availableDays.findIndex((record) => record.date === elements.hourlySelect.value);
  const nextIndex = current >= 0 ? Math.min(availableDays.length - 1, Math.max(0, current + direction)) : availableDays.length - 1;
  const target = availableDays[nextIndex];
  if (!target) return;
  elements.hourlySelect.value = target.date;
  drawHourlyChart();
}

function renderHourlyCurtailmentNote(day) {
  const info = day.curtailment;
  elements.hourlyCurtailedLegend.hidden = !(info && info.hours > 0);
  if (!info) {
    elements.hourlyCurtailmentNote.textContent = day.signals_checked
      ? "AlphaESS liefert für diesen Tag keine Akku- oder Netzdaten; Abregelung kann nicht beurteilt werden."
      : "Dieser Tag wurde vor der Abregelungserkennung erfasst. Beim nächsten Start werden die Akku- und Netzdaten nachgeladen.";
  } else if (!info.hours) {
    elements.hourlyCurtailmentNote.textContent = "Keine Abregelung erkannt.";
  } else {
    const label = info.hours === 1 ? "Stunde" : "Stunden";
    const upper = info.lost_kwh_upper === null
      ? ""
      : `, Obergrenze ${formatNumber(info.lost_kwh_upper)} kWh (Potenzial minus Ist, inklusive Modellabweichung)`;
    elements.hourlyCurtailmentNote.textContent = `${info.hours} ${label} mit wahrscheinlicher Abregelung: geschätzt ${formatNumber(info.lost_kwh)} kWh${upper}.`;
  }
}

function drawHourlyChart() {
  const availableDays = daysWithHourly();
  const selectedDay = availableDays.find((record) => record.date === elements.hourlySelect.value) || availableDays.at(-1);
  if (!selectedDay) {
    elements.hourlyCanvas.hidden = true;
    elements.hourlyEmpty.hidden = false;
    elements.hourlyCurtailedLegend.hidden = true;
    elements.hourlyCurtailmentNote.textContent = "";
    return;
  }
  elements.hourlyCanvas.hidden = false;
  elements.hourlyEmpty.hidden = true;
  renderHourlyCurtailmentNote(selectedDay);
  drawChart(elements.hourlyCanvas, selectedDay.hourly, "actual_kwh", GREEN, "potential_kwh", {
    unit: "kWh",
    comparisonLabel: "Potentieller Ertrag",
    title: (item) => `${formatDate(selectedDay.date)} · ${item.hour}`,
    xLabel: (item) => item.hour.slice(0, 2),
    highlight: (item) => (item.curtailed ? CURTAILED_BAND : null),
    extraLine: hourlyTooltipExtra,
  });
}

function hourProfile() {
  const days = daysWithHourly().filter((record) => record.hourly.some((point) => point.actual_kwh !== null && point.actual_kwh !== undefined));
  const sums = new Map();
  let excluded = 0;
  days.forEach((record) => {
    record.hourly.forEach((point) => {
      if (point.actual_kwh === null || point.actual_kwh === undefined) return;
      if (point.curtailed) {
        excluded += 1; // abgeregelte Stunden würden Verschattung vortäuschen
        return;
      }
      const entry = sums.get(point.hour) || { hour: point.hour, actual: 0, potential: 0, days: 0 };
      entry.actual += Number(point.actual_kwh);
      entry.potential += Number(point.potential_kwh);
      entry.days += 1;
      sums.set(point.hour, entry);
    });
  });
  const data = [...sums.values()]
    .filter((entry) => entry.potential >= MIN_POTENTIAL_FOR_HOUR_PROFILE)
    .sort((a, b) => a.hour.localeCompare(b.hour))
    .map((entry) => ({ hour: entry.hour, ratio_pct: ratioPercent(entry.actual, entry.potential), days: entry.days }));
  return { dayCount: days.length, data, excluded };
}

function drawProfileChart() {
  const { dayCount, data, excluded } = hourProfile();
  elements.profileNote.textContent = excluded ? `${excluded} als abgeregelt erkannte Stundenwerte wurden aus dieser Auswertung ausgenommen.` : "";
  const enough = dayCount >= MIN_DAYS_FOR_HOUR_PROFILE && data.length > 0;
  elements.profileCanvas.hidden = !enough;
  elements.profileEmpty.hidden = enough;
  if (!enough) {
    elements.profileEmptyText.textContent = `Die Auswertung erscheint ab ${MIN_DAYS_FOR_HOUR_PROFILE} Tagen mit Stundenprofil (aktuell ${dayCount}).`;
    return;
  }
  drawChart(elements.profileCanvas, data, "ratio_pct", GREEN, null, {
    label: "Ø Ist/Potenzial",
    unit: "%",
    referenceLine: 100,
    minimumMaximum: 100,
    title: (item) => `${item.hour} Uhr`,
    extraLine: (item) => `Basis: ${item.days} ${item.days === 1 ? "Tag" : "Tage"}`,
    xLabel: (item) => item.hour.slice(0, 2),
  });
}

function validPairs(data) {
  return data.filter((item) => item.actual_kwh !== null && item.actual_kwh !== undefined && item.potential_kwh !== null && item.potential_kwh !== undefined && Number.isFinite(Number(item.actual_kwh)) && Number.isFinite(Number(item.potential_kwh)) && Number(item.actual_kwh) >= 0 && Number(item.potential_kwh) > 0);
}

function setAnalysisState(canvas, empty, hasData) {
  canvas.hidden = !hasData;
  empty.hidden = hasData;
}

function beginAnalysisChart(canvas, data, { left = 44, right = 12, top = 10, bottom = 28, title, tooltipLines, pickIndex } = {}) {
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height || !data.length) return null;
  const pixelRatio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * pixelRatio);
  canvas.height = Math.round(bounds.height * pixelRatio);
  const context = canvas.getContext("2d");
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  hideTooltip(canvas);
  canvas.pvChart = {
    data,
    title: title || ((item) => formatDate(item.date)),
    tooltipLines,
    pickIndex,
    left,
    right,
    activeIndex: null,
  };
  bindChartInteraction(canvas);
  return { context, width: bounds.width, height: bounds.height, left, right, top, bottom, plotWidth: bounds.width - left - right, plotHeight: bounds.height - top - bottom };
}

function drawAnalysisAxes(context, frame, maximum, formatter = formatNumber) {
  context.font = "10px Trebuchet MS, sans-serif";
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (let tick = 0; tick <= 4; tick += 1) {
    const y = frame.top + (frame.plotHeight * tick) / 4;
    const value = maximum * (1 - tick / 4);
    context.strokeStyle = "#e8eeea";
    context.beginPath();
    context.moveTo(frame.left, y);
    context.lineTo(frame.width - frame.right, y);
    context.stroke();
    context.fillStyle = "#687872";
    context.fillText(formatter(value), frame.left - 6, y);
  }
}

function median(values) {
  const sorted = values.filter(Number.isFinite).slice().sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function drawScatterAnalysis() {
  const data = validPairs(records);
  const enough = data.length >= 2;
  setAnalysisState(elements.analysisScatter, elements.analysisScatterEmpty, enough);
  setAnalysisState(elements.analysisResiduals, elements.analysisResidualsEmpty, enough);
  if (!enough) {
    elements.regressionNote.textContent = "";
    return;
  }
  const actual = data.map((item) => Number(item.actual_kwh));
  const potential = data.map((item) => Number(item.potential_kwh));
  const xMean = potential.reduce((sum, value) => sum + value, 0) / data.length;
  const yMean = actual.reduce((sum, value) => sum + value, 0) / data.length;
  const denominator = potential.reduce((sum, value) => sum + (value - xMean) ** 2, 0);
  const slope = denominator ? data.reduce((sum, item) => sum + (Number(item.potential_kwh) - xMean) * (Number(item.actual_kwh) - yMean), 0) / denominator : 0;
  const intercept = yMean - slope * xMean;
  const limit = Math.max(...actual, ...potential, 1) * 1.08;
  const frame = beginAnalysisChart(elements.analysisScatter, data, {
    title: (item) => formatDate(item.date),
    tooltipLines: (item) => [formatDate(item.date), `Ist: ${formatNumber(item.actual_kwh)} kWh`, `Potenzial: ${formatNumber(item.potential_kwh)} kWh`, `Residuum: ${formatNumber(Number(item.actual_kwh) - Number(item.potential_kwh))} kWh`],
    pickIndex: (x, y, bounds) => {
      let closest = -1;
      let distance = Infinity;
      data.forEach((item, index) => {
        const px = 44 + (Number(item.potential_kwh) / limit) * (bounds.width - 56);
        const py = 10 + (1 - Number(item.actual_kwh) / limit) * (bounds.height - 38);
        const candidate = (px - x) ** 2 + (py - y) ** 2;
        if (candidate < distance) { distance = candidate; closest = index; }
      });
      return closest;
    },
  });
  if (frame) {
    drawAnalysisAxes(frame.context, frame, limit);
    const coordinate = (value) => frame.left + (value / limit) * frame.plotWidth;
    const vertical = (value) => frame.top + frame.plotHeight - (value / limit) * frame.plotHeight;
    frame.context.save();
    frame.context.strokeStyle = ORANGE;
    frame.context.setLineDash([5, 4]);
    frame.context.beginPath();
    frame.context.moveTo(coordinate(0), vertical(0));
    frame.context.lineTo(coordinate(limit), vertical(limit));
    frame.context.stroke();
    frame.context.setLineDash([]);
    frame.context.strokeStyle = GREEN;
    frame.context.beginPath();
    frame.context.moveTo(coordinate(0), vertical(intercept));
    frame.context.lineTo(coordinate(limit), vertical(slope * limit + intercept));
    frame.context.stroke();
    data.forEach((item) => {
      frame.context.beginPath();
      frame.context.fillStyle = GREEN;
      frame.context.arc(coordinate(Number(item.potential_kwh)), vertical(Number(item.actual_kwh)), 3.2, 0, Math.PI * 2);
      frame.context.fill();
    });
    frame.context.restore();
    frame.context.fillStyle = "#687872";
    frame.context.font = "9px Trebuchet MS, sans-serif";
    frame.context.textAlign = "center";
    frame.context.textBaseline = "top";
    frame.context.fillText("Potenzial (kWh)", frame.left + frame.plotWidth / 2, frame.height - 14);
  }
  elements.regressionNote.textContent = `Regression: Ist = ${formatNumber(slope)} × Potenzial ${intercept < 0 ? "−" : "+"} ${formatNumber(Math.abs(intercept))} kWh.`;

  const residuals = data.map((item) => ({ ...item, residual_kwh: Number(item.actual_kwh) - Number(item.potential_kwh) }));
  const residualLimit = Math.max(...residuals.map((item) => Math.abs(item.residual_kwh)), 0.1) * 1.12;
  const residualFrame = beginAnalysisChart(elements.analysisResiduals, residuals, {
    title: (item) => formatDate(item.date),
    tooltipLines: (item) => [formatDate(item.date), `Residuum: ${formatNumber(item.residual_kwh)} kWh`],
  });
  if (residualFrame) {
    const context = residualFrame.context;
    const zero = residualFrame.top + residualFrame.plotHeight / 2;
    const slot = residualFrame.plotWidth / residuals.length;
    context.strokeStyle = "#aebbb4";
    context.beginPath();
    context.moveTo(residualFrame.left, zero);
    context.lineTo(residualFrame.width - residualFrame.right, zero);
    context.stroke();
    residuals.forEach((item, index) => {
      const height = (Math.abs(item.residual_kwh) / residualLimit) * (residualFrame.plotHeight / 2);
      context.fillStyle = item.residual_kwh >= 0 ? GREEN : ORANGE;
      context.fillRect(residualFrame.left + index * slot + slot * 0.15, item.residual_kwh >= 0 ? zero - height : zero, Math.max(2, slot * 0.7), height);
    });
    context.font = "10px Trebuchet MS, sans-serif";
    context.fillStyle = "#687872";
    context.textAlign = "right";
    context.fillText(`${formatNumber(residualLimit)} kWh`, residualFrame.left - 6, residualFrame.top + 5);
    context.fillText(`−${formatNumber(residualLimit)} kWh`, residualFrame.left - 6, residualFrame.top + residualFrame.plotHeight - 5);
  }
}

function drawRatioHistogram() {
  const ratios = validPairs(records).map((item) => ({ ...item, ratio_pct: ratioPercent(item.actual_kwh, item.potential_kwh) }));
  const data = ratios.length >= 3;
  setAnalysisState(elements.analysisHistogram, elements.analysisHistogramEmpty, data);
  if (!data) return;
  const bounds = [0, 50, 75, 100, 125, 150, 200, Infinity];
  const bins = bounds.slice(0, -1).map((start, index) => {
    const end = bounds[index + 1];
    const label = Number.isFinite(end) ? `${start}–${end}` : `≥${start}`;
    const members = ratios.filter((item) => item.ratio_pct >= start && item.ratio_pct < end);
    return { label, count: members.length, ratio_pct: members.length / ratios.length * 100, members, date: members.at(-1)?.date || "" };
  });
  const frame = beginAnalysisChart(elements.analysisHistogram, bins, {
    title: (item) => item.label,
    tooltipLines: (item) => [item.label, `${item.count} ${item.count === 1 ? "Tag" : "Tage"} (${formatNumber(item.ratio_pct)} %)`],
  });
  if (!frame) return;
  const maximum = Math.max(10, ...bins.map((item) => item.ratio_pct)) * 1.15;
  drawAnalysisAxes(frame.context, frame, maximum, (value) => `${formatNumber(value)}%`);
  const slot = frame.plotWidth / bins.length;
  bins.forEach((item, index) => {
    const height = item.ratio_pct / maximum * frame.plotHeight;
    frame.context.fillStyle = GREEN;
    frame.context.fillRect(frame.left + index * slot + slot * 0.12, frame.top + frame.plotHeight - height, slot * 0.76, height);
    frame.context.fillStyle = "#687872";
    frame.context.font = "9px Trebuchet MS, sans-serif";
    frame.context.textAlign = "center";
    frame.context.textBaseline = "top";
    frame.context.fillText(item.label, frame.left + slot * (index + 0.5), frame.top + frame.plotHeight + 5);
  });
}

function drawTrend() {
  const pairs = validPairs(records);
  const enough = pairs.length >= 7;
  setAnalysisState(elements.analysisTrend, elements.analysisTrendEmpty, enough);
  elements.annualNote.textContent = "";
  if (!enough) return;
  let startIndex = 0;
  const data = pairs.map((item, index) => {
    const start = addDays(item.date, -29);
    while (pairs[startIndex].date < start) startIndex += 1;
    const window = pairs.slice(startIndex, index + 1);
    return {
      ...item,
      actual_median: median(window.map((entry) => Number(entry.actual_kwh))),
      potential_median: median(window.map((entry) => Number(entry.potential_kwh))),
      sample_count: window.length,
    };
  });
  const frame = beginAnalysisChart(elements.analysisTrend, data, {
    title: (item) => formatDate(item.date),
    tooltipLines: (item) => [formatDate(item.date), `30-Tage-Median Ist: ${formatNumber(item.actual_median)} kWh`, `30-Tage-Median Potenzial: ${formatNumber(item.potential_median)} kWh`, `Tageswerte im Fenster: ${item.sample_count}`],
  });
  if (frame) {
    const maximum = Math.max(...data.flatMap((item) => [item.actual_median, item.potential_median])) * 1.12;
    drawAnalysisAxes(frame.context, frame, maximum);
    const slot = frame.plotWidth / data.length;
    for (const [key, color] of [["potential_median", ORANGE], ["actual_median", GREEN]]) {
      frame.context.strokeStyle = color;
      frame.context.lineWidth = 2;
      frame.context.beginPath();
      data.forEach((item, index) => {
        const x = frame.left + slot * (index + 0.5);
        const y = frame.top + frame.plotHeight - item[key] / maximum * frame.plotHeight;
        if (!index) frame.context.moveTo(x, y); else frame.context.lineTo(x, y);
      });
      frame.context.stroke();
    }
    frame.context.fillStyle = "#687872";
    frame.context.font = "9px Trebuchet MS, sans-serif";
    frame.context.textAlign = "center";
    frame.context.textBaseline = "top";
    const stride = Math.max(1, Math.ceil(data.length / 6));
    data.forEach((item, index) => {
      if (index % stride === 0 || index === data.length - 1) frame.context.fillText(formatShortDate(item.date), frame.left + slot * (index + 0.5), frame.top + frame.plotHeight + 5);
    });
  }

  const latest = records.at(-1);
  const previousStart = addDays(latest.date, -394);
  const previousEnd = addDays(latest.date, -365);
  const previousYear = validPairs(records.filter((item) => item.date >= previousStart && item.date <= previousEnd));
  const currentStart = addDays(latest.date, -29);
  const current = validPairs(records.filter((item) => item.date >= currentStart && item.date <= latest.date));
  if (current.length >= 7 && previousYear.length >= 7) {
    const currentRatio = ratioPercent(sumOf(current, "actual_kwh"), sumOf(current, "potential_kwh"));
    const previousRatio = ratioPercent(sumOf(previousYear, "actual_kwh"), sumOf(previousYear, "potential_kwh"));
    elements.annualNote.textContent = `30-Tage-Jahresvergleich Ist/Potenzial: ${formatNumber(currentRatio)} % aktuell gegenüber ${formatNumber(previousRatio)} % im Vorjahr.`;
  } else {
    elements.annualNote.textContent = "Jahresvergleich noch nicht verfügbar: Für denselben Zeitraum im Vorjahr fehlen mindestens sieben Tageswerte.";
  }
}

function heatColor(ratio) {
  if (!Number.isFinite(ratio)) return HEATMAP_COLORS.at(-1).color;
  if (ratio < 50) return HEATMAP_COLORS[0].color;
  if (ratio < 60) return HEATMAP_COLORS[1].color;
  if (ratio < 70) return HEATMAP_COLORS[2].color;
  if (ratio < 80) return HEATMAP_COLORS[3].color;
  if (ratio < 90) return HEATMAP_COLORS[4].color;
  if (ratio <= 100) return HEATMAP_COLORS[5].color;
  return HEATMAP_COLORS.at(-1).color;
}

function drawHeatmap() {
  const days = daysWithHourly().slice(-30);
  const cells = [];
  const hours = [...new Set(days.flatMap((day) => day.hourly.map((point) => point.hour)))].sort();
  days.forEach((day, dayIndex) => day.hourly.forEach((point) => {
    const ratio = ratioPercent(point.actual_kwh, point.potential_kwh);
    if (ratio === null || !Number.isFinite(ratio)) return;
    cells.push({ date: day.date, hour: point.hour, ratio_pct: ratio, dayIndex, hourIndex: hours.indexOf(point.hour) });
  }));
  const enough = cells.length > 0;
  setAnalysisState(elements.analysisHeatmap, elements.analysisHeatmapEmpty, enough);
  if (!enough) return;
  let geometry;
  const frame = beginAnalysisChart(elements.analysisHeatmap, cells, {
    left: 44, right: 8, top: 10, bottom: 30,
    title: (item) => `${formatDate(item.date)} · ${item.hour}`,
    tooltipLines: (item) => [`${formatDate(item.date)} · ${item.hour}`, `Ist / Potenzial: ${formatNumber(item.ratio_pct)} %`],
    pickIndex: (x, y) => {
      if (!geometry) return -1;
      const dayIndex = Math.floor((x - geometry.left) / geometry.cellWidth);
      const hourIndex = Math.floor((y - geometry.top) / geometry.cellHeight);
      return cells.findIndex((cell) => cell.dayIndex === dayIndex && cell.hourIndex === hourIndex);
    },
  });
  if (!frame) return;
  geometry = { left: frame.left, top: frame.top, cellWidth: frame.plotWidth / days.length, cellHeight: frame.plotHeight / Math.max(hours.length, 1) };
  frame.context.font = "8px Trebuchet MS, sans-serif";
  cells.forEach((cell) => {
    frame.context.fillStyle = heatColor(Math.min(cell.ratio_pct, 150));
    frame.context.fillRect(frame.left + cell.dayIndex * geometry.cellWidth, frame.top + cell.hourIndex * geometry.cellHeight, Math.max(1, geometry.cellWidth - 1), Math.max(1, geometry.cellHeight - 1));
  });
  frame.context.fillStyle = "#687872";
  frame.context.textAlign = "right";
  frame.context.textBaseline = "middle";
  hours.forEach((hour, index) => frame.context.fillText(hour.slice(0, 2), frame.left - 5, frame.top + (index + 0.5) * geometry.cellHeight));
  frame.context.textAlign = "center";
  frame.context.textBaseline = "top";
  const stride = Math.max(1, Math.ceil(days.length / 6));
  days.forEach((day, index) => {
    if (index % stride === 0 || index === days.length - 1) frame.context.fillText(formatShortDate(day.date), frame.left + (index + 0.5) * geometry.cellWidth, frame.top + frame.plotHeight + 5);
  });
}

function drawCurtailmentSeries() {
  const months = new Map();
  records.forEach((record) => (record.hourly || []).forEach((point) => {
    if (point.curtailed !== "limit" && point.curtailed !== "battery") return;
    const potential = Number(point.potential_kwh);
    const actual = Number(point.actual_kwh);
    if (!Number.isFinite(potential) || !Number.isFinite(actual)) return;
    const month = record.date.slice(0, 7);
    const entry = months.get(month) || { month, limit: 0, battery: 0 };
    entry[point.curtailed] += Math.max(0, potential - actual);
    months.set(month, entry);
  }));
  const data = [...months.values()].sort((a, b) => a.month.localeCompare(b.month));
  setAnalysisState(elements.analysisCurtailment, elements.analysisCurtailmentEmpty, data.length > 0);
  if (!data.length) return;
  const frame = beginAnalysisChart(elements.analysisCurtailment, data, {
    title: (item) => item.month,
    tooltipLines: (item) => [`${item.month}`, `Einspeiselimit: ${formatNumber(item.limit)} kWh`, `Akku voll: ${formatNumber(item.battery)} kWh`],
  });
  if (!frame) return;
  const maximum = Math.max(0.1, ...data.map((item) => item.limit + item.battery)) * 1.15;
  drawAnalysisAxes(frame.context, frame, maximum);
  const slot = frame.plotWidth / data.length;
  data.forEach((item, index) => {
    const x = frame.left + index * slot + slot * 0.1;
    const barWidth = slot * 0.8;
    const limitHeight = item.limit / maximum * frame.plotHeight;
    const batteryHeight = item.battery / maximum * frame.plotHeight;
    frame.context.fillStyle = ORANGE;
    frame.context.fillRect(x, frame.top + frame.plotHeight - limitHeight, barWidth, limitHeight);
    frame.context.fillStyle = GREEN;
    frame.context.fillRect(x, frame.top + frame.plotHeight - limitHeight - batteryHeight, barWidth, batteryHeight);
    frame.context.fillStyle = "#687872";
    frame.context.font = "9px Trebuchet MS, sans-serif";
    frame.context.textAlign = "center";
    frame.context.textBaseline = "top";
    frame.context.fillText(item.month.slice(5), x + barWidth / 2, frame.top + frame.plotHeight + 5);
  });
}

function drawSocChart() {
  const day = daysWithHourly().slice().reverse().find((record) =>
    record.hourly.some((point) => point.soc_pct !== null && point.soc_pct !== undefined && Number.isFinite(Number(point.soc_pct))),
  );
  const data = day
    ? day.hourly
        .filter((point) => point.soc_pct !== null && point.soc_pct !== undefined && Number.isFinite(Number(point.soc_pct)))
        .map((point) => ({ ...point, date: day.date, soc_pct: Number(point.soc_pct) }))
    : [];
  setAnalysisState(elements.analysisSoc, elements.analysisSocEmpty, data.length > 0);
  if (!data.length) return;
  const frame = beginAnalysisChart(elements.analysisSoc, data, {
    title: (item) => `${formatDate(item.date)} · ${item.hour}`,
    tooltipLines: (item) => [`${formatDate(item.date)} · ${item.hour}`, `Akku-Ladezustand: ${formatNumber(item.soc_pct)} %`],
  });
  if (!frame) return;
  drawAnalysisAxes(frame.context, frame, 100, (value) => `${formatNumber(value)}%`);
  const slot = frame.plotWidth / data.length;
  frame.context.strokeStyle = GREEN;
  frame.context.lineWidth = 2;
  frame.context.beginPath();
  data.forEach((item, index) => {
    const x = frame.left + slot * (index + 0.5);
    const y = frame.top + frame.plotHeight - Math.max(0, Math.min(100, item.soc_pct)) / 100 * frame.plotHeight;
    if (!index) frame.context.moveTo(x, y); else frame.context.lineTo(x, y);
  });
  frame.context.stroke();
  data.forEach((item, index) => {
    const x = frame.left + slot * (index + 0.5);
    const y = frame.top + frame.plotHeight - Math.max(0, Math.min(100, item.soc_pct)) / 100 * frame.plotHeight;
    frame.context.beginPath();
    frame.context.fillStyle = GREEN;
    frame.context.arc(x, y, 2.5, 0, Math.PI * 2);
    frame.context.fill();
    if (index % Math.max(1, Math.ceil(data.length / 6)) === 0 || index === data.length - 1) {
      frame.context.fillStyle = "#687872";
      frame.context.font = "9px Trebuchet MS, sans-serif";
      frame.context.textAlign = "center";
      frame.context.textBaseline = "top";
      frame.context.fillText(item.hour.slice(0, 2), x, frame.top + frame.plotHeight + 5);
    }
  });
}

function renderAnomalies() {
  const ratios = validPairs(records).map((item) => ({ item, ratio: ratioPercent(item.actual_kwh, item.potential_kwh) }));
  elements.anomalies.replaceChildren();
  if (ratios.length < 7) {
    elements.anomalies.textContent = "Auffällige Tage erscheinen ab sieben gültigen Tagesverhältnissen.";
    return;
  }
  const center = median(ratios.map((entry) => entry.ratio));
  const mad = median(ratios.map((entry) => Math.abs(entry.ratio - center)));
  const unusual = ratios.filter((entry) => mad === 0 ? entry.ratio !== center : Math.abs(0.6745 * (entry.ratio - center) / mad) >= 3.5);
  if (!unusual.length) {
    elements.anomalies.textContent = "Keine robusten Ausreißer im Tagesverhältnis erkannt.";
  } else {
    const list = document.createElement("ul");
    unusual.sort((a, b) => Math.abs(b.ratio - center) - Math.abs(a.ratio - center)).slice(0, 8).forEach(({ item, ratio }) => {
      const row = document.createElement("li");
      const profile = Array.isArray(item.hourly) ? item.hourly : [];
      const missing = profile.some((point) => point.actual_kwh === null || point.actual_kwh === undefined);
      const qualityDescriptions = {
        low_coverage: "geringe Probenabdeckung",
        epv_mismatch: "Stundenintegral weicht vom Tageswert ab",
        hourly_missing: "Stundenprofil fehlt",
        daylight_coverage_low: "geringe Tageslichtabdeckung",
      };
      const qualityFlags = Array.isArray(item.quality?.flags)
        ? item.quality.flags.map((flag) => qualityDescriptions[flag] || flag).join(", ")
        : "";
      const context = [
        `Ist/Potenzial ${formatNumber(ratio)} %`,
        `Sonne ${formatNumber(item.sunshine_hours)} h`,
        item.poa_kwh_m2 != null ? `Einstrahlung ${formatNumber(item.poa_kwh_m2)} kWh/m²` : "",
        item.weather_source ? `Wetter ${({ archive: "Archiv", forecast: "Vorhersage" })[item.weather_source] || "Quelle nicht vermerkt"}` : "Wetterquelle nicht vermerkt",
        item.curtailment?.hours ? `Abregelung ${item.curtailment.hours} h` : "",
        qualityFlags ? `Datenqualität: ${qualityFlags}` : "",
        missing ? "Stundenprofil lückenhaft" : "",
      ].filter(Boolean);
      row.textContent = `${formatDate(item.date)} — ${context.join(" · ")}`;
      list.append(row);
    });
    elements.anomalies.append(list);
  }
  const note = document.createElement("p");
  note.textContent = "Temperatur- und Schnee-Hinweise sind im eingebetteten Tagesformat nicht enthalten.";
  elements.anomalies.append(note);
}

function drawAnalysisCharts() {
  drawScatterAnalysis();
  drawRatioHistogram();
  drawTrend();
  drawHeatmap();
  drawCurtailmentSeries();
  drawSocChart();
  drawReferenceChart();
  renderAnomalies();
}

/* ------------------------------------------------------------------------------- Rendern */

function drawCharts() {
  const data = visibleRecords();
  if (data.length) {
    const sourceOptions = weatherSourceOptions();
    drawChart(elements.energyCanvas, data, "actual_kwh", GREEN, "potential_kwh", {
      ...sourceOptions,
      highlight: null,
      comparisonColor: (item) => WEATHER_SOURCE_COLORS[item.weather_source],
    });
    drawChart(elements.sunshineCanvas, data, "sunshine_hours", SUN, null, sourceOptions);
    drawChart(
      elements.ratioCanvas,
      data.map((item) => ({ ...item, ratio_pct: ratioPercent(item.actual_kwh, item.potential_kwh) })),
      "ratio_pct",
      GREEN,
      null,
      {
        ...sourceOptions,
        highlight: null,
        valueColor: (item) => WEATHER_SOURCE_COLORS[item.weather_source],
        label: "Ist/Potenzial",
        unit: "%",
        referenceLine: 100,
        minimumMaximum: 100,
      },
    );
  }
  drawHourlyChart();
  drawProfileChart();
  drawAnalysisCharts();
}

function updateAccessibleLabels(data) {
  elements.energyCanvas.setAttribute(
    "aria-label",
    describeSeries("Täglicher Ist-Ertrag und potentieller Ertrag", data, `Summe Ist ${formatNumber(sumOf(data, "actual_kwh"))} kWh, Summe Potenzial ${formatNumber(sumOf(data, "potential_kwh"))} kWh.`),
  );
  elements.sunshineCanvas.setAttribute(
    "aria-label",
    describeSeries("Tägliche Sonnenstunden", data, `Summe ${formatNumber(sumOf(data, "sunshine_hours"))} Stunden.`),
  );
  elements.ratioCanvas.setAttribute(
    "aria-label",
    describeSeries("Tägliches Verhältnis von Ist-Ertrag zu Potenzial", data, `Gesamtverhältnis ${percentText(ratioPercent(sumOf(data, "actual_kwh"), sumOf(data, "potential_kwh")))}.`),
  );
}

function render() {
  const data = visibleRecords();
  setEmptyState(data.length > 0);
  renderMetrics();
  renderSummary();
  renderHistory(data);
  renderSourceNote();
  renderMetricsSummary(data);
  renderModelWarning();
  renderCompleteness();
  renderRunHistory();
  updateAccessibleLabels(data);
  drawCharts();
  elements.exportButton.disabled = records.length === 0;
}

/* -------------------------------------------------------------------------------- Export */

function csvNumber(value) {
  if (value === null || value === undefined || value === "") return "";
  // Deutsches Excel erwartet das Dezimalkomma; mit Punkt würde es Werte als Datum oder Text lesen.
  return String(value).replace(".", ",");
}

function buildCsv() {
  const rows = [
    ["date", "actual_kwh", "potential_kwh", "sunshine_hours", "curtailed_hours", "curtailed_kwh"],
    ...records.map((item) => [
      item.date,
      csvNumber(item.actual_kwh),
      csvNumber(item.potential_kwh),
      csvNumber(item.sunshine_hours),
      csvNumber(item.curtailment?.hours),
      csvNumber(item.curtailment?.lost_kwh),
    ]),
  ];
  return rows.map((row) => row.join(";")).join("\r\n");
}

function exportCsv() {
  const blob = new Blob(["\ufeff", buildCsv()], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "pv-tagesbericht.csv";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ------------------------------------------------------------------------------- Start */

function debounce(callback, delay) {
  let timer = null;
  return () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(callback, delay);
  };
}

document.querySelectorAll("[data-range]").forEach((button) => {
  button.addEventListener("click", () => {
    activeRange = button.dataset.range === "all" ? "all" : Number(button.dataset.range);
    document.querySelectorAll("[data-range]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    render();
    pollPublicHealth();
  });
});
elements.exportButton.addEventListener("click", exportCsv);
elements.hourlySelect.addEventListener("change", drawHourlyChart);
document.querySelector("#hourly-prev")?.addEventListener("click", () => stepHourlyDay(-1));
document.querySelector("#hourly-next")?.addEventListener("click", () => stepHourlyDay(1));

elements.connection.dataset.state = records.length ? "ready" : "loading";
elements.connectionLabel.textContent = records.length ? "Lokal gespeichert" : "Noch keine Tagesdaten";
populateHourlySelect();
render();
// Bei Größenänderung nur neu zeichnen: Tabellen und die Tag-Auswahl bleiben unangetastet.
window.addEventListener("resize", debounce(drawCharts, 150));
