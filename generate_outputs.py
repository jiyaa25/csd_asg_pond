"""Run the complete pipeline on the included sample map and save its JSON result."""
import json
from pathlib import Path

from catchment import calculate_flow_accumulation, delineate_catchment_bfs, detect_ridge_nodes, detect_river_nodes, select_top_pond_candidates
from contour_parser import parse_kml_or_kmz
from graph import build_terrain_graph
from terrain import build_terrain_grid


ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "contours_1m.kml"
OUTPUT = ROOT / "outputs" / "sample_analysis.json"


def main():
    data = SAMPLE.read_bytes()
    contours, bounds, waterways = parse_kml_or_kmz(data, SAMPLE.name)
    terrain = build_terrain_grid(contours, bounds, grid_size=120)
    graph = build_terrain_graph(terrain)
    flow_acc = calculate_flow_accumulation(graph)
    river_nodes = detect_river_nodes(graph, flow_acc, waterways)
    ridge_nodes = detect_ridge_nodes(graph)
    selected, analysis = select_top_pond_candidates(
        graph, flow_acc, river_nodes, ridge_nodes, safety_buffer_m=30.0, number_of_ponds=5
    )

    pond_locations = []
    for rank, (pond, score, river_distance) in enumerate(selected, start=1):
        _, catchment = delineate_catchment_bfs(graph, pond.id)
        pond_locations.append({
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
            "distance_from_channel_m": round(float(river_distance), 2),
            "catchment": catchment,
        })

    channel_segments = []
    for node_id in sorted(river_nodes):
        node = graph.nodes[node_id]
        if node.downstream_node_id in river_nodes:
            downstream = graph.nodes[node.downstream_node_id]
            channel_segments.append([
                [round(node.lat, 6), round(node.lon, 6)],
                [round(downstream.lat, 6), round(downstream.lon, 6)],
            ])

    explicit_waterway_lines = [
        {"name": w["name"], "coordinates": [[round(lat, 6), round(lon, 6)] for lon, lat in w["coords"]]}
        for w in waterways
    ]

    analysis["ponds_selected"] = len(pond_locations)
    analysis["channel_node_count"] = len(river_nodes)
    analysis["explicit_waterway_count"] = len(waterways)

    best = pond_locations[0]
    result = {
        "status": "success",
        "input": {
            "filename": SAMPLE.name,
            "contour_count": len(contours),
            "explicit_waterway_count": len(waterways),
            "elevation_min_m": round(terrain.min_elevation, 2),
            "elevation_max_m": round(terrain.max_elevation, 2),
            "bounds_wgs84": bounds,
            "grid_size": terrain.rows,
        },
        "pond_locations": pond_locations,
        "pond_location": {k: best[k] for k in ("latitude", "longitude", "elevation", "suitability_score")},
        "catchment": best["catchment"],
        "river_safety": {
            "is_on_or_near_detected_channel": best["distance_from_channel_m"] < 30.0,
            "distance_to_river_meters": best["distance_from_channel_m"],
            "safety_buffer_meters": 30.0,
            "status": "SAFE" if best["distance_from_channel_m"] >= 30.0 else "REJECTED",
        },
        "channels": {
            "terrain_derived_segments": channel_segments,
            "explicit_waterways": explicit_waterway_lines,
        },
        "analysis": analysis,
    }

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"\nSaved: {OUTPUT}")


if __name__ == "__main__":
    main()
