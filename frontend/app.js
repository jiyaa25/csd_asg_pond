const API_URL = "";

let map;
let pondMarkers = [];
let catchmentLayer = null;
let channelLayer = null;
let mapExtentLayer = null;
let currentResults = [];

function initMap() {
  map = L.map("map").setView([20, 80], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);
}

function handleFileSelect() {
  const input = document.getElementById("contourFile");
  document.getElementById("fileName").textContent = input.files.length ? input.files[0].name : "No file selected";
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

async function analyzeMap() {
  hideMessage();
  const fileInput = document.getElementById("contourFile");
  const distance = Number(document.getElementById("riverDistance").value);
  const pondCount = Number(document.getElementById("pondCount").value);

  if (!fileInput.files.length) return showMessage("Please select a KML or KMZ file.", true);
  const file = fileInput.files[0];
  if (!/\.(kml|kmz)$/i.test(file.name)) return showMessage("Please select a valid .kml or .kmz file.", true);
  if (!Number.isFinite(distance) || distance <= 0) return showMessage("Please enter a valid river distance.", true);
  if (!Number.isInteger(pondCount) || pondCount < 1 || pondCount > 50) return showMessage("Please enter a valid pond count between 1 and 50.", true);

  const button = document.getElementById("analyzeButton");
  button.disabled = true;
  button.textContent = "Analyzing...";
  showMessage("Analyzing contour map...");

  try {
    const formData = new FormData();
    formData.append("file", file);
    const url = `${API_URL}/analyzeContour?drainage_safety_buffer_m=${encodeURIComponent(distance)}&number_of_ponds=${encodeURIComponent(pondCount)}`;
    const response = await fetch(url, { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok || data.status !== "success") throw new Error(data.message || "The uploaded file could not be analyzed.");

    currentResults = data.pond_locations || [];
    displayPonds(currentResults);
    displayCatchment(currentResults[0]);
    displayChannels(data.channels);
    showAnalysisSummary(data);
    hideMessage();
  } catch (error) {
    showMessage(error.message || "The uploaded file could not be analyzed.", true);
  } finally {
    button.disabled = false;
    button.textContent = "Analyze Map";
  }
}

function clearMapLayers() {
  pondMarkers.forEach(marker => map.removeLayer(marker));
  pondMarkers = [];
  if (catchmentLayer) map.removeLayer(catchmentLayer);
  if (channelLayer) map.removeLayer(channelLayer);
  if (mapExtentLayer) map.removeLayer(mapExtentLayer);
  catchmentLayer = null;
  channelLayer = null;
  mapExtentLayer = null;
}

function pondIcon(rank) {
  return L.divIcon({ className: "", html: `<div class="pond-marker">P${rank}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] });
}

function pondPopup(pond) {
  const c = pond.catchment;
  return `<strong>Pond #${pond.rank}</strong><br>
    Latitude: ${pond.latitude}<br>
    Longitude: ${pond.longitude}<br>
    Elevation: ${pond.elevation} m<br>
    Suitability Score: ${pond.suitability_score}<br><br>
    <strong>Catchment</strong><br>
    ${c.area_square_meters} m²<br>
    ${c.area_hectares} hectares<br>
    Catchment cells: ${c.number_of_cells}<br>
    Distance from channel: ${pond.distance_from_channel_m} m`;
}

function displayPonds(ponds) {
  clearMapLayers();
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
  if (!ponds.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">No valid pond candidates were returned.</td></tr>`;
    return;
  }
  tbody.innerHTML = ponds.map(p => `<tr data-rank="${p.rank}" onclick="selectPond(${p.rank})">
    <td><strong>${p.rank}</strong></td><td>${p.latitude}</td><td>${p.longitude}</td>
    <td>${p.elevation} m</td><td>${p.suitability_score}</td><td>${p.catchment_area_hectares} ha</td>
  </tr>`).join("");
}

function displayCatchment(pond) {
  if (catchmentLayer) map.removeLayer(catchmentLayer);
  if (!pond || !pond.catchment || !pond.catchment.cells) return;

  catchmentLayer = L.layerGroup();
  pond.catchment.cells.forEach(cell => {
    L.polygon(cell, { weight: 0.7, fillOpacity: 0.18 }).addTo(catchmentLayer);
  });
  catchmentLayer.addTo(map);
  const catchmentBounds = L.latLngBounds(pond.catchment.cells.flat());
  catchmentBounds.extend([pond.latitude, pond.longitude]);
  map.fitBounds(catchmentBounds, { padding: [70, 70], maxZoom: 17 });
}

function displayChannels(channels) {
  channelLayer = L.layerGroup();
  if (!channels) return;
  (channels.terrain_derived_segments || []).forEach(segment => L.polyline(segment, { weight: 2.5, opacity: .8 }).addTo(channelLayer));
  (channels.explicit_waterways || []).forEach(water => L.polyline(water.coordinates, { weight: 3, opacity: .9 }).bindTooltip(water.name).addTo(channelLayer));
  channelLayer.addTo(map);
}

function showAnalysisSummary(data) {
  const input = data.input;
  const a = data.analysis;
  document.getElementById("summary").innerHTML = [
    ["Contours", input.contour_count],
    ["Elevation range", `${input.elevation_min_m}–${input.elevation_max_m} m`],
    ["Terrain grid", `${input.grid_size} × ${input.grid_size}`],
    ["Candidates found", a.valid_candidate_count],
    ["Removed near channels", a.river_candidates_removed],
    ["Removed near ridges", a.ridge_candidates_removed],
    ["Ponds requested", a.requested_ponds],
    ["Ponds selected", a.ponds_selected]
  ].map(([label, value]) => `<div class="stat"><span class="label">${label}</span><span class="value">${value}</span></div>`).join("");
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
  document.querySelectorAll("#pondTable tr").forEach(row => row.classList.toggle("active", Number(row.dataset.rank) === rank));
  document.getElementById("selectedLabel").textContent = `Pond #${rank} selected`;
}

window.handleFileSelect = handleFileSelect;
window.analyzeMap = analyzeMap;
window.selectPond = selectPond;

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  document.getElementById("contourFile").addEventListener("change", handleFileSelect);
  document.getElementById("analyzeButton").addEventListener("click", analyzeMap);
});
