# Distributed Pond Location and Catchment Detection System

A high-performance, fault-tolerant distributed GIS terrain analysis system that determines optimal pond candidates, flow catchments, and expected harvestable water volumes across **3 flexible workflows**:

1. **Case 1: Contour Map Upload** — Upload `.kml` or `.kmz` contour maps (SHA-256 content-cached).
2. **Case 2: Interactive Map Area Selection** — Select any custom bounding box on Leaflet; backend queries a Global Digital Elevation Model (DEM), derives elevation grids and vector contours, and runs hydrological analysis (spatially quantized cache).
3. **Case 3: Village / Place Search** — Search any village, town, or city name; backend geocodes via OpenStreetMap Nominatim, retrieves DEM elevation grid & contours, fetches live agro-climatological rainfall, and computes pond locations and catchments automatically (normalized place cache).

---

## 1. Distributed Multi-Node Cluster Architecture

The application is deployed across **4 distributed Linux nodes**:

```text
                                  User / Web Browser
                                          │
                           (Port 5261 → Host Port 5000)
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      SYSTEM 1: GATEWAY, LOAD BALANCER & CACHE                   │
│                                                                                 │
│   • Node: stu46_sys1 (Internal IP: 172.17.0.62)                                 │
│   • Reverse Proxy & Smart Load Balancer (Round-Robin with Health Checks)        │
│   • Serves Interactive Web Frontend (Leaflet GIS UI)                            │
│   • SQLite Persistent 24-Hour Cache (WAL Mode, Thread-Safe)                     │
└───────────────┬───────────────────────┬───────────────────────┬─────────────────┘
                │                       │                       │
      (HTTP internal call)    (HTTP internal call)    (HTTP internal call)
         ~10ms latency           ~10ms latency           ~10ms latency
                │                       │                       │
                ▼                       ▼                       ▼
    ┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐
    │       SYSTEM 2       ││       SYSTEM 3       ││       SYSTEM 4       │
    │   Backend Worker 1   ││   Backend Worker 2   ││   Backend Worker 3   │
    │                      ││                      ││                      │
    │ • stu46_sys2         ││ • stu46_sys3         ││ • stu46_sys4         │
    │ • 172.17.0.63:5000   ││ • 172.17.0.64:5000   ││ • 172.17.0.65:5000   │
    │ • IDW Interpolation  ││ • IDW Interpolation  ││ • IDW Interpolation  │
    │ • D8 Flow Routing    ││ • D8 Flow Routing    ││ • D8 Flow Routing    │
    │ • BFS Catchments     ││ • BFS Catchments     ││ • BFS Catchments     │
    │ • Rational Volume    ││ • Rational Volume    ││ • Rational Volume    │
    └──────────────────────┘└──────────────────────┘└──────────────────────┘
```

---

## 2. Intelligent 24-Hour Caching Strategy

To ensure instantaneous sub-5ms responses and protect external APIs from rate limits, System 1 implements a multi-strategy cache layer with a **24-hour Time-To-Live (TTL)**:

| Workflow | Cache Key Strategy | Cache Hit Performance | What Gets Bypassed |
| :--- | :--- | :---: | :--- |
| **Case 1: KML Upload** | `kml:<sha256_hash>:<buffer>:<ponds>:<runoff>` | **~2 ms** | XML parsing (1.5s) & IDW terrain surface interpolation |
| **Case 2: Area DEM** | `area:<snapped_lat>:<snapped_lon>:...` (quantized to $0.002^\circ \approx 200\text{m}$) | **~5 ms** | HTTP queries to Global DEM API & Matplotlib contour vectorization |
| **Case 3: Village Search** | `place:<normalized_name>:<buffer>:<ponds>:<runoff>` | **~5 ms** | OpenStreetMap Nominatim geocoding & DEM batch fetch |
| **Climate Rainfall** | `rain:<snapped_lat>:<snapped_lon>` (quantized to $0.05^\circ \approx 5\text{km}$) | **< 1 ms** | External Open-Meteo & NASA POWER Climatology API calls |

---

## 3. High Availability & Fault Tolerance (SPOF Mitigations)

1. **Automatic Worker Failover:** The Gateway polls `/health` on all worker nodes. If a worker goes down, traffic is automatically re-routed to the remaining healthy nodes without user-facing errors.
2. **Transparent Mid-Flight Retries:** If a worker node drops a connection mid-flight, System 1 catches the exception and immediately retries the request on the next worker.
3. **Emergency Local Fallback:** In the event of a total network partition isolating workers, System 1 contains local fallback pipelines to prevent complete service outages.
4. **Resilient Climate Service:** Dual-API architecture queries Open-Meteo and automatically fails over to NASA POWER Climatology.

---

## 4. Endpoints & API Reference

### Hosted Web Interface & Gateway Base
```text
http://10.1.75.79:5261/
```

### Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Web GIS Application (Leaflet UI with cluster status bar) |
| `GET` | `/health` | Gateway health check & worker count (`{"gateway":"stu46_sys1","healthy_workers":"3/3"}`) |
| `GET` | `/cluster/status` | Real-time cluster status, worker latencies, request counts, and cache statistics |
| `GET` | `/api/rainfall` | Fetch dynamic rainfall for coordinates (`lat`, `lon`) with 24h cache |
| `GET` | `/api/geocode` | Geocode village/place name to geographic bounding box (`q`) with 24h cache |
| `POST`| `/analyzeContour` | Universal endpoint supporting KML upload, selected area, or village name |
| `POST`| `/analyzeArea` | Case 2: Direct DEM query for map bounding box with spatial quantization cache |
| `POST`| `/analyzePlace` | Case 3: Village search DEM query & catchment analysis with normalized place cache |

---

## 5. Hydrological Formulas

### Expected Water Volume (Rational Method)
$$\text{Expected Water Volume } (V) = A \times R \times C$$
- $A$ = Catchment Area ($m^2$) delineated via reverse-flow BFS
- $R$ = Annual Precipitation ($m = \text{mm} / 1000$) fetched dynamically from Open-Meteo / NASA POWER API
- $C$ = Runoff Coefficient (dimensionless ratio between $0.01$ and $1.0$) based on soil category ($0.30$ to $0.60$)

---

## 6. Verification Commands

### Check Live Cluster Health
```bash
curl -s http://10.1.75.79:5261/health
```

### Check Cluster Workers & Cache Statistics
```bash
curl -s http://10.1.75.79:5261/cluster/status
```

### Run Full Test Suite
```bash
pytest tests/ -v
```
All 15 automated test cases validate parsing, flow routing, rainfall fallback, geocoding, and DEM terrain analysis.
