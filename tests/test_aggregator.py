"""Tests für den Score-Aggregator (ohne Netzwerk)."""

from __future__ import annotations

from contextlib import contextmanager

from blackjack import influx_db
from scripts import score_aggregator as agg


class _Response:
    def __init__(self, text="", ok=True, status_code=200):
        self.text = text
        self.ok = ok
        self.status_code = status_code


class _FakeSession:
    def __init__(self, responses_by_bucket=None, writes_ok=True):
        self.responses_by_bucket = responses_by_bucket or {}
        self.writes_ok = writes_ok
        self.writes = []
        self.queries = []

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        body = data.decode("utf-8") if isinstance(data, bytes) else data
        if url.endswith("/api/v2/write"):
            self.writes.append({
                "bucket": params["bucket"],
                "lines": body.strip().splitlines(),
            })
            return _Response(ok=self.writes_ok)
        for bucket, resp in self.responses_by_bucket.items():
            if f'from(bucket: "{bucket}")' in body:
                self.queries.append(bucket)
                return _Response(text=resp)
        return _Response(text="", ok=True)


@contextmanager
def _test_env():
    """Setzt URL/Tokens auf feste Testwerte - in beiden Modulen."""
    old = {
        "URL": influx_db.INFLUX_URL,
        "ORG": influx_db.INFLUX_ORG,
        "TR":  influx_db.INFLUX_TOKEN_READ,
        "TW":  influx_db.INFLUX_TOKEN_WRITE,
        "AURL": agg.INFLUX_URL,
        "AORG": agg.INFLUX_ORG,
        "ATR":  agg.INFLUX_TOKEN_READ,
        "ATW":  agg.INFLUX_TOKEN_WRITE,
    }
    for mod in (influx_db, agg):
        mod.INFLUX_URL         = "http://example.local"
        mod.INFLUX_ORG         = "o"
        mod.INFLUX_TOKEN_READ  = "tr"
        mod.INFLUX_TOKEN_WRITE = "tw"
    try:
        yield
    finally:
        influx_db.INFLUX_URL         = old["URL"]
        influx_db.INFLUX_ORG         = old["ORG"]
        influx_db.INFLUX_TOKEN_READ  = old["TR"]
        influx_db.INFLUX_TOKEN_WRITE = old["TW"]
        agg.INFLUX_URL               = old["AURL"]
        agg.INFLUX_ORG               = old["AORG"]
        agg.INFLUX_TOKEN_READ        = old["ATR"]
        agg.INFLUX_TOKEN_WRITE       = old["ATW"]


def _csv(tag, user, score):
    return (
        "#datatype,string,long,string,long\r\n"
        "#group,false,false,true,false\r\n"
        "#default,_result,,,\r\n"
        f",result,table,{tag},_value\r\n"
        f",,0,{user},{score}\r\n"
    )


# ---------------------------------------------------------------------------
def test_all_six_source_buckets_listed():
    buckets = [row[0] for row in agg.SOURCE_BUCKETS]
    assert set(buckets) == {
        "HeisserDraht", "Ampelsequenz", "TimerStrike",
        "Wurfgenauigkeit", "Whackamole", "Gedaechtnistest",
    }


def test_collect_totals_sums_scores_across_buckets():
    responses = {
        "HeisserDraht":    _csv("userID",  "alice", 10),
        "Ampelsequenz":    _csv("rfidTag", "alice", 20),
        "TimerStrike":     _csv("user_id", "alice", 30),
        "Wurfgenauigkeit": _csv("user_id", "alice", 40),
        "Whackamole":      _csv("rfidTag", "alice", 50),
        "Gedaechtnistest": _csv("user_id", "alice", 60),
    }
    sess = _FakeSession(responses)
    with _test_env():
        totals = agg.collect_totals(sess)
    assert totals == {"alice": 210}
    assert set(sess.queries) == set(responses.keys())


def test_collect_totals_merges_different_users():
    responses = {
        "HeisserDraht": _csv("userID", "alice", 10),
        "Ampelsequenz": (
            "#datatype,string,long,string,long\r\n"
            "#group,false,false,true,false\r\n"
            "#default,_result,,,\r\n"
            ",result,table,rfidTag,_value\r\n"
            ",,0,alice,20\r\n"
            ",,1,bob,50\r\n"
        ),
    }
    sess = _FakeSession(responses)
    with _test_env():
        totals = agg.collect_totals(sess)
    assert totals == {"alice": 30, "bob": 50}


def test_write_totals_sends_line_protocol():
    sess = _FakeSession()
    with _test_env():
        assert agg.write_totals(sess, {"alice": 150}) is True
    assert len(sess.writes) == 1
    w = sess.writes[0]
    assert w["bucket"] == "SpieloAutomat"
    assert len(w["lines"]) == 1
    assert w["lines"][0].startswith("endscore,user_id=alice score=150i ")


def test_write_totals_empty_is_noop():
    sess = _FakeSession()
    with _test_env():
        assert agg.write_totals(sess, {}) is True
    assert sess.writes == []


def test_write_totals_handles_http_error():
    sess = _FakeSession(writes_ok=False)
    with _test_env():
        assert agg.write_totals(sess, {"alice": 10}) is False
