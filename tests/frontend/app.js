const API_URL = "http://127.0.0.1:8000";

let map;
let pondMarkers = [];
let catchmentLayer = null;
let channelLayers = [];
let currentPondsData = [];

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    setupEventListeners();
});

function initMap() {
    map = L.map('map').setView([21.25, 81.28], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
}

function setupEventListeners() {
    const fileInput = document.getElementById("contourFile");
    fileInput.addEventListener("change", (e) => {
        const file = e.target.files[0];
        document.getElementById("fileNameDisplay").textContent = file ? file.name : "";
    });

    document.getElementById("analysisForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        await analyzeMap();
    });
}

async function analyzeMap() {
    const fileInput = document.getElementById("contourFile");
    const riverDistInput = document.getElementById("riverDistance");
    const pondCountInput = document.getElementById("pondCount");

    if (!fileInput.files || fileInput.files.length === 0) {
        alert("Please select a KML or KMZ contour file.");
        return;
    }

    const file = fileInput.files[0];
    const riverDist = parseFloat(riverDistInput.value);
    const pondCount = parseInt(pondCountInput.value, 10);

    if (isNaN(riverDist) || riverDist < 0) {
        alert("Please enter a valid positive river distance.");
        return;
    }

    if (isNaN(pondCount) || pondCount < 1) {
        alert("Please enter a valid number of ponds.");
        return;
    }

    showLoading(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await fetch(`${API_URL}/analyzeContour?drainage_safety_buffer_m=${riverDist}&number_of_ponds=${pondCount}`, {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (data.status === "error") {
            alert(data.message || "An error occurred during analysis.");
            return;
        }

        currentPondsData = data.pond_locations || [];
        renderAnalysisResults(data);

    } catch (err) {
        alert("Failed to communicate with backend server: " + err.message);
    } finally {
        showLoading(false);
    }
}

function renderAnalysisResults(data) {
    clearMapLayers();
    displayChannels(data.channels || []);
    displayPonds(data.pond_locations || []);
    displaySummary(data);
    displayTable(data.pond_locations || []);

    if (data.pond_locations && data.pond_locations.length > 0) {
        selectPond(0);
    }
}

function displayChannels(channels) {
    channels.forEach(poly => {
        const line = L.polyline(poly, { color: '#0284c7', weight: 2, opacity: 0.8 }).addTo(map);
        channelLayers.push(line);
    });
}

function displayPonds(ponds) {
    if (ponds.length === 0) return;

    const bounds = L.latLngBounds();

    ponds.forEach((pond, index) => {
        const marker = L.marker([pond.latitude, pond.longitude], {
            icon: L.divIcon({
                className: 'custom-pond-marker',
                html: `<div style="background-color:#ef4444; color:white; border-radius:50%; width:26px; height:26px; display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:12px; border:2px solid white; box-shadow:0 2px 4px rgba(0,0,0,0.3);">P${pond.rank}</div>`,
                iconSize: [26, 26],
                iconAnchor: [13, 13]
            })
        }).addTo(map);

        const popupContent = `
            <div style="font-size:13px;">
                <strong>Pond #${pond.rank}</strong><br/>
                Latitude: ${pond.latitude}<br/>
                Longitude: ${pond.longitude}<br/>
                Elevation: ${pond.elevation} m<br/>
                <strong>Suitability Score: ${pond.suitability_score}</strong><br/><br/>
                <strong>Catchment:</strong><br/>
                ${pond.catchment_area_square_meters.toLocaleString()} m² (${pond.catchment_area_hectares} ha)<br/>
                Catchment cells: ${pond.catchment_cells}<br/>
                Distance from channel: ${pond.distance_from_channel_m} m
            </div>
        `;
        marker.bindPopup(popupContent);

        marker.on('click', () => {
            selectPond(index);
        });

        pondMarkers.push(marker);
        bounds.extend([pond.latitude, pond.longitude]);
    });

    map.fitBounds(bounds, { padding: [50, 50] });
}

function displayCatchment(catchment) {
    if (catchmentLayer) {
        map.removeLayer(catchmentLayer);
    }
    if (catchment && catchment.boundary) {
        catchmentLayer = L.polygon(catchment.boundary, {
            color: '#2563eb',
            fillColor: '#3b82f6',
            fillOpacity: 0.35,
            weight: 2
        }).addTo(map);
    }
}

function displayTable(ponds) {
    const tbody = document.querySelector("#resultsTable tbody");
    tbody.innerHTML = "";

    if (ponds.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center">No valid pond candidates found meeting criteria.</td></tr>`;
        return;
    }

    ponds.forEach((pond, index) => {
        const row = document.createElement("tr");
        row.id = `pond-row-${index}`;
        row.innerHTML = `
            <td><strong>P${pond.rank}</strong></td>
            <td>${pond.latitude}</td>
            <td>${pond.longitude}</td>
            <td>${pond.elevation}</td>
            <td><strong>${pond.suitability_score}</strong></td>
            <td>${pond.catchment_area_hectares} ha</td>
            <td>${pond.distance_from_channel_m}</td>
        `;
        row.addEventListener("click", () => selectPond(index));
        tbody.appendChild(row);
    });
}

function selectPond(index) {
    document.querySelectorAll("#resultsTable tbody tr").forEach(r => r.classList.remove("selected-row"));
    const selectedRow = document.getElementById(`pond-row-${index}`);
    if (selectedRow) selectedRow.classList.add("selected-row");

    const pond = currentPondsData[index];
    if (pond) {
        displayCatchment(pond.catchment);
        const marker = pondMarkers[index];
        if (marker) {
            marker.openPopup();
            map.panTo(marker.getLatLng());
        }
    }
}

function displaySummary(data) {
    const card = document.getElementById("summaryCard");
    const container = document.getElementById("summaryContent");
    card.classList.remove("hidden");

    const input = data.input || {};
    const analysis = data.analysis || {};

    container.innerHTML = `
        <div class="summary-item"><span>Contours:</span> <strong>${input.contour_count || 0}</strong></div>
        <div class="summary-item"><span>Elevation Range:</span> <strong>${input.elevation_min_m} - ${input.elevation_max_m} m</strong></div>
        <div class="summary-item"><span>Terrain Grid:</span> <strong>${input.grid_size} × ${input.grid_size}</strong></div>
        <div class="summary-item"><span>Candidates Found:</span> <strong>${analysis.candidate_count || 0}</strong></div>
        <div class="summary-item"><span>Channel Buffer Removed:</span> <strong>${analysis.river_candidates_removed || 0}</strong></div>
        <div class="summary-item"><span>Ridge Buffer Removed:</span> <strong>${analysis.ridge_candidates_removed || 0}</strong></div>
        <div class="summary-item"><span>Ponds Requested:</span> <strong>${analysis.requested_ponds || 0}</strong></div>
        <div class="summary-item"><span>Ponds Selected:</span> <strong>${data.pond_locations ? data.pond_locations.length : 0}</strong></div>
    `;
}

function clearMapLayers() {
    pondMarkers.forEach(m => map.removeLayer(m));
    pondMarkers = [];
    if (catchmentLayer) map.removeLayer(catchmentLayer);
    catchmentLayer = null;
    channelLayers.forEach(l => map.removeLayer(l));
    channelLayers = [];
}

function showLoading(show) {
    const overlay = document.getElementById("loadingOverlay");
    if (show) overlay.classList.remove("hidden");
    else overlay.classList.add("hidden");
}