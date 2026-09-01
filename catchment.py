import math
from collections import deque
from typing import Any, Dict, List, Set, Tuple

import numpy as np
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point

from graph import TerrainGraph, TerrainNode, haversine_distance_m


def calculate_flow_accumulation(graph: TerrainGraph) -> Dict[int, float]:
    """Each cell contributes one unit; contributions move along D8 downstream edges."""
    remaining_inputs = {node_id: 0 for node_id in graph.nodes}
    for node in graph.nodes.values():
        if node.downstream_node_id is not None:
            remaining_inputs[node.downstream_node_id] += 1

    accumulation = {node_id: 1.0 for node_id in graph.nodes}
    queue = deque(node_id for node_id, degree in remaining_inputs.items() if degree == 0)

    processed = 0
    while queue:
        current = queue.popleft()
        processed += 1
        downstream = graph.nodes[current].downstream_node_id
        if downstream is None:
            continue
        accumulation[downstream] += accumulation[current]
        remaining_inputs[downstream] -= 1
        if remaining_inputs[downstream] == 0:
            queue.append(downstream)

    if processed < len(graph.nodes):
        for node_id, degree in remaining_inputs.items():
            if degree > 0:
                accumulation[node_id] = max(accumulation[node_id], 1.0)
    return accumulation


def detect_river_nodes(
    graph: TerrainGraph,
    flow_accumulation: Dict[int, float],
    explicit_waterways: List[Dict[str, Any]],
    percentile: float = 98.5,
) -> Set[int]:
    """Detect likely channel cells from explicit water features and high flow accumulation."""
    river_nodes: Set[int] = set()
    values = np.asarray(list(flow_accumulation.values()), dtype=float)
    threshold = float(np.percentile(values, percentile)) if values.size else float("inf")

    for node_id, acc in flow_accumulation.items():
        if acc >= threshold and acc >= 10:
            river_nodes.add(node_id)

    for node_id, node in graph.nodes.items():
        point = Point(node.lon, node.lat)
        for waterway in explicit_waterways:
            if waterway["geometry"].distance(point) <= 0.00045:
                river_nodes.add(node_id)
                break
    return river_nodes


def detect_ridge_nodes(graph: TerrainGraph, elevation_percentile: float = 90.0) -> Set[int]:
    """Flag high local maxima as simple ridge candidates."""
    elevations = np.asarray([n.elevation for n in graph.nodes.values()])
    high_threshold = float(np.percentile(elevations, elevation_percentile))
    ridges: Set[int] = set()

    for node in graph.nodes.values():
        if node.elevation < high_threshold:
            continue
        neighbour_elevations = [graph.nodes[edge.to_node].elevation for edge in node.neighbours]
        if neighbour_elevations and node.elevation >= max(neighbour_elevations):
            ridges.add(node.id)
    return ridges


def _cell_area_m2(graph: TerrainGraph, node: TerrainNode) -> float:
    """Approximate each geographic grid cell area from local north/east spacing."""
    r, c = node.row, node.col

    if 0 < r < graph.rows - 1:
        north = graph.nodes[graph.grid_map[(r - 1, c)]]
        south = graph.nodes[graph.grid_map[(r + 1, c)]]
        height = (
            haversine_distance_m(node.lat, node.lon, north.lat, north.lon)
            + haversine_distance_m(node.lat, node.lon, south.lat, south.lon)
        ) / 2.0
    elif graph.rows > 1:
        other = graph.nodes[graph.grid_map[(r + 1 if r == 0 else r - 1, c)]]
        height = haversine_distance_m(node.lat, node.lon, other.lat, other.lon)
    else:
        height = 1.0

    if 0 < c < graph.cols - 1:
        west = graph.nodes[graph.grid_map[(r, c - 1)]]
        east = graph.nodes[graph.grid_map[(r, c + 1)]]
        width = (
            haversine_distance_m(node.lat, node.lon, west.lat, west.lon)
            + haversine_distance_m(node.lat, node.lon, east.lat, east.lon)
        ) / 2.0
    elif graph.cols > 1:
        other = graph.nodes[graph.grid_map[(r, c + 1 if c == 0 else c - 1)]]
        width = haversine_distance_m(node.lat, node.lon, other.lat, other.lon)
    else:
        width = 1.0

    return max(1.0, height * width)


def _cell_polygon(graph: TerrainGraph, node: TerrainNode) -> List[List[float]]:
    """Return the geographic polygon of one grid cell as [lat, lon] pairs."""
    r, c = node.row, node.col

    if graph.rows == 1:
        lat_step = 0.00001
    elif r == 0:
        lat_step = abs(node.lat - graph.nodes[graph.grid_map[(r + 1, c)]].lat)
    else:
        lat_step = abs(node.lat - graph.nodes[graph.grid_map[(r - 1, c)]].lat)
    if graph.cols == 1:
        lon_step = 0.00001
    elif c == 0:
        lon_step = abs(node.lon - graph.nodes[graph.grid_map[(r, c + 1)]].lon)
    else:
        lon_step = abs(node.lon - graph.nodes[graph.grid_map[(r, c - 1)]].lon)

    half_lat = lat_step / 2.0
    half_lon = lon_step / 2.0
    return [
        [node.lat - half_lat, node.lon - half_lon],
        [node.lat - half_lat, node.lon + half_lon],
        [node.lat + half_lat, node.lon + half_lon],
        [node.lat + half_lat, node.lon - half_lon],
        [node.lat - half_lat, node.lon - half_lon],
    ]


def delineate_catchment_bfs(graph: TerrainGraph, pond_node_id: int) -> Tuple[Set[int], Dict[str, Any]]:
    """Traverse reverse D8 flow edges to collect every cell draining to the pond."""
    catchment: Set[int] = {pond_node_id}
    queue = deque([pond_node_id])

    while queue:
        current = queue.popleft()
        for upstream in graph.nodes[current].in_edges:
            if upstream not in catchment:
                catchment.add(upstream)
                queue.append(upstream)

    area = sum(_cell_area_m2(graph, graph.nodes[node_id]) for node_id in catchment)
    elevations = [graph.nodes[node_id].elevation for node_id in catchment]
    cells = [_cell_polygon(graph, graph.nodes[node_id]) for node_id in sorted(catchment)]
    metrics = {
        "area_square_meters": round(area, 2),
        "area_hectares": round(area / 10000.0, 3),
        "number_of_cells": len(catchment),
        "min_elevation_m": round(float(min(elevations)), 2),
        "max_elevation_m": round(float(max(elevations)), 2),
        "mean_elevation_m": round(float(np.mean(elevations)), 2),
        "cells": cells,
    }
    return catchment, metrics


def _valley_score(graph: TerrainGraph, node: TerrainNode) -> float:
    nearby = [graph.nodes[edge.to_node].elevation for edge in node.neighbours]
    if not nearby:
        return 0.0
    relief = max(0.0, float(np.mean(nearby)) - node.elevation)
    return min(35.0, relief * 12.0)


def _candidate_pool(
    graph: TerrainGraph,
    flow_accumulation: Dict[int, float],
    river_nodes: Set[int],
    ridge_nodes: Set[int],
    safety_buffer_m: float,
    min_catchment_cells: int,
) -> Tuple[List[Tuple[float, TerrainNode, float]], Dict[str, Any]]:
    river_mask = np.zeros((graph.rows, graph.cols), dtype=bool)
    for node_id in river_nodes:
        n = graph.nodes[node_id]
        river_mask[n.row, n.col] = True

    if river_nodes:
        distance_to_river = distance_transform_edt(~river_mask) * graph.cell_size_m
    else:
        distance_to_river = np.full((graph.rows, graph.cols), np.inf)

    max_acc = max(flow_accumulation.values()) if flow_accumulation else 1.0
    min_ele = min(n.elevation for n in graph.nodes.values())
    max_ele = max(n.elevation for n in graph.nodes.values())
    ele_range = max(max_ele - min_ele, 1e-9)

    candidates: List[Tuple[float, TerrainNode, float]] = []
    stats = {
        "candidate_count": 0,
        "valid_candidate_count": 0,
        "river_candidates_removed": 0,
        "ridge_candidates_removed": 0,
        "boundary_candidates_removed": 0,
        "insufficient_catchment_removed": 0,
        "separation_candidates_skipped": 0,
    }
    margin = 2

    for node_id, node in graph.nodes.items():
        stats["candidate_count"] += 1
        if node.row < margin or node.row >= graph.rows - margin or node.col < margin or node.col >= graph.cols - margin:
            stats["boundary_candidates_removed"] += 1
            continue
        if flow_accumulation[node_id] < min_catchment_cells:
            stats["insufficient_catchment_removed"] += 1
            continue
        if node_id in river_nodes or distance_to_river[node.row, node.col] < safety_buffer_m:
            stats["river_candidates_removed"] += 1
            continue
        if node_id in ridge_nodes:
            stats["ridge_candidates_removed"] += 1
            continue

        low_score = (max_ele - node.elevation) / ele_range * 15.0
        catchment_score = math.log1p(flow_accumulation[node_id]) / math.log1p(max_acc) * 45.0
        valley_score = _valley_score(graph, node)
        total = low_score + catchment_score + valley_score
        candidates.append((total, node, float(distance_to_river[node.row, node.col])))

    candidates.sort(key=lambda x: (-x[0], x[1].id))
    stats["valid_candidate_count"] = len(candidates)
    return candidates, stats


def select_top_pond_candidates(
    graph: TerrainGraph,
    flow_accumulation: Dict[int, float],
    river_nodes: Set[int],
    ridge_nodes: Set[int],
    safety_buffer_m: float = 30.0,
    min_catchment_cells: int = 10,
    number_of_ponds: int = 5,
    min_separation_cells: int = None,
) -> Tuple[List[Tuple[TerrainNode, float, float]], Dict[str, Any]]:
    """Return the highest-scoring spatially separated terrain-derived pond candidates."""
    if number_of_ponds < 1:
        raise ValueError("number_of_ponds must be at least 1.")

    candidates, stats = _candidate_pool(
        graph, flow_accumulation, river_nodes, ridge_nodes, safety_buffer_m, min_catchment_cells
    )
    if not candidates:
        raise ValueError("No suitable pond candidate was found after river, ridge and catchment filtering.")

    # A small, deterministic separation rule: about 5% of the smaller grid dimension.
    if min_separation_cells is None:
        min_separation_cells = max(3, round(min(graph.rows, graph.cols) * 0.05))

    selected: List[Tuple[TerrainNode, float, float]] = []
    separation_m = max(graph.cell_size_m, 1.0) * min_separation_cells
    for score, node, distance in candidates:
        too_close = any(
            math.hypot(node.row - chosen.row, node.col - chosen.col) < min_separation_cells
            for chosen, _, _ in selected
        )
        if too_close:
            stats["separation_candidates_skipped"] += 1
            continue
        selected.append((node, score, distance))
        if len(selected) >= number_of_ponds:
            break

    if not selected:
        raise ValueError("No suitable pond candidate was found after spatial separation filtering.")

    stats["selected_candidate_count"] = len(selected)
    stats["requested_ponds"] = number_of_ponds
    stats["minimum_separation_cells"] = min_separation_cells
    stats["minimum_separation_meters"] = round(separation_m, 2)
    stats["selected_score"] = round(float(selected[0][1]), 2)
    return selected, stats


def select_best_pond_candidate(
    graph: TerrainGraph,
    flow_accumulation: Dict[int, float],
    river_nodes: Set[int],
    ridge_nodes: Set[int],
    safety_buffer_m: float = 30.0,
    min_catchment_cells: int = 10,
) -> Tuple[TerrainNode, Dict[str, Any], float]:
    """Backward-compatible wrapper returning only the best candidate."""
    selected, stats = select_top_pond_candidates(
        graph,
        flow_accumulation,
        river_nodes,
        ridge_nodes,
        safety_buffer_m=safety_buffer_m,
        min_catchment_cells=min_catchment_cells,
        number_of_ponds=1,
    )
    pond, score, distance = selected[0]
    stats["selected_score"] = round(float(score), 2)
    return pond, stats, distance
