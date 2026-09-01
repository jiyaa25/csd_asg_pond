# Assignment Report — Pond Location and Catchment Detection

## 1. Objective

The system accepts a KML/KMZ contour map, derives a terrain surface from contour elevations, models that surface as a graph, estimates downhill drainage, ranks suitable pond candidates and calculates terrain-derived upstream catchments.

## 2. Input

The included sample is `contours_1m.kml`.

Inspection of the actual file showed:
- KML namespace: `http://www.opengis.net/kml/2.2`
- 1,355 `Placemark` contour features
- contour elevation stored in numeric `<name>` values such as `277.0`, `280`, etc.
- contour geometry stored as `<LineString><coordinates>...`
- `<ExtendedData>` contains an ID, not the contour elevation
- coordinates are 2D longitude/latitude
- no explicit river/waterway LineStrings were present in the sample

The existing parser was preserved and supports this structure plus common alternative elevation locations and KMZ input.

## 3. Method

### Step 1 — KML/KMZ parsing

`contour_parser.py` extracts LineString coordinates and elevation metadata. For KMZ files it opens the ZIP archive and locates a KML file, preferring `doc.kml`.

### Step 2 — Terrain representation

`terrain.py` creates a regular 120 × 120 grid over the contour bounds. Elevation is interpolated using inverse-distance weighting (IDW) from contour vertices.

### Step 3 — Graph construction

`graph.py` creates one node per grid cell. Nodes store row/column, latitude, longitude, elevation, neighbours, downstream node and upstream nodes. Edges store physical Haversine distance, elevation difference and slope.

### Step 4 — Downhill flow

The D8 rule selects the neighbouring cell with the greatest positive downhill slope. If no neighbour is lower, the node becomes a local sink/outlet.

### Step 5 — Flow accumulation

Every cell begins with one unit of contribution. Contributions move downstream through the directed graph. High-accumulation cells are used as terrain-derived channel indicators.

### Step 6 — River/channel exclusion

Explicit KML waterway features are used when present. Otherwise high-flow terrain cells are used as likely channels. Candidates on or within the configured safety buffer of detected channels are rejected.

### Step 7 — Ridge/watershed handling

High-elevation local maxima are flagged as ridge candidates and excluded. The catchment itself remains flow-based: reverse traversal only includes cells whose D8 path reaches the selected pond, so cells draining to the other side of a watershed divide are not included.

### Step 8 — Pond candidate ranking

Valid cells are scored using lower relative elevation, upstream flow accumulation and local valley/depression character. After filtering, candidates are sorted by score. A simple minimum grid-cell separation (5% of the smaller grid dimension, with a minimum of three cells) is then applied while walking down the sorted list. This produces distinct candidate locations without complicated optimization or hard-coded coordinates.

### Step 9 — Catchment

For each selected pond, BFS is run on the reverse flow graph. The visited cells are the estimated catchment.

### Step 10 — Catchment area and visualization geometry

Each catchment cell receives an approximate geographic area from local Haversine north/south and east/west spacing. The backend also returns the geographic corners of the actual catchment grid cells. The frontend draws those cells directly; it does not replace the catchment with a circle or arbitrary buffer.

Terrain-derived channel cells are returned as short downstream-connected line segments. Explicit KML waterways are returned as their original coordinates when available.

## 4. Visualization Interface

A small frontend was added only for visualization and testing. It allows the user to:

- upload a KML/KMZ contour map
- specify the minimum river/channel distance
- specify the number of pond candidates
- run the backend analysis
- visualize ranked candidate locations on a Leaflet map
- inspect elevation, suitability score and catchment information
- compare candidates in a dynamic table
- select a table row or map marker to focus on that candidate and its catchment

The frontend does **not** perform terrain analysis. The backend remains responsible for contour extraction, terrain interpolation, graph construction, flow analysis, candidate selection and catchment calculation.

Leaflet is loaded from a CDN and OpenStreetMap is used for the base map, so no Google Maps API key or frontend framework is required.

The UI deliberately labels results as **Terrain-derived Pond Candidates**. They are not engineering-grade hydrological recommendations.

## 5. API Extension

The existing endpoint remains:

```text
POST /analyzeContour
```

It now accepts:

```text
drainage_safety_buffer_m=30
number_of_ponds=5
```

The response adds a `pond_locations` array containing ranked candidates. Each candidate includes its own reverse-flow catchment. The original `pond_location`, `catchment` and `river_safety` fields remain in the response for compatibility with existing clients and tests.

## 6. Sample Demonstration

The real `contours_1m.kml` was processed after the extension.

For 30 m river/channel distance and 5 requested ponds, the current generated results are:

| Rank | Latitude | Longitude | Elevation (m) | Score | Catchment (m²) | Catchment (ha) | Cells | Channel distance (m) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 21.252800 | 81.287180 | 272.00 | 76.53 | 16308.31 | 1.631 | 27 | 165.50 |
| 2 | 21.258789 | 81.300570 | 279.09 | 72.10 | 14495.69 | 1.450 | 24 | 121.68 |
| 3 | 21.252600 | 81.294532 | 279.00 | 70.61 | 18724.37 | 1.872 | 31 | 146.52 |
| 4 | 21.257791 | 81.311334 | 284.24 | 67.01 | 13891.81 | 1.389 | 23 | 146.52 |
| 5 | 21.254796 | 81.297945 | 278.93 | 66.36 | 17516.14 | 1.752 | 29 | 38.48 |

Input summary:
- contours extracted: **1,355**
- explicit waterways: **0**
- elevation range: **267.0–298.0 m**
- terrain grid: **120 × 120**
- valid candidates before separation: **900**
- minimum separation: **6 grid cells / about 163.25 m**
- selected candidates: **5**
- terrain-derived channel nodes: **227**

The exact full response, including catchment-cell geometry, is stored in `outputs/sample_analysis.json` and is generated from the sample map rather than hard-coded.

## 7. Testing Evidence

Automated tests:

```text
9 passed
```

Additional real-sample API checks were performed for:
- 30 m / 5 ponds
- 100 m / 3 ponds
- 30 m / 1 pond
- KMZ upload created from the real sample KML
- invalid file upload
- no file selected at the frontend validation layer

The real sample generated five distinct candidates for the 30 m / 5-pond case.

## 8. Limitations

This is a simplified academic terrain model. It does not replace a professional hydrological study. Results depend on contour accuracy, contour interval, IDW interpolation, grid resolution, KML waterway information and the simplified D8 flow assumption. Candidate locations are screening outputs, not guaranteed engineering sites.
