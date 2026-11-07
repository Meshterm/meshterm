"""Property tests for the validation/sanitising helpers (hypothesis, derandomized)."""

import base64

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from meshterm.connection import _parse_psk, _valid_packet_id  # noqa: E402
from meshterm.formatting import position_from_dict, sanitize_text, text_fits_mesh  # noqa: E402

PROPERTY_SETTINGS = dict(
    max_examples=200,
    derandomize=True,
    deadline=None,
    # The autouse isolated_xdg fixture is function-scoped and harmless here.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

VALID_PSK_LENGTHS = (1, 16, 32)
KEYWORDS = {"default", "none", "random"}


def prop(**overrides):
    return settings(**{**PROPERTY_SETTINGS, **overrides})


# ---------------------------------------------------------------------------
# _parse_psk
# ---------------------------------------------------------------------------


class TestParsePsk:
    @prop()
    @given(raw=st.binary(min_size=0, max_size=80))
    def test_hex_accepts_only_valid_key_lengths(self, raw):
        text = raw.hex()
        if len(raw) in VALID_PSK_LENGTHS:
            assert _parse_psk(text) == raw
        else:
            with pytest.raises(ValueError):
                _parse_psk(text)

    @prop()
    @given(raw=st.binary(min_size=0, max_size=80))
    def test_raw_bytes_accept_only_valid_key_lengths(self, raw):
        if len(raw) in VALID_PSK_LENGTHS:
            assert _parse_psk(raw) == raw
        else:
            with pytest.raises(ValueError):
                _parse_psk(raw)

    @prop()
    @given(
        raw=st.binary(min_size=1, max_size=1)
        | st.binary(min_size=16, max_size=16)
        | st.binary(min_size=32, max_size=32)
    )
    def test_base64_of_valid_lengths_round_trips(self, raw):
        # Padding for 1/16/32 bytes guarantees the text is never mistaken for hex.
        assert _parse_psk(base64.b64encode(raw).decode("ascii")) == raw

    @prop()
    @given(raw=st.binary(min_size=0, max_size=80).filter(lambda b: len(b) not in VALID_PSK_LENGTHS))
    def test_base64_of_invalid_lengths_never_yields_a_key_of_that_length(self, raw):
        text = base64.b64encode(raw).decode("ascii")
        try:
            result = _parse_psk(text)
        except ValueError:
            return
        # Only possible when the text is itself valid hex of an allowed length.
        assert len(result) in VALID_PSK_LENGTHS
        assert result == bytes.fromhex(text.strip())

    @prop()
    @given(text=st.text(max_size=100))
    def test_arbitrary_text_is_rejected_or_a_valid_length_key(self, text):
        try:
            result = _parse_psk(text)
        except ValueError:
            return
        assert isinstance(result, bytes)
        assert len(result) in VALID_PSK_LENGTHS

    @prop()
    @given(
        value=st.one_of(st.none(), st.integers(), st.floats(), st.lists(st.integers(), max_size=3))
    )
    def test_non_text_non_bytes_is_rejected(self, value):
        with pytest.raises(ValueError):
            _parse_psk(value)

    def test_keywords_and_blank(self):
        assert _parse_psk("default") == b"\x01"
        assert _parse_psk("none") == b"\x00"
        assert len(_parse_psk("random")) == 32
        for blank in ("", "   ", "\n"):
            with pytest.raises(ValueError):
                _parse_psk(blank)


# ---------------------------------------------------------------------------
# _valid_packet_id
# ---------------------------------------------------------------------------


class TestValidPacketId:
    @prop()
    @given(value=st.integers(min_value=-(2**40), max_value=2**40))
    def test_exactly_unsigned_32_bit(self, value):
        assert _valid_packet_id(value) is (0 <= value <= 0xFFFFFFFF)

    @pytest.mark.parametrize("value", [0, 1, 0xFFFFFFFF])
    def test_boundaries_accepted(self, value):
        assert _valid_packet_id(value) is True

    @pytest.mark.parametrize("value", [-1, 0x100000000, 2**63, 2**64])
    def test_boundaries_rejected(self, value):
        assert _valid_packet_id(value) is False

    @prop()
    @given(value=st.one_of(st.none(), st.floats(), st.text(max_size=12), st.binary(max_size=4)))
    def test_non_integers_rejected(self, value):
        assert _valid_packet_id(value) is False


# ---------------------------------------------------------------------------
# text_fits_mesh
# ---------------------------------------------------------------------------

MULTIBYTE_TEXT = st.text(alphabet=st.sampled_from("aZ é€😀漢\n"), max_size=300)


class TestTextFitsMesh:
    @prop()
    @given(text=MULTIBYTE_TEXT)
    def test_limit_is_utf8_bytes_not_characters(self, text):
        assert text_fits_mesh(text) is (len(text.encode("utf-8")) <= 233)

    @prop()
    @given(text=MULTIBYTE_TEXT, overhead=st.integers(min_value=0, max_value=40))
    def test_overhead_counts_against_the_limit(self, text, overhead):
        assert text_fits_mesh(text, overhead) is (len(text.encode("utf-8")) + overhead <= 233)

    def test_exact_boundaries(self):
        assert text_fits_mesh("a" * 233)
        assert not text_fits_mesh("a" * 234)
        # 77 x 3-byte chars = 231 bytes; +2 ASCII = 233 fits, +3 does not.
        assert text_fits_mesh("€" * 77 + "ab")
        assert not text_fits_mesh("€" * 77 + "abc")
        # 78 characters but 234 bytes.
        assert not text_fits_mesh("€" * 78)
        # 233 characters of 1 byte vs 117 characters of 2 bytes (234 bytes).
        assert not text_fits_mesh("é" * 117)
        assert text_fits_mesh("é" * 116)


# ---------------------------------------------------------------------------
# position_from_dict
# ---------------------------------------------------------------------------

LAT = st.floats(min_value=-90.0, max_value=90.0, allow_nan=False)
LON = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False)


class TestPositionFromDict:
    @prop()
    @given(lat=LAT, lon=LON)
    def test_valid_float_coordinates_round_trip(self, lat, lon):
        result = position_from_dict({"latitude": lat, "longitude": lon})
        if lat == 0.0 and lon == 0.0:
            return  # (0, 0) is Meshtastic's "unknown position" sentinel
        assert result == pytest.approx((lat, lon))
        assert -90.0 <= result[0] <= 90.0 and -180.0 <= result[1] <= 180.0

    @prop()
    @given(
        lat_i=st.integers(min_value=-900_000_000, max_value=900_000_000),
        lon_i=st.integers(min_value=-1_800_000_000, max_value=1_800_000_000),
    )
    def test_integer_fields_are_scaled_by_1e7(self, lat_i, lon_i):
        result = position_from_dict({"latitudeI": lat_i, "longitudeI": lon_i})
        if lat_i == 0 and lon_i == 0:
            return
        assert result == pytest.approx((lat_i / 1e7, lon_i / 1e7))

    @prop()
    @given(
        lat=st.one_of(
            st.floats(min_value=90.0001, max_value=1e6),
            st.floats(min_value=-1e6, max_value=-90.0001),
            st.just(float("nan")),
            st.just(float("inf")),
        ),
        lon=LON,
    )
    def test_out_of_range_latitude_is_rejected(self, lat, lon):
        assert position_from_dict({"latitude": lat, "longitude": lon}) is None

    @prop()
    @given(
        lat=LAT,
        lon=st.one_of(
            st.floats(min_value=180.0001, max_value=1e6),
            st.floats(min_value=-1e6, max_value=-180.0001),
            st.just(float("nan")),
            st.just(float("-inf")),
        ),
    )
    def test_out_of_range_longitude_is_rejected(self, lat, lon):
        assert position_from_dict({"latitude": lat, "longitude": lon}) is None

    @prop()
    @given(
        lat_i=st.integers(min_value=900_000_001, max_value=2_000_000_000),
        lon_i=st.integers(min_value=-1_800_000_000, max_value=1_800_000_000),
    )
    def test_out_of_range_integer_latitude_is_rejected(self, lat_i, lon_i):
        assert position_from_dict({"latitudeI": lat_i, "longitudeI": lon_i}) is None

    @pytest.mark.parametrize(
        "position",
        [None, {}, {"latitude": 10.0}, {"longitude": 10.0}, {"latitude": "x", "longitude": "y"}],
    )
    def test_missing_or_garbage_is_rejected(self, position):
        assert position_from_dict(position) is None

    def test_equator_and_prime_meridian_are_valid(self):
        assert position_from_dict({"latitude": 0.0, "longitude": 10.5}) == (0.0, 10.5)
        assert position_from_dict({"latitude": 45.25, "longitude": 0.0}) == (45.25, 0.0)
        assert position_from_dict({"latitudeI": 0, "longitudeI": 105_000_000}) == (0.0, 10.5)


# ---------------------------------------------------------------------------
# sanitize_text
# ---------------------------------------------------------------------------


def _is_c0_c1(char: str) -> bool:
    code = ord(char)
    return code <= 0x1F or 0x7F <= code <= 0x9F


# Newline and tab are intentionally preserved for display.
_ALLOWED_CONTROLS = {"\n", "\t", "\r"}

ANY_TEXT = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0, max_codepoint=0x2FF),
        st.sampled_from("😀👍🏽❤\ufe0f\u200d漢€"),
    ),
    max_size=200,
)


class TestSanitizeText:
    @prop()
    @given(text=ANY_TEXT)
    def test_no_c0_or_c1_controls_survive(self, text):
        out = sanitize_text(text)
        leftovers = {c for c in out if _is_c0_c1(c)} - _ALLOWED_CONTROLS
        assert not leftovers, f"control characters survived: {sorted(map(ord, leftovers))}"
        assert "\x1b" not in out

    @prop()
    @given(text=ANY_TEXT)
    def test_printable_content_is_preserved_in_order(self, text):
        out = sanitize_text(text)
        assert [c for c in out if not _is_c0_c1(c)] == [c for c in text if not _is_c0_c1(c)]

    @prop()
    @given(text=ANY_TEXT)
    def test_newline_and_tab_are_preserved(self, text):
        out = sanitize_text(text)
        assert out.count("\n") == text.count("\n")
        assert out.count("\t") == text.count("\t")

    @prop()
    @given(text=ANY_TEXT)
    def test_idempotent(self, text):
        once = sanitize_text(text)
        assert sanitize_text(once) == once

    @prop()
    @given(value=st.one_of(st.integers(), st.floats(allow_nan=False), st.none()))
    def test_non_strings_become_safe_text(self, value):
        out = sanitize_text(value)
        assert isinstance(out, str)
        assert not any(_is_c0_c1(c) for c in out)
