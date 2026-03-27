import pytest

from app.geo import bounding_box_from_center, haversine_miles


def test_haversine_known_short_distance():
    lat, lon = 40.0, -74.0
    dlat = 1.0 / 69.172
    d = haversine_miles(lat, lon, lat + dlat, lon)
    assert abs(d - 1.0) < 0.02


def test_bounding_box_contains_center():
    bbox = bounding_box_from_center(37.62, -122.38, 1.0)
    assert bbox.min_lat < 37.62 < bbox.max_lat
    assert bbox.min_lon < -122.38 < bbox.max_lon


def test_bounding_box_invalid_radius():
    with pytest.raises(ValueError):
        bounding_box_from_center(0, 0, 0)
