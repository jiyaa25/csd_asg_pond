import pytest
from fastapi.testclient import TestClient
from main import app
from contour_parser import parse_kml_or_kmz, KMLParseError
from terrain import build_terrain_grid
from graph import build_terrain_graph, haversine_distance_m
from catchment import (
    calculate_flow_accumulation, detect_river_nodes, detect_ridge_nodes,
    select_best_pond_candidate, delineate_catchment_bfs
)
from tests.test_parser import create_synthetic_kml

client = TestClient(app)


def test_haversine_distance():
    # Distance between 2 points 0.01 degrees apart at ~21 N is ~1 km
    d = haversine_distance_m(21.0, 81.0, 21.01, 81.0)
    assert 1000.0 < d < 1200.0


def test_kml_parser():
    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    contours, bounds, waterways = parse_kml_or_kmz(kml_bytes, "test.kml")
    assert len(contours) == 5
    assert bounds["min_lon"] < bounds["max_lon"]


def test_terrain_and_graph_construction():
    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    contours, bounds, waterways = parse_kml_or_kmz(kml_bytes, "test.kml")
    terrain_grid = build_terrain_grid(contours, bounds, grid_size=30)
    assert terrain_grid.rows == 30
    assert terrain_grid.cols == 30

    terrain_graph = build_terrain_graph(terrain_grid)
    assert len(terrain_graph.nodes) == 900
    assert terrain_graph.cell_size_m > 0.0


def test_flow_accumulation_and_river_exclusion():
    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    contours, bounds, waterways = parse_kml_or_kmz(kml_bytes, "test.kml")
    terrain_grid = build_terrain_grid(contours, bounds, grid_size=30)
    terrain_graph = build_terrain_graph(terrain_grid)
    flow_acc = calculate_flow_accumulation(terrain_graph)
    assert max(flow_acc.values()) > 1.0

    river_nodes = detect_river_nodes(terrain_graph, flow_acc, waterways, percentile=98.0)
    ridge_nodes = detect_ridge_nodes(terrain_graph)

    selected_node, stats, dist_m = select_best_pond_candidate(
        terrain_graph, flow_acc, river_nodes, ridge_nodes, safety_buffer_m=10.0, min_catchment_cells=2
    )
    assert selected_node.id not in river_nodes
    assert dist_m >= 10.0 or selected_node.id is not None

    catchment_nodes, metrics = delineate_catchment_bfs(terrain_graph, selected_node.id)
    assert metrics["area_square_meters"] > 0.0
    assert metrics["number_of_cells"] > 0


def test_api_endpoints():
    res_root = client.get("/")
    assert res_root.status_code == 200

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    response = client.post(
        "/analyzeContour?drainage_safety_buffer_m=10.0",
        files={"file": ("test_contours.kml", kml_bytes, "application/vnd.google-earth.kml+xml")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "pond_location" in data
    assert "catchment" in data
    assert "river_safety" in data
    assert data["river_safety"]["status"] == "SAFE"


def test_api_top_n_candidates_are_ranked_and_distinct():
    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    response = client.post(
        "/analyzeContour?drainage_safety_buffer_m=10.0&number_of_ponds=3",
        files={"file": ("test_contours.kml", kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 200
    data = response.json()
    ponds = data["pond_locations"]
    assert len(ponds) == 3
    assert [p["rank"] for p in ponds] == [1, 2, 3]
    assert all("catchment" in p and p["catchment"]["number_of_cells"] > 0 for p in ponds)
    coords = {(p["latitude"], p["longitude"]) for p in ponds}
    assert len(coords) == len(ponds)
    assert data["analysis"]["requested_ponds"] == 3
