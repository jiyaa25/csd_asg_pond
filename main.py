from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from catchment import (
    calculate_flow_accumulation,
    delineate_catchment_bfs,
    detect_ridge_nodes,
    detect_river_nodes,
    select_top_pond_candidates,
)
from contour_parser import KMLParseError, parse_kml_or_kmz
from graph import build_terrain_graph
from terrain import TerrainGrid, build_terrain_grid
from rainfall_service import fetch_annual_rainfall
from dem_service import fetch_dem_elevation_grid, geocode_place

ROOT = Path(__file__).resolve().parent

app = FastAPI(
    title="Pond Location & Catchment Analysis API",
    version="2.0.0",
    description="Terrain analysis system supporting KML upload, map area selection (DEM), and village name search with dynamic climate rainfall.",
)

# CORS configuration allowing all external origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/", tags=["Health"])
def root():
    return FileResponse(
        ROOT / "frontend" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}


@app.get("/api/rainfall", tags=["Hydrology"])
def get_rainfall(lat: float = Query(21.25), lon: float = Query(81.30)):
    """Fetch live annual rainfall from Open-Meteo / NASA POWER Climatology API."""
    return fetch_annual_rainfall(lat, lon)


@app.get("/api/geocode", tags=["Geocoding"])
def geocode_api(q: str = Query(..., description="Village or place name")):
    """Geocode a village, town or place name to its geographic bounding box."""
    res = geocode_place(q)
    if not res:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"Place or village '{q}' could not be located."}
        )
    return {"status": "success", "result": res}


def execute_terrain_analysis(
    terrain: TerrainGrid,
    waterways: List[Dict[str, Any]],
    drainage_safety_buffer_m: float,
    number_of_ponds: int,
    effective_rainfall_mm: float,
    rainfall_source: str,
    runoff_coefficient: float,
    soil_type_desc: str,
    meta_input: Dict[str, Any],
    generated_contours: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    graph = build_terrain_graph(terrain)
    flow_acc = calculate_flow_accumulation(graph)
    river_nodes = detect_river_nodes(graph, flow_acc, waterways)
    ridge_nodes = detect_ridge_nodes(graph)

    selected, analysis = select_top_pond_candidates(
        graph,
        flow_acc,
        river_nodes,
        ridge_nodes,
        safety_buffer_m=drainage_safety_buffer_m,
        number_of_ponds=number_of_ponds,
    )

    pond_locations = []
    for rank, (pond, score, distance_to_river) in enumerate(selected, start=1):
        _, catchment = delineate_catchment_bfs(
            graph,
            pond.id,
            annual_rainfall_mm=effective_rainfall_mm,
            runoff_coefficient=runoff_coefficient,
        )
        pond_locations.append(
            {
                "rank": rank,
                "latitude": round(pond.lat, 6),
                "longitude": round(pond.lon, 6),
                "elevation": round(pond.elevation, 2),
                "suitability_score": round(float(score), 2),
                "catchment_area_square_meters": catchment["area_square_meters"],
                "catchment_area_hectares": catchment["area_hectares"],
                "catchment_cells": catchment["number_of_cells"],
                "expected_water_volume_m3": catchment["expected_water_volume_m3"],
                "expected_water_volume_liters": catchment["expected_water_volume_liters"],
                "expected_water_volume_megaliters": catchment["expected_water_volume_megaliters"],
                "distance_from_channel_m": round(float(distance_to_river), 2),
                "catchment": catchment,
            }
        )

    channel_segments = []
    for node_id in sorted(river_nodes):
        node = graph.nodes[node_id]
        downstream_id = node.downstream_node_id
        if downstream_id in river_nodes:
            downstream = graph.nodes[downstream_id]
            channel_segments.append([
                [round(node.lat, 6), round(node.lon, 6)],
                [round(downstream.lat, 6), round(downstream.lon, 6)],
            ])

    explicit_waterway_lines = [
        {
            "name": waterway["name"],
            "coordinates": [[round(lat, 6), round(lon, 6)] for lon, lat in waterway["coords"]],
        }
        for waterway in waterways
    ]

    analysis["ponds_selected"] = len(pond_locations)
    analysis["channel_node_count"] = len(river_nodes)
    analysis["explicit_waterway_count"] = len(waterways)

    if not pond_locations:
        return {
            "status": "success",
            "message": "No valid pond candidates found.",
            "input": meta_input,
            "pond_locations": [],
            "analysis": analysis,
        }

    best = pond_locations[0]
    best_distance = best["distance_from_channel_m"]

    response_payload = {
        "status": "success",
        "input": meta_input,
        "water_volume_parameters": {
            "annual_rainfall_mm": effective_rainfall_mm,
            "rainfall_source": rainfall_source,
            "runoff_coefficient": runoff_coefficient,
            "soil_type": soil_type_desc,
            "formula": "Rational Method: Volume (m³) = Catchment Area (m²) * Rainfall (m) * Runoff Coefficient",
        },
        "pond_locations": pond_locations,
        "pond_location": {
            "latitude": best["latitude"],
            "longitude": best["longitude"],
            "elevation": best["elevation"],
            "suitability_score": best["suitability_score"],
            "expected_water_volume_m3": best["expected_water_volume_m3"],
            "expected_water_volume_megaliters": best["expected_water_volume_megaliters"],
        },
        "catchment": best["catchment"],
        "river_safety": {
            "is_on_or_near_detected_channel": best_distance < drainage_safety_buffer_m,
            "distance_to_river_meters": best_distance,
            "safety_buffer_meters": drainage_safety_buffer_m,
            "status": "SAFE" if best_distance >= drainage_safety_buffer_m else "REJECTED",
        },
        "channels": {
            "terrain_derived_segments": channel_segments,
            "explicit_waterways": explicit_waterway_lines,
        },
        "analysis": analysis,
    }

    if generated_contours:
        response_payload["generated_contours"] = generated_contours

    return response_payload


@app.post("/analyzePlace", tags=["Analysis"])
async def analyze_place(
    place_name: str = Query(..., description="Name of village, town or city (e.g., Khapri, Bhilai, Patan)"),
    drainage_safety_buffer_m: float = Query(200.0, ge=0.0, description="Minimum distance from detected channels"),
    number_of_ponds: int = Query(5, ge=1, le=50, description="Number of top spatially separated pond candidates"),
    annual_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=10000.0, description="Annual rainfall (auto from API if omitted)"),
    runoff_coefficient: float = Query(0.40, ge=0.01, le=1.0, description="Runoff coefficient C (0.40 default)"),
):
    """Case 3: User searches a village or place name without providing a contour map."""
    geo = geocode_place(place_name)
    if not geo:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"Place or village '{place_name}' could not be found."}
        )

    bounds = geo["bounds"]
    terrain, contours = fetch_dem_elevation_grid(bounds, query_dim=15, target_dim=50)

    center_lat = geo["latitude"]
    center_lon = geo["longitude"]

    if annual_rainfall_mm is None or annual_rainfall_mm <= 0:
        rain_info = fetch_annual_rainfall(center_lat, center_lon)
        eff_rain = rain_info["annual_rainfall_mm"]
        rain_src = rain_info["source"]
    else:
        eff_rain = float(annual_rainfall_mm)
        rain_src = f"Manual input / preset ({eff_rain} mm)"

    soil_catalog = {
        0.30: "Sandy Loam with vegetation cover",
        0.40: "Clay/Silt Loam (Standard agricultural catchment)",
        0.50: "Hard Clay soils",
        0.60: "Barren or high-slope clay soils",
    }
    soil_desc = soil_catalog.get(round(runoff_coefficient, 2), f"Custom soil runoff coefficient C={runoff_coefficient}")

    meta = {
        "mode": "village_search_dem",
        "place_name": geo["display_name"],
        "bounds_wgs84": bounds,
        "selected_land_area": bounds,
        "elevation_min_m": round(terrain.min_elevation, 2),
        "elevation_max_m": round(terrain.max_elevation, 2),
        "grid_size": terrain.rows,
        "contour_count": len(contours),
        "explicit_waterway_count": 0,
    }

    try:
        return execute_terrain_analysis(
            terrain=terrain,
            waterways=[],
            drainage_safety_buffer_m=drainage_safety_buffer_m,
            number_of_ponds=number_of_ponds,
            effective_rainfall_mm=eff_rain,
            rainfall_source=rain_src,
            runoff_coefficient=runoff_coefficient,
            soil_type_desc=soil_desc,
            meta_input=meta,
            generated_contours=contours,
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Analysis error: {exc}"})


@app.post("/analyzeArea", tags=["Analysis"])
async def analyze_area(
    selected_min_lat: float = Query(..., description="Min Latitude (South)"),
    selected_max_lat: float = Query(..., description="Max Latitude (North)"),
    selected_min_lon: float = Query(..., description="Min Longitude (West)"),
    selected_max_lon: float = Query(..., description="Max Longitude (East)"),
    drainage_safety_buffer_m: float = Query(200.0, ge=0.0, description="Minimum distance from detected channels"),
    number_of_ponds: int = Query(5, ge=1, le=50, description="Number of top spatially separated pond candidates"),
    annual_rainfall_mm: Optional[float] = Query(None, ge=0.0, le=10000.0, description="Annual rainfall (auto from API if omitted)"),
    runoff_coefficient: float = Query(0.40, ge=0.01, le=1.0, description="Runoff coefficient C (0.40 default)"),
):
    """Case 2: User selects an area on the map without providing a contour map."""
    bounds = {
        "min_lat": min(selected_min_lat, selected_max_lat),
        "max_lat": max(selected_min_lat, selected_max_lat),
        "min_lon": min(selected_min_lon, selected_max_lon),
        "max_lon": max(selected_min_lon, selected_max_lon),
    }

    terrain, contours = fetch_dem_elevation_grid(bounds, query_dim=15, target_dim=50)

    center_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2.0
    center_lon = (bounds["min_lon"] + bounds["max_lon"]) / 2.0

    if annual_rainfall_mm is None or annual_rainfall_mm <= 0:
        rain_info = fetch_annual_rainfall(center_lat, center_lon)
        eff_rain = rain_info["annual_rainfall_mm"]
        rain_src = rain_info["source"]
    else:
        eff_rain = float(annual_rainfall_mm)
        rain_src = f"Manual input / preset ({eff_rain} mm)"

    soil_catalog = {
        0.30: "Sandy Loam with vegetation cover",
        0.40: "Clay/Silt Loam (Standard agricultural catchment)",
        0.50: "Hard Clay soils",
        0.60: "Barren or high-slope clay soils",
    }
    soil_desc = soil_catalog.get(round(runoff_coefficient, 2), f"Custom soil runoff coefficient C={runoff_coefficient}")

    meta = {
        "mode": "map_area_dem",
        "bounds_wgs84": bounds,
        "selected_land_area": bounds,
        "elevation_min_m": round(terrain.min_elevation, 2),
        "elevation_max_m": round(terrain.max_elevation, 2),
        "grid_size": terrain.rows,
        "contour_count": len(contours),
        "explicit_waterway_count": 0,
    }

    try:
        return execute_terrain_analysis(
            terrain=terrain,
            waterways=[],
            drainage_safety_buffer_m=drainage_safety_buffer_m,
            number_of_ponds=number_of_ponds,
            effective_rainfall_mm=eff_rain,
            rainfall_source=rain_src,
            runoff_coefficient=runoff_coefficient,
            soil_type_desc=soil_desc,
            meta_input=meta,
            generated_contours=contours,
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Analysis error: {exc}"})


@app.post("/analyzeContour", tags=["Analysis"])
async def analyze_contour(
    contour_map: Optional[UploadFile] = File(
        None,
        description=".kml or .kmz contour map"
    ),
    file: Optional[UploadFile] = File(
        None,
        description="Alias for contour_map upload"
    ),
    place_name: Optional[str] = Query(
        None,
        description="Optional village/place name if not uploading a file"
    ),
    drainage_safety_buffer_m: float = Query(
        200.0,
        ge=0.0,
        description="Minimum distance from detected channels."
    ),
    number_of_ponds: int = Query(
        5,
        ge=1,
        le=50,
        description="Number of top spatially separated pond candidates."
    ),
    annual_rainfall_mm: Optional[float] = Query(
        None,
        ge=0.0,
        le=10000.0,
        description="Annual rainfall in mm. If omitted or 0, automatically fetched from Open-Meteo/NASA POWER API."
    ),
    runoff_coefficient: float = Query(
        0.40,
        ge=0.01,
        le=1.0,
        description="Runoff coefficient C (Default 0.40: Clay/Silt Loam standard agricultural catchment)."
    ),
    selected_min_lat: Optional[float] = Query(None, description="Selected land area min latitude"),
    selected_max_lat: Optional[float] = Query(None, description="Selected land area max latitude"),
    selected_min_lon: Optional[float] = Query(None, description="Selected land area min longitude"),
    selected_max_lon: Optional[float] = Query(None, description="Selected land area max longitude"),
):
    """Universal endpoint supporting:
    - Case 1: KML/KMZ contour map upload
    - Case 2: Selected area on map (DEM API mode if no file uploaded)
    - Case 3: Village / Place name (DEM API mode if place_name provided)
    """
    upload = contour_map or file

    # Case 3 via analyzeContour: place_name provided without file
    if upload is None and place_name:
        return await analyze_place(
            place_name=place_name,
            drainage_safety_buffer_m=drainage_safety_buffer_m,
            number_of_ponds=number_of_ponds,
            annual_rainfall_mm=annual_rainfall_mm,
            runoff_coefficient=runoff_coefficient,
        )

    # Case 2 via analyzeContour: map coordinates provided without file
    has_selection = all(
        v is not None for v in [selected_min_lat, selected_max_lat, selected_min_lon, selected_max_lon]
    )
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

    # Error if nothing provided
    if upload is None:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": (
                    "No input provided. You can: "
                    "1. Upload a contour_map file (.kml/.kmz), OR "
                    "2. Select a land area on the map, OR "
                    "3. Search a village/place name."
                )
            }
        )

    # Case 1: File uploaded
    filename = upload.filename or ""
    if not filename.lower().endswith((".kml", ".kmz")):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Unsupported file format. Upload a .kml or .kmz file."
            },
        )

    data = await upload.read()
    if not data:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Uploaded contour file is empty."
            }
        )

    try:
        contours, bounds, waterways = parse_kml_or_kmz(data, filename)

        selected_bounds = None
        effective_bounds = bounds

        if has_selection:
            sel_s = min(float(selected_min_lat), float(selected_max_lat))
            sel_n = max(float(selected_min_lat), float(selected_max_lat))
            sel_w = min(float(selected_min_lon), float(selected_max_lon))
            sel_e = max(float(selected_min_lon), float(selected_max_lon))

            inter_s = max(bounds["min_lat"], sel_s)
            inter_n = min(bounds["max_lat"], sel_n)
            inter_w = max(bounds["min_lon"], sel_w)
            inter_e = min(bounds["max_lon"], sel_e)

            if inter_s >= inter_n or inter_w >= inter_e:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "The selected land area does not overlap with the contour map extent."
                    }
                )

            effective_bounds = {
                "min_lat": inter_s,
                "max_lat": inter_n,
                "min_lon": inter_w,
                "max_lon": inter_e,
            }
            selected_bounds = {
                "min_lat": round(inter_s, 6),
                "max_lat": round(inter_n, 6),
                "min_lon": round(inter_w, 6),
                "max_lon": round(inter_e, 6),
            }

        center_lat = (effective_bounds["min_lat"] + effective_bounds["max_lat"]) / 2.0
        center_lon = (effective_bounds["min_lon"] + effective_bounds["max_lon"]) / 2.0

        if annual_rainfall_mm is None or annual_rainfall_mm <= 0:
            rain_info = fetch_annual_rainfall(center_lat, center_lon)
            effective_rainfall_mm = rain_info["annual_rainfall_mm"]
            rainfall_source = rain_info["source"]
        else:
            effective_rainfall_mm = float(annual_rainfall_mm)
            rainfall_source = f"Manual input / preset ({effective_rainfall_mm} mm)"

        soil_catalog = {
            0.30: "Sandy Loam with vegetation cover",
            0.40: "Clay/Silt Loam (Standard agricultural catchment)",
            0.50: "Hard Clay soils",
            0.60: "Barren or high-slope clay soils",
        }
        soil_type_desc = soil_catalog.get(
            round(runoff_coefficient, 2),
            f"Custom soil runoff coefficient C={runoff_coefficient}"
        )

        terrain = build_terrain_grid(
            contours,
            effective_bounds,
            grid_size=120
        )

        meta = {
            "mode": "kml_contour_upload",
            "filename": filename,
            "contour_count": len(contours),
            "explicit_waterway_count": len(waterways),
            "elevation_min_m": round(terrain.min_elevation, 2),
            "elevation_max_m": round(terrain.max_elevation, 2),
            "bounds_wgs84": bounds,
            "effective_bounds": effective_bounds,
            "selected_land_area": selected_bounds,
            "grid_size": terrain.rows,
        }

        return execute_terrain_analysis(
            terrain=terrain,
            waterways=waterways,
            drainage_safety_buffer_m=drainage_safety_buffer_m,
            number_of_ponds=number_of_ponds,
            effective_rainfall_mm=effective_rainfall_mm,
            rainfall_source=rainfall_source,
            runoff_coefficient=runoff_coefficient,
            soil_type_desc=soil_type_desc,
            meta_input=meta,
        )

    except KMLParseError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"status": "error", "message": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Internal analysis error: {exc}"})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid request parameters."})


app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
