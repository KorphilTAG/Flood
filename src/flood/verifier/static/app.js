/**
 * Flood Physics Verifier UI
 * Vanilla JavaScript module bound strictly to Contract 1 and Clock Service endpoints.
 */

// Contract 1 and Clock Service API endpoints
export const API = {
  scenarios: '/scenarios',
  scenario: '/scenarios/{scenario_id}',
  runs: '/runs',
  run: '/runs/{run}',
  state: '/runs/{run}/state?p=&t=',
  reaches: '/runs/{run}/reaches?p=&t=',
  gauges: '/runs/{run}/gauges?p=',
  overlay: '/runs/{run}/overlay.png?p=&t=&band=&max_px=2048',
  skill: '/runs/{run}/skill',
  clock: '/clock',
  clockReset: '/clock/reset',
  clockWs: '/clock/ws',
};

// Application State
export const state = {
  runId: null,
  mode: 'forecast', // 'nowcast' | 'forecast' | 'stale'
  lagMin: 60,
  horizonMin: 120,
  t: null, // clock simulation time ISO string
  band: 'depth_mid',
  showProb: false,
  showDiff: false,

  // Scenario context
  scenarioId: null,
  scenarioTz: 'UTC',

  // Clock state
  clockState: null, // { mode, t, speed, playing, record_start, record_end }
  isDraggingSlider: false,

  // Products and tables
  lastState: null,
  reachesData: [],
  reachSortCol: 'reach_ref',
  reachSortAsc: true,
};

// Global handles
let map = null;
let mainOverlay = null;
let mainOverlayUrl = null;
let diffOverlay = null;
let diffOverlayUrl = null;
let probOverlay = null;
let probOverlayUrl = null;
let hasFitBounds = false;

const gaugeCharts = new Map(); // gauge_ref -> Chart instance
let debounceTimer = null;
let currentAbortController = null;
let clockWs = null;

// Depth ramp color stops for legend
const DEPTH_RAMP_STOPS = [
  { threshold: '0.03', color: '#bfe3ff' },
  { threshold: '0.5', color: '#6fb3ff' },
  { threshold: '1.0', color: '#2a7fff' },
  { threshold: '2.0', color: '#0a4fc0' },
  { threshold: '4.0', color: '#052a66' },
];

/**
 * Format Date to contract ISO 8601 string: YYYY-MM-DDTHH:MM:SSZ
 */
export function formatIsoUtc(d) {
  const date = d instanceof Date ? d : new Date(d);
  if (isNaN(date.getTime())) return null;
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * Format timestamp in given timezone
 */
export function formatDateTime(isoStr, timeZone = 'UTC') {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    return formatter.format(d);
  } catch {
    return isoStr;
  }
}

/**
 * Escape HTML to prevent injection
 */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Non-modal error banner display
 */
export function showError(code, message) {
  const banner = document.getElementById('error-banner');
  const msgSpan = document.getElementById('error-message');
  if (!banner || !msgSpan) return;
  msgSpan.textContent = `[${code || 'error'}] ${message || 'Unknown error'}`;
  banner.classList.remove('hidden');
}

export function clearError() {
  const banner = document.getElementById('error-banner');
  if (banner) banner.classList.add('hidden');
}

/**
 * Safe fetch JSON wrapper: never throws uncaught errors
 */
export async function safeFetchJson(url, options = {}) {
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      let errBody = null;
      try {
        errBody = await res.json();
      } catch {
        // Not JSON
      }
      const code = errBody?.error?.code || `http_${res.status}`;
      const message = errBody?.error?.message || res.statusText || 'Request failed';
      return { ok: false, status: res.status, error: { code, message } };
    }
    const data = await res.json();
    return { ok: true, status: res.status, data };
  } catch (err) {
    if (err.name === 'AbortError') {
      return { aborted: true };
    }
    return { ok: false, error: { code: 'network_error', message: err.message } };
  }
}

/**
 * Derive (p, t) per mode
 * - nowcast: p = clockT, t = clockT
 * - forecast: p = clockT, t = p + horizon
 * - stale: t = clockT, p = t - lag
 */
export function deriveCutoffAndValid(clockIso, mode, horizonMin, lagMin) {
  if (!clockIso) return { p: null, t: null };
  const clockDate = new Date(clockIso);
  if (isNaN(clockDate.getTime())) return { p: null, t: null };

  let pDate, tDate;
  if (mode === 'nowcast') {
    pDate = new Date(clockDate.getTime());
    tDate = new Date(clockDate.getTime());
  } else if (mode === 'forecast') {
    pDate = new Date(clockDate.getTime());
    tDate = new Date(clockDate.getTime() + Number(horizonMin) * 60 * 1000);
  } else if (mode === 'stale') {
    tDate = new Date(clockDate.getTime());
    pDate = new Date(clockDate.getTime() - Number(lagMin) * 60 * 1000);
  } else {
    pDate = new Date(clockDate.getTime());
    tDate = new Date(clockDate.getTime());
  }

  return {
    p: formatIsoUtc(pDate),
    t: formatIsoUtc(tDate),
  };
}

/**
 * Update header readouts
 */
export function updateHeader(p, t) {
  const modeEl = document.getElementById('readout-mode');
  const offsetLabelEl = document.getElementById('readout-offset-label');
  const offsetValEl = document.getElementById('readout-offset');
  const pUtcEl = document.getElementById('readout-p-utc');
  const pLocalEl = document.getElementById('readout-p-local');
  const tUtcEl = document.getElementById('readout-t-utc');
  const tLocalEl = document.getElementById('readout-t-local');

  if (modeEl) modeEl.textContent = state.mode;

  if (offsetLabelEl && offsetValEl) {
    if (state.mode === 'forecast') {
      offsetLabelEl.textContent = 'Horizon:';
      offsetValEl.textContent = `${state.horizonMin} min`;
      offsetValEl.parentElement.classList.remove('hidden');
    } else if (state.mode === 'stale') {
      offsetLabelEl.textContent = 'Lag:';
      offsetValEl.textContent = `${state.lagMin} min`;
      offsetValEl.parentElement.classList.remove('hidden');
    } else {
      offsetValEl.parentElement.classList.add('hidden');
    }
  }

  const tz = state.scenarioTz || 'UTC';
  if (pUtcEl) pUtcEl.textContent = p ? `${formatDateTime(p, 'UTC')} UTC` : '-';
  if (pLocalEl) pLocalEl.textContent = p && tz !== 'UTC' ? `${formatDateTime(p, tz)} (${tz})` : '';
  if (tUtcEl) tUtcEl.textContent = t ? `${formatDateTime(t, 'UTC')} UTC` : '-';
  if (tLocalEl) tLocalEl.textContent = t && tz !== 'UTC' ? `${formatDateTime(t, tz)} (${tz})` : '';
}

/**
 * Debounced refresh trigger
 */
export function scheduleUpdate() {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
  debounceTimer = setTimeout(() => {
    executeFetchCycle();
  }, 150);
}

/**
 * Main fetch cycle: GET state then parallel overlay, reaches, gauges
 */
let inFlight = false;
let rerunPending = false;
let lastBucketKey = null;

/**
 * Key of the snapped (p, t) request the current settings would produce.
 * Clock ticks that stay inside the same 5-minute buckets do not trigger fetches.
 */
function bucketKey() {
  if (!state.runId || !state.t) return null;
  const { p, t } = deriveCutoffAndValid(state.t, state.mode, state.horizonMin, state.lagMin);
  if (!p || !t) return null;
  const step = 5 * 60 * 1000;
  const floor = (iso) => new Date(Math.floor(new Date(iso).getTime() / step) * step).toISOString();
  const nearest = (iso) => new Date(Math.round(new Date(iso).getTime() / step) * step).toISOString();
  return `${state.runId}|${state.mode}|${floor(p)}|${nearest(t)}|${state.band}|${state.showProb}|${state.showDiff}`;
}

/**
 * At most one fetch cycle in flight. Requests arriving while one runs coalesce into a
 * single rerun afterwards, so the server never sees a queue of stale computations.
 */
export async function executeFetchCycle() {
  if (!state.runId || !state.t) return;
  if (inFlight) {
    rerunPending = true;
    return;
  }
  inFlight = true;
  rerunPending = false;
  lastBucketKey = bucketKey();
  try {
    await runFetchCycle();
  } finally {
    inFlight = false;
    const again = rerunPending && bucketKey() !== lastBucketKey;
    rerunPending = false;
    if (again) scheduleUpdate();
  }
}

async function runFetchCycle() {

  if (currentAbortController) {
    currentAbortController.abort();
  }
  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;

  const { p, t } = deriveCutoffAndValid(state.t, state.mode, state.horizonMin, state.lagMin);
  updateHeader(p, t);

  if (!p || !t) return;

  // 1. GET state
  const stateUrl = API.state
    .replace('{run}', encodeURIComponent(state.runId))
    .replace('p=', `p=${encodeURIComponent(p)}`)
    .replace('t=', `t=${encodeURIComponent(t)}`);

  const stateRes = await safeFetchJson(stateUrl, { signal });
  if (stateRes.aborted) return;
  if (!stateRes.ok) {
    showError(stateRes.error.code, stateRes.error.message);
    return;
  }

  state.lastState = stateRes.data;
  renderTimingReadout(state.lastState);

  // 2. In parallel: overlay, reaches, gauges, diff overlay, prob overlay
  const tasks = [
    fetchMainOverlay(p, t, state.band, signal),
    fetchReaches(p, t, signal),
    fetchGauges(p, signal),
  ];

  if (state.showDiff) {
    tasks.push(fetchDiffOverlay(t, state.band, signal));
  } else {
    removeDiffOverlay();
  }

  if (state.showProb) {
    tasks.push(fetchProbOverlay(p, t, signal));
  } else {
    removeProbOverlay();
  }

  await Promise.allSettled(tasks);
}

/**
 * Fetch and display main overlay PNG
 */
async function fetchMainOverlay(p, t, band, signal) {
  const url = API.overlay
    .replace('{run}', encodeURIComponent(state.runId))
    .replace('p=', `p=${encodeURIComponent(p)}`)
    .replace('t=', `t=${encodeURIComponent(t)}`)
    .replace('band=', `band=${encodeURIComponent(band)}`);

  const overlayData = await loadOverlayImage(url, signal);
  if (!overlayData) return;

  const prevUrl = mainOverlayUrl;
  if (mainOverlay) {
    map.removeLayer(mainOverlay);
    mainOverlay = null;
  }

  mainOverlayUrl = overlayData.url;
  if (overlayData.bounds) {
    mainOverlay = L.imageOverlay(overlayData.url, overlayData.bounds, {
      opacity: 1.0,
      zIndex: 10,
    }).addTo(map);

    if (!hasFitBounds) {
      map.fitBounds(overlayData.bounds);
      hasFitBounds = true;
    }
  }
  if (prevUrl) URL.revokeObjectURL(prevUrl);
}

/**
 * Fetch and display hindsight difference overlay PNG
 */
async function fetchDiffOverlay(t, band, signal) {
  const url = API.overlay
    .replace('{run}', encodeURIComponent(state.runId))
    .replace('p=', 'p=hindsight')
    .replace('t=', `t=${encodeURIComponent(t)}`)
    .replace('band=', `band=${encodeURIComponent(band)}`);

  const overlayData = await loadOverlayImage(url, signal);
  if (!overlayData) return;

  const prevUrl = diffOverlayUrl;
  if (diffOverlay) {
    map.removeLayer(diffOverlay);
    diffOverlay = null;
  }

  diffOverlayUrl = overlayData.url;
  if (overlayData.bounds) {
    diffOverlay = L.imageOverlay(overlayData.url, overlayData.bounds, {
      opacity: 0.5,
      zIndex: 5,
      className: 'hindsight-diff-overlay',
    }).addTo(map);

    const el = diffOverlay.getElement();
    if (el) {
      el.style.filter = 'hue-rotate(120deg)';
      el.style.opacity = '0.5';
    }
  }
  if (prevUrl) URL.revokeObjectURL(prevUrl);
}

function removeDiffOverlay() {
  if (diffOverlay) {
    map.removeLayer(diffOverlay);
    diffOverlay = null;
  }
  if (diffOverlayUrl) {
    URL.revokeObjectURL(diffOverlayUrl);
    diffOverlayUrl = null;
  }
}

/**
 * Fetch and display probability overlay PNG
 */
async function fetchProbOverlay(p, t, signal) {
  const url = API.overlay
    .replace('{run}', encodeURIComponent(state.runId))
    .replace('p=', `p=${encodeURIComponent(p)}`)
    .replace('t=', `t=${encodeURIComponent(t)}`)
    .replace('band=', 'band=prob_inundated');

  const overlayData = await loadOverlayImage(url, signal);
  if (!overlayData) return;

  const prevUrl = probOverlayUrl;
  if (probOverlay) {
    map.removeLayer(probOverlay);
    probOverlay = null;
  }

  probOverlayUrl = overlayData.url;
  if (overlayData.bounds) {
    probOverlay = L.imageOverlay(overlayData.url, overlayData.bounds, {
      opacity: 0.5,
      zIndex: 15,
      className: 'prob-inundated-overlay',
    }).addTo(map);

    const el = probOverlay.getElement();
    if (el) {
      el.style.opacity = '0.5';
    }
  }
  if (prevUrl) URL.revokeObjectURL(prevUrl);
}

function removeProbOverlay() {
  if (probOverlay) {
    map.removeLayer(probOverlay);
    probOverlay = null;
  }
  if (probOverlayUrl) {
    URL.revokeObjectURL(probOverlayUrl);
    probOverlayUrl = null;
  }
}

/**
 * Common loader for overlay image and X-Bounds-3857 parsing
 */
async function loadOverlayImage(url, signal) {
  try {
    const resp = await fetch(url, { signal });
    if (!resp.ok) {
      let errBody = null;
      try {
        errBody = await resp.json();
      } catch {
        // Not JSON
      }
      const code = errBody?.error?.code || `http_${resp.status}`;
      const message = errBody?.error?.message || resp.statusText || 'Failed to fetch overlay';
      showError(code, message);
      return null;
    }

    const boundsHeader = resp.headers.get('X-Bounds-3857');
    let bounds = null;
    if (boundsHeader) {
      const parts = boundsHeader.split(',').map(Number);
      if (parts.length === 4 && parts.every((n) => !isNaN(n))) {
        const [xmin, ymin, xmax, ymax] = parts;
        const sw = L.CRS.EPSG3857.unproject(L.point(xmin, ymin));
        const ne = L.CRS.EPSG3857.unproject(L.point(xmax, ymax));
        bounds = L.latLngBounds(sw, ne);
      }
    }

    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    return { url: blobUrl, bounds };
  } catch (err) {
    if (err.name !== 'AbortError') {
      showError('overlay_error', err.message);
    }
    return null;
  }
}

/**
 * Fetch and render reach table
 */
async function fetchReaches(p, t, signal) {
  const url = API.reaches
    .replace('{run}', encodeURIComponent(state.runId))
    .replace('p=', `p=${encodeURIComponent(p)}`)
    .replace('t=', `t=${encodeURIComponent(t)}`);

  const res = await safeFetchJson(url, { signal });
  if (res.aborted) return;
  if (!res.ok) {
    showError(res.error.code, res.error.message);
    return;
  }

  state.reachesData = Array.isArray(res.data) ? res.data : [];
  renderReachTable();
}

/**
 * Render reach table rows with sorting and source==observed tinting
 */
export function renderReachTable() {
  const tbody = document.getElementById('reach-tbody');
  if (!tbody) return;

  if (!state.reachesData || state.reachesData.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">No reach data</td></tr>';
    return;
  }

  const col = state.reachSortCol;
  const asc = state.reachSortAsc;

  const sorted = [...state.reachesData].sort((a, b) => {
    let va = a[col];
    let vb = b[col];
    if (va === vb) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') {
      return asc ? va - vb : vb - va;
    }
    if (typeof va === 'boolean' && typeof vb === 'boolean') {
      return asc ? (va ? 1 : -1) : (vb ? 1 : -1);
    }
    return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  });

  const rowsHtml = sorted
    .map((r) => {
      const isObserved = r.source === 'observed';
      const trClass = isObserved ? ' class="row-observed"' : '';
      return `<tr${trClass}>
        <td>${escapeHtml(r.reach_ref)}</td>
        <td>${escapeHtml(r.gauge_ref || '-')}</td>
        <td>${r.q_mid_cms != null ? r.q_mid_cms.toFixed(1) : '-'}</td>
        <td>${r.q_low_cms != null ? r.q_low_cms.toFixed(1) : '-'}</td>
        <td>${r.q_high_cms != null ? r.q_high_cms.toFixed(1) : '-'}</td>
        <td>${r.stage_mid_m != null ? r.stage_mid_m.toFixed(2) : '-'}</td>
        <td>${r.rate_of_rise_m_per_h != null ? r.rate_of_rise_m_per_h.toFixed(2) : '-'}</td>
        <td>${r.velocity_ms != null ? r.velocity_ms.toFixed(2) : '-'}</td>
        <td>${escapeHtml(r.source || '-')}</td>
        <td>${r.clipped_to_src ? 'true' : 'false'}</td>
      </tr>`;
    })
    .join('');

  tbody.innerHTML = rowsHtml;

  // Update table header sorting classes
  document.querySelectorAll('#reach-table thead th').forEach((th) => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.getAttribute('data-col') === col) {
      th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
    }
  });
}

/**
 * Fetch and render gauge hydrographs
 */
async function fetchGauges(p, signal) {
  const url = API.gauges
    .replace('{run}', encodeURIComponent(state.runId))
    .replace('p=', `p=${encodeURIComponent(p)}`);

  const res = await safeFetchJson(url, { signal });
  if (res.aborted) return;
  if (!res.ok) {
    showError(res.error.code, res.error.message);
    return;
  }

  const rows = Array.isArray(res.data) ? res.data : [];
  renderGaugeCharts(rows, p);
}

/**
 * Render one Chart.js line chart per gauge
 */
export function renderGaugeCharts(rows, p) {
  const container = document.getElementById('gauges-container');
  if (!container) return;

  if (!rows || rows.length === 0) {
    container.innerHTML = '<div class="empty-state">No gauge data available</div>';
    return;
  }

  // Group by gauge_ref
  const grouped = new Map();
  for (const row of rows) {
    const ref = row.gauge_ref || row.site;
    if (!ref) continue;
    if (!grouped.has(ref)) grouped.set(ref, []);
    grouped.get(ref).push(row);
  }

  const recordStart = state.clockState?.record_start;
  const horizonDate = new Date(new Date(p).getTime() + Number(state.horizonMin) * 60 * 1000);
  const pPlusHorizon = formatIsoUtc(horizonDate);

  // Inline Chart.js plugin to draw vertical marker at p
  const verticalMarkerPlugin = {
    id: 'verticalMarkerP',
    afterDraw(chart) {
      if (chart._pIndex === undefined || chart._pIndex < 0) return;
      const meta = chart.getDatasetMeta(0);
      if (!meta || !meta.data || !meta.data[chart._pIndex]) return;
      const x = meta.data[chart._pIndex].x;
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = '#dc2626';
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.fillStyle = '#dc2626';
      ctx.font = '10px sans-serif';
      ctx.fillText('p', x + 3, top + 10);
      ctx.restore();
    },
  };

  grouped.forEach((gaugeRows, ref) => {
    // Sort ascending by t
    gaugeRows.sort((a, b) => String(a.t).localeCompare(String(b.t)));

    // Filter x from record_start to p + horizon
    const filtered = gaugeRows.filter((r) => {
      if (recordStart && r.t < recordStart) return false;
      if (pPlusHorizon && r.t > pPlusHorizon) return false;
      return true;
    });

    if (filtered.length === 0) return;

    const labels = filtered.map((r) => r.t.substring(11, 16));
    const pIndex = filtered.findIndex((r) => r.t === p);

    const observedData = filtered.map((r) => r.observed_q_cms);
    const predMidData = filtered.map((r) => r.predicted_q_mid_cms);
    const predLowData = filtered.map((r) => r.predicted_q_low_cms);
    const predHighData = filtered.map((r) => r.predicted_q_high_cms);

    let chart = gaugeCharts.get(ref);
    if (!chart) {
      // Create DOM elements
      const card = document.createElement('div');
      card.className = 'gauge-chart-card';

      const title = document.createElement('div');
      title.className = 'gauge-chart-title';
      title.textContent = `Gauge ${ref}`;

      const canvasWrapper = document.createElement('div');
      canvasWrapper.className = 'gauge-canvas-wrapper';

      const canvas = document.createElement('canvas');
      canvasWrapper.appendChild(canvas);
      card.appendChild(title);
      card.appendChild(canvasWrapper);

      // Clear empty state if first chart
      if (container.querySelector('.empty-state')) {
        container.innerHTML = '';
      }
      container.appendChild(card);

      chart = new Chart(canvas, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Observed Q',
              data: observedData,
              borderColor: '#0284c7',
              backgroundColor: '#0284c7',
              borderWidth: 2,
              pointRadius: 0,
              spanGaps: false,
            },
            {
              label: 'Predicted Mid',
              data: predMidData,
              borderColor: '#ea580c',
              backgroundColor: '#ea580c',
              borderWidth: 2,
              borderDash: [5, 4],
              pointRadius: 0,
            },
            {
              label: 'Low',
              data: predLowData,
              borderColor: 'transparent',
              pointRadius: 0,
              fill: false,
            },
            {
              label: 'High (Band)',
              data: predHighData,
              borderColor: 'transparent',
              backgroundColor: 'rgba(234, 88, 12, 0.18)',
              pointRadius: 0,
              fill: '-1',
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: {
            legend: {
              display: true,
              labels: { boxWidth: 10, font: { size: 10 } },
            },
            tooltip: { mode: 'index', intersect: false },
          },
          scales: {
            x: {
              ticks: { maxTicksLimit: 6, font: { size: 9 } },
              grid: { display: false },
            },
            y: {
              title: { display: true, text: 'cms', font: { size: 9 } },
              ticks: { font: { size: 9 } },
            },
          },
        },
        plugins: [verticalMarkerPlugin],
      });

      chart._pIndex = pIndex;
      gaugeCharts.set(ref, chart);
    } else {
      chart.data.labels = labels;
      chart.data.datasets[0].data = observedData;
      chart.data.datasets[1].data = predMidData;
      chart.data.datasets[2].data = predLowData;
      chart.data.datasets[3].data = predHighData;
      chart._pIndex = pIndex;
      chart.update('none');
    }
  });
}

/**
 * Fetch and render skill table
 */
export async function fetchSkill() {
  const container = document.getElementById('skill-container');
  if (!container || !state.runId) return;

  const url = API.skill.replace('{run}', encodeURIComponent(state.runId));
  const res = await safeFetchJson(url);

  if (!res.ok) {
    if (res.status === 404 || res.error?.code === 'skill_not_computed') {
      container.innerHTML = `
        <div class="skill-not-computed">
          <p>Skill not computed</p>
          <div class="skill-cli-box">flood skill ${escapeHtml(state.runId)}</div>
        </div>`;
    } else {
      showError(res.error.code, res.error.message);
      container.innerHTML = `<div class="empty-state">${escapeHtml(res.error.message)}</div>`;
    }
    return;
  }

  const rows = Array.isArray(res.data) ? res.data : [];
  if (rows.length === 0) {
    container.innerHTML = '<div class="empty-state">No skill rows available</div>';
    return;
  }

  const tableHtml = `
    <div class="skill-table-wrapper">
      <table class="skill-table">
        <thead>
          <tr>
            <th>Gauge Ref</th>
            <th>Horizon</th>
            <th>MAE (cms)</th>
            <th>Persist MAE</th>
            <th>Skill</th>
            <th>IoU 0.15</th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map((r) => {
              const skillVal =
                r.skill != null
                  ? r.skill
                  : r.mae_cms != null && r.persistence_mae_cms
                    ? 1 - r.mae_cms / r.persistence_mae_cms
                    : null;
              return `<tr>
                <td>${escapeHtml(r.gauge_ref || '-')}</td>
                <td>${r.horizon_minutes != null ? `${r.horizon_minutes}m` : '-'}</td>
                <td>${r.mae_cms != null ? r.mae_cms.toFixed(2) : '-'}</td>
                <td>${r.persistence_mae_cms != null ? r.persistence_mae_cms.toFixed(2) : '-'}</td>
                <td>${skillVal != null ? skillVal.toFixed(3) : '-'}</td>
                <td>${r.iou_015 != null ? r.iou_015.toFixed(3) : '-'}</td>
              </tr>`;
            })
            .join('')}
        </tbody>
      </table>
    </div>`;

  container.innerHTML = tableHtml;
}

/**
 * Timing readout rendering
 */
export function renderTimingReadout(stateData) {
  const el = document.getElementById('timing-readout');
  if (!el) return;

  if (!stateData || !stateData.compute_ms) {
    el.textContent = 'No timing data';
    return;
  }

  const isHit = stateData.cache === 'hit';
  const badgeClass = isHit ? 'cache-hit' : 'cache-miss';
  const cacheBadge = `<span class="timing-badge ${badgeClass}">Cache: ${escapeHtml(stateData.cache || 'unknown')}</span>`;

  const stages = stateData.compute_ms;
  const stageEntries = Object.entries(stages)
    .filter(([k]) => k !== 'total')
    .map(([k, v]) => `${escapeHtml(k)}: ${v}ms`)
    .join(' | ');

  const totalStr = stages.total !== undefined ? `<strong>Total: ${stages.total}ms</strong>` : '';
  el.innerHTML = `${cacheBadge} ${totalStr} &nbsp;[${stageEntries}]`;
}

/**
 * Clock Service WebSocket client
 */
export function initClockWebSocket() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${window.location.host}${API.clockWs}`;

  try {
    clockWs = new WebSocket(wsUrl);
  } catch {
    // Live WS not available
    return;
  }

  clockWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleClockMessage(msg);
    } catch {
      // Ignored malformed WS
    }
  };

  clockWs.onerror = () => {
    // Handled gracefully without throwing
  };

  clockWs.onclose = () => {
    // Reconnect after 3s if disconnected
    setTimeout(() => {
      initClockWebSocket();
    }, 3000);
  };
}

/**
 * Handle clock state push
 */
export function handleClockMessage(msg) {
  if (!msg || !msg.t) return;
  state.clockState = msg;
  state.t = msg.t;

  // Update play / pause button text
  const playBtn = document.getElementById('btn-play');
  if (playBtn) {
    playBtn.textContent = msg.playing ? 'Playing' : 'Play';
  }

  // Update speed select
  const speedSel = document.getElementById('speed-select');
  if (speedSel && msg.speed != null) {
    speedSel.value = String(msg.speed);
  }

  // Update timeline slider unless dragging
  updateTimelineSlider(msg);

  // Fetch only when the snapped (p, t) actually changes
  if (bucketKey() !== lastBucketKey) {
    scheduleUpdate();
  }
}

/**
 * Update timeline slider bounds and value
 */
function updateTimelineSlider(clock) {
  const slider = document.getElementById('timeline-slider');
  const startEl = document.getElementById('timeline-start');
  const currEl = document.getElementById('timeline-current');
  const endEl = document.getElementById('timeline-end');

  if (!slider || !clock) return;

  const startSec = clock.record_start ? Math.floor(new Date(clock.record_start).getTime() / 1000) : 0;
  const endSec = clock.record_end ? Math.floor(new Date(clock.record_end).getTime() / 1000) : 100;
  const currSec = clock.t ? Math.floor(new Date(clock.t).getTime() / 1000) : 0;

  slider.min = startSec;
  slider.max = endSec;

  if (!state.isDraggingSlider) {
    slider.value = currSec;
  }

  if (startEl && clock.record_start) startEl.textContent = formatDateTime(clock.record_start, 'UTC');
  if (endEl && clock.record_end) endEl.textContent = formatDateTime(clock.record_end, 'UTC');
  if (currEl && clock.t && !state.isDraggingSlider) {
    currEl.textContent = formatDateTime(clock.t, 'UTC');
  }
}

/**
 * Send POST to /clock
 */
export async function sendClockPost(payload) {
  const res = await safeFetchJson(API.clock, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    showError(res.error.code, res.error.message);
  } else if (res.data) {
    handleClockMessage(res.data);
  }
}

/**
 * Initialize Leaflet Map
 */
export function initMap() {
  map = L.map('map', {
    zoomControl: true,
  }).setView([30.07, -99.25], 11);

  // OpenStreetMap standard tiles with attribution
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Legend control with depth ramp stops
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = function () {
    const div = L.DomUtil.create('div', 'map-legend');
    div.innerHTML = `
      <div class="legend-title">Depth (m)</div>
      <div class="legend-ramp-bar"></div>
      <div class="legend-stops">
        ${DEPTH_RAMP_STOPS.map((s) => `<span>${s.threshold}</span>`).join('')}
      </div>
    `;
    return div;
  };
  legend.addTo(map);
}

/**
 * Load runs and initialize scenario
 */
export async function loadRuns() {
  const res = await safeFetchJson(API.runs);
  if (!res.ok) {
    showError(res.error.code, res.error.message);
    return;
  }

  const runs = Array.isArray(res.data) ? res.data : [];
  const select = document.getElementById('run-select');
  if (!select) return;

  select.innerHTML = '';
  if (runs.length === 0) {
    select.innerHTML = '<option value="">(No runs found)</option>';
    return;
  }

  runs.forEach((r) => {
    const opt = document.createElement('option');
    opt.value = r.run_id || r.id || r;
    opt.textContent = r.run_id || r.name || r;
    select.appendChild(opt);
  });

  state.runId = select.value;
  await onRunSelected(state.runId);
}

/**
 * Handle run change: get run manifest, scenario timezone, and skill
 */
export async function onRunSelected(runId) {
  if (!runId) return;
  state.runId = runId;
  hasFitBounds = false;

  // Clear charts
  gaugeCharts.forEach((c) => c.destroy());
  gaugeCharts.clear();

  // Fetch run manifest
  const runUrl = API.run.replace('{run}', encodeURIComponent(runId));
  const runRes = await safeFetchJson(runUrl);
  if (runRes.ok && runRes.data) {
    const runData = runRes.data;
    // Manifest nests the scenario block (contract 1 section 3); accept a flat id too.
    state.scenarioId = (runData.scenario && runData.scenario.scenario_id) || runData.scenario_id || null;
    if (state.scenarioId) {
      await loadScenario(state.scenarioId);
    }
  }

  // Fetch skill
  await fetchSkill();

  // Schedule refresh
  scheduleUpdate();
}

/**
 * Fetch scenario details for timezone and name
 */
export async function loadScenario(scenarioId) {
  const scenarioUrl = API.scenario.replace('{scenario_id}', encodeURIComponent(scenarioId));
  const res = await safeFetchJson(scenarioUrl);
  if (res.ok && res.data) {
    state.scenarioTz = res.data.timezone || 'UTC';
    const badge = document.getElementById('scenario-badge');
    if (badge) {
      badge.textContent = `${res.data.name || scenarioId} (${state.scenarioTz})`;
    }
  }
}

/**
 * Wire UI event listeners
 */
export function setupEventListeners() {
  // Error banner dismiss
  const dismissBtn = document.getElementById('btn-dismiss-error');
  if (dismissBtn) dismissBtn.addEventListener('click', clearError);

  // Run select
  const runSelect = document.getElementById('run-select');
  if (runSelect) {
    runSelect.addEventListener('change', (e) => {
      onRunSelected(e.target.value);
    });
  }

  // Mode radio buttons
  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener('change', (e) => {
      state.mode = e.target.value;
      const horizonGrp = document.getElementById('horizon-group');
      const lagGrp = document.getElementById('lag-group');
      if (state.mode === 'forecast') {
        if (horizonGrp) horizonGrp.classList.remove('hidden');
        if (lagGrp) lagGrp.classList.add('hidden');
      } else if (state.mode === 'stale') {
        if (horizonGrp) horizonGrp.classList.add('hidden');
        if (lagGrp) lagGrp.classList.remove('hidden');
      } else {
        if (horizonGrp) horizonGrp.classList.add('hidden');
        if (lagGrp) lagGrp.classList.add('hidden');
      }
      scheduleUpdate();
    });
  });

  // Horizon select
  const horizonSel = document.getElementById('horizon-select');
  if (horizonSel) {
    horizonSel.addEventListener('change', (e) => {
      state.horizonMin = Number(e.target.value);
      scheduleUpdate();
    });
  }

  // Lag select
  const lagSel = document.getElementById('lag-select');
  if (lagSel) {
    lagSel.addEventListener('change', (e) => {
      state.lagMin = Number(e.target.value);
      scheduleUpdate();
    });
  }

  // Band select
  const bandSel = document.getElementById('band-select');
  if (bandSel) {
    bandSel.addEventListener('change', (e) => {
      state.band = e.target.value;
      scheduleUpdate();
    });
  }

  // Probability toggle
  const probToggle = document.getElementById('prob-toggle');
  if (probToggle) {
    probToggle.addEventListener('change', (e) => {
      state.showProb = e.target.checked;
      scheduleUpdate();
    });
  }

  // Hindsight diff toggle
  const diffToggle = document.getElementById('diff-toggle');
  if (diffToggle) {
    diffToggle.addEventListener('change', (e) => {
      state.showDiff = e.target.checked;
      scheduleUpdate();
    });
  }

  // Clock play / pause / reset
  const playBtn = document.getElementById('btn-play');
  if (playBtn) {
    playBtn.addEventListener('click', () => {
      sendClockPost({ playing: true });
    });
  }

  const pauseBtn = document.getElementById('btn-pause');
  if (pauseBtn) {
    pauseBtn.addEventListener('click', () => {
      sendClockPost({ playing: false });
    });
  }

  const resetBtn = document.getElementById('btn-reset');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      const res = await safeFetchJson(API.clockReset, { method: 'POST' });
      if (!res.ok) showError(res.error.code, res.error.message);
      else if (res.data) handleClockMessage(res.data);
    });
  }

  // Speed select
  const speedSel = document.getElementById('speed-select');
  if (speedSel) {
    speedSel.addEventListener('change', (e) => {
      sendClockPost({ speed: Number(e.target.value) });
    });
  }

  // Timeline slider
  const timelineSlider = document.getElementById('timeline-slider');
  const currEl = document.getElementById('timeline-current');
  if (timelineSlider) {
    timelineSlider.addEventListener('input', (e) => {
      state.isDraggingSlider = true;
      const d = new Date(Number(e.target.value) * 1000);
      const iso = formatIsoUtc(d);
      if (currEl) currEl.textContent = formatDateTime(iso, 'UTC');
    });

    timelineSlider.addEventListener('change', (e) => {
      state.isDraggingSlider = false;
      const d = new Date(Number(e.target.value) * 1000);
      const iso = formatIsoUtc(d);
      sendClockPost({ t: iso });
    });
  }

  // Reach table sorting
  document.querySelectorAll('#reach-table thead th').forEach((th) => {
    th.addEventListener('click', () => {
      const col = th.getAttribute('data-col');
      if (state.reachSortCol === col) {
        state.reachSortAsc = !state.reachSortAsc;
      } else {
        state.reachSortCol = col;
        state.reachSortAsc = true;
      }
      renderReachTable();
    });
  });
}

/**
 * Initialize application
 */
export async function init() {
  initMap();
  setupEventListeners();
  initClockWebSocket();

  // Initial GET /clock to get initial state immediately
  const clockRes = await safeFetchJson(API.clock);
  if (clockRes.ok && clockRes.data) {
    handleClockMessage(clockRes.data);
  }

  await loadRuns();
}

// Auto-boot on DOM ready
if (typeof window !== 'undefined') {
  window.addEventListener('DOMContentLoaded', () => {
    init();
  });
}
