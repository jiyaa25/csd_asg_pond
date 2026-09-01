# Pond Location and Catchment Detection

A simple FastAPI + Leaflet demonstration for terrain-derived pond candidate selection and upstream catchment estimation from KML/KMZ contour maps.

> **Scope:** This is an academic terrain-analysis system, not an engineering-grade hydrological model. The frontend is only a visualization/testing interface; all terrain analysis remains in the Python backend.

## 1. Assignment Pipeline

```text
KML/KMZ upload
      ↓
KML/KMZ parsing
      ↓
Contour + elevation extraction
      ↓
IDW terrain interpolation
      ↓
8-neighbour terrain graph
      ↓
D8 steepest-downhill flow
      ↓
Flow accumulation
      ↓
River/channel detection
      ↓
Ridge candidate detection
      ↓
Pond candidate filtering + scoring
      ↓
Spatially separated top-N selection
      ↓
Reverse-flow BFS catchment
      ↓
Geographic catchment-area calculation
      ↓
JSON response
      ↓
Leaflet visualization
```

## 2. Project Structure

```text
csd_asg_phase2/
├── main.py
├── contour_parser.py
├── terrain.py
├── graph.py
├── catchment.py
├── generate_outputs.py
├── requirements.txt
├── contours_1m.kml
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tests/
│   ├── __init__.py
│   ├── test_parser.py
│   └── test_all.py
├── outputs/
│   └── sample_analysis.json
├── README.md
├── REPORT.md
└── SUBMISSION_CHECKLIST.md
```

Do not submit `.venv/`, Python caches, pytest caches, IDE folders or other temporary files.

## 3. Backend

The existing backend was preserved and extended rather than rebuilt. It still performs:

- KML/KMZ parsing and elevation extraction
- IDW terrain interpolation
- 8-neighbour graph construction
- Haversine edge distances and D8 downhill flow
- flow accumulation
- terrain-derived channel detection and explicit-waterway detection
- ridge filtering
- pond candidate scoring
- reverse-flow BFS catchment calculation
- geographic catchment area estimation

The new selection step ranks valid candidates and applies a simple minimum grid-cell separation so multiple results are meaningful, rather than returning neighbouring copies of the same location.

## 4. API

### `POST /analyzeContour`

Multipart field:

```text
file = KML/KMZ file
```

Query parameters:

```text
drainage_safety_buffer_m=30
number_of_ponds=5
```

Example:

```text
POST http://127.0.0.1:8000/analyzeContour?drainage_safety_buffer_m=30&number_of_ponds=5
```

The response now contains `pond_locations`, with rank, coordinates, elevation, suitability score, channel distance and graph-derived catchment information for every selected candidate. The original single-result fields (`pond_location`, `catchment`, and `river_safety`) are retained for backward compatibility with the previous API/tests.

The catchment contains the actual grid-cell polygons visited by reverse-flow BFS. It is **not** a circular buffer around a pond.

The response also contains terrain-derived channel line segments and any explicit KML waterways. No river geometry is fabricated when none exists.

### Other endpoints

```text
GET /                 frontend
GET /health           health check
GET /docs             Swagger API documentation
```

## 5. Frontend Demonstration

The frontend is deliberately plain HTML/CSS/JavaScript. It uses Leaflet from a CDN and OpenStreetMap tiles; no React, Vite, database, authentication or cloud service is required.

It provides:

1. KML/KMZ file selection
2. User-controlled minimum river/channel distance
3. User-controlled number of pond candidates
4. Analyze button and loading/error messages
5. Ranked pond markers (`P1`, `P2`, ...)
6. Clickable map popups with elevation, score, catchment and channel distance
7. Flow-derived catchment-cell visualization for the selected pond
8. Terrain-derived/explicit channel visualization when available
9. Dynamic result table
10. Analysis summary
11. Clicking a table row selects and centers the corresponding pond

The locations are described as **Terrain-derived Pond Candidates**, not guaranteed or engineering-grade pond sites.

## 6. Running the Application

### Windows PowerShell

```powershell
cd path\to\csd_asg_phase2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, Command Prompt can use:

```cmd
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Linux/macOS

```bash
cd path/to/csd_asg_phase2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open:

```text
http://127.0.0.1:8000/
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

The preferred setup serves the frontend directly from FastAPI, so a separate frontend server is not required.

## 7. Frontend Demonstration Steps

1. Start the application with `python main.py`.
2. Open `http://127.0.0.1:8000/`.
3. Select `contours_1m.kml`.
4. Enter `30` for minimum distance from river/channel.
5. Enter `5` for number of pond locations.
6. Click **Analyze Map**.
7. Wait for **Analyzing contour map...** to finish.
8. Inspect the ranked markers and result table.
9. Click a marker or table row to inspect that pond's catchment.
10. Change the distance or pond count and run the analysis again.

## 8. Test Through Swagger

1. Open `http://127.0.0.1:8000/docs`.
2. Open `POST /analyzeContour`.
3. Click **Try it out**.
4. Choose `contours_1m.kml`.
5. Set `drainage_safety_buffer_m` and `number_of_ponds`.
6. Click **Execute**.
7. Confirm `status: success` and inspect `pond_locations`.

## 9. curl Examples

Windows/Linux/macOS:

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour?drainage_safety_buffer_m=30&number_of_ponds=5" -F "file=@contours_1m.kml"
```

For a KMZ:

```bash
curl -X POST "http://127.0.0.1:8000/analyzeContour?drainage_safety_buffer_m=30&number_of_ponds=5" -F "file=@contour_map.kmz"
```

## 10. Automated Tests

```bash
pytest -q
```

The test suite covers parsing, KML/KMZ handling, terrain/grid construction, graph construction, flow accumulation, filtering, catchment traversal and the API.

## 11. Generate the Sample Demonstration JSON

```bash
python generate_outputs.py
```

This runs the real `contours_1m.kml` through the backend and writes:

```text
outputs/sample_analysis.json
```

No sample coordinates are hard-coded into the analysis.

## 12. Sample Response Shape

```json
{
  "status": "success",
  "input": {
    "filename": "contours_1m.kml",
    "contour_count": 1355,
    "elevation_min_m": 267.0,
    "elevation_max_m": 298.0,
    "grid_size": 120
  },
  "pond_locations": [
    {
      "rank": 1,
      "latitude": 0.0,
      "longitude": 0.0,
      "elevation": 0.0,
      "suitability_score": 0.0,
      "catchment_area_square_meters": 0.0,
      "catchment_area_hectares": 0.0,
      "catchment_cells": 0,
      "distance_from_channel_m": 0.0,
      "catchment": {
        "area_square_meters": 0.0,
        "area_hectares": 0.0,
        "number_of_cells": 0,
        "cells": []
      }
    }
  ],
  "analysis": {
    "requested_ponds": 5,
    "valid_candidate_count": 0,
    "ponds_selected": 0
  }
}
```

The numeric values above are schema placeholders only. The live API calculates the actual values from the uploaded map.

## 13. Error Handling

The API returns friendly JSON errors such as:

```json
{"status":"error","message":"No file uploaded."}
```

```json
{"status":"error","message":"Unsupported file format. Upload a .kml or .kmz file."}
```

The frontend converts these into readable messages such as **Please select a KML or KMZ file.** or **The uploaded file could not be analyzed.**

## 14. Important Limitations

- IDW creates an estimated surface between contour lines; it is not a measured DEM.
- D8 sends each cell to one steepest-downhill neighbour, so it is a simplified flow model.
- High flow accumulation is used as a terrain-derived channel indicator when explicit waterways are unavailable.
- The river safety distance is an academic screening rule, not a legal or engineering setback.
- Catchment area is approximate and depends on the contour map and grid resolution.
- Candidate locations are terrain-derived screening candidates, not guaranteed pond sites.
