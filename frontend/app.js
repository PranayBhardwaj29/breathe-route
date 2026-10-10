/**
 * Breathe Route & Canopy - Unified Clean-Air Navigation & Urban Forestry Engine
 * Built for Hackathon: Environmental Hacks by AWS x WeMakeDevs
 */

const API_BASE = window.BREATHE_ROUTE_API_URL || "http://127.0.0.1:8000";
const ROUTES_API_URL = `${API_BASE}/routes`;
const OVERVIEW_API_URL = `${API_BASE}/api/overview`;
const RECOMMEND_API_URL = `${API_BASE}/api/recommend`;

// Delhi Landmark Presets
const DELHI_PRESETS = {
  "cp-ig": {
    name: "CP to India Gate",
    start: { lat: 28.6328, lng: 77.2197, label: "Connaught Place (28.6328, 77.2197)" },
    end: { lat: 28.6129, lng: 77.2295, label: "India Gate (28.6129, 77.2295)" }
  },
  "hk-saket": {
    name: "Hauz Khas to Saket",
    start: { lat: 28.5494, lng: 77.2001, label: "Hauz Khas (28.5494, 77.2001)" },
    end: { lat: 28.5244, lng: 77.2185, label: "Saket Metro (28.5244, 77.2185)" }
  },
  "du-rf": {
    name: "DU to Red Fort",
    start: { lat: 28.6904, lng: 77.2088, label: "DU North Campus (28.6904, 77.2088)" },
    end: { lat: 28.6562, lng: 77.2410, label: "Red Fort (28.6562, 77.2410)" }
  },
  "dwarka-airport": {
    name: "Dwarka to Airport",
    start: { lat: 28.5921, lng: 77.0460, label: "Dwarka Sec 10 (28.5921, 77.0460)" },
    end: { lat: 28.5562, lng: 77.0999, label: "IGI Airport T3 (28.5562, 77.0999)" }
  }
};

// Map & Layer State
let map;
let streetLayer, satelliteLayer;
let currentTileLayer;

// Navigation state
let startMarker = null;
let endMarker = null;
let routePolylines = [];
let windMarkers = [];
let currentRoutes = [];
let selectedRouteId = null;
let currentStart = { ...DELHI_PRESETS["cp-ig"].start };
let currentEnd = { ...DELHI_PRESETS["cp-ig"].end };
let clickStep = 0; // 0 = origin, 1 = destination

// Canopy Tree Recommender state
let currentMode = "navigation"; // 'navigation' | 'canopy'
let overviewSites = [];
let overviewPatches = [];
let patchesLayerGroup;
let studySitesLayerGroup;
let activeCanopyResultLayerGroup;
let showPatchesOverlay = false;
let currentCanopyData = null;
let activeMetric = "canopy";
let chartAInstance = null;
let chartBInstance = null;

// Helpers
const fmt = (x, d = 0) => Number(x || 0).toLocaleString('en-IN', { maximumFractionDigits: d });
const inr = x => x >= 1e7 ? `₹${(x / 1e7).toFixed(2)} Cr` : x >= 1e5 ? `₹${(x / 1e5).toFixed(1)} Lakh` : `₹${fmt(x)}`;

function getAQICategory(pm25) {
  if (pm25 <= 50) return { name: "Good", color: "#1d8102" };
  if (pm25 <= 100) return { name: "Satisfactory", color: "#65a30d" };
  if (pm25 <= 200) return { name: "Moderate", color: "#d97706" };
  if (pm25 <= 300) return { name: "Poor", color: "#ea580c" };
  if (pm25 <= 400) return { name: "Very Poor", color: "#dc2626" };
  return { name: "Severe", color: "#991b1b" };
}

// Chart.js Default styling
if (window.Chart) {
  Chart.defaults.font.family = "'Open Sans', sans-serif";
  Chart.defaults.color = '#545b64';
}

/**
 * Initializes Map with layer groups and tiles
 */
function initMap() {
  map = L.map("map", {
    zoomControl: true,
    attributionControl: false
  }).setView([28.6250, 77.2200], 12);

  streetLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  });

  satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri'
  });

  currentTileLayer = streetLayer;
  currentTileLayer.addTo(map);

  patchesLayerGroup = L.layerGroup();
  studySitesLayerGroup = L.layerGroup().addTo(map);
  activeCanopyResultLayerGroup = L.layerGroup().addTo(map);

  // Map Click Listener
  map.on("click", (e) => {
    const lat = parseFloat(e.latlng.lat.toFixed(5));
    const lng = parseFloat(e.latlng.lng.toFixed(5));

    if (currentMode === "navigation") {
      if (clickStep === 0) {
        currentStart = { lat, lng, label: `Custom (${lat}, ${lng})` };
        document.getElementById("startInput").value = currentStart.label;
        updateNavMarkers();
        clickStep = 1;
      } else {
        currentEnd = { lat, lng, label: `Custom (${lat}, ${lng})` };
        document.getElementById("endInput").value = currentEnd.label;
        updateNavMarkers();
        clickStep = 0;
        fetchRoutes();
      }
    } else {
      // Canopy mode click -> recommend for clicked coordinates
      document.getElementById("canopyQueryInput").value = `${lat}, ${lng}`;
      runCanopyRecommendation({ lat, lon: lng });
    }
  });

  updateNavMarkers();
}

/**
 * Updates Origin and Destination markers on map
 */
function updateNavMarkers() {
  if (startMarker) map.removeLayer(startMarker);
  if (endMarker) map.removeLayer(endMarker);

  if (currentStart) {
    const startIcon = L.divIcon({
      className: "custom-marker-icon",
      html: '<div class="marker-origin">A</div>',
      iconSize: [22, 22],
      iconAnchor: [11, 11]
    });
    startMarker = L.marker([currentStart.lat, currentStart.lng], { icon: startIcon }).addTo(map);
    startMarker.bindPopup(`<b>Origin:</b> ${currentStart.label || "Start"}`);
  }

  if (currentEnd) {
    const endIcon = L.divIcon({
      className: "custom-marker-icon",
      html: '<div class="marker-dest">B</div>',
      iconSize: [22, 22],
      iconAnchor: [11, 11]
    });
    endMarker = L.marker([currentEnd.lat, currentEnd.lng], { icon: endIcon }).addTo(map);
    endMarker.bindPopup(`<b>Destination:</b> ${currentEnd.label || "Destination"}`);
  }
}

/**
 * Fetches Navigation Routes
 */
async function fetchRoutes() {
  const routesList = document.getElementById("routesList");
  const tradeoffBanner = document.getElementById("tradeoffBanner");
  routesList.innerHTML = `
    <div class="loading-state">
      <div class="aws-spinner"></div>
      <span>Evaluating route alternatives against live Delhi air quality telemetry...</span>
    </div>
  `;
  tradeoffBanner.style.display = "none";
  clearRoutePolylines();

  const payload = {
    start: { lat: currentStart.lat, lng: currentStart.lng },
    end: { lat: currentEnd.lat, lng: currentEnd.lng },
    mode: "cycling"
  };

  let data = null;
  try {
    const response = await fetch(ROUTES_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (response.ok) {
      data = await response.json();
    } else {
      throw new Error(`API returned status ${response.status}`);
    }
  } catch (err) {
    console.warn("[BreatheRoute] Backend not reachable, using local fallback snapshot:", err);
    try {
      const mockResp = await fetch("../mock/mock_routes.json");
      if (mockResp.ok) {
        data = await mockResp.json();
        data.data_status = "cached, local snapshot";
      }
    } catch (mockErr) {
      console.error("[BreatheRoute] Fallback snapshot load error:", mockErr);
    }
  }

  if (!data || !data.routes || data.routes.length === 0) {
    routesList.innerHTML = `
      <div class="info-note" style="color: #dc2626;">
        No cycling routes found for these coordinates. Please try another pair of points in Delhi.
      </div>
    `;
    return;
  }

  currentRoutes = data.routes;
  selectedRouteId = data.recommended_id || data.routes[0].id;
  renderNavUI(data);
}

/**
 * Renders Navigation UI (Cards, departure, source apportionment)
 */
function renderNavUI(data) {
  const weatherText = document.getElementById("weatherText");
  const windArrow = document.getElementById("windArrow");
  const dataStatusLabel = document.getElementById("dataStatusLabel");
  const lastUpdatedVal = document.getElementById("lastUpdatedVal");
  const limitationsText = document.getElementById("limitationsText");
  const tradeoffBanner = document.getElementById("tradeoffBanner");
  const tradeoffTitle = document.getElementById("tradeoffTitle");
  const tradeoffDesc = document.getElementById("tradeoffDesc");
  const routesCountBadge = document.getElementById("routesCountBadge");
  const routesList = document.getElementById("routesList");

  const weather = data.weather || {};
  const windSpd = weather.wind_speed != null ? `${weather.wind_speed} km/h` : "N/A";
  const windDir = weather.wind_dir || 0;

  weatherText.textContent = `Wind ${windSpd}`;
  windArrow.style.transform = `rotate(${windDir}deg)`;

  if (data.data_status && data.data_status.startsWith("cached")) {
    dataStatusLabel.textContent = `Cached Data (${data.data_status.split(",")[1] || "recent"})`;
    document.querySelector(".status-dot").style.background = "#d97706";
  } else {
    dataStatusLabel.textContent = "Live Data (Copernicus / OpenAQ)";
    document.querySelector(".status-dot").style.background = "#1d8102";
  }

  lastUpdatedVal.textContent = data.aqi_updated_at ? new Date(data.aqi_updated_at).toLocaleTimeString() : "Live";
  if (data.limitations) limitationsText.textContent = data.limitations;

  if (data.trade_off) {
    tradeoffBanner.style.display = "flex";
    tradeoffTitle.textContent = data.trade_off;
    const recRoute = data.routes.find(r => r.id === data.recommended_id);
    const recName = recRoute ? recRoute.id.toUpperCase() : "R1";
    tradeoffDesc.textContent = `Route ${recName} provides optimal PM2.5 avoidance along cleaner urban corridors.`;
  }

  routesCountBadge.textContent = `${data.routes.length} Available`;
  routesList.innerHTML = "";

  data.routes.forEach((route, index) => {
    const isRecommended = route.id === data.recommended_id;
    const isSelected = route.id === selectedRouteId;
    const distKm = (route.distance_m / 1000).toFixed(1);
    const durMin = Math.round(route.duration_s / 60);
    const aqiCat = getAQICategory(route.avg_aqi || route.exposure_score);

    const card = document.createElement("div");
    card.className = `route-card ${isSelected ? 'selected' : ''}`;
    card.id = `card-${route.id}`;
    card.style.animationDelay = `${index * 0.08}s`;
    card.innerHTML = `
      <div class="route-card-header">
        <div class="route-name-wrap">
          <span class="route-name">Route ${index + 1} (${route.id.toUpperCase()})</span>
          ${isRecommended ? '<span class="pill-cleanest">★ Cleanest</span>' : ''}
        </div>
        <span class="pill-naqi" style="background-color: ${aqiCat.color};">${aqiCat.name}</span>
      </div>
      
      <div class="route-metrics-table">
        <div class="metric-cell">
          <span class="metric-label">Estimated Time</span>
          <span class="metric-value">${durMin} min</span>
        </div>
        <div class="metric-cell">
          <span class="metric-label">Total Distance</span>
          <span class="metric-value">${distKm} km</span>
        </div>
        <div class="metric-cell">
          <span class="metric-label">PM2.5 Exposure</span>
          <span class="metric-value exposure-highlight">${route.exposure_score} <small>μg/m³</small></span>
        </div>
      </div>
    `;

    card.addEventListener("click", () => selectRoute(route.id));
    routesList.appendChild(card);
  });

  renderDepartureForecast(data.departure_forecast);
  renderSourceLikelihood(data.source_likelihood);
  drawRoutesOnMap(data.routes, data.recommended_id, data.weather);
}

function renderDepartureForecast(forecast) {
  const forecastCard = document.getElementById("forecastCard");
  const heading = document.getElementById("departureTimeHeading");
  const recText = document.getElementById("departureRecText");
  const timeline = document.getElementById("forecastTimeline");

  if (!forecast || forecast.status !== "available") {
    forecastCard.style.display = "none";
    return;
  }

  forecastCard.style.display = "block";
  heading.textContent = `Optimal Departure: ${forecast.recommended_departure_time}`;
  recText.textContent = forecast.recommendation_text;

  timeline.innerHTML = "";
  (forecast.hourly_timeline || []).slice(0, 8).forEach(item => {
    const isOptimal = item.time === forecast.recommended_departure_time;
    const cat = getAQICategory(item.pm25);

    const step = document.createElement("div");
    step.className = `forecast-step ${isOptimal ? 'optimal' : ''}`;
    step.innerHTML = `
      <span class="forecast-time">${item.time}</span>
      <span class="forecast-pm25">${item.pm25}</span>
      <span class="forecast-badge" style="background-color: ${cat.color};">${cat.name}</span>
    `;
    timeline.appendChild(step);
  });
}

function renderSourceLikelihood(sources) {
  const sourceCard = document.getElementById("sourceCard");
  const primaryName = document.getElementById("sourcePrimaryName");
  const explanation = document.getElementById("sourceExplanation");
  const container = document.getElementById("sourceBarsContainer");

  if (!sources || !sources.breakdown) {
    sourceCard.style.display = "none";
    return;
  }

  sourceCard.style.display = "block";
  primaryName.textContent = sources.primary_source;
  explanation.textContent = sources.explanation;

  container.innerHTML = "";
  sources.breakdown.forEach(item => {
    const row = document.createElement("div");
    row.className = "source-bar-row";
    row.innerHTML = `
      <div class="source-bar-header">
        <span>${item.source}</span>
        <strong>${item.percentage}%</strong>
      </div>
      <div class="source-bar-track">
        <div class="source-bar-fill" style="width: ${item.percentage}%; background-color: ${item.color};"></div>
      </div>
    `;
    container.appendChild(row);
  });
}

function drawRoutesOnMap(routes, recommendedId, weather) {
  clearRoutePolylines();
  const allBounds = [];

  routes.forEach((route) => {
    const isSelected = route.id === selectedRouteId;
    const isRecommended = route.id === recommendedId;
    const aqiCat = getAQICategory(route.avg_aqi || route.exposure_score);

    const latLngs = route.geometry;
    latLngs.forEach(pt => allBounds.push(pt));

    const polyline = L.polyline(latLngs, {
      color: isSelected ? (isRecommended ? "#1d8102" : aqiCat.color) : "#545b64",
      weight: isSelected ? 6 : 4,
      opacity: isSelected ? 0.95 : 0.5,
      lineCap: "round",
      lineJoin: "round"
    }).addTo(map);

    polyline.on("click", () => selectRoute(route.id));
    polyline.bindTooltip(
      `<b>Route ${route.id.toUpperCase()}</b><br>Exposure: ${route.exposure_score} μg/m³ (${aqiCat.name})<br>Time: ${Math.round(route.duration_s / 60)} min`,
      { sticky: true }
    );

    routePolylines.push({ id: route.id, polyline, categoryColor: aqiCat.color });
  });

  // Wind Drift Vectors
  if (weather && weather.wind_dir != null && routes.length > 0) {
    const recRoute = routes.find(r => r.id === recommendedId) || routes[0];
    const geom = recRoute.geometry || [];
    if (geom.length > 4) {
      const idxs = [Math.floor(geom.length * 0.35), Math.floor(geom.length * 0.7)];
      idxs.forEach(idx => {
        const pt = geom[idx];
        const windIcon = L.divIcon({
          className: "custom-wind-icon",
          html: `<div class="wind-drift-marker" style="transform: rotate(${weather.wind_dir}deg);" title="Wind Drift: ${weather.wind_speed} km/h">➤</div>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14]
        });
        const wMarker = L.marker([pt[0], pt[1]], { icon: windIcon }).addTo(map);
        wMarker.bindTooltip(`<b>Wind Drift:</b> ${weather.wind_speed} km/h from ${weather.wind_dir}°<br><small>Carries airborne particulates</small>`);
        windMarkers.push(wMarker);
      });
    }
  }

  if (allBounds.length > 0 && currentMode === "navigation") {
    map.fitBounds(allBounds, { padding: [40, 40] });
  }
}

function selectRoute(routeId) {
  selectedRouteId = routeId;
  document.querySelectorAll(".route-card").forEach(c => c.classList.remove("selected"));
  const card = document.getElementById(`card-${routeId}`);
  if (card) card.classList.add("selected");

  routePolylines.forEach(item => {
    if (item.id === routeId) {
      item.polyline.setStyle({
        color: item.categoryColor,
        weight: 6,
        opacity: 1.0
      });
      item.polyline.bringToFront();
    } else {
      item.polyline.setStyle({
        color: "#545b64",
        weight: 3.5,
        opacity: 0.4
      });
    }
  });
}

function clearRoutePolylines() {
  routePolylines.forEach(item => map.removeLayer(item.polyline));
  routePolylines = [];
  windMarkers.forEach(m => map.removeLayer(m));
  windMarkers = [];
}

// ==========================================================================
// Canopy Tree Recommender Logic
// ==========================================================================

async function loadCanopyOverview() {
  try {
    const res = await fetch(OVERVIEW_API_URL);
    if (!res.ok) throw new Error("Overview status " + res.status);
    const data = await res.json();
    overviewSites = data.sites || [];
    overviewPatches = data.patches || [];

    // Render Study Sites on Map
    studySitesLayerGroup.clearLayers();
    overviewSites.forEach(s => {
      const siteIcon = L.divIcon({
        className: "study-site-marker",
        html: `<div style="background:#e8a317;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.4);" title="${s.name}"></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7]
      });
      const marker = L.marker([s.lat, s.lon], { icon: siteIcon });
      marker.bindTooltip(`<b>Study Site:</b> ${s.name}<br><small>Click to recommend trees</small>`, { direction: "top" });
      marker.on("click", () => {
        document.getElementById("canopyQueryInput").value = s.name;
        runCanopyRecommendation({ query: s.name, lat: s.lat, lon: s.lon });
      });
      studySitesLayerGroup.addLayer(marker);
    });

    // Populate Patches Layer
    patchesLayerGroup.clearLayers();
    overviewPatches.forEach(p => {
      const radius = Math.max(Math.sqrt(p.area_m2 / Math.PI), 5);
      const circle = L.circle([p.lat, p.lon], {
        radius: radius,
        color: "#1f7a4d",
        weight: 1.5,
        fillColor: "#9be3b4",
        fillOpacity: 0.35
      });
      circle.bindTooltip(`<b>Planting Patch ${p.patch_id}</b><br>Area: ${fmt(p.area_m2)} m²<br>Type: ${p.site_type || 'Open land'}`);
      circle.on("click", () => {
        runCanopyRecommendation({ lat: p.lat, lon: p.lon });
      });
      patchesLayerGroup.addLayer(circle);
    });

  } catch (err) {
    console.warn("[Canopy] Failed to load overview:", err);
  }
}

async function runCanopyRecommendation(reqBody) {
  const btn = document.getElementById("canopySearchBtn");
  const errMsg = document.getElementById("canopyErrMsg");
  errMsg.textContent = "";
  btn.disabled = true;
  btn.textContent = "Analyzing...";

  try {
    const res = await fetch(RECOMMEND_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ top_k: 6, ...reqBody })
    });

    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      throw new Error(errJson.detail || errJson.error || `Error ${res.status}`);
    }

    const data = await res.json();
    currentCanopyData = data;
    renderCanopyResults(data);

    // Switch to Canopy Mode UI if not active
    if (currentMode !== "canopy") {
      switchMode("canopy");
    }
  } catch (e) {
    errMsg.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Search";
  }
}

function renderCanopyResults(data) {
  const res = data.result;
  const m = res.matched_location;
  const q = res.input_point;
  const plan = res.patch_plan;
  const ps = res.plan_summary;
  const baseline = res.baseline;
  const annual = baseline.annual;
  const needs = res.needs;

  // 1. Draw Active Results on Map
  activeCanopyResultLayerGroup.clearLayers();
  const boundsPts = [[q.lat, q.lon], [m.lat, m.lon]];

  const names = {};
  plan.forEach(p => {
    boundsPts.push([p.lat, p.lon]);
    const rad = Math.max(Math.sqrt(p.area_m2 / Math.PI), 5);
    if (p.recommended) {
      names[p.recommended] = p.common_name;
      const col = data.colors[p.recommended] || "#1f7a4d";
      const c = L.circle([p.lat, p.lon], {
        radius: rad,
        color: col,
        weight: 2.5,
        fillColor: col,
        fillOpacity: 0.55
      }).addTo(activeCanopyResultLayerGroup);

      c.bindPopup(`
        <div style="font-family: 'Open Sans', sans-serif; font-size: 0.82rem;">
          <b style="color: ${col}; font-size: 0.92rem;">${p.common_name}</b><br>
          <i>${p.scientific_name}</i><br>
          <strong>${p.n_trees} trees</strong> on ${fmt(p.area_m2)} m² (${p.site_type})<br>
          Fit Score: <strong>${fmt(p.fit_score)}/100</strong><br>
          Estimated 7yr Cost: ${inr(p.est_cost_7yr_inr)}
        </div>
      `);
    } else {
      L.circle([p.lat, p.lon], {
        radius: rad,
        color: "#999",
        weight: 1.5,
        dashArray: "4 4",
        fillOpacity: 0.1
      }).bindTooltip("No species fits this patch constraints").addTo(activeCanopyResultLayerGroup);
    }
  });

  // Connecting line if queried point differs from matched site
  if (m.distance_km > 0.03) {
    L.polyline([[q.lat, q.lon], [m.lat, m.lon]], {
      color: "#232f3e",
      weight: 2,
      dashArray: "4 6"
    }).addTo(activeCanopyResultLayerGroup);
  }

  // Target query pin
  const pinIcon = L.divIcon({
    className: "canopy-query-pin",
    html: '<div style="background:#d97706;width:18px;height:18px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.3);"></div>',
    iconSize: [18, 18],
    iconAnchor: [9, 18]
  });
  L.marker([q.lat, q.lon], { icon: pinIcon })
    .bindTooltip(`<b>Search Target:</b> ${res.query || 'Selected location'}`, { permanent: false })
    .addTo(activeCanopyResultLayerGroup);

  if (boundsPts.length > 0) {
    map.fitBounds(boundsPts, { padding: [40, 40], maxZoom: 17 });
  }

  // Map Legend
  const legendBox = document.getElementById("canopyMapLegend");
  const legendItems = document.getElementById("canopyLegendItems");
  const allocatedIds = Object.keys(names);
  if (allocatedIds.length > 0) {
    legendBox.style.display = "block";
    legendItems.innerHTML = allocatedIds.map(id => `
      <div class="legend-dot-row">
        <span class="legend-dot" style="background: ${data.colors[id]}"></span>
        <span>${names[id]}: <strong>${fmt(ps.by_species[id])}</strong> trees</span>
      </div>
    `).join("");
  } else {
    legendBox.style.display = "none";
  }

  // 2. Render Baseline Card
  const bCard = document.getElementById("canopyBaselineCard");
  bCard.style.display = "block";
  document.getElementById("baselineHeading").textContent = `${needs.pm_need >= needs.heat_need ? 'Particulate Pollution' : 'Urban Heat'} is the dominant pressure at ${m.name}`;
  document.getElementById("baselineSiteBadge").textContent = `${m.name} (${m.distance_km} km)`;

  const pm = annual.mean.pm2_5;
  const ex = 100 * (annual.exceedance_frac.pm2_5 || 0);
  const hot = 100 * annual.heat_hours_frac;
  document.getElementById("baselineSummaryText").innerHTML = `
    PM2.5 averages <strong>${fmt(pm)} µg/m³</strong> here, exceeding national limits in <strong>${fmt(ex)}%</strong> of measured hours.
    Heat index feels &ge; 35 °C in <strong>${fmt(hot)}%</strong> of hours. Annual precipitation is ~${fmt(baseline.precip_mm_per_year)} mm.
    ${res.warnings.length ? `<br><small style="color: #ea580c;">${res.warnings.join(' ')}</small>` : ''}
  `;

  const needsLabels = {
    pm_need: "PM2.5 Particulate Burden",
    heat_need: "Heat Stress / Urban Heat Island",
    voc_sensitivity: "Ozone Precursor Sensitivity",
    water_scarcity: "Water Scarcity & VPD",
    waterlogging_risk: "Monsoon Waterlogging Risk"
  };

  const needsGrid = document.getElementById("needsGrid");
  needsGrid.innerHTML = Object.entries(needsLabels).map(([k, lbl]) => {
    const val = Math.round((needs[k] || 0) * 100);
    return `
      <div class="need-item">
        <div class="need-label-row">
          <span>${lbl}</span>
          <strong>${val}%</strong>
        </div>
        <div class="need-bar-track">
          <div class="need-bar-fill" style="width: ${val}%;"></div>
        </div>
      </div>
    `;
  }).join("");

  // 3. Render Species Ranking Table
  const sCard = document.getElementById("canopySpeciesCard");
  sCard.style.display = "block";
  document.getElementById("speciesCountBadge").textContent = `${data.table.length} Species Evaluated`;

  const tb = document.getElementById("canopyTableBody");
  tb.innerHTML = data.table.map(t => `
    <tr>
      <td>
        <div class="species-name-cell">
          <span class="species-color-swatch" style="background: ${t.color};"></span>
          <div class="species-title">
            <strong>${t.common_name}</strong>
            <em>${t.scientific_name}</em>
          </div>
        </div>
      </td>
      <td>
        <div class="fit-score-cell">
          <div class="fit-bar-track">
            <div class="fit-bar-fill" style="width: ${t.score}%; background: ${t.color};"></div>
          </div>
          <strong>${fmt(t.score)}</strong>
        </div>
      </td>
      <td>${fmt(t.pm25_g)} g</td>
      <td>${fmt(t.cooling_c, 1)} °C</td>
      <td>${fmt(t.crown_m2)} m²</td>
      <td>${fmt(t.water_l)} L</td>
      <td>${fmt(t.survival10)}%</td>
      <td>${inr(t.cost7)}</td>
      <td style="font-size: 0.69rem; color: #545b64; max-width: 140px;">${(t.why || []).slice(0, 2).join('; ') || 'Balanced fit'}</td>
    </tr>
  `).join("");

  // 4. Render 20-Year Projections & Chart.js
  const pCard = document.getElementById("canopyProjectionsCard");
  pCard.style.display = "block";

  const P = data.projection;
  const T = P.totals;
  const lastIdx = T.cum_cost.length - 1;
  const kg = T.pm25_cum_kg[lastIdx];

  const factsGrid = document.getElementById("planFactsGrid");
  factsGrid.innerHTML = [
    [fmt(ps.trees), "Trees Recommended"],
    [`${fmt(kg, 1)} kg`, "PM2.5 Captured (20 Yrs)"],
    [`${fmt(T.shade_m2[lastIdx])} m²`, "Shade Canopy Coverage (Yr 20)"],
    [inr(T.cum_cost[lastIdx]), "Total 20-Year Investment"],
    [kg ? inr(T.cum_cost[lastIdx] / kg) : 'n/a', "Cost per kg PM2.5 Captured"]
  ].map(([val, lbl]) => `
    <div class="plan-fact-item">
      <span class="plan-fact-val">${val}</span>
      <span class="plan-fact-lbl">${lbl}</span>
    </div>
  `).join("");

  drawChartA();
  drawChartB(T, P.years);

  // Export actions
  document.getElementById("downloadJsonBtn").onclick = () => downloadFile(res, "canopy_recommendations.json");
  document.getElementById("downloadGeoJsonBtn").onclick = () => downloadFile(data.geojson, "canopy_map_layers.geojson");

  // Scroll sidebar to show new recommendations smoothly
  document.getElementById("appSidebar").scrollTo({ top: bCard.offsetTop - 20, behavior: "smooth" });
}

const METRICS_META = {
  canopy: ['Growth Curve', 'canopy', 'Mature Canopy Reached (%)', 'How fast each species fills out its crown. Fast growers deliver shade and filtration sooner.'],
  pm25: ['Impact Scaled by Size', 'pm25', 'PM2.5 Captured / Tree / Yr (g)', 'Yearly particle capture per planted tree, scaled by canopy growth and survival.'],
  survival: ['Survival Rate', 'survival', 'Trees Still Alive (%)', 'Share of saplings expected to survive; losses are front-loaded in the first 3 years.'],
  cost: ['Cost Timeline', 'cum_cost', 'Cumulative Cost / Tree (₹)', 'Sapling purchase and tree guards represent upfront costs; maintenance drops steadily by year 4.']
};

function drawChartA() {
  if (!currentCanopyData) return;
  const P = currentCanopyData.projection;
  const meta = METRICS_META[activeMetric];
  document.getElementById("metricExplainerText").textContent = meta[3];

  if (chartAInstance) chartAInstance.destroy();

  const ctx = document.getElementById("chartA").getContext("2d");
  chartAInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: P.years,
      datasets: P.species.map(s => ({
        label: s.common_name,
        data: s[meta[1]],
        borderColor: s.color,
        backgroundColor: s.color,
        borderWidth: 2.2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.3
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          title: { display: true, text: "Years After Planting", font: { size: 10 } },
          grid: { display: false }
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: meta[2], font: { size: 10 } },
          grid: { color: "#eaeded" }
        }
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { usePointStyle: true, boxWidth: 6, font: { size: 10 } }
        }
      }
    }
  });
}

function drawChartB(totals, years) {
  if (chartBInstance) chartBInstance.destroy();

  const ctx = document.getElementById("chartB").getContext("2d");
  chartBInstance = new Chart(ctx, {
    data: {
      labels: years,
      datasets: [
        {
          type: "bar",
          label: "Annual Cost (₹)",
          data: totals.annual_cost,
          backgroundColor: "#ff990066",
          yAxisID: "y",
          order: 3
        },
        {
          type: "line",
          label: "Cumulative Cost (₹)",
          data: totals.cum_cost,
          borderColor: "#ec7211",
          borderWidth: 2.2,
          pointRadius: 0,
          tension: 0.3,
          yAxisID: "y",
          order: 2
        },
        {
          type: "line",
          label: "PM2.5 Captured Each Year (kg)",
          data: totals.pm25_kg,
          borderColor: "#137333",
          borderWidth: 2.2,
          pointRadius: 0,
          tension: 0.3,
          yAxisID: "y1",
          order: 1
        },
        {
          type: "line",
          label: "PM2.5 Captured Cumulative (kg)",
          data: totals.pm25_cum_kg,
          borderColor: "#1f7a4d",
          borderDash: [5, 4],
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          yAxisID: "y1",
          order: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          title: { display: true, text: "Years After Planting", font: { size: 10 } },
          grid: { display: false }
        },
        y: {
          beginAtZero: true,
          position: "left",
          title: { display: true, text: "Investment (₹)", font: { size: 10 } },
          grid: { color: "#eaeded" }
        },
        y1: {
          beginAtZero: true,
          position: "right",
          title: { display: true, text: "PM2.5 Captured (kg)", font: { size: 10 } },
          grid: { display: false }
        }
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { usePointStyle: true, boxWidth: 6, font: { size: 10 } }
        }
      }
    }
  });
}

function downloadFile(content, fileName) {
  const blob = new Blob([JSON.stringify(content, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}

// ==========================================================================
// Mode Switching & Event Listeners
// ==========================================================================

function switchMode(newMode) {
  currentMode = newMode;
  const tabNav = document.getElementById("tabNavMode");
  const tabCanopy = document.getElementById("tabCanopyMode");
  const panelNav = document.getElementById("navViewPanel");
  const panelCanopy = document.getElementById("canopyViewPanel");
  const activeLayerLabel = document.getElementById("activeLayerLabel");

  if (newMode === "navigation") {
    tabNav.classList.add("active");
    tabCanopy.classList.remove("active");
    panelNav.classList.add("active");
    panelCanopy.classList.remove("active");
    activeLayerLabel.textContent = "Navigation Mode";
    document.getElementById("canopyMapLegend").style.display = "none";
  } else {
    tabCanopy.classList.add("active");
    tabNav.classList.remove("active");
    panelCanopy.classList.add("active");
    panelNav.classList.remove("active");
    activeLayerLabel.textContent = "Canopy Tree Plan";
    if (currentCanopyData) {
      document.getElementById("canopyMapLegend").style.display = "block";
    }
  }

  // Smooth map resize & layout refresh
  setTimeout(() => {
    map.invalidateSize({ pan: false });
  }, 150);
}

document.getElementById("tabNavMode").addEventListener("click", () => switchMode("navigation"));
document.getElementById("tabCanopyMode").addEventListener("click", () => switchMode("canopy"));

// Preset buttons
document.querySelectorAll(".btn-preset").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".btn-preset").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    const presetKey = btn.getAttribute("data-preset");
    const preset = DELHI_PRESETS[presetKey];
    if (preset) {
      currentStart = { ...preset.start };
      currentEnd = { ...preset.end };
      document.getElementById("startInput").value = preset.start.label;
      document.getElementById("endInput").value = preset.end.label;
      updateNavMarkers();
      fetchRoutes();
    }
  });
});

// Swap Points
document.getElementById("swapPointsBtn").addEventListener("click", () => {
  const temp = { ...currentStart };
  currentStart = { ...currentEnd };
  currentEnd = { ...temp };
  document.getElementById("startInput").value = currentStart.label || "Origin";
  document.getElementById("endInput").value = currentEnd.label || "Destination";
  updateNavMarkers();
  fetchRoutes();
});

// Reset Delhi View
document.getElementById("resetViewBtn").addEventListener("click", () => {
  map.setView([28.6250, 77.2200], 12);
});

// Calculate routes button
document.getElementById("findCleanestBtn").addEventListener("click", fetchRoutes);

// Tile Layer Toggles
document.getElementById("btnLayerStreets").addEventListener("click", () => {
  map.removeLayer(currentTileLayer);
  currentTileLayer = streetLayer.addTo(map);
  document.getElementById("btnLayerStreets").classList.add("active");
  document.getElementById("btnLayerSatellite").classList.remove("active");
});

document.getElementById("btnLayerSatellite").addEventListener("click", () => {
  map.removeLayer(currentTileLayer);
  currentTileLayer = satelliteLayer.addTo(map);
  document.getElementById("btnLayerSatellite").classList.add("active");
  document.getElementById("btnLayerStreets").classList.remove("active");
});

// Toggle Planting Patches
const btnTogglePatches = document.getElementById("btnTogglePatches");
btnTogglePatches.addEventListener("click", () => {
  showPatchesOverlay = !showPatchesOverlay;
  if (showPatchesOverlay) {
    patchesLayerGroup.addTo(map);
    btnTogglePatches.classList.add("active");
  } else {
    map.removeLayer(patchesLayerGroup);
    btnTogglePatches.classList.remove("active");
  }
});

// Canopy Form
document.getElementById("canopySearchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("canopyQueryInput").value.trim();
  if (!q) return;

  const coordMatch = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (coordMatch) {
    runCanopyRecommendation({ lat: parseFloat(coordMatch[1]), lon: parseFloat(coordMatch[2]) });
  } else {
    runCanopyRecommendation({ query: q });
  }
});

// Canopy Study Site Chips
document.querySelectorAll(".chip-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const siteName = btn.getAttribute("data-site");
    document.getElementById("canopyQueryInput").value = siteName;
    runCanopyRecommendation({ query: siteName });
  });
});

// Chart tabs
document.querySelectorAll(".chart-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".chart-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    activeMetric = tab.getAttribute("data-metric");
    drawChartA();
  });
});

// Initialize on DOM Ready
window.addEventListener("DOMContentLoaded", () => {
  initMap();
  fetchRoutes();
  loadCanopyOverview();
});
