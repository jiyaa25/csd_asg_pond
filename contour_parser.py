import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import LineString


class KMLParseError(Exception):
    """Raised when a KML/KMZ file cannot provide usable contour data."""


def parse_kml_or_kmz(
    file_bytes: bytes, filename: str
) -> Tuple[List[Dict[str, Any]], Dict[str, float], List[Dict[str, Any]]]:
    """Parse KML/KMZ and return contours, WGS84 bounds and explicit waterways."""
    name = filename.lower()
    is_kmz = name.endswith(".kmz") or file_bytes[:4] == b"PK\x03\x04"

    if is_kmz:
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                kml_names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
                if not kml_names:
                    raise KMLParseError("Invalid KMZ archive: no KML file was found inside it.")
                target = next((n for n in kml_names if n.lower().endswith("/doc.kml") or n.lower() == "doc.kml"), kml_names[0])
                return parse_kml_content(archive.read(target))
        except zipfile.BadZipFile:
            raise KMLParseError("Invalid KMZ archive: the ZIP container is corrupted.")

    return parse_kml_content(file_bytes)


def parse_kml_content(kml_bytes: bytes) -> Tuple[List[Dict[str, Any]], Dict[str, float], List[Dict[str, Any]]]:
    try:
        root = ET.fromstring(kml_bytes)
    except ET.ParseError as exc:
        raise KMLParseError(f"Invalid KML XML: {exc}") from exc

    # Use local-name matching so common KML namespace variants are accepted.
    placemarks = [el for el in root.iter() if local_name(el.tag) == "Placemark"]
    if not placemarks:
        raise KMLParseError("No <Placemark> elements found in the KML file.")

    contours: List[Dict[str, Any]] = []
    waterways: List[Dict[str, Any]] = []
    all_lons: List[float] = []
    all_lats: List[float] = []

    water_keywords = ("river", "stream", "drain", "water", "canal", "channel", "creek")

    for placemark in placemarks:
        name = child_text(placemark, "name")
        description = child_text(placemark, "description")
        combined = f"{name} {description}".lower()
        is_water = any(word in combined for word in water_keywords)

        elevation = extract_elevation(placemark, name, description)
        for line, coords in extract_linestrings(placemark):
            if is_water:
                waterways.append({"name": name or "waterway", "geometry": line, "coords": coords})

            if elevation is not None:
                contours.append({
                    "elevation": float(elevation),
                    "geometry": line,
                    "coords": coords,
                    "name": name,
                })
                all_lons.extend(p[0] for p in coords)
                all_lats.extend(p[1] for p in coords)

    if not contours:
        raise KMLParseError(
            "No contour lines with elevation information were found. "
            "Elevation was checked in Placemark name/description, ExtendedData and 3D coordinates."
        )

    bounds = {
        "min_lon": float(min(all_lons)),
        "max_lon": float(max(all_lons)),
        "min_lat": float(min(all_lats)),
        "max_lat": float(max(all_lats)),
    }
    if bounds["min_lon"] == bounds["max_lon"] or bounds["min_lat"] == bounds["max_lat"]:
        raise KMLParseError("Insufficient terrain extent: contour coordinates do not form an area.")

    return contours, bounds, waterways


def extract_elevation(placemark: ET.Element, name: str, description: str) -> Optional[float]:
    """Find an elevation from common KML metadata patterns."""
    # 1. Numeric Placemark name, e.g. <name>277.0</name> or "Contour 277m".
    value = parse_elevation_text(name)
    if value is not None:
        return value

    # 2. Description, preferring a value next to an elevation-like keyword.
    value = parse_elevation_text(description)
    if value is not None:
        return value

    # 3. ExtendedData/Data/SimpleData values.
    for el in placemark.iter():
        tag = local_name(el.tag).lower()
        if tag not in {"simpledata", "data"}:
            continue
        key = (el.attrib.get("name") or "").lower()
        if any(k in key for k in ("elevation", "elev", "height", "altitude", "level", "contour")):
            value = parse_number(el.text or "")
            if value is not None:
                return value

    # 4. A 3D coordinate z value when present.
    for coord_el in placemark.iter():
        if local_name(coord_el.tag).lower() != "coordinates" or not coord_el.text:
            continue
        for token in coord_el.text.split():
            parts = token.split(",")
            if len(parts) >= 3:
                z = parse_number(parts[2])
                if z is not None:
                    return z

    return None


def parse_elevation_text(text: str) -> Optional[float]:
    if not text:
        return None
    stripped = text.strip()
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", stripped):
        return float(stripped)

    match = re.search(
        r"(?:elev(?:ation)?|height|altitude|level|contour)\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*(?:m|meters?)?",
        stripped,
        re.IGNORECASE,
    )
    if match:
        return float(match.group(1))
    return None


def parse_number(text: str) -> Optional[float]:
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return None


def extract_linestrings(placemark: ET.Element) -> List[Tuple[LineString, List[Tuple[float, float]]]]:
    results = []
    for element in placemark.iter():
        if local_name(element.tag) != "LineString":
            continue
        coord_el = next((c for c in element.iter() if local_name(c.tag) == "coordinates"), None)
        if coord_el is None or not coord_el.text:
            continue

        coords: List[Tuple[float, float]] = []
        for token in coord_el.text.split():
            parts = token.split(",")
            if len(parts) < 2:
                continue
            try:
                coords.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue

        if len(coords) >= 2:
            line = LineString(coords)
            if not line.is_empty and line.length > 0:
                results.append((line, coords))
    return results


def child_text(parent: ET.Element, name: str) -> str:
    for child in parent:
        if local_name(child.tag).lower() == name.lower():
            return (child.text or "").strip()
    return ""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
