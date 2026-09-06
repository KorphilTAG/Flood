/**
 * Flood Terrain View
 *
 * MapLibre GL JS 3D terrain from public terrarium-encoded tiles, with the engine's overlay PNG
 * draped on it. Every engine value comes from the contract 1 endpoints the 2D verifier already
 * uses, plus the run's reach network as GeoJSON. The clock is shared with the verifier: both
 * pages read and drive the same /clock service, so they always show the same moment.
 */

export const API = {
  scenario: '/scenarios/{scenario_id}',
  runs: '/runs',
  run: '/runs/{run}',
  state: '/runs/{run}/state?p=&t=',
  reaches: '/runs/{run}/reaches?p=&t=',
  gauges: '/runs/{run}/gauges?p=',
  overlay: '/runs/{run}/overlay.png?p=&t=&band=&max_px=&smooth=',
  network: '/runs/{run}/network.geojson',
  vulnerability: '/runs/{run}/vulnerability.geojson',
  exposure: '/runs/{run}/exposure?p=&t=',
  clock: '/clock',
  clockWs: '/clock/ws',
};

const TERRAIN_TILES = ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'];
const TERRAIN_ATTRIBUTION =
  'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles</a> (USGS 3DEP, SRTM) on AWS Open Data';

// Free raster basemaps that need no API key. CARTO's public tiles now watermark without a key.
const BASEMAPS = {
  dark: {
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'],
    labels: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}'],
    attribution: 'Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS User Community',
    maxzoom: 16,
  },
  satellite: {
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    maxzoom: 19,
  },
  streets: {
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxzoom: 19,
  },
};

// Must match DEPTH_RAMP in flood.products.raster: the server colours every band with it.
const RAMP = [
  { v: 0.03, c: '#bfe3ff' },
  { v: 0.5, c: '#6fb3ff' },
  { v: 1.0, c: '#2a7fff' },
  { v: 2.0, c: '#0a4fc0' },
  { v: 4.0, c: '#052a66' },
];
const BAND_UNITS = {
  depth_mid: 'm',
  depth_low: 'm',
  depth_high: 'm',
  velocity_ms: 'm/s',
  hazard_dv: 'm2/s',
  prob_inundated: 'fraction',
};
const BAND_TITLES = {
  depth_mid: 'Depth, mid member',
  depth_low: 'Depth, low member',
  depth_high: 'Depth, high member',
  velocity_ms: 'Velocity proxy',
  hazard_dv: 'Hazard, depth x velocity',
  prob_inundated: 'Probability of inundation',
};

const STEP_MS = 5 * 60 * 1000;
// 1x1 transparent PNG; the image source needs a URL before the first overlay arrives.
const TRANSPARENT_PX =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const PLACEHOLDER_COORDS = [
  [-99.2, 30.1],
  [-99.1, 30.1],
  [-99.1, 30.0],
  [-99.2, 30.0],
];

export const state = {
  runId: null,
  manifest: null,
  tz: 'UTC',
  gaugeNames: new Map(), // site -> name from the scenario file

  mode: 'forecast', // nowcast | forecast | stale | hindsight
  horizonMin: 120,
  lagMin: 60,

  band: 'depth_mid',
  maxPx: 6144, // about 12 m per pixel over the corridor, close to the 10 m grid
  opacity: 0.85,
  basemap: 'dark',
  exaggeration: 1.6,
  showHillshade: true,
  showReaches: true,
  showGauges: true,
  precomputedOnly: true, // nearest prewarmed product; never start a computation
  // Addendum 2: two independent, off-by-default demographic context layers -- neither
  // replaces the other, and neither is a core map element (PRD Addendum 2, Section 3/7).
  showVulnerability: false,
  showExposure: false,

  clock: null,
  t: null,
  dragging: false,

  overlayCoords: null, // [[lon, lat] x 4] of the last overlay
  networkReaches: [],
  gaugePoints: [],
  reachRows: new Map(), // feature_id -> reach row at (p, t)
  gaugeSeries: new Map(), // site -> [{ms, row}] sorted by ms
  lastKey: null,
  lastGaugeKey: null,
  lastState: null,
  footprintCentroids: new Map(), // structure feature_ref -> [lon, lat], from the static layer
};

let map = null;
// MapLibre finishes loading its style inside a render frame, which a hidden tab never gets.
// Data fetching therefore never waits on the map; map writes queue here until the style is in.
let styleReady = false;
const pendingMapOps = [];
let mapLoaded = false;
let pendingFit = false;
let userMoved = false;
let clockWs = null;
let debounceTimer = null;
let controller = null;
let fitted = false;
const blobUrls = [];
const gaugeMarkers = new Map(); // site -> { marker, el, feature }
let popup = null;

// ---------------------------------------------------------------------------
// Time helpers
// ---------------------------------------------------------------------------

export function formatIsoUtc(d) {
  const date = d instanceof Date ? d : new Date(d);
  if (isNaN(date.getTime())) return null;
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function formatDateTime(isoStr, timeZone = 'UTC', withZone = false) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return String(isoStr);
  try {
    const opts = {
      timeZone,
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    };
    if (withZone) opts.timeZoneName = 'short';
    return new Intl.DateTimeFormat('en-US', opts).format(d);
  } catch {
    return String(isoStr);
  }
}

const floor5 = (iso) => new Date(Math.floor(new Date(iso).getTime() / STEP_MS) * STEP_MS).toISOString();
const round5 = (iso) => new Date(Math.round(new Date(iso).getTime() / STEP_MS) * STEP_MS).toISOString();

/**
 * Same derivation as the verifier, plus hindsight:
 * - nowcast: p = clockT, t = clockT
 * - forecast: p = clockT, t = p + horizon
 * - stale: t = clockT, p = t - lag
 * - hindsight: p = 'hindsight', t = clockT
 */
export function deriveCutoffAndValid(clockIso, mode, horizonMin, lagMin) {
  if (!clockIso) return { p: null, t: null };
  const c = new Date(clockIso);
  if (isNaN(c.getTime())) return { p: null, t: null };
  if (mode === 'hindsight') return { p: 'hindsight', t: formatIsoUtc(c) };
  if (mode === 'forecast') {
    return { p: formatIsoUtc(c), t: formatIsoUtc(new Date(c.getTime() + Number(horizonMin) * 60000)) };
  }
  if (mode === 'stale') {
    return { p: formatIsoUtc(new Date(c.getTime() - Number(lagMin) * 60000)), t: formatIsoUtc(c) };
  }
  return { p: formatIsoUtc(c), t: formatIsoUtc(c) };
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const fmt = (v, digits = 1) => (v == null || Number.isNaN(Number(v)) ? '-' : Number(v).toFixed(digits));

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

function apiUrl(template, params = {}) {
  const base = template.split('?')[0].replace('{run}', encodeURIComponent(state.runId ?? ''));
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null) qs.set(k, String(v));
  }
  const q = qs.toString();
  return q ? `${base}?${q}` : base;
}

async function apiError(resp) {
  let msg = `${resp.status} ${resp.statusText}`;
  try {
    const j = await resp.json();
    if (j && j.error && j.error.message) msg = `${j.error.code}: ${j.error.message}`;
  } catch {
    /* not JSON */
  }
  return new Error(msg);
}

async function fetchJson(url, signal, init = {}) {
  const resp = await fetch(url, { ...init, signal });
  if (!resp.ok) throw await apiError(resp);
  return resp.json();
}

async function fetchOverlay(p, t, signal) {
  // smooth=1: bilinear at every scale, no dilation, anti-aliased edge. Draped on terrain the
  // verifier's cell-crisp rendering reads as blocks, and its one-pixel dilation as square rims.
  const url = apiUrl(API.overlay, { p, t, band: state.band, max_px: state.maxPx, smooth: 1, precomputed: state.precomputedOnly ? 1 : null });
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw await apiError(resp);
  // The API sends the extent both in degrees (X-Bounds-4326) and Web Mercator (X-Bounds-3857).
  const deg = resp.headers.get('X-Bounds-4326');
  const merc = resp.headers.get('X-Bounds-3857');
  const blob = await resp.blob();
  return {
    blobUrl: URL.createObjectURL(blob),
    bounds4326: deg ? deg.split(',').map(Number) : null,
    bounds3857: merc ? merc.split(',').map(Number) : null,
  };
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function showError(msg) {
  const banner = document.getElementById('error-banner');
  const text = document.getElementById('error-message');
  if (text) text.textContent = msg;
  if (banner) banner.classList.remove('hidden');
}

function hideError() {
  document.getElementById('error-banner')?.classList.add('hidden');
}

let busyCount = 0;
function setBusy(on, label = 'computing') {
  busyCount = Math.max(0, busyCount + (on ? 1 : -1));
  const el = document.getElementById('busy');
  const text = document.getElementById('busy-text');
  if (text && on) text.textContent = label;
  if (el) el.classList.toggle('hidden', busyCount === 0);
}

function updateReadout(p, t, st) {
  const tz = state.tz || 'UTC';
  const modeEl = document.getElementById('readout-mode');
  const pEl = document.getElementById('readout-p');
  const tEl = document.getElementById('readout-t');
  const cEl = document.getElementById('readout-compute');
  if (modeEl) {
    let extra = '';
    if (state.mode === 'forecast') extra = ` +${state.horizonMin} min`;
    if (state.mode === 'stale') extra = ` -${state.lagMin} min`;
    modeEl.textContent = `${state.mode}${extra}`;
  }
  const stamp = (iso) =>
    iso
      ? `${formatDateTime(iso, 'UTC')}Z<span class="local">${escapeHtml(formatDateTime(iso, tz, true))}</span>`
      : '-';
  // Served values, with the requested ones alongside when the server snapped to a
  // prewarmed neighbour, so the readout never silently disagrees with the clock.
  const req = st && st.requested ? st.requested : null;
  const servedP = p === 'hindsight' ? 'hindsight' : p;
  const askedP = req && req.p !== servedP ? ` <span class="local">asked ${escapeHtml(req.p === 'hindsight' ? 'hindsight' : formatDateTime(req.p, 'UTC') + 'Z')}</span>` : '';
  const askedT = req && req.t !== t ? ` <span class="local">asked ${escapeHtml(formatDateTime(req.t, 'UTC'))}Z</span>` : '';
  if (pEl) pEl.innerHTML = (p === 'hindsight' ? 'hindsight' : stamp(p)) + askedP;
  if (tEl) tEl.innerHTML = stamp(t) + askedT;
  if (cEl) {
    if (st && st.compute_ms) {
      const parts = [];
      if (st.compute_ms.routing != null) parts.push(`route ${st.compute_ms.routing}`);
      if (st.compute_ms.hand_mapping != null) parts.push(`map ${st.compute_ms.hand_mapping}`);
      cEl.textContent = `${st.compute_ms.total} ms (${st.cache})${parts.length ? ' ' + parts.join(', ') : ''}`;
    } else {
      cEl.textContent = '-';
    }
  }
}

function buildLegend() {
  const title = document.getElementById('legend-title');
  const ramp = document.getElementById('legend-ramp');
  if (title) title.textContent = BAND_TITLES[state.band] || state.band;
  if (!ramp) return;
  const unit = BAND_UNITS[state.band] || '';
  ramp.innerHTML = RAMP.map((s, i) => {
    const next = RAMP[i + 1];
    const label = next ? `${s.v} to ${next.v} ${unit}` : `${s.v}+ ${unit}`;
    return `<div class="legend-stop"><span class="swatch" style="background:${s.c}"></span><span>${escapeHtml(label)}</span></div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------

const emptyFC = () => ({ type: 'FeatureCollection', features: [] });

function reachColorExpr() {
  const ror = ['coalesce', ['feature-state', 'ror'], -99];
  return [
    'case',
    ['<', ror, -50],
    '#2c4b6b',
    ['interpolate', ['linear'], ror, -1, '#4dd0e1', 0, '#7fa8cc', 0.3, '#ffe082', 1, '#ffab40', 3, '#ff5252', 8, '#ff1744'],
  ];
}

function reachWidthExpr(mult) {
  const order = ['coalesce', ['get', 'stream_order'], 1];
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    9,
    ['*', mult * 0.35, order],
    12,
    ['*', mult * 0.8, order],
    15,
    ['*', mult * 2.0, order],
  ];
}

function buildStyle() {
  const sources = {
    'terrain-dem': {
      type: 'raster-dem',
      tiles: TERRAIN_TILES,
      encoding: 'terrarium',
      tileSize: 256,
      maxzoom: 15,
      attribution: TERRAIN_ATTRIBUTION,
    },
    // MapLibre asks for a separate DEM source for hillshading to keep terrain mesh quality.
    'hillshade-dem': { type: 'raster-dem', tiles: TERRAIN_TILES, encoding: 'terrarium', tileSize: 256, maxzoom: 15 },
    depth: { type: 'image', url: TRANSPARENT_PX, coordinates: PLACEHOLDER_COORDS },
    reaches: { type: 'geojson', data: emptyFC(), promoteId: 'feature_id' },
    // Addendum 2: static (Addendum 1) and live-fused vulnerability layers. Both are
    // time-invariant *sources* that just get new data pushed in; only their layer
    // visibility toggles.
    'vulnerability-static': { type: 'geojson', data: emptyFC() },
    'exposure-live': { type: 'geojson', data: emptyFC() },
  };
  for (const [k, b] of Object.entries(BASEMAPS)) {
    sources[`basemap-${k}`] = { type: 'raster', tiles: b.tiles, tileSize: 256, maxzoom: b.maxzoom, attribution: b.attribution };
    if (b.labels) sources[`labels-${k}`] = { type: 'raster', tiles: b.labels, tileSize: 256, maxzoom: b.maxzoom };
  }

  const layers = [{ id: 'background', type: 'background', paint: { 'background-color': '#05080f' } }];
  for (const k of Object.keys(BASEMAPS)) {
    layers.push({
      id: `basemap-${k}`,
      type: 'raster',
      source: `basemap-${k}`,
      layout: { visibility: k === state.basemap ? 'visible' : 'none' },
      paint: { 'raster-opacity': 1, 'raster-fade-duration': 150 },
    });
  }
  layers.push({
    id: 'hillshade',
    type: 'hillshade',
    source: 'hillshade-dem',
    layout: { visibility: state.showHillshade ? 'visible' : 'none' },
    paint: {
      'hillshade-exaggeration': 0.6,
      'hillshade-illumination-direction': 315,
      'hillshade-shadow-color': '#020509',
      'hillshade-highlight-color': '#6d8fb0',
      'hillshade-accent-color': '#0b1a2c',
    },
  });
  // Addendum 2 ordering: below the live hazard tiles, above terrain/hillshade, so current
  // flood conditions always visually dominate these supplementary demographic layers.
  layers.push({
    id: 'vulnerability-heat',
    type: 'heatmap',
    source: 'vulnerability-static',
    layout: { visibility: state.showVulnerability ? 'visible' : 'none' },
    paint: {
      'heatmap-weight': ['coalesce', ['get', 'weight'], 0],
      'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 8, 0.6, 14, 1.4],
      'heatmap-color': [
        'interpolate', ['linear'], ['heatmap-density'],
        0, 'rgba(0,0,0,0)',
        0.3, '#c9b7ff',
        0.6, '#8f6bff',
        1, '#4b1fbd',
      ],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 8, 12, 14, 28],
      'heatmap-opacity': 0.75,
    },
  });
  layers.push({
    id: 'exposure-heat',
    type: 'heatmap',
    source: 'exposure-live',
    layout: { visibility: state.showExposure ? 'visible' : 'none' },
    paint: {
      'heatmap-weight': ['coalesce', ['get', 'weight'], 0],
      'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 8, 0.6, 14, 1.4],
      'heatmap-color': [
        'interpolate', ['linear'], ['heatmap-density'],
        0, 'rgba(0,0,0,0)',
        0.3, '#ffffb2',
        0.6, '#fd8d3c',
        1, '#bd0026',
      ],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 8, 12, 14, 28],
      'heatmap-opacity': 0.8,
    },
  });
  layers.push({
    id: 'depth',
    type: 'raster',
    source: 'depth',
    paint: { 'raster-opacity': state.opacity, 'raster-fade-duration': 0, 'raster-resampling': 'linear' },
  });
  const reachFilter = ['==', ['get', 'in_aoi'], true];
  const lineLayout = { 'line-cap': 'round', 'line-join': 'round', visibility: state.showReaches ? 'visible' : 'none' };
  layers.push({
    id: 'reaches-glow',
    type: 'line',
    source: 'reaches',
    filter: reachFilter,
    layout: lineLayout,
    paint: { 'line-color': reachColorExpr(), 'line-width': reachWidthExpr(3.2), 'line-opacity': 0.28, 'line-blur': 3 },
  });
  layers.push({
    id: 'reaches',
    type: 'line',
    source: 'reaches',
    filter: reachFilter,
    layout: lineLayout,
    paint: { 'line-color': reachColorExpr(), 'line-width': reachWidthExpr(1.0), 'line-opacity': 0.95 },
  });
  // Place-name labels sit above the water and reaches so towns stay readable under the flood.
  for (const [k, b] of Object.entries(BASEMAPS)) {
    if (!b.labels) continue;
    layers.push({
      id: `labels-${k}`,
      type: 'raster',
      source: `labels-${k}`,
      layout: { visibility: k === state.basemap ? 'visible' : 'none' },
      paint: { 'raster-opacity': 0.9, 'raster-fade-duration': 150 },
    });
  }

  return {
    version: 8,
    sources,
    layers,
    sky: {
      'sky-color': '#0b1a2e',
      'horizon-color': '#1b3552',
      'fog-color': '#070c14',
      'fog-ground-blend': 0.55,
      'horizon-fog-blend': 0.75,
      'sky-horizon-blend': 0.85,
      'atmosphere-blend': 0.6,
    },
    terrain: { source: 'terrain-dem', exaggeration: state.exaggeration },
  };
}

function initMap() {
  map = new maplibregl.Map({
    container: 'map',
    style: buildStyle(),
    center: [-99.15, 30.03],
    zoom: 10.4,
    pitch: 60,
    bearing: -15,
    maxPitch: 80,
    // The terrain tiles stop at zoom 15 and draped layers stop rendering past the terrain
    // source's maxzoom; 15 already shows a 10 m grid cell at several screen pixels.
    maxZoom: 15,
    attributionControl: { compact: true },
  });
  // A camera move by hand before the first overlay arrives cancels the automatic corridor fit.
  map.on('movestart', (e) => {
    if (e && e.originalEvent) userMoved = true;
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
  map.once('style.load', () => {
    styleReady = true;
    for (const fn of pendingMapOps.splice(0)) fn();
  });
  map.once('load', () => {
    mapLoaded = true;
    if (pendingFit) {
      pendingFit = false;
      fitCorridor();
    }
  });

  map.on('mouseenter', 'reaches', () => (map.getCanvas().style.cursor = 'pointer'));
  map.on('mouseleave', 'reaches', () => (map.getCanvas().style.cursor = ''));
  map.on('click', 'reaches', (e) => {
    const f = e.features && e.features[0];
    if (f) showReachPopup(f, e.lngLat);
  });
  map.on('error', (e) => {
    // Tile 404s at the edge of coverage are routine; only surface source-level failures.
    const msg = e && e.error && e.error.message;
    if (msg && /style|source|WebGL/i.test(msg)) showError(msg);
  });
}

// ---------------------------------------------------------------------------
// Overlay, reaches, gauges
// ---------------------------------------------------------------------------

function whenStyleReady(fn) {
  if (styleReady) fn();
  else pendingMapOps.push(fn);
}

function mercToLngLat(x, y) {
  const R = 6378137;
  const lon = ((x / R) * 180) / Math.PI;
  const lat = ((2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180) / Math.PI;
  return [lon, lat];
}

const validBounds = (b) => Array.isArray(b) && b.length === 4 && b.every(Number.isFinite);

function mercBoundsToCoords([xmin, ymin, xmax, ymax]) {
  return [mercToLngLat(xmin, ymax), mercToLngLat(xmax, ymax), mercToLngLat(xmax, ymin), mercToLngLat(xmin, ymin)];
}

function degBoundsToCoords([west, south, east, north]) {
  return [[west, north], [east, north], [east, south], [west, south]];
}

function applyOverlay({ blobUrl, bounds4326, bounds3857 }) {
  let coords = state.overlayCoords;
  if (validBounds(bounds4326)) coords = degBoundsToCoords(bounds4326);
  else if (validBounds(bounds3857)) coords = mercBoundsToCoords(bounds3857);
  if (!coords) return;
  state.overlayCoords = coords;
  whenStyleReady(() => {
    const src = map.getSource('depth');
    if (src) src.updateImage({ url: blobUrl, coordinates: coords });
    // Revoke with a two-generation delay so a still-loading image is never pulled away.
    blobUrls.push(blobUrl);
    while (blobUrls.length > 2) URL.revokeObjectURL(blobUrls.shift());
  });
}

// Mirrors flood.impact.exposure_fusion.demographic_feature_id_to_feature_ref exactly. The
// ingest-time FEMA/static identity match has already aligned the static OSM ID with the
// impact extractor's structure ID, so this remains a deterministic transform at render time.
function demographicFeatureIdToFeatureRef(featureId, layerId = 'structure') {
  const stripped = String(featureId).replace(/^[a-z_]+:/, '');
  return `${layerId}:${stripped.replace(/[:/]/g, '.')}`;
}

function applyVulnerability(fc) {
  state.footprintCentroids = new Map();
  for (const f of fc.features || []) {
    const fid = f.properties && f.properties.feature_id;
    if (!fid || !f.geometry || f.geometry.type !== 'Point') continue;
    state.footprintCentroids.set(demographicFeatureIdToFeatureRef(fid), f.geometry.coordinates);
  }
  whenStyleReady(() => map.getSource('vulnerability-static')?.setData(fc));
}

async function fetchExposure(p, t, signal) {
  // Supplementary layer: never block or error out the main refresh cycle if it is unavailable
  // (e.g. this tick has not been through `flood impacts extract` yet).
  try {
    return await fetchJson(apiUrl(API.exposure, { p, t, precomputed: state.precomputedOnly ? 1 : null }), signal);
  } catch {
    return [];
  }
}

function applyExposure(features) {
  const fc = {
    type: 'FeatureCollection',
    features: (features || [])
      .map((f) => {
        const coords = state.footprintCentroids.get(f.feature_id);
        if (!coords) return null;
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: coords },
          properties: { weight: f.weight, feature_id: f.feature_id },
        };
      })
      .filter(Boolean),
  };
  whenStyleReady(() => map.getSource('exposure-live')?.setData(fc));
}

function applyReaches(rows) {
  state.reachRows = new Map(rows.map((r) => [Number(r.feature_id), r]));
  whenStyleReady(() => {
    if (!map.getSource('reaches')) return;
    for (const f of state.networkReaches) {
      const id = Number(f.properties.feature_id);
      const r = state.reachRows.get(id);
      map.setFeatureState(
        { source: 'reaches', id },
        r ? { ror: r.rate_of_rise_m_per_h, stage: r.stage_mid_m, q: r.q_mid_cms } : { ror: null, stage: null, q: null },
      );
    }
  });
}

function indexGauges(rows) {
  const series = new Map();
  for (const r of rows) {
    const site = String(r.site);
    if (!series.has(site)) series.set(site, []);
    series.get(site).push({ ms: Date.parse(r.t), row: r });
  }
  for (const arr of series.values()) arr.sort((a, b) => a.ms - b.ms);
  state.gaugeSeries = series;
}

function nearestRow(arr, ms, toleranceMs = 10 * 60 * 1000) {
  if (!arr || !arr.length) return null;
  let lo = 0;
  let hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid].ms < ms) lo = mid + 1;
    else hi = mid;
  }
  const cands = [arr[lo], arr[lo - 1]].filter(Boolean);
  cands.sort((a, b) => Math.abs(a.ms - ms) - Math.abs(b.ms - ms));
  return Math.abs(cands[0].ms - ms) <= toleranceMs ? cands[0].row : null;
}

function gaugeLabel(site) {
  const name = state.gaugeNames.get(site);
  if (!name) return site;
  // "Guadalupe Rv at Hunt, TX" -> "Hunt"; "N Fk Guadalupe Rv nr Hunt, TX" -> "N Fk nr Hunt"
  const short = name.replace(/,\s*TX$/, '').replace(/Guadalupe Rv\s*/, '').replace(/^(at|nr|abv)\s+/, '').trim();
  return short || site;
}

function rebuildGaugeMarkers() {
  for (const g of gaugeMarkers.values()) g.marker.remove();
  gaugeMarkers.clear();
  for (const f of state.gaugePoints) {
    const site = String(f.properties.site);
    // MapLibre positions the marker element itself, so the styled chip is a child of a bare wrapper.
    const wrapper = document.createElement('div');
    wrapper.className = 'gauge-marker';
    const el = document.createElement('div');
    el.className = 'gauge-chip nodata';
    el.innerHTML = `<span class="gauge-name">${escapeHtml(gaugeLabel(site))}</span><span class="gauge-vals">no data</span>`;
    wrapper.appendChild(el);
    wrapper.addEventListener('click', (ev) => {
      ev.stopPropagation();
      showGaugePopup(site, f.geometry.coordinates);
    });
    const marker = new maplibregl.Marker({ element: wrapper, anchor: 'bottom' }).setLngLat(f.geometry.coordinates);
    if (state.showGauges) marker.addTo(map);
    gaugeMarkers.set(site, { marker, el, feature: f });
  }
}

function currentGaugeRow(site) {
  if (!state.lastState || !state.lastState.t) return null;
  return nearestRow(state.gaugeSeries.get(site), Date.parse(state.lastState.t));
}

function updateGaugeChips() {
  for (const [site, g] of gaugeMarkers) {
    const row = currentGaugeRow(site);
    const vals = g.el.querySelector('.gauge-vals');
    g.el.classList.remove('forecast', 'rising', 'nodata');
    if (!row) {
      vals.textContent = 'no data at t';
      g.el.classList.add('nodata');
      continue;
    }
    const pred = row.predicted_q_mid_cms;
    const obs = row.observed_q_cms;
    vals.textContent = `Q ${fmt(pred, 0)} cms${obs != null ? ` (obs ${fmt(obs, 0)})` : ''}`;
    if (row.is_forecast) g.el.classList.add('forecast');
    const rr = state.reachRows.get(Number(row.feature_id));
    if (rr && rr.rate_of_rise_m_per_h > 0.3) g.el.classList.add('rising');
  }
}

function openPopup(lngLat, html) {
  if (popup) popup.remove();
  popup = new maplibregl.Popup({ closeButton: true, maxWidth: '340px' }).setLngLat(lngLat).setHTML(html).addTo(map);
}

function showGaugePopup(site, lngLat) {
  const row = currentGaugeRow(site);
  const name = state.gaugeNames.get(site) || site;
  const tz = state.tz || 'UTC';
  let body;
  if (!row) {
    body = '<div class="popup-note">No gauge row within 10 minutes of the valid time.</div>';
  } else {
    body = `
      <div class="popup-grid">
        <span class="k">valid t</span><span>${escapeHtml(formatDateTime(row.t, tz, true))}${row.is_forecast ? ' (forecast)' : ''}</span>
        <span class="k">Q predicted</span><span>${fmt(row.predicted_q_mid_cms, 0)} cms (${fmt(row.predicted_q_low_cms, 0)} to ${fmt(row.predicted_q_high_cms, 0)})</span>
        <span class="k">Q observed</span><span>${row.observed_q_cms != null ? `${fmt(row.observed_q_cms, 0)} cms` : '-'}</span>
        <span class="k">WSE predicted</span><span>${fmt(row.predicted_wse_mid_m, 2)} m ${escapeHtml(row.wse_datum || '')}</span>
        <span class="k">WSE observed</span><span>${row.observed_wse_m != null ? `${fmt(row.observed_wse_m, 2)} m` : '-'}</span>
      </div>`;
    const rr = state.reachRows.get(Number(row.feature_id));
    if (rr) {
      body += `<div class="popup-note">Reach ${rr.feature_id}: stage ${fmt(rr.stage_mid_m, 2)} m, rate of rise ${fmt(rr.rate_of_rise_m_per_h, 2)} m/h, source ${escapeHtml(rr.source)}</div>`;
    }
  }
  openPopup(lngLat, `<div class="popup-title">${escapeHtml(name)}</div><div class="popup-note">USGS ${escapeHtml(site)}</div>${body}`);
}

function showReachPopup(feature, lngLat) {
  const p = feature.properties || {};
  const fid = Number(p.feature_id);
  const r = state.reachRows.get(fid);
  const tz = state.tz || 'UTC';
  let body;
  if (!r) {
    body = '<div class="popup-note">No reach row at the current (p, t).</div>';
  } else {
    body = `
      <div class="popup-grid">
        <span class="k">valid t</span><span>${escapeHtml(formatDateTime(r.t, tz, true))}${r.is_forecast ? ' (forecast)' : ''}</span>
        <span class="k">Q mid</span><span>${fmt(r.q_mid_cms, 0)} cms (${fmt(r.q_low_cms, 0)} to ${fmt(r.q_high_cms, 0)})</span>
        <span class="k">stage mid</span><span>${fmt(r.stage_mid_m, 2)} m (${fmt(r.stage_low_m, 2)} to ${fmt(r.stage_high_m, 2)})</span>
        <span class="k">rate of rise</span><span>${fmt(r.rate_of_rise_m_per_h, 2)} m/h</span>
        <span class="k">velocity</span><span>${fmt(r.velocity_ms, 2)} m/s</span>
        <span class="k">source</span><span>${escapeHtml(r.source)}${r.clipped_to_src ? ', clipped to rating curve' : ''}</span>
      </div>`;
  }
  const gauge = p.gauge_site ? ` &middot; gauge ${escapeHtml(p.gauge_site)}` : '';
  openPopup(
    lngLat,
    `<div class="popup-title">Reach ${fid}</div><div class="popup-note">order ${escapeHtml(p.stream_order)}, levelpath ${escapeHtml(p.levelpath_id)}, ${fmt(Number(p.length_m) / 1000, 1)} km${gauge}</div>${body}`,
  );
}

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------

function coordsBbox(coordsList) {
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  for (const [lon, lat] of coordsList) {
    if (lon < w) w = lon;
    if (lon > e) e = lon;
    if (lat < s) s = lat;
    if (lat > n) n = lat;
  }
  return Number.isFinite(w) ? [[w, s], [e, n]] : null;
}

function reachCoords() {
  const out = [];
  for (const f of state.networkReaches) {
    if (!f.properties.in_aoi) continue;
    const g = f.geometry;
    if (g.type === 'LineString') out.push(...g.coordinates);
    else if (g.type === 'MultiLineString') for (const part of g.coordinates) out.push(...part);
  }
  return out;
}

function fitCorridor() {
  const bbox = coordsBbox(state.overlayCoords || reachCoords());
  if (!bbox) return;
  const el = map.getContainer();
  const w = el.clientWidth;
  const h = el.clientHeight;
  // Fitting before the first render, or into a hidden zero-size pane, lands on zoom 0. Wait for load.
  if (!mapLoaded || w < 200 || h < 200) {
    pendingFit = true;
    return;
  }
  const padding = {
    top: Math.min(70, Math.round(h * 0.15)),
    bottom: Math.min(100, Math.round(h * 0.2)),
    left: Math.min(330, Math.round(w * 0.4)),
    right: Math.min(40, Math.round(w * 0.05)),
  };
  map.fitBounds(bbox, { padding, pitch: 58, bearing: -12, duration: 1400 });
}

function flyToSite(site) {
  const g = gaugeMarkers.get(site);
  if (!g) {
    showError(`Gauge ${site} is not in this run's network`);
    return;
  }
  userMoved = true;
  map.flyTo({ center: g.marker.getLngLat(), zoom: 13.4, pitch: 66, bearing: -28, duration: 1600 });
}

// ---------------------------------------------------------------------------
// Fetch cycle
// ---------------------------------------------------------------------------

function bucketKey() {
  if (!state.runId || !state.t) return null;
  const { p, t } = deriveCutoffAndValid(state.t, state.mode, state.horizonMin, state.lagMin);
  if (!p || !t) return null;
  const pKey = p === 'hindsight' ? p : floor5(p);
  return `${state.runId}|${state.mode}|${pKey}|${round5(t)}|${state.band}|${state.maxPx}|${state.precomputedOnly}`;
}

export function scheduleRefresh() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(refresh, 150);
}

// One request cycle at a time. The server serialises Run computations, and an aborted fetch
// does not cancel the server-side work, so a playing clock would otherwise queue a cycle per
// tick. While a cycle is in flight, later ticks only mark a rerun; the newest (p, t) wins.
let inFlight = false;
let rerunPending = false;

async function refresh() {
  const key = bucketKey();
  if (!key || key === state.lastKey) return;
  if (inFlight) {
    rerunPending = true;
    return;
  }
  inFlight = true;
  controller = new AbortController();
  const { signal } = controller;
  const { p, t } = deriveCutoffAndValid(state.t, state.mode, state.horizonMin, state.lagMin);
  state.lastKey = key;
  updateReadout(p, t, null);
  setBusy(true, state.lastState ? 'computing' : 'routing the record (up to a minute)');
  try {
    const st = await fetchJson(apiUrl(API.state, { p, t, precomputed: state.precomputedOnly ? 1 : null }), signal);
    state.lastState = st;
    updateReadout(st.p == null ? 'hindsight' : st.p, st.t, st);

    const [overlay, reaches, exposure] = await Promise.all([
      fetchOverlay(p, t, signal),
      fetchJson(apiUrl(API.reaches, { p, t, precomputed: state.precomputedOnly ? 1 : null }), signal),
      fetchExposure(p, t, signal),
    ]);
    applyOverlay(overlay);
    applyReaches(reaches);
    applyExposure(exposure);

    const gaugeKey = `${state.runId}|${p === 'hindsight' ? p : floor5(p)}`;
    if (gaugeKey !== state.lastGaugeKey) {
      const rows = await fetchJson(apiUrl(API.gauges, { p, precomputed: state.precomputedOnly ? 1 : null }), signal);
      indexGauges(rows);
      state.lastGaugeKey = gaugeKey;
    }
    updateGaugeChips();

    if (!fitted) {
      fitted = true;
      if (!userMoved) fitCorridor();
    }
    hideError();
  } catch (err) {
    if (!(err && err.name === 'AbortError')) showError(err && err.message ? err.message : String(err));
  } finally {
    inFlight = false;
    setBusy(false);
    if (rerunPending) {
      rerunPending = false;
      scheduleRefresh();
    }
  }
}

function forceRefresh() {
  state.lastKey = null;
  scheduleRefresh();
}

function abortInFlight() {
  if (controller) controller.abort();
  rerunPending = false;
}

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

function connectClock() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  try {
    clockWs = new WebSocket(`${proto}//${window.location.host}${API.clockWs}`);
  } catch {
    return;
  }
  clockWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg && msg.error) {
        showError(msg.error.message || 'clock error');
        return;
      }
      handleClock(msg);
    } catch {
      /* ignore malformed frames */
    }
  };
  clockWs.onclose = () => setTimeout(connectClock, 3000);
  clockWs.onerror = () => {
    try {
      clockWs.close();
    } catch {
      /* already closed */
    }
  };
}

function handleClock(msg) {
  if (!msg || !msg.t) return;
  state.clock = msg;
  state.t = msg.t;
  const playBtn = document.getElementById('btn-play');
  if (playBtn) playBtn.textContent = msg.playing ? 'Playing' : 'Play';
  const speedSel = document.getElementById('speed-select');
  if (speedSel && msg.speed != null && !speedSel.matches(':focus')) speedSel.value = String(msg.speed);
  updateTimeline(msg);
  if (bucketKey() !== state.lastKey) scheduleRefresh();
}

function updateTimeline(clock) {
  const slider = document.getElementById('timeline-slider');
  const startEl = document.getElementById('timeline-start');
  const currEl = document.getElementById('timeline-current');
  const endEl = document.getElementById('timeline-end');
  if (!slider || !clock) return;
  const tz = state.tz || 'UTC';
  const startS = clock.record_start ? Math.floor(Date.parse(clock.record_start) / 1000) : 0;
  const endS = clock.record_end ? Math.floor(Date.parse(clock.record_end) / 1000) : startS + 86400;
  const currS = clock.t ? Math.floor(Date.parse(clock.t) / 1000) : startS;
  slider.min = String(startS);
  slider.max = String(endS);
  if (!state.dragging) {
    slider.value = String(Math.min(Math.max(currS, startS), endS));
    if (currEl) currEl.textContent = formatDateTime(clock.t, tz, true);
  }
  if (startEl && clock.record_start) startEl.textContent = formatDateTime(clock.record_start, tz, true);
  if (endEl && clock.record_end) endEl.textContent = formatDateTime(clock.record_end, tz, true);
}

async function postClock(body) {
  try {
    const st = await fetchJson(API.clock, undefined, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    handleClock(st);
  } catch (err) {
    showError(err.message || String(err));
  }
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

async function loadRuns() {
  const runs = await fetchJson(API.runs);
  const sel = document.getElementById('run-select');
  sel.innerHTML = '';
  for (const r of runs) {
    const opt = document.createElement('option');
    opt.value = r.run_id;
    const name = r.scenario && r.scenario.name ? r.scenario.name : r.scenario_id || '';
    opt.textContent = name ? `${r.run_id} (${name})` : r.run_id;
    sel.appendChild(opt);
  }
  if (!runs.length) {
    showError('No runs found. Create one with the flood CLI or POST /runs, then reload.');
    return;
  }
  const wanted = new URLSearchParams(window.location.search).get('run');
  const chosen = runs.find((r) => r.run_id === wanted) ? wanted : runs[0].run_id;
  sel.value = chosen;
  await selectRun(chosen);
}

async function selectRun(runId) {
  abortInFlight();
  state.runId = runId;
  state.lastKey = null;
  state.lastGaugeKey = null;
  state.lastState = null;
  state.reachRows = new Map();
  state.gaugeSeries = new Map();
  fitted = false;
  setBusy(true, 'loading run');
  try {
    state.manifest = await fetchJson(apiUrl(API.run));
    const sc = state.manifest.scenario || {};
    state.tz = sc.timezone || 'UTC';
    const badge = document.getElementById('scenario-badge');
    if (badge) badge.textContent = sc.name || sc.scenario_id || runId;
    // The clock usually arrives before the manifest; redraw its labels in the scenario's time zone.
    if (state.clock) updateTimeline(state.clock);

    state.gaugeNames = new Map();
    if (sc.scenario_id) {
      try {
        const scenario = await fetchJson(API.scenario.replace('{scenario_id}', encodeURIComponent(sc.scenario_id)));
        for (const g of scenario.hydrology?.gauges || []) state.gaugeNames.set(String(g.site), g.name);
      } catch {
        /* names are cosmetic */
      }
    }

    try {
      applyVulnerability(await fetchJson(apiUrl(API.vulnerability)));
    } catch {
      /* Addendum 1 layer is optional: absent for scenarios with no demographic-risk output */
    }

    const fc = await fetchJson(apiUrl(API.network));
    state.networkReaches = fc.features.filter((f) => f.properties && f.properties.kind === 'reach');
    const gaugeFilter = state.gaugeNames.size
      ? (f) => state.gaugeNames.has(String(f.properties.site))
      : (f) => f.properties.in_aoi;
    state.gaugePoints = fc.features.filter((f) => f.properties && f.properties.kind === 'gauge' && gaugeFilter(f));
    const reachFC = { type: 'FeatureCollection', features: state.networkReaches };
    whenStyleReady(() => map.getSource('reaches')?.setData(reachFC));
    rebuildGaugeMarkers();
    const clock = state.clock;
    if (clock) updateTimeline(clock);
    scheduleRefresh();
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

function bindControls() {
  document.getElementById('btn-dismiss-error')?.addEventListener('click', hideError);

  document.getElementById('run-select')?.addEventListener('change', (e) => selectRun(e.target.value));

  document.getElementById('mode-group')?.addEventListener('change', (e) => {
    if (e.target.name !== 'mode') return;
    state.mode = e.target.value;
    document.getElementById('horizon-group')?.classList.toggle('hidden', state.mode !== 'forecast');
    document.getElementById('lag-group')?.classList.toggle('hidden', state.mode !== 'stale');
    forceRefresh();
  });
  document.getElementById('horizon-select')?.addEventListener('change', (e) => {
    state.horizonMin = Number(e.target.value);
    forceRefresh();
  });
  document.getElementById('lag-select')?.addEventListener('change', (e) => {
    state.lagMin = Number(e.target.value);
    forceRefresh();
  });

  document.getElementById('band-select')?.addEventListener('change', (e) => {
    state.band = e.target.value;
    buildLegend();
    forceRefresh();
  });
  document.getElementById('res-select')?.addEventListener('change', (e) => {
    state.maxPx = Number(e.target.value);
    forceRefresh();
  });
  document.getElementById('opacity-range')?.addEventListener('input', (e) => {
    state.opacity = Number(e.target.value);
    document.getElementById('opacity-val').textContent = `${Math.round(state.opacity * 100)}%`;
    if (map.getLayer('depth')) map.setPaintProperty('depth', 'raster-opacity', state.opacity);
  });
  document.getElementById('reaches-toggle')?.addEventListener('change', (e) => {
    state.showReaches = e.target.checked;
    for (const id of ['reaches', 'reaches-glow']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', state.showReaches ? 'visible' : 'none');
    }
  });
  document.getElementById('gauges-toggle')?.addEventListener('change', (e) => {
    state.showGauges = e.target.checked;
    for (const g of gaugeMarkers.values()) {
      if (state.showGauges) g.marker.addTo(map);
      else g.marker.remove();
    }
  });

  document.getElementById('exaggeration-range')?.addEventListener('input', (e) => {
    state.exaggeration = Number(e.target.value);
    document.getElementById('exaggeration-val').textContent = `${state.exaggeration.toFixed(1)}x`;
    map.setTerrain({ source: 'terrain-dem', exaggeration: state.exaggeration });
  });
  document.getElementById('basemap-select')?.addEventListener('change', (e) => {
    state.basemap = e.target.value;
    for (const k of Object.keys(BASEMAPS)) {
      const vis = k === state.basemap ? 'visible' : 'none';
      if (map.getLayer(`basemap-${k}`)) map.setLayoutProperty(`basemap-${k}`, 'visibility', vis);
      if (map.getLayer(`labels-${k}`)) map.setLayoutProperty(`labels-${k}`, 'visibility', vis);
    }
    // Imagery carries its own shading; keep the hillshade light so it does not muddy it.
    if (map.getLayer('hillshade')) map.setPaintProperty('hillshade', 'hillshade-exaggeration', state.basemap === 'satellite' ? 0.3 : 0.6);
  });
  document.getElementById('hillshade-toggle')?.addEventListener('change', (e) => {
    state.showHillshade = e.target.checked;
    if (map.getLayer('hillshade')) map.setLayoutProperty('hillshade', 'visibility', state.showHillshade ? 'visible' : 'none');
  });
  document.getElementById('vulnerability-toggle')?.addEventListener('change', (e) => {
    state.showVulnerability = e.target.checked;
    if (map.getLayer('vulnerability-heat')) {
      map.setLayoutProperty('vulnerability-heat', 'visibility', state.showVulnerability ? 'visible' : 'none');
    }
  });
  document.getElementById('exposure-toggle')?.addEventListener('change', (e) => {
    state.showExposure = e.target.checked;
    if (map.getLayer('exposure-heat')) {
      map.setLayoutProperty('exposure-heat', 'visibility', state.showExposure ? 'visible' : 'none');
    }
  });
  for (const btn of document.querySelectorAll('[data-camera]')) {
    btn.addEventListener('click', () => {
      const target = btn.getAttribute('data-camera');
      if (target === 'corridor') fitCorridor();
      else flyToSite(target);
    });
  }

  document.getElementById('btn-play')?.addEventListener('click', () => postClock({ playing: true }));
  document.getElementById('btn-pause')?.addEventListener('click', () => postClock({ playing: false }));
  document.getElementById('speed-select')?.addEventListener('change', (e) => postClock({ speed: Number(e.target.value) }));

  const slider = document.getElementById('timeline-slider');
  slider?.addEventListener('input', (e) => {
    state.dragging = true;
    const iso = new Date(Number(e.target.value) * 1000).toISOString();
    const currEl = document.getElementById('timeline-current');
    if (currEl) currEl.textContent = formatDateTime(iso, state.tz || 'UTC', true);
  });
  slider?.addEventListener('change', (e) => {
    state.dragging = false;
    postClock({ t: formatIsoUtc(new Date(Number(e.target.value) * 1000)) });
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
  if (typeof maplibregl === 'undefined') {
    showError('MapLibre GL JS failed to load from the CDN');
    return;
  }
  buildLegend();
  initMap();
  bindControls();
  // Debugging handle for the browser console; this is a development page.
  window.terrainView = { map, state, fitCorridor, flyToSite };
  // Clock and run data load in parallel with the terrain tiles; map writes wait for the style.
  try {
    handleClock(await fetchJson(API.clock));
  } catch (err) {
    showError(err.message || String(err));
  }
  connectClock();
  try {
    await loadRuns();
  } catch (err) {
    showError(err.message || String(err));
  }
}

if (typeof document !== 'undefined') {
  boot();
}

// Prewarmed-only mode: the server snaps to the nearest prewarmed product and never computes.
{
  const el = document.getElementById('precomputed-toggle');
  if (el) {
    el.checked = state.precomputedOnly;
    el.addEventListener('change', (e) => {
      state.precomputedOnly = e.target.checked;
      forceRefresh();
    });
  }
}
