/**
 * Breathe Route - AWS Delhi Air Quality Cycling Optimizer
 * Clean, Minimalist Console Engine
 */

const DEFAULT_API_URL = window.BREATHE_ROUTE_API_URL || "http://127.0.0.1:8000/routes";

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

// State
let map;
let startMarker = null;
let endMarker = null;
let routePolylines = [];
let windMarkers = [];
let currentRoutes = [];
let selectedRouteId = null;

let currentStart = { ...DELHI_PRESETS["cp-ig"].start };
let currentEnd = { ...DELHI_PRESETS["cp-ig"].end };
let clickStep = 0; // 0 = pick origin, 1 = pick destination

// DOM Elements
const startInput = document.getElementById("startInput");
const endInput = document.getElementById("endInput");
const findCleanestBtn = document.getElementById("findCleanestBtn");
const swapPointsBtn = document.getElementById("swapPointsBtn");
const resetViewBtn = document.getElementById("resetViewBtn");
const routesList = document.getElementById("routesList");
const routesCountBadge = document.getElementById("routesCountBadge");
const tradeoffBanner = document.getElementById("tradeoffBanner");
const tradeoffTitle = document.getElementById("tradeoffTitle");
const tradeoffDesc = document.getElementById("tradeoffDesc");
const dataStatusLabel = document.getElementById("dataStatusLabel");
const weatherText = document.getElementById("weatherText");
const windArrow = document.getElementById("windArrow");
const lastUpdatedVal = document.getElementById("lastUpdatedVal");
const limitationsText = document.getElementById("limitationsText");

/**
 * Returns Indian NAQI Category & Color
 */
function getAQICategory(pm25) {
  if (pm25 <= 50) return { name: "Good", color: "#1d8102" };
  if (pm25 <= 100) return { name: "Satisfactory", color: "#65a30d" };
  if (pm25 <= 200) return { name: "Moderate", color: "#d97706" };
  if (pm25 <= 300) return { name: "Poor", color: "#ea580c" };
  if (pm25 <= 400) return { name: "Very Poor", color: "#dc2626" };
  return { name: "Severe", color: "#991b1b" };
}

/**
 * Initializes Leaflet with standard, completely free OpenStreetMap tiles.
 * (Zero API key required, no rate limit errors or watermarks).
 */
function initMap() {
  map = L.map("map", {
    zoomControl: true,
    attributionControl: false
  }).setView([28.6250, 77.2200], 13);

  // Standard OpenStreetMap Tiles (100% Free & Open)
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  // Map Click Listener
  map.on("click", (e) => {
    const lat = parseFloat(e.latlng.lat.toFixed(5));
    const lng = parseFloat(e.latlng.lng.toFixed(5));

    if (clickStep === 0) {
      currentStart = { lat, lng, label: `Custom (${lat}, ${lng})` };
      startInput.value = currentStart.label;
      updateMarkers();
      clickStep = 1;
    } else {
      currentEnd = { lat, lng, label: `Custom (${lat}, ${lng})` };
      endInput.value = currentEnd.label;
      updateMarkers();
      clickStep = 0;
      fetchRoutes();
    }
  });

  updateMarkers();
}

/**
 * Updates Origin (A) and Destination (B) markers on map.
 */
function updateMarkers() {
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
 * Calls backend API (AWS Lambda or local server) with mock fallback.
 */
async function fetchRoutes() {
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
    const response = await fetch(DEFAULT_API_URL, {
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
    console.warn("[BreatheRoute] Backend not reachable at", DEFAULT_API_URL, "using local fallback snapshot:", err);
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

  renderUI(data);
}

/**
 * Updates UI with received data.
 */
function renderUI(data) {
  // 1. Weather & Status Telemetry
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

  if (data.limitations) {
    limitationsText.textContent = data.limitations;
  }

  // 2. Recommendation Banner
  if (data.trade_off) {
    tradeoffBanner.style.display = "flex";
    tradeoffTitle.textContent = data.trade_off;
    const recRoute = data.routes.find(r => r.id === data.recommended_id);
    const recName = recRoute ? recRoute.id.toUpperCase() : "R1";
    tradeoffDesc.textContent = `Route ${recName} provides optimal PM2.5 avoidance along cleaner urban corridors.`;
  }

  // 3. Render Route Cards
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

  // 4. Stage 5: Render Departure Forecast
  renderDepartureForecast(data.departure_forecast);

  // 5. Stage 5: Render Source Likelihood
  renderSourceLikelihood(data.source_likelihood);

  // 6. Draw Polylines & Wind Drift Vectors
  drawRoutesOnMap(data.routes, data.recommended_id, data.weather);
}

/**
 * Stage 5: Renders the 12-hour departure forecast & optimal departure window.
 */
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

/**
 * Stage 5: Renders particulate source likelihood contribution bars.
 */
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

/**
/**
 * Draws polylines and wind drift flow indicators on OpenStreetMap.
 */
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

  // Stage 5: Draw Wind Drift Vector Arrows on Map
  if (weather && weather.wind_dir != null && routes.length > 0) {
    const recRoute = routes.find(r => r.id === recommendedId) || routes[0];
    const geom = recRoute.geometry || [];
    if (geom.length > 4) {
      // Sample 2 intermediate points along route to display wind vectors
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

  if (allBounds.length > 0) {
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

/**
 * Event Listeners
 */
findCleanestBtn.addEventListener("click", fetchRoutes);

swapPointsBtn.addEventListener("click", () => {
  const temp = { ...currentStart };
  currentStart = { ...currentEnd };
  currentEnd = { ...temp };

  startInput.value = currentStart.label || "Origin";
  endInput.value = currentEnd.label || "Destination";
  updateMarkers();
  fetchRoutes();
});

resetViewBtn.addEventListener("click", () => {
  map.setView([28.6250, 77.2200], 13);
});

document.querySelectorAll(".btn-preset").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".btn-preset").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    const presetKey = btn.getAttribute("data-preset");
    const preset = DELHI_PRESETS[presetKey];
    if (preset) {
      currentStart = { ...preset.start };
      currentEnd = { ...preset.end };
      startInput.value = preset.start.label;
      endInput.value = preset.end.label;
      updateMarkers();
      fetchRoutes();
    }
  });
});

window.addEventListener("DOMContentLoaded", () => {
  initMap();
  fetchRoutes();
});
