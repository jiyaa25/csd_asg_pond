from typing import Optional
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
from terrain import build_terrain_grid

ROOT = Path(__file__).resolve().parent

app = FastAPI(
    title="Pond Location & Catchment Analysis API",
    version="1.1.0",
    description="Student-level graph-based terrain analysis from KML/KMZ contour maps.",
)

# CORS configuration allowing all external origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
def root():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}

@app.post("/analyzeContour", tags=["Analysis"])
async def analyze_contour(
    contour_map: Optional[UploadFile] = File(
        None,
        description=".kml or .kmz contour map"
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
):
    if contour_map is None:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": (
                    "No contour_map file uploaded. "
                    "Send the KML/KMZ file using multipart/form-data "
                    "with field name 'contour_map'."
                )
            }
        )

    filename = contour_map.filename or ""

    if not filename.lower().endswith((".kml", ".kmz")):
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Unsupported file format. Upload a .kml or .kmz file."
            },
        )

    data = await contour_map.read()

    if not data:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Uploaded contour_map file is empty."
            }
        )

    try:
        contours, bounds, waterways = parse_kml_or_kmz(data, filename)

        terrain = build_terrain_grid(
            contours,
            bounds,
            grid_size=120
        )

        graph = build_terrain_graph(terrain)

        flow_acc = calculate_flow_accumulation(graph)

        river_nodes = detect_river_nodes(
            graph,
            flow_acc,
            waterways
        )

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

        for rank, (pond, score, distance_to_river) in enumerate(
            selected,
            start=1
        ):
            _, catchment = delineate_catchment_bfs(
                graph,
                pond.id
            )

            pond_locations.append(
                {
                    "rank": rank,
                    "latitude": round(pond.lat, 6),
                    "longitude": round(pond.lon, 6),
                    "elevation": round(pond.elevation, 2),
                    "suitability_score": round(float(score), 2),
                    "catchment_area_square_meters":
                        catchment["area_square_meters"],
                    "catchment_area_hectares":
                        catchment["area_hectares"],
                    "catchment_cells":
                        catchment["number_of_cells"],
                    "distance_from_channel_m":
                        round(float(distance_to_river), 2),
                    "catchment": catchment,
                }
            )

        channel_segments = []

        for node_id in sorted(river_nodes):
            node = graph.nodes[node_id]

            downstream_id = node.downstream_node_id

            if downstream_id in river_nodes:
                downstream = graph.nodes[downstream_id]

                channel_segments.append(
                    [
                        [round(node.lat, 6), round(node.lon, 6)],
                        [
                            round(downstream.lat, 6),
                            round(downstream.lon, 6)
                        ],
                    ]
                )

        explicit_waterway_lines = [
            {
                "name": waterway["name"],
                "coordinates": [
                    [round(lat, 6), round(lon, 6)]
                    for lon, lat in waterway["coords"]
                ],
            }
            for waterway in waterways
        ]

        analysis["ponds_selected"] = len(pond_locations)
        analysis["channel_node_count"] = len(river_nodes)
        analysis["explicit_waterway_count"] = len(waterways)

        if not pond_locations:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "No valid pond candidates found.",
                    "input": {
                        "filename": filename,
                        "contour_count": len(contours),
                        "explicit_waterway_count": len(waterways),
                    },
                    "pond_locations": [],
                    "analysis": analysis,
                }
            )

        best = pond_locations[0]

        best_catchment = best["catchment"]

        best_distance = best["distance_from_channel_m"]

        return {
            "status": "success",

            "input": {
                "filename": filename,
                "contour_count": len(contours),
                "explicit_waterway_count": len(waterways),
                "elevation_min_m":
                    round(terrain.min_elevation, 2),
                "elevation_max_m":
                    round(terrain.max_elevation, 2),
                "bounds_wgs84": bounds,
                "grid_size": terrain.rows,
            },

            "pond_locations": pond_locations,

            "pond_location": {
                "latitude": best["latitude"],
                "longitude": best["longitude"],
                "elevation": best["elevation"],
                "suitability_score":
                    best["suitability_score"],
            },

            "catchment": best_catchment,

            "river_safety": {
                "is_on_or_near_detected_channel":
                    best_distance < drainage_safety_buffer_m,
                "distance_to_river_meters":
                    best_distance,
                "safety_buffer_meters":
                    drainage_safety_buffer_m,
                "status":
                    "SAFE"
                    if best_distance >= drainage_safety_buffer_m
                    else "REJECTED",
            },

            "channels": {
                "terrain_derived_segments":
                    channel_segments,
                "explicit_waterways":
                    explicit_waterway_lines,
            },

            "analysis": analysis,
        }

    except KMLParseError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(exc)
            }
        )

    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "message": str(exc)
            }
        )

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Internal analysis error: {exc}"
            }
        )
             


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid request parameters."})


app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
