from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.spatial import cKDTree


class TerrainGrid:
    """Regular WGS84 grid containing an interpolated elevation surface."""

    def __init__(self, grid_elevation, lons, lats, min_elevation, max_elevation):
        self.grid = grid_elevation
        self.lons = lons
        self.lats = lats
        self.rows, self.cols = grid_elevation.shape
        self.min_elevation = float(min_elevation)
        self.max_elevation = float(max_elevation)

    def get_cell_coords(self, row: int, col: int) -> Tuple[float, float, float]:
        return float(self.lats[row]), float(self.lons[col]), float(self.grid[row, col])


def build_terrain_grid(
    contours: List[Dict[str, Any]], bounds: Dict[str, float], grid_size: int = 120, idw_k: int = 12
) -> TerrainGrid:
    """Create a terrain surface using simple inverse-distance weighting (IDW)."""
    if len(contours) < 3:
        raise ValueError("Insufficient terrain information: at least 3 contours are required.")

    # Contour vertices are already dense in the supplied sample. Keeping the
    # original vertices makes the method simple and preserves the measured contour elevations.
    xs, ys, zs = [], [], []
    for contour in contours:
        z = float(contour["elevation"])
        for lon, lat in contour["coords"]:
            xs.append(lon)
            ys.append(lat)
            zs.append(z)

    points = np.column_stack((xs, ys))
    values = np.asarray(zs, dtype=float)
    if len(points) < 3 or np.all(values == values[0]):
        raise ValueError("Insufficient terrain information: contour elevations are not usable.")

    lons = np.linspace(bounds["min_lon"], bounds["max_lon"], grid_size)
    lats = np.linspace(bounds["max_lat"], bounds["min_lat"], grid_size)
    grid_lon, grid_lat = np.meshgrid(lons, lats)
    targets = np.column_stack((grid_lon.ravel(), grid_lat.ravel()))

    tree = cKDTree(points)
    k = min(idw_k, len(points))
    distances, indices = tree.query(targets, k=k)
    if k == 1:
        distances = distances[:, None]
        indices = indices[:, None]

    weights = 1.0 / np.maximum(distances, 1e-12) ** 2
    weights /= weights.sum(axis=1, keepdims=True)
    interpolated = np.sum(values[indices] * weights, axis=1).reshape(grid_lon.shape)

    return TerrainGrid(interpolated, lons, lats, values.min(), values.max())
