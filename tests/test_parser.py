"""
Synthetic KML helper and contour parser tests.
"""
import pytest
import zipfile
import io
from contour_parser import parse_kml_or_kmz, KMLParseError


def create_synthetic_kml(elevations=[100.0, 105.0, 110.0, 115.0, 120.0]) -> bytes:
    """Generate a clean synthetic KML byte stream for testing."""
    placemarks = []
    for idx, ele in enumerate(elevations):
        # Create concentric square contour rings (outer = higher)
        offset = idx * 0.001
        coords = f"""
        {81.0 - offset},{21.0 - offset}
        {81.1 + offset},{21.0 - offset}
        {81.1 + offset},{21.1 + offset}
        {81.0 - offset},{21.1 + offset}
        {81.0 - offset},{21.0 - offset}
        """
        pm = f"""
        <Placemark>
            <name>{ele}</name>
            <LineString>
                <coordinates>{coords.strip()}</coordinates>
            </LineString>
        </Placemark>
        """
        placemarks.append(pm)

    kml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
            {''.join(placemarks)}
        </Document>
    </kml>
    """
    return kml_str.encode('utf-8')


def test_parse_valid_kml():
    kml_bytes = create_synthetic_kml()
    contours, bounds, waterways = parse_kml_or_kmz(kml_bytes, "test.kml")
    assert len(contours) == 5
    assert contours[0]["elevation"] == 100.0
    assert contours[-1]["elevation"] == 120.0
    assert bounds["min_lon"] < bounds["max_lon"]


def test_parse_kmz():
    kml_bytes = create_synthetic_kml()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml_bytes)
    kmz_bytes = buf.getvalue()

    contours, bounds, waterways = parse_kml_or_kmz(kmz_bytes, "test.kmz")
    assert len(contours) == 5
    assert contours[0]["elevation"] == 100.0


def test_parse_invalid_xml():
    with pytest.raises(KMLParseError):
        parse_kml_or_kmz(b"This is not valid XML data", "invalid.kml")


def test_parse_no_elevations():
    bad_kml = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
            <Placemark>
                <name>Not a number</name>
                <LineString><coordinates>81.0,21.0 81.1,21.1</coordinates></LineString>
            </Placemark>
        </Document>
    </kml>
    """.encode('utf-8')
    with pytest.raises(KMLParseError):
        parse_kml_or_kmz(bad_kml, "bad.kml")
