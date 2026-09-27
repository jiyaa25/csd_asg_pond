# Pond Location and Catchment Detection System

A high-performance FastAPI and GIS terrain analysis web application that determines optimal pond candidates, flow catchments, and expected harvestable water volumes across **3 flexible workflows**:

1. **Case 1: Contour Map Upload** — Upload `.kml` or `.kmz` contour maps.
2. **Case 2: Interactive Map Area Selection** — Select any custom bounding box on Leaflet; backend queries a Global Digital Elevation Model (DEM), derives elevation grids and vector contours, and runs hydrological analysis.
3. **Case 3: Village / Place Search** — Search any village, town, or city name; backend geocodes via OpenStreetMap Nominatim, retrieves DEM elevation grid & contours, fetches live agro-climatological rainfall, and computes pond locations and catchments automatically.

---

## 1. System Architecture & Workflows

```text
========================================================================================
                                 INPUT WORKFLOWS
========================================================================================
  [Case 1: KML / KMZ Upload]       [Case 2: Select Bounding Box]     [Case 3: Search Village]
              │                                   │                              │
     Extract Contour Paths               Query Global DEM API             OSM Nominatim Geocode
     & Measured Heights              (lat/lon bounding box)               (lat/lon & bounds)
              │                                   │                              │
    IDW Terrain Interpolation         Bicubic Spline Grid Zoom                   │
              │                                   │                              │
              │                       Vectorize Contour Lines ◄──────────────────┘
              │                       (matplotlib QuadContour)
              ▼                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                            UNIFIED HYDROLOGICAL PIPELINE                             │
│                                                                                      │
│  1. 8-Neighbour Surface Graph (WGS84 spherical distances)                            │
│  2. D8 Downhill Flow Routing & Topographic Gradient Determination                    │
│  3. Flow Accumulation Matrix & Stream Network Extraction                             │
│  4. River Channel & Ridge Line Exclusion Masking                                     │
│  5. Multi-criteria Pond Suitability Scoring & Minimum Spatial Separation             │
│  6. Upstream Reverse-Flow BFS Catchment Delineation                                  │
│  7. Rational Method Water Volume: Volume = Catchment Area × Rainfall × Runoff (C)    │
│  8. Dynamic Climate Rainfall: Open-Meteo Archive API + NASA POWER Climatology        │
└───────────────────────────────────┬──────────────────────────────────────────────────┘
                                    ▼
       Interactive Leaflet GIS Web App Overlay & Structured JSON Response
```

---

## 2. Project Structure

```text
csd_asg_pond/
├── main.py                 # FastAPI application, CORS, routing, unified analysis pipeline
├── contour_parser.py       # XML/KML/KMZ extraction of contour LineStrings and heights
├── terrain.py              # TerrainGrid representation and IDW interpolation
├── graph.py                # 8-neighbour terrain graph with D8 flow routing
├── catchment.py            # Flow accumulation, channel detection, BFS catchment routing, volume
├── rainfall_service.py     # Live climate rainfall service (Open-Meteo & NASA POWER Climatology)
├── dem_service.py          # Global DEM elevation grid fetching, bicubic zoom & contour vectorization
├── generate_outputs.py     # Batch pipeline runner saving JSON output for sample maps
├── requirements.txt        # Production dependencies
├── contours_1m.kml         # Sample contour map
├── frontend/
│   ├── index.html          # Web UI with 3 workflow mode tabs, village search, and GIS map
│   ├── style.css           # Modern aesthetic stylesheet with dark/light visual cues
│   └── app.js              # Leaflet integration, area drag-select, contour rendering, table
├── tests/
│   ├── test_parser.py      # Unit tests for KML/KMZ parser and edge cases
│   └── test_all.py         # End-to-end tests for all 3 workflows, APIs, and hydrology
└── outputs/
    └── sample_analysis.json# Precomputed sample analysis output
```

---

## 3. Endpoints & API Reference

### Hosted Web Interface & API Base
```text
http://10.1.75.79:5261/
```

### Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Web GIS Application (Leaflet UI) |
| `GET` | `/health` | System health check (`{"status": "healthy"}`) |
| `GET` | `/api/rainfall` | Fetch dynamic rainfall for coordinates (`lat`, `lon`) |
| `GET` | `/api/geocode` | Geocode village/place name to geographic bounding box (`q`) |
| `POST`| `/analyzeContour` | Universal endpoint supporting KML upload, selected area, or village name |
| `POST`| `/analyzeArea` | Case 2: Direct DEM query for map bounding box |
| `POST`| `/analyzePlace` | Case 3: Village search DEM query & catchment analysis |

---

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :---: | :--- |
| `drainage_safety_buffer_m` | Float | `200.0` | Minimum clearance from natural streams/channels |
| `number_of_ponds` | Integer | `5` | Number of top spatially separated pond candidates |
| `annual_rainfall_mm` | Float | *Auto* | Expected annual precipitation (auto-fetched from climate API if omitted) |
| `runoff_coefficient` | Float | `0.40` | Rational runoff coefficient $C$ (0.30 Sandy Loam, 0.40 Clay/Silt Loam, 0.50 Hard Clay, 0.60 Barren) |
| `selected_min_lat`, `selected_max_lat` | Float | *None* | Bounding latitudes for land area of interest |
| `selected_min_lon`, `selected_max_lon` | Float | *None* | Bounding longitudes for land area of interest |

---

## 4. Hydrological Formulas

### Expected Water Volume (Rational Method)
$$\text{Expected Water Volume } (V) = A \times R \times C$$
- $A$ = Catchment Area ($m^2$) delineated via reverse-flow BFS
- $R$ = Annual Precipitation ($m = \text{mm} / 1000$) fetched dynamically from Open-Meteo / NASA POWER API
- $C$ = Runoff Coefficient (dimensionless ratio between $0.01$ and $1.0$)

---

## 5. Running & Verification

### Running the Server Locally
```bash
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

### Running Test Suite
```bash
pytest tests/ -v
```
All 15 automated test cases validate parsing, flow routing, rainfall API fallback, geocoding, and DEM terrain analysis.
