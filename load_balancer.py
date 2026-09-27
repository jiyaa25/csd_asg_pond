import asyncio
import io
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cache_service import (
    generate_area_cache_key,
    generate_kml_cache_key,
    generate_place_cache_key,
    get_cache,
    get_cache_stats,
    normalize_text,
    set_cache,
    snap_coordinate,
)

ROOT = Path(__file__).resolve().parent

app = FastAPI(
    title="Pond & Catchment Distributed Gateway & Load Balancer",
    version="3.0.0",
    description="High-availability distributed gateway routing traffic across Systems 2, 3, and 4 with 24-hour intelligent caching.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Static files mount
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

# Worker Node Topology
# System 1 is Gateway (172.17.0.62)
# System 2 is Worker 1 (172.17.0.63)
# System 3 is Worker 2 (172.17.0.64)
# System 4 is Worker 3 (172.17.0.65)
WORKER_NODES = [
    {
        "id": "sys2",
        "name": "stu46_sys2 (Worker 1)",
        "host": "172.17.0.63",
        "port": 5000,
        "url": "http://172.17.0.63:5000",
        "healthy": True,
        "latency_ms": 0.0,
        "active_requests": 0,
        "total_requests": 0,
    },
    {
        "id": "sys3",
        "name": "stu46_sys3 (Worker 2)",
        "host": "172.17.0.64",
        "port": 5000,
        "url": "http://172.17.0.64:5000",
        "healthy": True,
        "latency_ms": 0.0,
        "active_requests": 0,
        "total_requests": 0,
    },
    {
        "id": "sys4",
        "name": "stu46_sys4 (Worker 3)",
        "host": "172.17.0.65",
        "port": 5000,
        "url": "http://172.17.0.65:5000",
        "healthy": True,
        "latency_ms": 0.0,
        "active_requests": 0,
        "total_requests": 0,
    },
]

round_robin_counter = 0


async def check_node_health(node: Dict[str, Any], client: httpx.AsyncClient):
    """Check health of an individual worker node."""
    t0 = time.time()
    try:
        res = await client.get(f"{node['url']}/health", timeout=2.0)
        if res.status_code == 200:
            node["healthy"] = True
            node["latency_ms"] = round((time.time() - t0) * 1000, 1)
        else:
            node["healthy"] = False
    except Exception:
        node["healthy"] = False
        node["latency_ms"] = -1.0


async def health_check_daemon():
    """Background task polling worker health periodically."""
    async with httpx.AsyncClient() as client:
        while True:
            tasks = [check_node_health(node, client) for node in WORKER_NODES]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(8)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(health_check_daemon())


def get_next_healthy_worker() -> Optional[Dict[str, Any]]:
    """Select the best healthy worker using round-robin with least-connections preference."""
    global round_robin_counter
    healthy_workers = [w for w in WORKER_NODES if w["healthy"]]
    if not healthy_workers:
        return None

    # Least active connections among healthy
    healthy_workers.sort(key=lambda w: (w["active_requests"], w["latency_ms"]))
    idx = round_robin_counter % len(healthy_workers)
    round_robin_counter += 1
    return healthy_workers[idx]


# ---------------- Frontend & Status ----------------

@app.get("/", tags=["UI"])
def root():
    return FileResponse(
        ROOT / "frontend" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health", tags=["Health"])
def health():
    healthy_count = sum(1 for w in WORKER_NODES if w["healthy"])
    return {
        "status": "healthy" if healthy_count > 0 else "degraded",
        "gateway": "stu46_sys1",
        "healthy_workers": f"{healthy_count}/{len(WORKER_NODES)}",
    }


@app.get("/cluster/status", tags=["Cluster"])
def cluster_status():
    """Detailed cluster status showing worker states, request stats, and cache info."""
    return {
        "gateway": {
            "node": "stu46_sys1",
            "role": "Load Balancer & Shared Cache Master",
            "port": 5000,
            "external_port": 5261,
        },
        "workers": WORKER_NODES,
        "cache": get_cache_stats(),
    }


# ---------------- Forwarding Engine with Automatic Failover ----------------

async def forward_with_failover(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    timeout: float = 45.0,
) -> Tuple[Dict[str, Any], int, str]:
    """Forward a request to an active worker with automatic retry/failover."""
    tried_workers = set()

    for _ in range(len(WORKER_NODES)):
        healthy_candidates = [w for w in WORKER_NODES if w["healthy"] and w["id"] not in tried_workers]
        if not healthy_candidates:
            # If all marked unhealthy, try any untried node
            healthy_candidates = [w for w in WORKER_NODES if w["id"] not in tried_workers]
        if not healthy_candidates:
            break

        global round_robin_counter
        worker = healthy_candidates[round_robin_counter % len(healthy_candidates)]
        round_robin_counter += 1

        tried_workers.add(worker["id"])
        target_url = f"{worker['url']}{path}"

        worker["active_requests"] += 1
        worker["total_requests"] += 1

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "POST":
                    resp = await client.post(target_url, params=params, data=data, files=files)
                else:
                    resp = await client.get(target_url, params=params)

                worker["active_requests"] = max(0, worker["active_requests"] - 1)
                worker["healthy"] = True

                try:
                    payload = resp.json()
                except Exception:
                    payload = {"raw": resp.text}

                return payload, resp.status_code, worker["id"]

        except Exception as exc:
            worker["active_requests"] = max(0, worker["active_requests"] - 1)
            worker["healthy"] = False
            print(f"Worker {worker['id']} failed for {path}: {exc}. Retrying on another worker...")

    # If all workers failed, try local fallback on System 1
    print("All remote workers failed. Executing local fallback on Gateway...")
    try:
        import main as local_backend
        if path == "/health":
            return {"status": "healthy", "mode": "local_fallback"}, 200, "local"
    except Exception as exc:
        pass

    return {
        "status": "error",
        "message": "All backend worker nodes (sys2, sys3, sys4) are currently unreachable.",
    }, 503, "none"


# ---------------- API Endpoints with 24-Hour Caching ----------------

@app.get("/api/rainfall", tags=["Hydrology"])
async def get_rainfall(lat: float = Query(21.25), lon: float = Query(81.30)):
    # Quantize coordinates to 0.05 deg (~5 km) for cache key
    s_lat = round(snap_coordinate(lat, resolution=0.05), 4)
    s_lon = round(snap_coordinate(lon, resolution=0.05), 4)
    cache_key = f"rain:{s_lat}:{s_lon}"

    cached = get_cache(cache_key)
    if cached:
        data, meta = cached
        data["cache"] = meta
        return data

    payload, status_code, worker_id = await forward_with_failover(
        "GET", "/api/rainfall", params={"lat": lat, "lon": lon}
    )
    if status_code == 200 and payload.get("annual_rainfall_mm"):
        set_cache(cache_key, payload, ttl_seconds=86400, category="rainfall")
        payload["cache"] = {"hit": False, "node": worker_id}

    return JSONResponse(status_code=status_code, content=payload)


@app.get("/api/geocode", tags=["Geocoding"])
async def geocode_api(q: str = Query(..., description="Village or place name")):
    norm = normalize_text(q)
    cache_key = f"geo:{norm}"

    cached = get_cache(cache_key)
    if cached:
        data, meta = cached
        data["cache"] = meta
        return data

    payload, status_code, worker_id = await forward_with_failover(
        "GET", "/api/geocode", params={"q": q}
    )
    if status_code == 200 and payload.get("status") == "success":
        set_cache(cache_key, payload, ttl_seconds=86400, category="geocode")
        payload["cache"] = {"hit": False, "node": worker_id}

    return JSONResponse(status_code=status_code, content=payload)


@app.post("/analyzePlace", tags=["Analysis"])
async def analyze_place(
    place_name: str = Query(..., description="Name of village or place"),
    drainage_safety_buffer_m: float = Query(200.0, ge=0.0),
    number_of_ponds: int = Query(5, ge=1, le=50),
    annual_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=10000.0),
    runoff_coefficient: float = Query(0.40, ge=0.01, le=1.0),
):
    """Case 3: Village search with 24-hour intelligent cache."""
    cache_key = generate_place_cache_key(
        place_name=place_name,
        buffer_m=drainage_safety_buffer_m,
        number_of_ponds=number_of_ponds,
        rainfall_mm=annual_rainfall_mm,
        runoff_c=runoff_coefficient,
    )

    cached = get_cache(cache_key)
    if cached:
        data, meta = cached
        data["cache"] = meta
        return data

    params = {
        "place_name": place_name,
        "drainage_safety_buffer_m": drainage_safety_buffer_m,
        "number_of_ponds": number_of_ponds,
        "runoff_coefficient": runoff_coefficient,
    }
    if annual_rainfall_mm is not None:
        params["annual_rainfall_mm"] = annual_rainfall_mm

    payload, status_code, worker_id = await forward_with_failover(
        "POST", "/analyzePlace", params=params
    )

    if status_code == 200 and payload.get("status") == "success":
        set_cache(cache_key, payload, ttl_seconds=86400, category="analyzePlace")
        payload["cache"] = {"hit": False, "node": worker_id}

    return JSONResponse(status_code=status_code, content=payload)


@app.post("/analyzeArea", tags=["Analysis"])
async def analyze_area(
    selected_min_lat: float = Query(..., description="Min Latitude"),
    selected_max_lat: float = Query(..., description="Max Latitude"),
    selected_min_lon: float = Query(..., description="Min Longitude"),
    selected_max_lon: float = Query(..., description="Max Longitude"),
    drainage_safety_buffer_m: float = Query(200.0, ge=0.0),
    number_of_ponds: int = Query(5, ge=1, le=50),
    annual_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=10000.0),
    runoff_coefficient: float = Query(0.40, ge=0.01, le=1.0),
):
    """Case 2: Map area DEM selection with spatial quantization cache."""
    cache_key = generate_area_cache_key(
        min_lat=selected_min_lat,
        max_lat=selected_max_lat,
        min_lon=selected_min_lon,
        max_lon=selected_max_lon,
        buffer_m=drainage_safety_buffer_m,
        number_of_ponds=number_of_ponds,
        rainfall_mm=annual_rainfall_mm,
        runoff_c=runoff_coefficient,
    )

    cached = get_cache(cache_key)
    if cached:
        data, meta = cached
        data["cache"] = meta
        return data

    params = {
        "selected_min_lat": selected_min_lat,
        "selected_max_lat": selected_max_lat,
        "selected_min_lon": selected_min_lon,
        "selected_max_lon": selected_max_lon,
        "drainage_safety_buffer_m": drainage_safety_buffer_m,
        "number_of_ponds": number_of_ponds,
        "runoff_coefficient": runoff_coefficient,
    }
    if annual_rainfall_mm is not None:
        params["annual_rainfall_mm"] = annual_rainfall_mm

    payload, status_code, worker_id = await forward_with_failover(
        "POST", "/analyzeArea", params=params
    )

    if status_code == 200 and payload.get("status") == "success":
        set_cache(cache_key, payload, ttl_seconds=86400, category="analyzeArea")
        payload["cache"] = {"hit": False, "node": worker_id}

    return JSONResponse(status_code=status_code, content=payload)


@app.post("/analyzeContour", tags=["Analysis"])
async def analyze_contour(
    contour_map: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    place_name: Optional[str] = Query(None),
    drainage_safety_buffer_m: float = Query(200.0, ge=0.0),
    number_of_ponds: int = Query(5, ge=1, le=50),
    annual_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=10000.0),
    runoff_coefficient: float = Query(0.40, ge=0.01, le=1.0),
    selected_min_lat: Optional[float] = Query(None),
    selected_max_lat: Optional[float] = Query(None),
    selected_min_lon: Optional[float] = Query(None),
    selected_max_lon: Optional[float] = Query(None),
):
    """Universal endpoint routing Case 1, 2, and 3 with intelligent caching."""
    upload = contour_map or file

    # Case 3 redirect
    if upload is None and place_name:
        return await analyze_place(
            place_name=place_name,
            drainage_safety_buffer_m=drainage_safety_buffer_m,
            number_of_ponds=number_of_ponds,
            annual_rainfall_mm=annual_rainfall_mm,
            runoff_coefficient=runoff_coefficient,
        )

    # Case 2 redirect
    has_selection = all(v is not None for v in [selected_min_lat, selected_max_lat, selected_min_lon, selected_max_lon])
    if upload is None and has_selection:
        return await analyze_area(
            selected_min_lat=float(selected_min_lat),
            selected_max_lat=float(selected_max_lat),
            selected_min_lon=float(selected_min_lon),
            selected_max_lon=float(selected_max_lon),
            drainage_safety_buffer_m=drainage_safety_buffer_m,
            number_of_ponds=number_of_ponds,
            annual_rainfall_mm=annual_rainfall_mm,
            runoff_coefficient=runoff_coefficient,
        )

    if upload is None:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "No input provided. Upload a file, select an area, or enter a village name.",
            }
        )

    # Case 1: File Upload
    file_bytes = await upload.read()
    if not file_bytes:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Uploaded contour file is empty."})

    sel_bounds = None
    if has_selection:
        sel_bounds = {
            "minLat": float(selected_min_lat),
            "maxLat": float(selected_max_lat),
            "minLon": float(selected_min_lon),
            "maxLon": float(selected_max_lon),
        }

    cache_key = generate_kml_cache_key(
        file_bytes=file_bytes,
        buffer_m=drainage_safety_buffer_m,
        number_of_ponds=number_of_ponds,
        rainfall_mm=annual_rainfall_mm,
        runoff_c=runoff_coefficient,
        selected_bounds=sel_bounds,
    )

    cached = get_cache(cache_key)
    if cached:
        data, meta = cached
        data["cache"] = meta
        return data

    params = {
        "drainage_safety_buffer_m": drainage_safety_buffer_m,
        "number_of_ponds": number_of_ponds,
        "runoff_coefficient": runoff_coefficient,
    }
    if annual_rainfall_mm is not None:
        params["annual_rainfall_mm"] = annual_rainfall_mm
    if has_selection:
        params["selected_min_lat"] = selected_min_lat
        params["selected_max_lat"] = selected_max_lat
        params["selected_min_lon"] = selected_min_lon
        params["selected_max_lon"] = selected_max_lon

    filename = upload.filename or "contours.kml"
    files = {"contour_map": (filename, file_bytes, upload.content_type or "application/octet-stream")}

    payload, status_code, worker_id = await forward_with_failover(
        "POST", "/analyzeContour", params=params, files=files
    )

    if status_code == 200 and payload.get("status") == "success":
        set_cache(cache_key, payload, ttl_seconds=86400, category="analyzeContour")
        payload["cache"] = {"hit": False, "node": worker_id}

    return JSONResponse(status_code=status_code, content=payload)
