"""Tests für den Score-Aggregator (ohne Netzwerk)."""

from __future__ import annotations

from blackjack.db_config import InfluxConfig
from blackjack.influx_db import parse_flux_grouped_sum, query_points
from scripts.score_aggregator import (
    SOURCE_BUCKETS,
    collect_totals,
    query_bucket_sums,
    write_totals,
)


_TEST_CFG = InfluxConfig(
    url="http://example.local", org="o", bucket="SpieloAutomat",
    bucket_id="bi", token_read="tr", token_write="tw",
)


# ---------------------------------------------------------------------------
# parse_flux_grouped_sum
# ---------------------------------------------------------------------------
GROUPED_SUM_CSV = (
    "#datatype,string,long,string,long,string\r\n"
    "#group,false,false,true,false,true\r\n"
    "#default,_result,,,,\r\n"
    ",result,table,user_id,_value,_field\r\n"
    ",,0,alice-uuid,120,score\r\n"
    ",,1,bob-uuid,80,score\r\n"
)


def test_parse_grouped_sum_single_table_per_user():
    sums = parse_flux_grouped_sum(GROUPED_SUM_CSV, "user_id")
    assert sums == {"alice-uuid": 120, "bob-uuid": 80}


def test_parse_grouped_sum_adds_multiple_rows_of_same_tag():
    csv = (
        "#datatype,string,long,string,long\r\n"
        "#group,false,false,true,false\r\n"
        "#default,_result,,,\r\n"
        ",result,table,user_id,_value\r\n"
        ",,0,alice-uuid,30\r\n"
        ",,0,alice-uuid,40\r\n"
    )
    assert parse_flux_grouped_sum(csv, "user_id") == {"alice-uuid": 70}


def test_parse_grouped_sum_ignores_rows_without_tag_column():
    # Falls der Tag "rfidTag" heißt, aber die Antwort "user_id" liefert,
    # muss die Funktion still liefern.
    assert parse_flux_grouped_sum(GROUPED_SUM_CSV, "rfidTag") == {}


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
def test_all_six_source_buckets_listed():
    buckets = [row[0] for row in SOURCE_BUCKETS]
    assert set(buckets) == {
        "HeisserDraht", "Ampelsequenz", "TimerStrike",
        "Wurfgenauigkeit", "Whackamole", "Gedaechtnistest",
    }


# ---------------------------------------------------------------------------
# query_bucket_sums + collect_totals + write_totals mit Fake-Session
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, text="", ok=True, status_code=200):
        self.text = text
        self.ok = ok
        self.status_code = status_code


class _RecordingSession:
    def __init__(self, response_by_bucket=None, write_ok=True):
        self.response_by_bucket = response_by_bucket or {}
        self.write_ok = write_ok
        self.writes = []
        self.queries = []

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        body = data.decode("utf-8") if isinstance(data, bytes) else data
        if url.endswith("/api/v2/write"):
            self.writes.append({
                "bucket": params["bucket"],
                "lines": body.strip().splitlines(),
            })
            return _FakeResponse(ok=self.write_ok)
        # Query: finde heraus, welcher Bucket angefragt wurde.
        for bucket, resp in self.response_by_bucket.items():
            if f'from(bucket: "{bucket}")' in body:
                self.queries.append(bucket)
                return _FakeResponse(text=resp)
        return _FakeResponse(text="", ok=True)


def test_collect_totals_merges_scores_across_buckets():
    # Jeder Bucket meldet Alice mit unterschiedlichem Score.
    def csv_for(tag, user, score):
        return (
            "#datatype,string,long,string,long\r\n"
            "#group,false,false,true,false\r\n"
            "#default,_result,,,\r\n"
            f",result,table,{tag},_value\r\n"
            f",,0,{user},{score}\r\n"
        )

    responses = {
        "HeisserDraht":    csv_for("userID",  "alice", 10),
        "Ampelsequenz":    csv_for("rfidTag", "alice", 20),
        "TimerStrike":     csv_for("user_id", "alice", 30),
        "Wurfgenauigkeit": csv_for("user_id", "alice", 40),
        "Whackamole":      csv_for("rfidTag", "alice", 50),
        "Gedaechtnistest": csv_for("user_id", "alice", 60),
    }
    sess = _RecordingSession(responses)
    totals = collect_totals(sess, _TEST_CFG, "0")
    assert totals == {"alice": 10 + 20 + 30 + 40 + 50 + 60}
    assert set(sess.queries) == set(responses.keys())


def test_write_totals_builds_line_protocol():
    sess = _RecordingSession()
    assert write_totals(sess, _TEST_CFG, {"alice-uuid": 150})
    assert len(sess.writes) == 1
    w = sess.writes[0]
    assert w["bucket"] == "SpieloAutomat"
    assert len(w["lines"]) == 1
    line = w["lines"][0]
    assert line.startswith("endscore,user_id=alice-uuid score=150i ")


def test_write_totals_empty_dict_is_noop():
    sess = _RecordingSession()
    assert write_totals(sess, _TEST_CFG, {})
    assert sess.writes == []


# ---------------------------------------------------------------------------
# query_points liest aus SpieloAutomat
# ---------------------------------------------------------------------------
def test_query_points_returns_int_from_last_value():
    csv = (
        "#datatype,string,long,string,string,long\r\n"
        "#group,false,false,true,true,false\r\n"
        "#default,_result,,,,\r\n"
        ",result,table,user_id,_field,_value\r\n"
        ",,0,alice-uuid,score,250\r\n"
    )

    class FakeResp:
        ok = True
        status_code = 200
        text = csv

    class FakeSess:
        def post(self, url, params=None, headers=None, data=None, timeout=None):
            body = data.decode("utf-8")
            assert 'from(bucket: "SpieloAutomat")' in body
            assert 'r.user_id == "alice-uuid"' in body
            return FakeResp()

    assert query_points("alice-uuid", cfg=_TEST_CFG, session=FakeSess()) == 250


def test_query_points_returns_none_when_db_not_configured():
    unconfigured = InfluxConfig(
        url="", org="", bucket="", bucket_id="", token_read="", token_write="",
    )
    assert query_points("alice-uuid", cfg=unconfigured) is None
