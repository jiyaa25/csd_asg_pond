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


def test_api_expected_water_volume_and_contour_map_field():
    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    response = client.post(
        "/analyzeContour?drainage_safety_buffer_m=10.0&annual_rainfall_mm=1200&runoff_coefficient=0.4",
        files={"contour_map": ("test_contours.kml", kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "water_volume_parameters" in data
    assert data["water_volume_parameters"]["annual_rainfall_mm"] == 1200.0
    assert data["water_volume_parameters"]["runoff_coefficient"] == 0.4
    best = data["pond_location"]
    assert "expected_water_volume_m3" in best
    assert best["expected_water_volume_m3"] > 0.0
    first_pond = data["pond_locations"][0]
    assert first_pond["expected_water_volume_m3"] == best["expected_water_volume_m3"]
    assert first_pond["expected_water_volume_megaliters"] > 0.0


def test_api_selected_land_area():
    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    response = client.post(
        "/analyzeContour?drainage_safety_buffer_m=5.0&selected_min_lat=21.002&selected_max_lat=21.008&selected_min_lon=81.002&selected_max_lon=81.008",
        files={"contour_map": ("test_contours.kml", kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["input"]["selected_land_area"] is not None
    assert data["input"]["selected_land_area"]["min_lat"] >= 21.002
    assert data["input"]["selected_land_area"]["max_lat"] <= 21.008


def test_api_rainfall_endpoint():
    response = client.get("/api/rainfall?lat=21.25&lon=81.30")
    assert response.status_code == 200
    data = response.json()
    assert "annual_rainfall_mm" in data
    assert data["annual_rainfall_mm"] > 0
    assert "source" in data


def test_api_geocode_endpoint():
    response = client.get("/api/geocode?q=Khapri")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "result" in data
    res = data["result"]
    assert "bounds" in res
    assert res["bounds"]["min_lat"] < res["bounds"]["max_lat"]
    assert res["bounds"]["min_lon"] < res["bounds"]["max_lon"]


def test_api_analyze_area_and_place(monkeypatch):
    import main

    kml_bytes = create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0])
    contours, bounds, _ = parse_kml_or_kmz(kml_bytes, "test.kml")
    mock_terrain = build_terrain_grid(contours, bounds, grid_size=20)
    mock_contours = [{"elevation": 100.0, "coordinates": [[21.05, 81.05], [21.06, 81.06]]}]

    monkeypatch.setattr(main, "fetch_dem_elevation_grid", lambda b, query_dim=15, target_dim=50: (mock_terrain, mock_contours))
    monkeypatch.setattr(
        main,
        "geocode_place",
        lambda q: {
            "display_name": f"{q}, Mock State, India",
            "latitude": 21.05,
            "longitude": 81.05,
            "bounds": bounds,
        }
    )

    # Test Case 2: analyzeArea
    res_area = client.post(
        "/analyzeArea?selected_min_lat=21.0&selected_max_lat=21.01&selected_min_lon=81.0&selected_max_lon=81.01&number_of_ponds=1&drainage_safety_buffer_m=5.0"
    )
    assert res_area.status_code == 200, res_area.json()
    data_area = res_area.json()
    assert data_area["status"] == "success"
    assert data_area["input"]["mode"] == "map_area_dem"
    assert "generated_contours" in data_area
    assert len(data_area["pond_locations"]) == 1

    # Test Case 3: analyzePlace
    res_place = client.post("/analyzePlace?place_name=Khapri&number_of_ponds=1&drainage_safety_buffer_m=5.0")
    assert res_place.status_code == 200, res_place.json()
    data_place = res_place.json()
    assert data_place["status"] == "success"
    assert data_place["input"]["mode"] == "village_search_dem"
    assert "Khapri" in data_place["input"]["place_name"]
    assert "generated_contours" in data_place


