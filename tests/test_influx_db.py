"""Tests für blackjack.influx_db.

HTTP wird gemockt - getestet werden der Flux-CSV-Parser und das
Verhalten von ``query_username`` bei verschiedenen DB-Antworten.
"""

from __future__ import annotations

from blackjack.db_config import InfluxConfig
from blackjack.influx_db import (
    _escape_flux_string,
    _escape_line_protocol_tag,
    _parse_flux_first_value,
    query_username,
    write_endscore,
)


# ---------------------------------------------------------------------------
# Flux-CSV-Parser
# ---------------------------------------------------------------------------
# Original-Antwort aus dem Server-Test:
#   ,result,table,_start,_stop,_time,_value,_field,_measurement,user_id
#   ,_result,1,...,...,2026-09-30T08:18:02.373Z,Jonathan,username,PPMaster,4c63...
REAL_SERVER_CSV = (
    "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,"
    "dateTime:RFC3339,string,string,string,string\r\n"
    "#group,false,false,true,true,false,false,true,true,true\r\n"
    "#default,_result,,,,,,,,\r\n"
    ",result,table,_start,_stop,_time,_value,_field,_measurement,user_id\r\n"
    ",,1,1970-01-01T00:00:00Z,2026-10-02T09:12:18Z,"
    "2026-09-30T08:18:02.373Z,Jonathan,username,PPMaster,"
    "4c63dfa5-9dc8-4f15-8133-1b30799cf97c\r\n"
)


def test_parse_flux_first_value_extracts_username():
    assert _parse_flux_first_value(REAL_SERVER_CSV) == "Jonathan"


def test_parse_flux_first_value_handles_empty_result():
    csv_only_headers = (
        "#datatype,string,long,string,string\r\n"
        "#group,false,false,true,true\r\n"
        "#default,_result,,,\r\n"
        ",result,table,_value,user_id\r\n"
    )
    assert _parse_flux_first_value(csv_only_headers) is None


def test_parse_flux_first_value_empty_input():
    assert _parse_flux_first_value("") is None


# ---------------------------------------------------------------------------
# query_username: Config-Pfad (kein HTTP)
# ---------------------------------------------------------------------------
def test_query_username_returns_none_when_db_not_configured():
    unconfigured = InfluxConfig(
        url="", org="", bucket="", bucket_id="", token_read="", token_write="",
    )
    assert query_username("some-uid", cfg=unconfigured) is None


def test_query_username_uses_mocked_session():
    cfg = InfluxConfig(
        url="http://example.local", org="o", bucket="PPMaster",
        bucket_id="bid", token_read="tr", token_write="tw",
    )

    captured = {}

    class FakeResponse:
        ok = True
        status_code = 200
        text = REAL_SERVER_CSV

    class FakeSession:
        def post(self, url, params=None, headers=None, data=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            captured["body"] = data.decode("utf-8")
            return FakeResponse()

    name = query_username(
        "4c63dfa5-9dc8-4f15-8133-1b30799cf97c",
        cfg=cfg,
        session=FakeSession(),
    )
    assert name == "Jonathan"
    assert captured["url"] == "http://example.local/api/v2/query"
    assert captured["params"] == {"org": "o"}
    assert captured["headers"]["Authorization"] == "Token tr"
    assert "4c63dfa5-9dc8-4f15-8133-1b30799cf97c" in captured["body"]
    assert 'r._measurement == "PPMaster"' in captured["body"]
    assert 'r._field == "username"' in captured["body"]


def test_query_username_returns_none_on_http_error():
    cfg = InfluxConfig(
        url="http://x", org="o", bucket="b",
        bucket_id="bi", token_read="tr", token_write="tw",
    )

    class FailResponse:
        ok = False
        status_code = 401
        text = "unauthorized"

    class FailSession:
        def post(self, *a, **kw):
            return FailResponse()

    assert query_username("uid", cfg=cfg, session=FailSession()) is None


# ---------------------------------------------------------------------------
# Escape-Helfer
# ---------------------------------------------------------------------------
def test_escape_flux_string_quotes_and_backslashes():
    assert _escape_flux_string('Alice "AA"') == r'Alice \"AA\"'
    assert _escape_flux_string("a\\b") == r"a\\b"


def test_escape_line_protocol_tag_spaces_commas_equals():
    assert _escape_line_protocol_tag("Alice, the great") \
        == r"Alice\,\ the\ great"
    assert _escape_line_protocol_tag("Bob=One") == r"Bob\=One"


# ---------------------------------------------------------------------------
# write_endscore: schreibt den aktuellen Kontostand in SpieloAutomat
# ---------------------------------------------------------------------------
class _CaptureSession:
    def __init__(self):
        self.captured = {}

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        self.captured.update(
            url=url, params=params, headers=headers,
            body=data.decode("utf-8"),
        )

        class R:
            ok = True
            status_code = 200
            text = ""

        return R()


def _test_cfg():
    return InfluxConfig(
        url="http://example.local", org="o", bucket="SpieloAutomat",
        bucket_id="bi", token_read="tr", token_write="tw",
    )


def test_write_endscore_uses_line_protocol():
    sess = _CaptureSession()
    assert write_endscore(
        "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb", 40,
        cfg=_test_cfg(), session=sess,
    )
    assert sess.captured["url"] == "http://example.local/api/v2/write"
    assert sess.captured["params"] == {
        "org": "o", "bucket": "SpieloAutomat", "precision": "ms",
    }
    assert sess.captured["headers"]["Authorization"] == "Token tw"
    line = sess.captured["body"].strip()
    assert line.startswith(
        "endscore,user_id=d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb score=40i "
    )


def test_write_endscore_includes_username_field_when_given():
    sess = _CaptureSession()
    assert write_endscore(
        "7c3ed021-5099-4d46-9283-002adf814597", 125,
        username="Tobias",
        cfg=_test_cfg(), session=sess,
    )
    line = sess.captured["body"].strip()
    # score und username im selben Datenpunkt, Komma-separiert
    assert (
        "endscore,user_id=7c3ed021-5099-4d46-9283-002adf814597 "
        'score=125i,username="Tobias" '
    ) in line + " "


def test_write_endscore_escapes_quotes_in_username():
    sess = _CaptureSession()
    assert write_endscore(
        "uid-x", 10, username='A"B\\C', cfg=_test_cfg(), session=sess,
    )
    line = sess.captured["body"].strip()
    assert r'username="A\"B\\C"' in line


def test_write_endscore_without_username_only_writes_score():
    sess = _CaptureSession()
    assert write_endscore("uid-x", 10, cfg=_test_cfg(), session=sess)
    line = sess.captured["body"].strip()
    assert "username" not in line
    assert "score=10i" in line


def test_write_endscore_rejects_unconfigured_db():
    unconfigured = InfluxConfig(
        url="", org="", bucket="", bucket_id="", token_read="", token_write="",
    )
    assert write_endscore("uid", 20, cfg=unconfigured) is False


def test_write_endscore_returns_false_on_http_error():
    cfg = InfluxConfig(
        url="http://x", org="o", bucket="b",
        bucket_id="bi", token_read="tr", token_write="tw",
    )

    class FailResponse:
        ok = False
        status_code = 500
        text = "boom"

    class FailSession:
        def post(self, *a, **kw):
            return FailResponse()

    assert write_endscore("uid", 20, cfg=cfg, session=FailSession()) is False
