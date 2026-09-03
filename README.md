# Pond Location and Catchment Detection

A FastAPI-based terrain analysis system that accepts KML/KMZ contour maps, identifies terrain-derived pond candidates, and estimates their upstream catchment areas using flow-based terrain analysis.

## 1. Project Overview

The system performs the following pipeline:

```text
KML/KMZ Contour Map
        ↓
Contour & Elevation Extraction
        ↓
IDW Terrain Interpolation
        ↓
8-Neighbour Terrain Graph
        ↓
D8 Flow Routing
        ↓
Flow Accumulation
        ↓
Drainage/Channel Detection
        ↓
Pond Candidate Selection & Filtering
        ↓
Top-N Pond Selection
        ↓
Reverse-Flow Catchment Detection
        ↓
Catchment Area Calculation
        ↓
JSON Response
```

The catchment is calculated from the terrain-derived flow network rather than using a circular buffer.

## 2. Project Structure

```text
csd_asg_pond/
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
└── REPORT.md
```

Temporary files such as virtual environments, Python caches and IDE folders should not be submitted.

## 3. Backend

The backend is implemented using **FastAPI**.

It performs:

* KML/KMZ contour parsing
* Elevation extraction
* IDW terrain interpolation
* 8-neighbour terrain graph construction
* D8 downhill flow routing
* Flow accumulation
* Drainage/channel detection
* Pond candidate filtering and scoring
* Spatially separated pond selection
* Reverse-flow BFS catchment detection
* Geographic catchment area calculation

## 4. API Endpoint

### `POST /analyzeContour`

**Hosted API:**

```text
http://10.1.75.79:5261/analyzeContour
```

The endpoint accepts a KML or KMZ file using the multipart form-data field:

```text
contour_map
```

### Query Parameters

| Parameter                  | Type    | Default | Description                                     |
| -------------------------- | ------- | ------: | ----------------------------------------------- |
| `drainage_safety_buffer_m` | Float   |   `200` | Minimum distance from detected drainage/channel |
| `number_of_ponds`          | Integer |     `5` | Number of pond candidates to return             |

### Example Request

```text
POST http://10.1.75.79:5261/analyzeContour
```

Use `multipart/form-data`:

```text
contour_map → KML/KMZ file
```

The default values are:

```text
drainage_safety_buffer_m = 200
number_of_ponds = 5
```

They can also be specified explicitly:

```text
POST http://10.1.75.79:5261/analyzeContour?drainage_safety_buffer_m=200&number_of_ponds=5
```

## 5. Testing Through Postman

1. Open Postman.
2. Select **POST**.
3. Enter:

```text
http://10.1.75.79:5261/analyzeContour
```

4. Go to **Body → form-data**.
5. Add:

```text
Key: contour_map
Type: File
Value: contours_1m.kml
```

6. Send the request.

The API returns a JSON response containing the analysis results.

## 6. Swagger Documentation

Interactive API documentation is available at:

```text
http://10.1.75.79:5261/docs
```

From Swagger, the `POST /analyzeContour` endpoint can be tested by uploading a KML/KMZ contour map and providing the analysis parameters.

## 7. Response

A successful response contains information such as:

```json
{
  "status": "success",
  "input": {
    "filename": "contours_1m.kml"
  },
  "pond_locations": [
    {
      "rank": 1,
      "latitude": "...",
      "longitude": "...",
      "elevation": "...",
      "suitability_score": "...",
      "catchment_area_square_meters": "...",
      "catchment_area_hectares": "...",
      "catchment_cells": "...",
      "distance_from_channel_m": "..."
    }
  ]
}
```

The response also includes catchment cell geometry and analysis statistics.

## 8. Frontend

The project includes a simple Leaflet-based frontend for visualization.

It allows the user to:

* Upload a KML/KMZ contour map
* Set the drainage safety distance
* Select the number of pond candidates
* View ranked pond locations
* View catchment regions
* View drainage/channel information
* Inspect pond properties on the map

The frontend communicates with the same FastAPI backend.

## 9. Running Locally

### Linux/macOS

```bash
git clone https://github.com/jiyaa25/csd_asg_pond.git
cd csd_asg_pond

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
python main.py
```

### Windows

```powershell
git clone https://github.com/jiyaa25/csd_asg_pond.git
cd csd_asg_pond

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
python main.py
```

The application will start using the configured FastAPI port.

## 10. Testing

Run the automated tests using:

```bash
pytest -q
```

A sample analysis can also be generated using:

```bash
python generate_outputs.py
```

This processes `contours_1m.kml` and generates:

```text
outputs/sample_analysis.json
```

## 11. Important Limitations

* IDW interpolation creates an estimated elevation surface between contour lines.
* D8 flow routing is a simplified terrain-flow model.
* Flow accumulation is used as a terrain-based indicator of drainage/channel areas.
* The 200 m drainage distance is an academic screening parameter, not an engineering or legal setback.
* Catchment areas are approximate and depend on the contour data and grid resolution.
* The identified locations are terrain-derived pond candidates and are not guaranteed engineering-grade pond sites.

## 12. Repository

GitHub Repository:

```text
https://github.com/jiyaa25/csd_asg_pond
```

Hosted API:

```text
http://10.1.75.79:5261/
```

API Endpoint:

```text
POST http://10.1.75.79:5261/analyzeContour
```

Swagger:

```text
http://10.1.75.79:5261/docs
```
