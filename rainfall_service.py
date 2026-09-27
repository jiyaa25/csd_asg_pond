import json
import urllib.request
from typing import Dict, Any


def fetch_annual_rainfall(lat: float, lon: float) -> Dict[str, Any]:
    """Fetch annual rainfall (mm) for coordinates using Open-Meteo with NASA POWER fallback."""
    # 1. Try Open-Meteo API
    open_meteo_url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={round(lat, 4)}&longitude={round(lon, 4)}&"
        f"start_date=2023-01-01&end_date=2023-12-31&daily=precipitation_sum&timezone=auto"
    )
    try:
        req = urllib.request.Request(open_meteo_url, headers={"User-Agent": "PondCatchmentAnalyzer/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if "daily" in data and "precipitation_sum" in data["daily"]:
                precip = data["daily"]["precipitation_sum"]
                total = round(sum(p for p in precip if p is not None), 1)
                if total > 0:
                    return {
                        "annual_rainfall_mm": total,
                        "source": "Open-Meteo Archive API (2023 Annual Sum)",
                        "latitude": round(lat, 4),
                        "longitude": round(lon, 4),
                        "status": "success",
                    }
    except Exception:
        pass

    # 2. Try NASA POWER Global Climatology API (Free, high-accuracy agricultural hydrology)
    nasa_url = (
        f"https://power.larc.nasa.gov/api/temporal/climatology/point?"
        f"parameters=PRECTOTCORR&community=AG&longitude={round(lon, 4)}&latitude={round(lat, 4)}&format=JSON"
    )
    try:
        req = urllib.request.Request(nasa_url, headers={"User-Agent": "PondCatchmentAnalyzer/2.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            ann_rate = data["properties"]["parameter"]["PRECTOTCORR"]["ANN"]
            # Convert mm/day climatological average to annual total (mm/year)
            annual_total = round(float(ann_rate) * 365.25, 1)
            return {
                "annual_rainfall_mm": annual_total,
                "source": "NASA POWER Climatology API (30-year agro-climatological average)",
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "status": "success",
            }
    except Exception:
        pass

    # 3. Default fallback for region
    return {
        "annual_rainfall_mm": 1200.0,
        "source": "Regional Climatological Standard (Central India default)",
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "status": "fallback",
    }
