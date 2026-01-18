"""Tests for meshterm.formatting module - pure functions."""

import time
from unittest.mock import patch

import pytest

from meshterm.formatting import (
    Colors,
    JsonColors,
    get_portnum_name,
    format_node_id,
    format_time_ago,
    haversine_distance,
    format_distance,
    get_node_position,
    PORTNUM_MAP,
)


class TestFormatNodeId:
    """Tests for format_node_id function."""

    def test_format_integer_node_id(self):
        """Integer node IDs should be formatted as !hex."""
        assert format_node_id(0x12345678) == "!12345678"

    def test_format_zero_node_id(self):
        """Zero should be formatted with leading zeros."""
        assert format_node_id(0) == "!00000000"

    def test_format_max_node_id(self):
        """Maximum 32-bit value should be formatted correctly."""
        assert format_node_id(0xFFFFFFFF) == "!ffffffff"

    def test_format_small_node_id(self):
        """Small numbers should have leading zeros."""
        assert format_node_id(0xFF) == "!000000ff"
        assert format_node_id(0x1) == "!00000001"

    def test_format_string_passthrough(self):
        """String node IDs should pass through unchanged."""
        assert format_node_id("!12345678") == "!12345678"
        assert format_node_id("^all") == "^all"
        assert format_node_id("some_string") == "some_string"

    def test_format_already_formatted(self):
        """Already formatted IDs should remain unchanged."""
        assert format_node_id("!aabbccdd") == "!aabbccdd"


class TestFormatTimeAgo:
    """Tests for format_time_ago function."""

    def test_none_timestamp(self):
        """None timestamp should return '?'."""
        assert format_time_ago(None) == "?"

    def test_zero_timestamp(self):
        """Zero timestamp (falsy) should return '?'."""
        assert format_time_ago(0) == "?"

    def test_future_timestamp(self):
        """Future timestamps should return 'now'."""
        future = int(time.time()) + 100
        assert format_time_ago(future) == "now"

    def test_recent_seconds(self):
        """Recent timestamps should show seconds."""
        now = int(time.time())
        assert format_time_ago(now - 5) == "5s"
        assert format_time_ago(now - 30) == "30s"
        assert format_time_ago(now - 59) == "59s"

    def test_minutes(self):
        """Timestamps 1-59 minutes ago should show minutes."""
        now = int(time.time())
        assert format_time_ago(now - 60) == "1m"
        assert format_time_ago(now - 120) == "2m"
        assert format_time_ago(now - 3599) == "59m"

    def test_hours(self):
        """Timestamps 1-23 hours ago should show hours."""
        now = int(time.time())
        assert format_time_ago(now - 3600) == "1h"
        assert format_time_ago(now - 7200) == "2h"
        assert format_time_ago(now - 86399) == "23h"

    def test_days(self):
        """Timestamps >= 24 hours ago should show days."""
        now = int(time.time())
        assert format_time_ago(now - 86400) == "1d"
        assert format_time_ago(now - 172800) == "2d"
        assert format_time_ago(now - 604800) == "7d"


class TestHaversineDistance:
    """Tests for haversine_distance function."""

    def test_same_point(self):
        """Distance between same point should be zero."""
        dist = haversine_distance(37.7749, -122.4194, 37.7749, -122.4194)
        assert dist == pytest.approx(0.0, abs=0.001)

    def test_known_distance_sf_to_oakland(self):
        """Test known distance between SF and Oakland (approx 13 km)."""
        # SF: 37.7749, -122.4194
        # Oakland: 37.8044, -122.2712
        dist = haversine_distance(37.7749, -122.4194, 37.8044, -122.2712)
        assert dist == pytest.approx(13.0, rel=0.1)  # Within 10%

    def test_known_distance_ny_to_la(self):
        """Test known distance between NYC and LA (approx 3940 km)."""
        # NYC: 40.7128, -74.0060
        # LA: 34.0522, -118.2437
        dist = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437)
        assert dist == pytest.approx(3940, rel=0.05)  # Within 5%

    def test_symmetric(self):
        """Distance should be symmetric (A to B == B to A)."""
        dist1 = haversine_distance(37.7749, -122.4194, 40.7128, -74.0060)
        dist2 = haversine_distance(40.7128, -74.0060, 37.7749, -122.4194)
        assert dist1 == pytest.approx(dist2)

    def test_antipodal_points(self):
        """Test points on opposite sides of Earth (approx 20000 km)."""
        # Roughly antipodal: North Pacific to South Atlantic
        dist = haversine_distance(0, 0, 0, 180)
        assert dist == pytest.approx(20015, rel=0.01)  # Half Earth circumference


class TestFormatDistance:
    """Tests for format_distance function."""

    @patch("meshterm.formatting._use_imperial", return_value=False)
    def test_metric_meters(self, mock_imperial):
        """Distances < 1km should show meters (metric)."""
        assert format_distance(0.5) == "500 m"
        assert format_distance(0.1) == "100 m"
        assert format_distance(0.999) == "999 m"

    @patch("meshterm.formatting._use_imperial", return_value=False)
    def test_metric_kilometers(self, mock_imperial):
        """Distances >= 1km should show kilometers (metric)."""
        assert format_distance(1.0) == "1.0 km"
        assert format_distance(5.5) == "5.5 km"
        assert format_distance(100.0) == "100.0 km"

    @patch("meshterm.formatting._use_imperial", return_value=False)
    def test_metric_short_format(self, mock_imperial):
        """Short format should omit spaces (metric)."""
        assert format_distance(0.5, short=True) == "500m"
        assert format_distance(5.5, short=True) == "5.5km"

    @patch("meshterm.formatting._use_imperial", return_value=True)
    def test_imperial_feet(self, mock_imperial):
        """Distances < 0.1 mi should show feet (imperial)."""
        # 0.1 km = 0.062 mi = 328 ft
        result = format_distance(0.05)  # ~0.031 mi = ~164 ft
        assert "ft" in result

    @patch("meshterm.formatting._use_imperial", return_value=True)
    def test_imperial_miles(self, mock_imperial):
        """Distances >= 0.1 mi should show miles (imperial)."""
        # 1 km = 0.621 mi
        result = format_distance(1.0)
        assert "mi" in result
        assert "0.6" in result

    @patch("meshterm.formatting._use_imperial", return_value=True)
    def test_imperial_short_format(self, mock_imperial):
        """Short format should omit spaces (imperial)."""
        result = format_distance(1.0, short=True)
        assert " " not in result
        assert "mi" in result


class TestGetNodePosition:
    """Tests for get_node_position function."""

    def test_none_node(self):
        """None node should return None."""
        assert get_node_position(None) is None

    def test_empty_node(self):
        """Empty node dict should return None."""
        assert get_node_position({}) is None

    def test_no_position_key(self):
        """Node without position key should return None."""
        node = {"user": {"shortName": "TEST"}}
        assert get_node_position(node) is None

    def test_empty_position(self):
        """Empty position dict should return None."""
        node = {"position": {}}
        assert get_node_position(node) is None

    def test_float_coordinates(self):
        """Float lat/lon should be returned directly."""
        node = {
            "position": {
                "latitude": 37.7749,
                "longitude": -122.4194,
            }
        }
        result = get_node_position(node)
        assert result == (37.7749, -122.4194)

    def test_integer_coordinates_normalization(self):
        """Integer lat/lon (1e7 scale) should be normalized."""
        node = {
            "position": {
                "latitudeI": 377749000,  # 37.7749 * 1e7
                "longitudeI": -1224194000,  # -122.4194 * 1e7
            }
        }
        result = get_node_position(node)
        assert result is not None
        lat, lon = result
        assert lat == pytest.approx(37.7749, rel=0.0001)
        assert lon == pytest.approx(-122.4194, rel=0.0001)

    def test_prefers_float_over_int(self):
        """Float keys should be preferred over integer keys."""
        node = {
            "position": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "latitudeI": 0,  # Should be ignored
                "longitudeI": 0,
            }
        }
        result = get_node_position(node)
        assert result == (37.7749, -122.4194)

    def test_zero_coordinates(self):
        """Zero coordinates should return None."""
        node = {
            "position": {
                "latitude": 0,
                "longitude": 0,
            }
        }
        assert get_node_position(node) is None


class TestGetPortnumName:
    """Tests for get_portnum_name function."""

    def test_known_string_portnum(self):
        """Known string portnums should return correct name and color."""
        name, color = get_portnum_name("TEXT_MESSAGE_APP")
        assert name == "TEXT"
        assert color == Colors.TEXT

        name, color = get_portnum_name("POSITION_APP")
        assert name == "POSITION"
        assert color == Colors.POSITION

        name, color = get_portnum_name("TELEMETRY_APP")
        assert name == "TELEMETRY"
        assert color == Colors.TELEMETRY

    def test_known_integer_portnum(self):
        """Known integer portnums should return correct name and color."""
        name, color = get_portnum_name(1)
        assert name == "TEXT"
        assert color == Colors.TEXT

        name, color = get_portnum_name(3)
        assert name == "POSITION"
        assert color == Colors.POSITION

        name, color = get_portnum_name(67)
        assert name == "TELEMETRY"
        assert color == Colors.TELEMETRY

    def test_unknown_string_portnum(self):
        """Unknown string portnums should be cleaned up."""
        name, color = get_portnum_name("SOME_CUSTOM_APP")
        assert name == "SOME_CUSTO"  # Truncated to 10 chars after removing _APP
        assert color == Colors.UNKNOWN

    def test_unknown_integer_portnum(self):
        """Unknown integer portnums should show PORT:num."""
        name, color = get_portnum_name(999)
        assert name == "PORT:999"
        assert color == Colors.UNKNOWN

    def test_all_mapped_portnums(self):
        """All mapped portnums should return non-None values."""
        for portnum in PORTNUM_MAP.keys():
            name, color = get_portnum_name(portnum)
            assert name is not None
            assert color is not None


class TestColors:
    """Tests for color constants."""

    def test_colors_are_strings(self):
        """All color values should be strings (Rich style names)."""
        assert isinstance(Colors.RESET, str)
        assert isinstance(Colors.TEXT, str)
        assert isinstance(Colors.POSITION, str)
        assert isinstance(Colors.TELEMETRY, str)

    def test_json_colors_are_strings(self):
        """All JSON color values should be strings."""
        assert isinstance(JsonColors.KEY, str)
        assert isinstance(JsonColors.STRING, str)
        assert isinstance(JsonColors.NUMBER, str)
        assert isinstance(JsonColors.BOOL, str)
        assert isinstance(JsonColors.NULL, str)
