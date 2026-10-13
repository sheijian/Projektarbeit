"""Tests für blackjack/influx_db.py (ohne Netzwerk)."""

from __future__ import annotations

import re
from contextlib import contextmanager

from blackjack import influx_db


UID = "7c3ed021-5099-4d46-9283-002adf814597"


# ---------------------------------------------------------------------------
class _Response:
    def __init__(self, text="", ok=True, status_code=200):
        self.text = text
        self.ok = ok
        self.status_code = status_code


class _FakeSession:
    """Antwortet je nach abgefragtem Bucket. ``buckets`` = {name: Response};
    nicht genannte Buckets liefern ein leeres Ergebnis."""

    def __init__(self, buckets=None, writes_ok=True):
        self.buckets = buckets or {}
        self.writes_ok = writes_ok
        self.calls = []

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        body = data.decode("utf-8") if isinstance(data, bytes) else data
        self.calls.append({
            "url": url, "params": params, "headers": headers, "body": body,
        })
        if url.endswith("/write") or url.endswith("/delete"):
            return _Response(ok=self.writes_ok,
                             status_code=204 if self.writes_ok else 500)
        bucket = re.search(r'from\(bucket: "([^"]+)"\)', body).group(1)
        return self.buckets.get(bucket, _Response(text=EMPTY_CSV))

    def queried(self):
        return [re.search(r'from\(bucket: "([^"]+)"\)', c["body"]).group(1)
                for c in self.calls if c["url"].endswith("/query")]


@contextmanager
def _test_env(session):
    """Setzt Config + Session und stellt alles danach zurück."""
    old = {
        "URL": influx_db.INFLUX_URL,
        "ORG": influx_db.INFLUX_ORG,
        "TR":  influx_db.INFLUX_TOKEN_READ,
        "TW":  influx_db.INFLUX_TOKEN_WRITE,
        "SESS": influx_db._session,
        "GETSESS": influx_db._get_session,
    }
    influx_db.INFLUX_URL         = "http://example.local"
    influx_db.INFLUX_ORG         = "o"
    influx_db.INFLUX_TOKEN_READ  = "tr"
    influx_db.INFLUX_TOKEN_WRITE = "tw"
    influx_db._session = None
    influx_db._get_session = lambda: session
    try:
        yield
    finally:
        influx_db.INFLUX_URL         = old["URL"]
        influx_db.INFLUX_ORG         = old["ORG"]
        influx_db.INFLUX_TOKEN_READ  = old["TR"]
        influx_db.INFLUX_TOKEN_WRITE = old["TW"]
        influx_db._session           = old["SESS"]
        influx_db._get_session       = old["GETSESS"]


# ---------------------------------------------------------------------------
def _value_csv(value):
    """Flux-Antwort mit genau einem Wert (last() oder group()+sum())."""
    return _Response(text=(
        "#datatype,string,long,long\r\n"
        "#group,false,false,false\r\n"
        "#default,_result,,\r\n"
        ",result,table,_value\r\n"
        f",,0,{value}\r\n"
    ))


LIVE_CSV = (
    "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,"
    "dateTime:RFC3339,long,string,string,string\r\n"
    "#group,false,false,true,true,false,false,true,true,true\r\n"
    "#default,_result,,,,,,,,\r\n"
    ",result,table,_start,_stop,_time,_value,_field,_measurement,userid\r\n"
    ",,0,1970-01-01T00:00:00Z,2026-10-12T10:00:00Z,"
    f"2026-10-12T09:00:00Z,125,live,durchlauf,{UID}\r\n"
)

USERNAME_CSV = (
    "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,"
    "dateTime:RFC3339,string,string,string,string\r\n"
    "#group,false,false,true,true,false,false,true,true,true\r\n"
    "#default,_result,,,,,,,,\r\n"
    ",result,table,_start,_stop,_time,_value,_field,_measurement,user_id\r\n"
    ",,0,1970-01-01T00:00:00Z,2026-10-07T10:00:00Z,"
    f"2026-09-30T08:18:02.373Z,Tobias,username,PPMaster,{UID}\r\n"
)

EMPTY_CSV = (
    "#datatype,string,long,string\r\n"
    "#group,false,false,false\r\n"
    "#default,_result,,\r\n"
    ",result,table,_value\r\n"
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def test_unified_schema():
    assert (influx_db.MEASUREMENT, influx_db.FIELD, influx_db.TAG) == (
        "durchlauf", "endscore", "userid",
    )
    assert set(influx_db.STATION_BUCKETS) == {
        "HeisserDraht", "Ampelsequenz", "TimerStrike",
        "Wurfgenauigkeit", "Whackamole", "Gedaechtnistest",
    }
    assert influx_db.SCORE_BUCKET == "SpieloAutomat"
    assert influx_db.SCORE_BUCKET not in influx_db.STATION_BUCKETS


# ---------------------------------------------------------------------------
# query_station_points
# ---------------------------------------------------------------------------
def test_station_points_queries_all_six_with_both_schemas():
    """Vereinbart ist durchlauf/endscore/userid - in der DB steht aber z. B.
    bei Gedaechtnistest noch endscore/score/user_id. Beides muss zählen."""
    sess = _FakeSession()
    with _test_env(sess):
        influx_db.query_station_points(UID)
    assert sess.queried() == list(influx_db.STATION_BUCKETS)
    for call in sess.calls:
        body = call["body"]
        assert '(r._measurement == "durchlauf" and r._field == "endscore")' in body
        assert '(r._measurement == "endscore" and r._field == "score")' in body
        assert f'(exists r.userid and r.userid == "{UID}")' in body
        assert f'(exists r.user_id and r.user_id == "{UID}")' in body
        assert "|> toFloat()" in body
        assert "|> group()" in body and "|> sum()" in body


def test_station_points_reads_float_sum_from_real_db_answer():
    """Antwort, wie InfluxDB sie nach toFloat()+sum() liefert (Gedaechtnistest,
    Wert 79 vom 12.10.)."""
    answer = _Response(text=(
        "#datatype,string,long,double\r\n"
        "#group,false,false,false\r\n"
        "#default,_result,,\r\n"
        ",result,table,_value\r\n"
        ",,0,79\r\n"
    ))
    with _test_env(_FakeSession({"Gedaechtnistest": answer})):
        assert influx_db.query_station_points(UID) == {"Gedaechtnistest": 79}
        assert influx_db.query_balance(UID) == 79


def test_station_points_skips_stations_without_data():
    sess = _FakeSession({
        "HeisserDraht": _value_csv(10),
        "Whackamole":   _value_csv(11),
    })
    with _test_env(sess):
        assert influx_db.query_station_points(UID) == {
            "HeisserDraht": 10, "Whackamole": 11,
        }


def test_station_points_missing_bucket_counts_as_zero():
    sess = _FakeSession({
        "HeisserDraht": _value_csv(10),
        "TimerStrike":  _Response(ok=False, status_code=404,
                                  text='{"code":"not found"}'),
    })
    with _test_env(sess):
        assert influx_db.query_station_points(UID) == {"HeisserDraht": 10}


def test_station_points_raises_on_db_error():
    sess = _FakeSession({
        "Ampelsequenz": _Response(ok=False, status_code=500, text="boom"),
    })
    with _test_env(sess):
        try:
            influx_db.query_station_points(UID)
        except influx_db.DBError as e:
            assert e.status == 500
        else:
            raise AssertionError("DBError erwartet")


# ---------------------------------------------------------------------------
# query_kontostand / query_live / query_glueck / query_balance
# ---------------------------------------------------------------------------
class _FieldSession(_FakeSession):
    """SpieloAutomat antwortet je nach "measurement/field"."""

    def __init__(self, fields, buckets=None):
        super().__init__(buckets)
        self.fields = fields

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        body = data.decode("utf-8") if isinstance(data, bytes) else data
        m = re.search(r'from\(bucket: "SpieloAutomat"\).*'
                      r'r\._measurement == "(\w+)" and r\._field == "(\w+)"',
                      body, re.S)
        if m:
            self.calls.append({"url": url, "params": params,
                               "headers": headers, "body": body})
            key = f"{m.group(1)}/{m.group(2)}"
            return self.fields.get(key, _Response(text=EMPTY_CSV))
        return super().post(url, params, headers, data, timeout)


def test_query_kontostand_reads_endscore_stationen():
    sess = _FakeSession({"SpieloAutomat": _value_csv(69)})
    with _test_env(sess):
        assert influx_db.query_kontostand(UID) == 69
    body = sess.calls[0]["body"]
    assert 'from(bucket: "SpieloAutomat")' in body
    assert ('r._measurement == "endscore_stationen" and '
            'r._field == "endscore"') in body
    assert f'r.userid == "{UID}"' in body
    assert "|> last()" in body


def test_query_live_reads_spieloautomat_live_field():
    sess = _FakeSession({"SpieloAutomat": _Response(text=LIVE_CSV)})
    with _test_env(sess):
        assert influx_db.query_live(UID) == 125
    body = sess.calls[0]["body"]
    assert 'from(bucket: "SpieloAutomat")' in body
    assert 'r._measurement == "durchlauf" and r._field == "live"' in body
    assert f'r.userid == "{UID}"' in body
    assert "|> last()" in body


def test_query_glueck_reads_durchlauf_endscore():
    sess = _FieldSession({"durchlauf/endscore": _value_csv(50)})
    with _test_env(sess):
        assert influx_db.query_glueck(UID) == 50


def test_query_balance_loads_only_endscore_stationen():
    """Login lädt aus endscore_stationen/endscore - nie aus durchlauf/live
    (Dashboard) oder durchlauf/endscore (Glücksfaktor)."""
    sess = _FieldSession({
        "endscore_stationen/endscore": _value_csv(69),
        "durchlauf/live":              _value_csv(70),
        "durchlauf/endscore":          _value_csv(50),
    }, {"HeisserDraht": _value_csv(21)})
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 69


def test_query_balance_dashboard_values_alone_are_no_balance():
    """Nur durchlauf/live + Glücksfaktor (z. B. alte Daten), aber noch kein
    Kontostand in endscore_stationen -> Startguthaben aus den Stationen."""
    sess = _FieldSession({
        "durchlauf/live":     _value_csv(70),
        "durchlauf/endscore": _value_csv(50),
    }, {"HeisserDraht": _value_csv(21)})
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 21


def test_query_balance_prefers_live():
    sess = _FakeSession({
        "SpieloAutomat": _value_csv(1),
        "HeisserDraht":  _value_csv(21),
    })
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 1
    # Mit Kontostand müssen die Stationen gar nicht erst gefragt werden.
    assert sess.queried() == ["SpieloAutomat"]


def test_query_balance_live_zero_is_kept():
    """Kontostand 0 (alles verspielt) ist ein gültiger Wert, kein "leer"."""
    sess = _FakeSession({
        "SpieloAutomat": _value_csv(0),
        "HeisserDraht":  _value_csv(21),
    })
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 0


def test_query_balance_sums_stations_as_startguthaben():
    sess = _FakeSession({
        "HeisserDraht":    _value_csv(5),
        "Ampelsequenz":    _value_csv(4),
        "Gedaechtnistest": _value_csv(12),
    })
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 21


def test_query_balance_none_without_any_data():
    with _test_env(_FakeSession()):
        assert influx_db.query_balance("unknown") is None


def test_query_balance_raises_instead_of_guessing_on_db_error():
    sess = _FakeSession({
        "SpieloAutomat": _Response(ok=False, status_code=401, text="unauth"),
    })
    with _test_env(sess):
        try:
            influx_db.query_balance(UID)
        except influx_db.DBError:
            pass
        else:
            raise AssertionError("DBError erwartet")


def test_query_balance_returns_none_when_not_configured():
    old = influx_db.INFLUX_TOKEN_READ
    influx_db.INFLUX_TOKEN_READ = ""
    try:
        assert influx_db.query_balance("uid") is None
    finally:
        influx_db.INFLUX_TOKEN_READ = old


# ---------------------------------------------------------------------------
# query_username
# ---------------------------------------------------------------------------
def test_query_username_parses_last_value():
    sess = _FakeSession({"PPMaster": _Response(text=USERNAME_CSV)})
    with _test_env(sess):
        assert influx_db.query_username(UID) == "Tobias"
    body = sess.calls[0]["body"]
    assert 'from(bucket: "PPMaster")' in body
    assert 'r._measurement == "PPMaster"' in body
    assert 'r._field == "username"' in body
    # ESP32 schreibt jetzt "userid", ältere Punkte haben noch "user_id".
    assert f'(exists r.userid and r.userid == "{UID}")' in body
    assert f'(exists r.user_id and r.user_id == "{UID}")' in body
    assert '|> sort(columns: ["_time"])' in body


def test_query_username_returns_none_on_empty_or_error():
    with _test_env(_FakeSession()):
        assert influx_db.query_username("uid") is None
    with _test_env(_FakeSession({"PPMaster": _Response(ok=False,
                                                       status_code=500)})):
        assert influx_db.query_username("uid") is None


# ---------------------------------------------------------------------------
# write_spielstand / delete_spielstand
# ---------------------------------------------------------------------------
def test_write_spielstand_live_only_after_each_hand():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_spielstand(UID, live=69) is True
    call = sess.calls[0]
    assert call["url"] == "http://example.local/api/v2/write"
    assert call["params"] == {
        "org": "o", "bucket": "SpieloAutomat", "precision": "ms",
    }
    assert call["headers"]["Authorization"] == "Token tw"
    # Ohne Zeitstempel - InfluxDB setzt die Serverzeit (Pi-Uhr geht falsch).
    # Guthaben an beide Stellen: Dashboard + Kontostand für den Login.
    assert call["body"].strip().splitlines() == [
        f"durchlauf,userid={UID} live=69i",
        f"endscore_stationen,userid={UID} endscore=69i",
    ]


def test_write_spielstand_live_and_luck_at_logout():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_spielstand(UID, live=69, glueck=50) is True
    assert len(sess.calls) == 1                     # ein Request
    assert sess.calls[0]["body"].strip().splitlines() == [
        f"durchlauf,userid={UID} live=69i,endscore=50i",
        f"endscore_stationen,userid={UID} endscore=69i",
    ]


def test_write_spielstand_luck_only():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_spielstand(UID, glueck=67) is True
    # Nur Glücksfaktor -> Kontostand bleibt unberührt.
    assert sess.calls[0]["body"].strip() == f"durchlauf,userid={UID} endscore=67i"


def test_write_spielstand_nothing_to_write():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_spielstand(UID) is True
    assert sess.calls == []


def test_delete_spielstand_targets_only_this_player_in_spieloautomat():
    import json
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.delete_spielstand(UID) is True
    # Ein Request pro Measurement (Delete-Prädikat kennt kein OR).
    predicates = []
    for call in sess.calls:
        assert call["url"] == "http://example.local/api/v2/delete"
        assert call["params"] == {"org": "o", "bucket": "SpieloAutomat"}
        assert call["headers"]["Authorization"] == "Token tw"
        predicates.append(json.loads(call["body"])["predicate"])
    assert predicates == [
        f'_measurement="durchlauf" AND userid="{UID}"',
        f'_measurement="endscore_stationen" AND userid="{UID}"',
    ]


def test_list_schema_shows_measurement_field_and_tags():
    # So sah Gedaechtnistest am 12.10. aus (curl-Ausgabe aus dem Chat).
    answer = _Response(text=(
        ",result,table,_start,_stop,_time,_value,_field,_measurement,"
        "run_id,user_id\r\n"
        ",_result,0,1970-01-01T00:00:00Z,2026-10-12T09:52:21Z,"
        "2026-10-12T09:04:11Z,100,score,endscore,0,dcac539e\r\n"
        ",_result,1,1970-01-01T00:00:00Z,2026-10-12T09:52:21Z,"
        f"2026-10-12T08:34:49Z,79,score,endscore,5,{UID}\r\n"
    ))
    with _test_env(_FakeSession({"Gedaechtnistest": answer})):
        assert influx_db.list_schema("Gedaechtnistest") == [
            ("endscore", "score", ("run_id", "user_id")),
        ]


def test_write_spielstand_returns_false_when_not_configured():
    old = influx_db.INFLUX_TOKEN_WRITE
    influx_db.INFLUX_TOKEN_WRITE = ""
    try:
        assert influx_db.write_spielstand("uid", live=10) is False
    finally:
        influx_db.INFLUX_TOKEN_WRITE = old


def test_write_spielstand_returns_false_on_http_error():
    with _test_env(_FakeSession(writes_ok=False)):
        assert influx_db.write_spielstand("uid", live=10) is False


# ---------------------------------------------------------------------------
# Low-Level
# ---------------------------------------------------------------------------
def test_first_value_handles_annotations_and_empty():
    assert influx_db._first_value(LIVE_CSV) == "125"
    assert influx_db._first_value(USERNAME_CSV) == "Tobias"
    assert influx_db._first_value("") is None
    assert influx_db._first_value(EMPTY_CSV) is None


def test_rows_handles_tables_with_own_headers():
    """Tabellen mit unterschiedlichem Schema kommen als eigene Blöcke."""
    text = LIVE_CSV + "\r\n" + USERNAME_CSV
    rows = list(influx_db._rows(text))
    assert [r["_measurement"] for r in rows] == ["durchlauf", "PPMaster"]
    assert [r["_value"] for r in rows] == ["125", "Tobias"]


def test_to_int_accepts_float_sums():
    assert influx_db._to_int("21") == 21
    assert influx_db._to_int("21.0") == 21
    assert influx_db._to_int(None) is None


def test_escapers():
    assert influx_db._esc_q('A"B\\C') == r'A\"B\\C'
    assert influx_db._esc_tag("a b,c=d") == r"a\ b\,c\=d"
