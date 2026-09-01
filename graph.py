import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from terrain import TerrainGrid


@dataclass
class Edge:
    to_node: int
    distance_m: float
    elevation_difference_m: float
    slope: float


@dataclass
class TerrainNode:
    id: int
    row: int
    col: int
    lat: float
    lon: float
    elevation: float
    neighbours: List[Edge] = field(default_factory=list)
    downstream_node_id: Optional[int] = None
    in_edges: List[int] = field(default_factory=list)


class TerrainGraph:
    def __init__(self, nodes: Dict[int, TerrainNode], rows: int, cols: int, cell_size_m: float):
        self.nodes = nodes
        self.rows = rows
        self.cols = cols
        self.cell_size_m = cell_size_m
        self.grid_map = {(n.row, n.col): n.id for n in nodes.values()}


def haversine_distance_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


NEIGHBOUR_OFFSETS = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
]


def build_terrain_graph(terrain_grid: TerrainGrid) -> TerrainGraph:
    nodes: Dict[int, TerrainNode] = {}
    node_id = 0

    for row in range(terrain_grid.rows):
        for col in range(terrain_grid.cols):
            lat, lon, elevation = terrain_grid.get_cell_coords(row, col)
            nodes[node_id] = TerrainNode(node_id, row, col, lat, lon, elevation)
            node_id += 1

    grid_map = {(n.row, n.col): n.id for n in nodes.values()}

    # Build the full 8-neighbour graph and store physical edge information.
    for node in nodes.values():
        for dr, dc in NEIGHBOUR_OFFSETS:
            key = (node.row + dr, node.col + dc)
            if key not in grid_map:
                continue
            neighbour = nodes[grid_map[key]]
            distance = haversine_distance_m(node.lat, node.lon, neighbour.lat, neighbour.lon)
            diff = node.elevation - neighbour.elevation
            slope = diff / distance if distance else 0.0
            node.neighbours.append(Edge(neighbour.id, distance, diff, slope))

        # D8 routing: select the neighbour with the steepest positive downhill slope.
        downhill = [edge for edge in node.neighbours if edge.slope > 0]
        if downhill:
            best = max(downhill, key=lambda edge: edge.slope)
            node.downstream_node_id = best.to_node
            nodes[best.to_node].in_edges.append(node.id)

    # Cell width at the centre latitude is used only as a convenient grid-spacing reference.
    if terrain_grid.cols > 1:
        mid = terrain_grid.rows // 2
        cell_size = haversine_distance_m(
            float(terrain_grid.lats[mid]), float(terrain_grid.lons[0]),
            float(terrain_grid.lats[mid]), float(terrain_grid.lons[1])
        )
    else:
        cell_size = 0.0

    return TerrainGraph(nodes, terrain_grid.rows, terrain_grid.cols, cell_size)
