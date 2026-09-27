import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

CACHE_DB_PATH = Path(__file__).resolve().parent / "cache.db"
DEFAULT_TTL = 86400  # 24 hours in seconds


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(CACHE_DB_PATH), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_cache_db():
    """Initialize the SQLite cache table and index."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_store (
                cache_key TEXT PRIMARY KEY,
                category TEXT,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache_store(expires_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON cache_store(category)")
        conn.commit()


# Initialize on import
try:
    init_cache_db()
except Exception as e:
    print(f"Cache init warning: {e}")


def get_cache(cache_key: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Retrieve an item from cache if not expired.
    Returns (data, meta) or None if cache miss.
    """
    now = time.time()
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                "SELECT payload_json, created_at, expires_at FROM cache_store WHERE cache_key = ?",
                (cache_key,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            payload_json, created_at, expires_at = row
            if now > expires_at:
                # Expired, clean up
                conn.execute("DELETE FROM cache_store WHERE cache_key = ?", (cache_key,))
                conn.commit()
                return None

            data = json.loads(payload_json)
            meta = {
                "hit": True,
                "cache_key": cache_key,
                "age_seconds": round(now - created_at, 1),
                "expires_in_seconds": round(expires_at - now, 1),
            }
            return data, meta
    except Exception as e:
        print(f"Cache read error: {e}")
        return None


def set_cache(
    cache_key: str,
    data: Any,
    ttl_seconds: int = DEFAULT_TTL,
    category: str = "general"
) -> bool:
    """Store an item in the SQLite cache."""
    now = time.time()
    expires_at = now + ttl_seconds
    try:
        payload_json = json.dumps(data)
        with _get_connection() as conn:
            conn.execute("""
                INSERT INTO cache_store (cache_key, category, payload_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    category=excluded.category,
                    payload_json=excluded.payload_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at
            """, (cache_key, category, payload_json, now, expires_at))
            conn.commit()
        return True
    except Exception as e:
        print(f"Cache write error: {e}")
        return False


def snap_coordinate(val: float, resolution: float = 0.002) -> float:
    """Snap coordinate to standard grid resolution (~200 meters)."""
    return round(round(val / resolution) * resolution, 6)


def normalize_text(text: str) -> str:
    """Normalize village/place name for deterministic cache keys."""
    t = (text or "").strip().lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t


def generate_kml_cache_key(
    file_bytes: bytes,
    buffer_m: float,
    number_of_ponds: int,
    rainfall_mm: Optional[float],
    runoff_c: float,
    selected_bounds: Optional[Dict[str, float]] = None
) -> str:
    """Generate SHA-256 content-based cache key for KML/KMZ upload."""
    h = hashlib.sha256(file_bytes).hexdigest()[:16]
    rain = round(float(rainfall_mm), 1) if rainfall_mm else "auto"
    bounds_str = "full"
    if selected_bounds:
        b = selected_bounds
        bounds_str = f"{snap_coordinate(b['minLat'])}:{snap_coordinate(b['maxLat'])}:{snap_coordinate(b['minLon'])}:{snap_coordinate(b['maxLon'])}"
    return f"kml:{h}:b{round(buffer_m, 1)}:p{number_of_ponds}:r{rain}:c{round(runoff_c, 2)}:{bounds_str}"


def generate_area_cache_key(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    buffer_m: float,
    number_of_ponds: int,
    rainfall_mm: Optional[float],
    runoff_c: float
) -> str:
    """Generate spatial quantized cache key for map area DEM queries."""
    s_min_lat = snap_coordinate(min(min_lat, max_lat))
    s_max_lat = snap_coordinate(max(min_lat, max_lat))
    s_min_lon = snap_coordinate(min(min_lon, max_lon))
    s_max_lon = snap_coordinate(max(min_lon, max_lon))
    rain = round(float(rainfall_mm), 1) if rainfall_mm else "auto"
    return f"area:{s_min_lat}:{s_max_lat}:{s_min_lon}:{s_max_lon}:b{round(buffer_m, 1)}:p{number_of_ponds}:r{rain}:c{round(runoff_c, 2)}"


def generate_place_cache_key(
    place_name: str,
    buffer_m: float,
    number_of_ponds: int,
    rainfall_mm: Optional[float],
    runoff_c: float
) -> str:
    """Generate normalized place name cache key for village search."""
    norm = normalize_text(place_name)
    rain = round(float(rainfall_mm), 1) if rainfall_mm else "auto"
    return f"place:{norm}:b{round(buffer_m, 1)}:p{number_of_ponds}:r{rain}:c{round(runoff_c, 2)}"


def get_cache_stats() -> Dict[str, Any]:
    """Return cache health, active count, and category breakdown."""
    now = time.time()
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cache_store WHERE expires_at > ?", (now,))
            active_count = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM cache_store WHERE expires_at <= ?", (now,))
            expired_count = cursor.fetchone()[0]

            cursor = conn.execute("""
                SELECT category, COUNT(*) FROM cache_store WHERE expires_at > ? GROUP BY category
            """, (now,))
            breakdown = dict(cursor.fetchall())

            return {
                "status": "healthy",
                "active_entries": active_count,
                "expired_entries": expired_count,
                "breakdown": breakdown,
                "ttl_hours": DEFAULT_TTL / 3600
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}
