const API_URL = "";

let map;
let pondMarkers = [];
let catchmentLayer = null;
let channelLayer = null;
let contourLayer = null;
let selectedAreaLayer = null;
let currentResults = [];
let activeMode = "file"; // "file" | "area" | "village"

// Land area selection state
let isSelectingArea = false;
let isMouseDown = false;
let startPoint = null;
let tempRect = null;
let selectedBounds = null;

function initMap() {
  map = L.map("map").setView([21.25, 81.30], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);

  initAreaSelectionListeners();
  initModeTabs();
  // Fetch initial climatological rainfall for central coordinates
  fetchRainfallForCoords(21.25, 81.30);
}

function initModeTabs() {
  const tabs = document.querySelectorAll(".mode-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const mode = tab.dataset.mode;
      switchMode(mode);
    });
  });
}

function switchMode(mode) {
  activeMode = mode;
  const villageCard = document.getElementById("villageSearchCard");
  const analyzeBtn = document.getElementById("analyzeButton");

  if (mode === "village") {
    villageCard.classList.remove("hidden");
    document.getElementById("villageInput").focus();
    analyzeBtn.textContent = "🔍 Analyze Village / Place";
  } else if (mode === "area") {
    villageCard.classList.add("hidden");
    analyzeBtn.textContent = "📐 Analyze Selected Area (DEM)";
    if (!selectedBounds) {
      startAreaSelection();
    }
  } else {
    villageCard.classList.add("hidden");
    analyzeBtn.textContent = "Analyze Map";
  }
}

function fillVillage(name) {
  const input = document.getElementById("villageInput");
  input.value = name;
  analyzeVillage(name);
}

async function fetchRainfallForCoords(lat, lon) {
  const badge = document.getElementById("rainfallApiStatus");
  if (badge) {
    badge.textContent = "Fetching...";
    badge.style.background = "#fff3cd";
    badge.style.color = "#856404";
  }
  try {
    const res = await fetch(`${API_URL}/api/rainfall?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.annual_rainfall_mm) {
        document.getElementById("rainfallInput").value = data.annual_rainfall_mm;
        if (badge) {
          badge.textContent = data.source.includes("Open-Meteo") ? "Open-Meteo" : "NASA POWER";
          badge.style.background = "#e3f2fd";
          badge.style.color = "#1565c0";
          badge.title = data.source;
        }
      }
    }
  } catch (err) {
    if (badge) {
      badge.textContent = "Auto-API";
      badge.style.background = "#e3f2fd";
      badge.style.color = "#1565c0";
    }
  }
}

function handleFileSelect() {
  const input = document.getElementById("contourFile");
  document.getElementById("fileName").textContent = input.files.length ? input.files[0].name : "No file selected";
  if (input.files.length) {
    // Switch to file mode automatically if user chooses a file
    const fileTab = document.querySelector(`.mode-tab[data-mode="file"]`);
    if (fileTab) fileTab.click();
  }
}

function showMessage(text, isError = false) {
  const box = document.getElementById("message");
  box.textContent = text;
  box.classList.remove("hidden", "error");
  if (isError) box.classList.add("error");
}

function hideMessage() {
  document.getElementById("message").classList.add("hidden");
}

function toggleAreaSelection() {
  if (isSelectingArea) {
    cancelAreaSelection();
  } else {
    startAreaSelection();
  }
}

function startAreaSelection() {
  isSelectingArea = true;
  isMouseDown = false;
  startPoint = null;
  if (tempRect) {
    map.removeLayer(tempRect);
    tempRect = null;
  }

  const btn = document.getElementById("selectAreaBtn");
  btn.classList.add("active");
  btn.textContent = "🔴 Select on Map (Click 2 Points or Drag)";

  const instruction = document.getElementById("mapInstruction");
  instruction.innerHTML = `<span><strong>Area Selection Active:</strong> Click two corners on the map, OR click &amp; drag to define your land area.</span>
    <button type="button" class="secondary" onclick="cancelAreaSelection()" style="margin-left:12px;padding:3px 10px;font-size:11px;background:#fff;border-radius:4px;cursor:pointer;">Cancel</button>`;
  instruction.classList.remove("hidden");

  document.getElementById("map").classList.add("crosshair-cursor");
  map.dragging.disable();
  showMessage("Mode active: Click corner 1 on the map, then corner 2 (or click and drag).");
}

function cancelAreaSelection() {
  isSelectingArea = false;
  isMouseDown = false;
  startPoint = null;
  if (tempRect) {
    map.removeLayer(tempRect);
    tempRect = null;
  }
  const btn = document.getElementById("selectAreaBtn");
  btn.classList.remove("active");
  btn.textContent = selectedBounds ? "📐 Re-select Area" : "📐 Select Area on Map";
  document.getElementById("mapInstruction").classList.add("hidden");
  document.getElementById("map").classList.remove("crosshair-cursor");
  map.dragging.enable();
}

function clearSelectedArea() {
  cancelAreaSelection();
  if (selectedAreaLayer) {
    map.removeLayer(selectedAreaLayer);
    selectedAreaLayer = null;
  }
  selectedBounds = null;
  const badge = document.getElementById("areaStatus");
  badge.textContent = "Entire contour area";
  badge.classList.remove("custom");
  document.getElementById("clearAreaBtn").classList.add("hidden");
  document.getElementById("selectAreaBtn").textContent = "📐 Select Area on Map";
  showMessage("Land area reset.");
}

function calculateBoundsAreaHectares(minLat, maxLat, minLon, maxLon) {
  const dLat = (maxLat - minLat) * 111139.0;
  const midLatRad = ((minLat + maxLat) / 2.0) * (Math.PI / 180.0);
  const dLon = (maxLon - minLon) * 111139.0 * Math.cos(midLatRad);
  return Math.max(0.01, (Math.abs(dLat) * Math.abs(dLon)) / 10000.0);
}

function finalizeAreaSelection(p1, p2) {
  const bounds = L.latLngBounds(p1, p2);
  const minLat = bounds.getSouth();
  const maxLat = bounds.getNorth();
  const minLon = bounds.getWest();
  const maxLon = bounds.getEast();

  if (Math.abs(maxLat - minLat) < 0.0001 || Math.abs(maxLon - minLon) < 0.0001) {
    return;
  }

  selectedBounds = {
    minLat: Number(minLat.toFixed(6)),
    maxLat: Number(maxLat.toFixed(6)),
    minLon: Number(minLon.toFixed(6)),
    maxLon: Number(maxLon.toFixed(6)),
  };

  if (tempRect) {
    map.removeLayer(tempRect);
    tempRect = null;
  }
  if (selectedAreaLayer) {
    map.removeLayer(selectedAreaLayer);
    selectedAreaLayer = null;
  }

  const ha = calculateBoundsAreaHectares(minLat, maxLat, minLon, maxLon);

  selectedAreaLayer = L.rectangle(bounds, {
    color: "#e76f51",
    weight: 2.5,
    dashArray: "6, 6",
    fillColor: "#e76f51",
    fillOpacity: 0.15
  }).addTo(map);

  selectedAreaLayer.bindTooltip(`Selected Land Area: ${ha.toFixed(2)} ha`, {
    permanent: true,
    direction: "center"
  });

  const badge = document.getElementById("areaStatus");
  badge.textContent = `Selected: ${ha.toFixed(2)} ha`;
  badge.classList.add("custom");
  document.getElementById("clearAreaBtn").classList.remove("hidden");

  // Query live rainfall for the center of the newly selected area
  const center = bounds.getCenter();
  fetchRainfallForCoords(center.lat, center.lng);

  cancelAreaSelection();
  showMessage(`Land area defined (${ha.toFixed(2)} ha). Click 'Analyze' to run analysis.`);
}

function initAreaSelectionListeners() {
  map.on("mousedown", (e) => {
    if (!isSelectingArea) return;
    isMouseDown = true;
    if (!startPoint) {
      startPoint = e.latlng;
      if (tempRect) map.removeLayer(tempRect);
      tempRect = L.rectangle([startPoint, startPoint], {
        color: "#e76f51",
        weight: 2,
        dashArray: "5, 5",
        fillColor: "#e76f51",
        fillOpacity: 0.18
      }).addTo(map);
    }
  });

  map.on("mousemove", (e) => {
    if (!isSelectingArea || !startPoint || !tempRect) return;
    tempRect.setBounds(L.latLngBounds(startPoint, e.latlng));
  });

  map.on("mouseup", (e) => {
    if (!isSelectingArea || !isMouseDown || !startPoint) return;
    isMouseDown = false;
    const endPoint = e.latlng;
    const d = map.distance(startPoint, endPoint);
    if (d > 20) {
      finalizeAreaSelection(startPoint, endPoint);
    }
  });

  map.on("click", (e) => {
    if (!isSelectingArea) return;
    if (!startPoint) {
      startPoint = e.latlng;
      if (tempRect) map.removeLayer(tempRect);
      tempRect = L.rectangle([startPoint, startPoint], {
        color: "#e76f51",
        weight: 2,
        dashArray: "5, 5",
        fillColor: "#e76f51",
        fillOpacity: 0.18
      }).addTo(map);
      const instruction = document.getElementById("mapInstruction");
      instruction.innerHTML = `<span><strong>Corner 1 set!</strong> Click opposite corner on map to complete selection.</span>
        <button type="button" class="secondary" onclick="cancelAreaSelection()" style="margin-left:12px;padding:3px 10px;font-size:11px;background:#fff;border-radius:4px;cursor:pointer;">Cancel</button>`;
    } else {
      finalizeAreaSelection(startPoint, e.latlng);
    }
  });
}

function getCommonParams() {
  const distance = Number(document.getElementById("riverDistance").value);
  const pondCount = Number(document.getElementById("pondCount").value);
  const rainfallInput = document.getElementById("rainfallInput");
  const rainfall = rainfallInput && rainfallInput.value ? Number(rainfallInput.value) : 0;
  const runoffSelect = document.getElementById("runoffSelect");
  const runoff = runoffSelect ? Number(runoffSelect.value) : 0.40;

  return { distance, pondCount, rainfall, runoff };
}

// Case 3: Search Village / Place Name
async function analyzeVillage(placeName) {
  if (!placeName || !placeName.trim()) {
    return showMessage("Please enter a village or place name.", true);
  }
  const query = placeName.trim();
  const { distance, pondCount, rainfall, runoff } = getCommonParams();

  const searchBtn = document.getElementById("villageSearchBtn");
  const mainBtn = document.getElementById("analyzeButton");
  if (searchBtn) searchBtn.disabled = true;
  if (mainBtn) mainBtn.disabled = true;

  showMessage(`Geocoding '${query}' and querying Global DEM elevation grid...`);

  try {
    let url = `${API_URL}/analyzePlace?place_name=${encodeURIComponent(query)}&drainage_safety_buffer_m=${encodeURIComponent(distance)}&number_of_ponds=${encodeURIComponent(pondCount)}&runoff_coefficient=${encodeURIComponent(runoff)}`;
    if (rainfall > 0) {
      url += `&annual_rainfall_mm=${encodeURIComponent(rainfall)}`;
    }

    const response = await fetch(url, { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message || `Could not analyze village '${query}'.`);
    }

    handleAnalysisSuccess(data);
    showMessage(`Successfully analyzed '${query}' using Global DEM data.`);
  } catch (error) {
    showMessage(error.message || "Failed to analyze village.", true);
  } finally {
    if (searchBtn) searchBtn.disabled = false;
    if (mainBtn) mainBtn.disabled = false;
  }
}

// Case 2: Selected Area (DEM)
async function analyzeAreaDEM(bounds) {
  const { distance, pondCount, rainfall, runoff } = getCommonParams();
  const mainBtn = document.getElementById("analyzeButton");
  mainBtn.disabled = true;
  mainBtn.textContent = "Fetching DEM...";

  showMessage("Querying Global Digital Elevation Model (DEM) for selected bounding box...");

  try {
    let url = `${API_URL}/analyzeArea?selected_min_lat=${bounds.minLat}&selected_max_lat=${bounds.maxLat}&selected_min_lon=${bounds.minLon}&selected_max_lon=${bounds.maxLon}&drainage_safety_buffer_m=${encodeURIComponent(distance)}&number_of_ponds=${encodeURIComponent(pondCount)}&runoff_coefficient=${encodeURIComponent(runoff)}`;
    if (rainfall > 0) {
      url += `&annual_rainfall_mm=${encodeURIComponent(rainfall)}`;
    }

    const response = await fetch(url, { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message || "Could not analyze the selected area.");
    }

    handleAnalysisSuccess(data);
    showMessage("DEM elevation grid processed and pond catchments successfully calculated!");
  } catch (error) {
    showMessage(error.message || "Area DEM analysis failed.", true);
  } finally {
    mainBtn.disabled = false;
    mainBtn.textContent = "📐 Analyze Selected Area (DEM)";
  }
}

// Case 1: Upload Contour Map (KML/KMZ)
async function analyzeContourFile(file) {
  const { distance, pondCount, rainfall, runoff } = getCommonParams();
  const button = document.getElementById("analyzeButton");
  button.disabled = true;
  button.textContent = "Analyzing KML...";
  showMessage("Processing KML terrain contours and routing flow catchments...");

  try {
    const formData = new FormData();
    formData.append("contour_map", file);
    formData.append("file", file);

    let url = `${API_URL}/analyzeContour?drainage_safety_buffer_m=${encodeURIComponent(distance)}&number_of_ponds=${encodeURIComponent(pondCount)}&runoff_coefficient=${encodeURIComponent(runoff)}`;
    if (rainfall > 0) {
      url += `&annual_rainfall_mm=${encodeURIComponent(rainfall)}`;
    }
    if (selectedBounds) {
      url += `&selected_min_lat=${selectedBounds.minLat}&selected_max_lat=${selectedBounds.maxLat}&selected_min_lon=${selectedBounds.minLon}&selected_max_lon=${selectedBounds.maxLon}`;
    }

    const response = await fetch(url, { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message || "The uploaded file could not be analyzed.");
    }

    handleAnalysisSuccess(data);
    showMessage("Contour analysis complete!");
  } catch (error) {
    showMessage(error.message || "The uploaded file could not be analyzed.", true);
  } finally {
    button.disabled = false;
    button.textContent = "Analyze Map";
  }
}

// Master Analyze Dispatcher
async function analyzeMap() {
  hideMessage();
  const fileInput = document.getElementById("contourFile");
  const villageInput = document.getElementById("villageInput");

  // If in village mode or village name is typed
  if (activeMode === "village" || (villageInput && villageInput.value.trim() && !fileInput.files.length && !selectedBounds)) {
    return analyzeVillage(villageInput.value);
  }

  // If a file is selected -> Case 1
  if (fileInput.files && fileInput.files.length) {
    const file = fileInput.files[0];
    if (!/\.(kml|kmz)$/i.test(file.name)) {
      return showMessage("Please select a valid .kml or .kmz file.", true);
    }
    return analyzeContourFile(file);
  }

  // If area is selected on map -> Case 2
  if (selectedBounds) {
    return analyzeAreaDEM(selectedBounds);
  }

  // Otherwise guide user
  if (activeMode === "area") {
    startAreaSelection();
    return showMessage("Click and drag on the map (or click two corners) to define the area to analyze.", true);
  }

  return showMessage("Please choose one option: 1) Upload a KML/KMZ file, 2) Click 'Select Area on Map', or 3) Switch to 'Search Village' tab.", true);
}

function handleAnalysisSuccess(data) {
  currentResults = data.pond_locations || [];

  clearMapLayers();

  // If bounds provided in input/meta, outline the area
  if (data.input && data.input.bounds_wgs84) {
    const b = data.input.bounds_wgs84;
    const lBounds = L.latLngBounds([[b.min_lat, b.min_lon], [b.max_lat, b.max_lon]]);
    if (selectedAreaLayer) map.removeLayer(selectedAreaLayer);
    selectedAreaLayer = L.rectangle(lBounds, {
      color: "#e76f51",
      weight: 2,
      dashArray: "6, 6",
      fillColor: "#e76f51",
      fillOpacity: 0.12
    }).addTo(map);
  }

  // Display DEM contours if generated
  if (data.generated_contours && data.generated_contours.length > 0) {
    displayContours(data.generated_contours);
  }

  displayPonds(currentResults);
  if (currentResults.length > 0) {
    displayCatchment(currentResults[0]);
  }
  displayChannels(data.channels);
  showAnalysisSummary(data);
}

function clearMapLayers() {
  pondMarkers.forEach(marker => map.removeLayer(marker));
  pondMarkers = [];
  if (catchmentLayer) map.removeLayer(catchmentLayer);
  if (channelLayer) map.removeLayer(channelLayer);
  if (contourLayer) map.removeLayer(contourLayer);
  catchmentLayer = null;
  channelLayer = null;
  contourLayer = null;
}

function displayContours(contours) {
  if (contourLayer) map.removeLayer(contourLayer);
  contourLayer = L.layerGroup();

  contours.forEach(c => {
    if (c.coordinates && c.coordinates.length > 1) {
      const line = L.polyline(c.coordinates, {
        color: "#8d6e63",
        weight: 1.4,
        opacity: 0.65
      }).bindTooltip(`${c.elevation} m (Contour)`, { sticky: true });
      line.addTo(contourLayer);
    }
  });

  contourLayer.addTo(map);
}

function pondIcon(rank) {
  return L.divIcon({
    className: "",
    html: `<div class="pond-marker">P${rank}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15]
  });
}

function pondPopup(pond) {
  const c = pond.catchment || {};
  const volM3 = (pond.expected_water_volume_m3 != null) ? pond.expected_water_volume_m3 : (c.expected_water_volume_m3 || 0);
  const volML = (pond.expected_water_volume_megaliters != null) ? pond.expected_water_volume_megaliters : (c.expected_water_volume_megaliters || 0);
  const volLakhL = (volM3 * 1000 / 100000).toFixed(2);

  return `<div style="min-width:220px;line-height:1.45;font-size:12px;">
    <div style="font-size:15px;font-weight:800;color:#c94743;margin-bottom:6px;">Pond Candidate #${pond.rank}</div>
    <div><strong>Coordinates:</strong> ${pond.latitude}, ${pond.longitude}</div>
    <div><strong>Elevation:</strong> ${pond.elevation} m</div>
    <div><strong>Suitability Score:</strong> ${pond.suitability_score}</div>
    <div><strong>Distance from Channel:</strong> ${pond.distance_from_channel_m} m</div>
    <hr style="border:0;border-top:1px solid #e0e0e0;margin:7px 0;">
    <div style="font-weight:700;color:#1e588f;">Catchment Area:</div>
    <div>&bull; ${c.area_square_meters ? c.area_square_meters.toLocaleString() : "N/A"} m² (${c.area_hectares || "N/A"} ha)</div>
    <div>&bull; ${c.number_of_cells || 0} cells draining to pond</div>
    <hr style="border:0;border-top:1px solid #e0e0e0;margin:7px 0;">
    <div style="font-weight:700;color:#136f3c;font-size:12px;">💧 Expected Water Volume:</div>
    <div style="font-size:16px;font-weight:900;color:#136f3c;margin:2px 0;">${volM3.toLocaleString()} m³</div>
    <div style="font-size:11px;color:#555;">&asymp; ${volML} Megaliters (${volLakhL} Lakh Liters)</div>
  </div>`;
}

function displayPonds(ponds) {
  const bounds = [];
  ponds.forEach(pond => {
    const marker = L.marker([pond.latitude, pond.longitude], { icon: pondIcon(pond.rank) })
      .addTo(map)
      .bindPopup(pondPopup(pond));
    marker.on("click", () => selectPond(pond.rank));
    pondMarkers.push(marker);
    bounds.push([pond.latitude, pond.longitude]);
  });
  renderPondTable(ponds);
  if (bounds.length) map.fitBounds(bounds, { padding: [55, 55], maxZoom: 16 });
}

function renderPondTable(ponds) {
  const tbody = document.getElementById("pondTable");
  if (!ponds || !ponds.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted">No valid pond candidates were returned for this area.</td></tr>`;
    return;
  }
  tbody.innerHTML = ponds.map(p => {
    const c = p.catchment || {};
    const volM3 = (p.expected_water_volume_m3 != null) ? p.expected_water_volume_m3 : (c.expected_water_volume_m3 || 0);
    const volML = (p.expected_water_volume_megaliters != null) ? p.expected_water_volume_megaliters : (c.expected_water_volume_megaliters || 0);
    const volText = `${volM3.toLocaleString()} m³`;
    const volSub = volML ? `<br><small style="color:#666;font-size:10px;">(${volML} ML)</small>` : "";

    return `<tr data-rank="${p.rank}" onclick="selectPond(${p.rank})">
      <td><strong>P${p.rank}</strong></td>
      <td>${p.latitude}</td>
      <td>${p.longitude}</td>
      <td>${p.elevation} m</td>
      <td>${p.suitability_score}</td>
      <td>${p.catchment_area_hectares} ha</td>
      <td style="color:#136f3c;font-weight:700;">${volText}${volSub}</td>
    </tr>`;
  }).join("");
}

function displayCatchment(pond) {
  if (catchmentLayer) map.removeLayer(catchmentLayer);
  if (!pond || !pond.catchment || !pond.catchment.cells) return;

  catchmentLayer = L.layerGroup();
  pond.catchment.cells.forEach(cell => {
    L.polygon(cell, { color: "#2d75b6", weight: 0.8, fillOpacity: 0.22, fillColor: "#3a86c8" }).addTo(catchmentLayer);
  });
  catchmentLayer.addTo(map);

  const catchmentBounds = L.latLngBounds(pond.catchment.cells.flat());
  catchmentBounds.extend([pond.latitude, pond.longitude]);
  map.fitBounds(catchmentBounds, { padding: [70, 70], maxZoom: 17 });
}

function displayChannels(channels) {
  channelLayer = L.layerGroup();
  if (!channels) return;
  (channels.terrain_derived_segments || []).forEach(segment =>
    L.polyline(segment, { color: "#1976d2", weight: 2.5, opacity: 0.85 }).addTo(channelLayer)
  );
  (channels.explicit_waterways || []).forEach(water =>
    L.polyline(water.coordinates, { color: "#0d47a1", weight: 3.5, opacity: 0.95 }).bindTooltip(water.name).addTo(channelLayer)
  );
  channelLayer.addTo(map);
}

function showAnalysisSummary(data) {
  const input = data.input;
  const a = data.analysis;
  const wp = data.water_volume_parameters || {};
  const topPond = (data.pond_locations && data.pond_locations.length) ? data.pond_locations[0] : null;

  const topVol = topPond && topPond.expected_water_volume_m3 != null
    ? `${topPond.expected_water_volume_m3.toLocaleString()} m³ (${topPond.expected_water_volume_megaliters} ML)`
    : "N/A";

  let areaText = "Full Extent";
  if (input.place_name) {
    areaText = `📍 ${input.place_name}`;
  } else if (input.selected_land_area) {
    areaText = `Custom (${input.selected_land_area.min_lat}, ${input.selected_land_area.min_lon} to ${input.selected_land_area.max_lat}, ${input.selected_land_area.max_lon})`;
  }

  const modeBadge = input.mode === "village_search_dem"
    ? "Case 3 (Village Search DEM)"
    : input.mode === "map_area_dem"
    ? "Case 2 (Map Selection DEM)"
    : "Case 1 (KML Contour Upload)";

  const isCacheHit = data.cache && data.cache.hit;
  const execNode = isCacheHit
    ? "⚡ Instant Cache Hit (<5ms)"
    : (data.cache && data.cache.node ? `🖥️ stu46_${data.cache.node} (Worker)` : "🖥️ Distributed Worker");

  const cacheStatus = isCacheHit
    ? `Cached (${data.cache.age_seconds}s ago, valid 24h)`
    : "Computed Fresh & Cached 24h";

  document.getElementById("summary").innerHTML = [
    ["Workflow Mode", modeBadge],
    ["Distributed Compute", execNode],
    ["Cache Lifetime", cacheStatus],
    ["Contours Extracted", input.contour_count],
    ["Elevation Range", `${input.elevation_min_m}–${input.elevation_max_m} m`],
    ["DEM Grid Dimension", `${input.grid_size} × ${input.grid_size}`],
    ["Location / Bounds", areaText],
    ["Ponds Detected", a.ponds_selected],
    ["Top Catchment Area", topPond ? `${topPond.catchment_area_hectares} ha` : "N/A"],
    ["Top Expected Volume", topVol],
    ["Rainfall Source", `${wp.annual_rainfall_mm || 1000} mm (${wp.rainfall_source || "API"})`],
    ["Runoff Coefficient", `${wp.soil_type || "C=" + (wp.runoff_coefficient || 0.40)}`]
  ].map(([label, value], idx) => {
    const isHighlight = idx === 1 ? " highlight" : "";
    return `<div class="stat${isHighlight}"><span class="label">${label}</span><span class="value">${value}</span></div>`;
  }).join("");
}

function selectPond(rank) {
  const pond = currentResults.find(p => p.rank === rank);
  if (!pond) return;
  pondMarkers.forEach(marker => marker.closePopup());
  const marker = pondMarkers[rank - 1];
  if (marker) {
    marker.openPopup();
    map.setView([pond.latitude, pond.longitude], Math.max(map.getZoom(), 15));
  }
  displayCatchment(pond);
  document.querySelectorAll("#pondTable tr").forEach(row => row.classList.toggle("active", row.dataset.rank === String(rank)));
  document.getElementById("selectedLabel").textContent = `Pond #${rank} selected`;
}

window.handleFileSelect = handleFileSelect;
window.analyzeMap = analyzeMap;
window.selectPond = selectPond;
window.toggleAreaSelection = toggleAreaSelection;
window.cancelAreaSelection = cancelAreaSelection;
window.clearSelectedArea = clearSelectedArea;
window.fillVillage = fillVillage;

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  document.getElementById("contourFile").addEventListener("change", handleFileSelect);
  document.getElementById("analyzeButton").addEventListener("click", analyzeMap);
  document.getElementById("selectAreaBtn").addEventListener("click", toggleAreaSelection);
  document.getElementById("clearAreaBtn").addEventListener("click", clearSelectedArea);

  const villageBtn = document.getElementById("villageSearchBtn");
  if (villageBtn) {
    villageBtn.addEventListener("click", () => {
      const q = document.getElementById("villageInput").value;
      analyzeVillage(q);
    });
  }

  const villageInput = document.getElementById("villageInput");
  if (villageInput) {
    villageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        analyzeVillage(villageInput.value);
      }
    });
  }

  const refreshBtn = document.getElementById("refreshRainfallBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      const center = selectedBounds
        ? { lat: (selectedBounds.minLat + selectedBounds.maxLat) / 2, lng: (selectedBounds.minLon + selectedBounds.maxLon) / 2 }
        : map.getCenter();
      fetchRainfallForCoords(center.lat, center.lng);
    });
  }

  fetchClusterStatus();
});

async function fetchClusterStatus() {
  try {
    const res = await fetch(`${API_URL}/cluster/status`);
    if (res.ok) {
      const data = await res.json();
      const healthyWorkers = (data.workers || []).filter(w => w.healthy);
      const label = document.getElementById("activeWorkersLabel");
      if (label) {
        label.textContent = `${healthyWorkers.map(w => w.id).join(", ")} (${healthyWorkers.length} Active)`;
      }
      const cacheLabel = document.getElementById("cacheStatusLabel");
      if (cacheLabel && data.cache) {
        cacheLabel.textContent = `24h Cache (${data.cache.active_entries || 0} active)`;
      }
    }
  } catch (err) {
    console.warn("Cluster status check:", err);
  }
}

