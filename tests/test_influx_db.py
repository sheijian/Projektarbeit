"""Tests für blackjack/influx_db.py (ohne Netzwerk)."""

from __future__ import annotations

from contextlib import contextmanager

from blackjack import influx_db


# ---------------------------------------------------------------------------
class _Response:
    def __init__(self, text="", ok=True, status_code=200):
        self.text = text
        self.ok = ok
        self.status_code = status_code


class _FakeSession:
    def __init__(self, response=None, writes_ok=True):
        self.response = response or _Response()
        self.writes_ok = writes_ok
        self.calls = []

    def post(self, url, params=None, headers=None, data=None, timeout=None):
        body = data.decode("utf-8") if isinstance(data, bytes) else data
        self.calls.append({
            "url": url, "params": params, "headers": headers, "body": body,
        })
        if url.endswith("/write"):
            return _Response(ok=self.writes_ok)
        return self.response


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
SCORE_CSV = (
    "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,"
    "dateTime:RFC3339,long,string,string,string\r\n"
    "#group,false,false,true,true,false,false,true,true,true\r\n"
    "#default,_result,,,,,,,,\r\n"
    ",result,table,_start,_stop,_time,_value,_field,_measurement,user_id\r\n"
    ",,0,1970-01-01T00:00:00Z,2026-10-07T10:00:00Z,"
    "2026-10-06T12:00:00Z,125,score,endscore,"
    "7c3ed021-5099-4d46-9283-002adf814597\r\n"
)

USERNAME_CSV = (
    "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,"
    "dateTime:RFC3339,string,string,string,string\r\n"
    "#group,false,false,true,true,false,false,true,true,true\r\n"
    "#default,_result,,,,,,,,\r\n"
    ",result,table,_start,_stop,_time,_value,_field,_measurement,user_id\r\n"
    ",,0,1970-01-01T00:00:00Z,2026-10-07T10:00:00Z,"
    "2026-09-30T08:18:02.373Z,Tobias,username,PPMaster,"
    "7c3ed021-5099-4d46-9283-002adf814597\r\n"
)

UID = "7c3ed021-5099-4d46-9283-002adf814597"


def _balance_csv(*rows):
    """Antwort auf die query_balance-Abfrage: eine Zeile pro Serie,
    ``rows`` = (measurement, field, value)."""
    out = (
        "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,"
        "dateTime:RFC3339,long,string,string,string\r\n"
        "#group,false,false,true,true,false,false,true,true,true\r\n"
        "#default,_result,,,,,,,,\r\n"
        ",result,table,_start,_stop,_time,_value,_field,_measurement,user_id\r\n"
    )
    for table, (meas, field, value) in enumerate(rows):
        out += (
            f",,{table},1970-01-01T00:00:00Z,2026-10-09T08:45:29Z,"
            f"2026-09-19T05:55:13Z,{value},{field},{meas},{UID}\r\n"
        )
    return out


EMPTY_CSV = (
    "#datatype,string,long,string\r\n"
    "#group,false,false,false\r\n"
    "#default,_result,,\r\n"
    ",result,table,_value\r\n"
)


# ---------------------------------------------------------------------------
# query_balance
# ---------------------------------------------------------------------------
def test_query_balance_prefers_blackjack_endwert():
    """Endwert aus Blackjack schlägt das Startguthaben vom Aggregator -
    egal in welcher Reihenfolge InfluxDB die Tabellen liefert."""
    for rows in (
        [("blackjack", "endwert", 1), ("endscore", "score", 21)],
        [("endscore", "score", 21), ("blackjack", "endwert", 1)],
    ):
        sess = _FakeSession(_Response(text=_balance_csv(*rows)))
        with _test_env(sess):
            assert influx_db.query_balance(UID) == 1


def test_query_balance_falls_back_to_startguthaben():
    sess = _FakeSession(_Response(text=_balance_csv(("endscore", "score", 21))))
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 21


def test_query_balance_endwert_zero_is_kept():
    """Endwert 0 (alles verspielt) ist ein gültiger Wert, kein "leer"."""
    sess = _FakeSession(_Response(text=_balance_csv(
        ("blackjack", "endwert", 0), ("endscore", "score", 21),
    )))
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 0


def test_query_balance_sends_one_query_for_both_values():
    sess = _FakeSession(_Response(text=SCORE_CSV))
    with _test_env(sess):
        assert influx_db.query_balance(UID) == 125
    assert len(sess.calls) == 1
    call = sess.calls[0]
    assert call["url"] == "http://example.local/api/v2/query"
    assert call["params"] == {"org": "o"}
    assert call["headers"]["Authorization"] == "Token tr"
    body = call["body"]
    assert 'from(bucket: "SpieloAutomat")' in body
    assert 'r._measurement == "blackjack" and r._field == "endwert"' in body
    assert 'r._measurement == "endscore" and r._field == "score"' in body
    assert f'r.user_id == "{UID}"' in body


def test_query_balance_returns_none_on_empty():
    with _test_env(_FakeSession(_Response(text=EMPTY_CSV))):
        assert influx_db.query_balance("unknown") is None


def test_query_balance_returns_none_when_not_configured():
    old = influx_db.INFLUX_TOKEN_READ
    influx_db.INFLUX_TOKEN_READ = ""
    try:
        assert influx_db.query_balance("uid") is None
    finally:
        influx_db.INFLUX_TOKEN_READ = old


def test_query_balance_returns_none_on_http_error():
    with _test_env(_FakeSession(
        _Response(ok=False, status_code=401, text="unauthorized"),
    )):
        assert influx_db.query_balance("uid") is None


# ---------------------------------------------------------------------------
# query_username
# ---------------------------------------------------------------------------
def test_query_username_parses_last_value():
    sess = _FakeSession(_Response(text=USERNAME_CSV))
    with _test_env(sess):
        assert influx_db.query_username(
            "7c3ed021-5099-4d46-9283-002adf814597",
        ) == "Tobias"
    body = sess.calls[0]["body"]
    assert 'from(bucket: "PPMaster")' in body
    assert 'r._measurement == "PPMaster"' in body
    assert 'r._field == "username"' in body
    assert 'r.user_id == "7c3ed021-5099-4d46-9283-002adf814597"' in body


def test_query_username_returns_none_on_empty():
    with _test_env(_FakeSession(_Response(text=EMPTY_CSV))):
        assert influx_db.query_username("uid") is None


# ---------------------------------------------------------------------------
# write_endwert
# ---------------------------------------------------------------------------
def test_write_endwert_sends_line_protocol():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_endwert("abc-uid", 40) is True
    call = sess.calls[0]
    assert call["url"] == "http://example.local/api/v2/write"
    assert call["params"] == {
        "org": "o", "bucket": "SpieloAutomat", "precision": "ms",
    }
    assert call["headers"]["Authorization"] == "Token tw"
    lines = call["body"].strip().splitlines()
    # Ohne Zeitstempel - InfluxDB setzt die Serverzeit (Pi-Uhr geht falsch).
    assert lines == ["blackjack,user_id=abc-uid endwert=40i"]


def test_write_endwert_never_touches_aggregator_measurement():
    """Das Startguthaben (endscore) gehört allein dem Aggregator."""
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_endwert(UID, 1, username="Tobias")
    assert not sess.calls[0]["body"].startswith("endscore")


def test_write_endwert_adds_username_field():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_endwert(UID, 125, username="Tobias")
    line = sess.calls[0]["body"].strip()
    assert line == f'blackjack,user_id={UID} endwert=125i,username="Tobias"'


def test_write_endwert_escapes_quotes_in_username():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_endwert("uid-x", 10, username='A"B\\C')
    line = sess.calls[0]["body"]
    assert r'username="A\"B\\C"' in line


def test_write_endwert_returns_false_when_not_configured():
    old = influx_db.INFLUX_TOKEN_WRITE
    influx_db.INFLUX_TOKEN_WRITE = ""
    try:
        assert influx_db.write_endwert("uid", 10) is False
    finally:
        influx_db.INFLUX_TOKEN_WRITE = old


def test_write_endwert_returns_false_on_http_error():
    with _test_env(_FakeSession(writes_ok=False)):
        assert influx_db.write_endwert("uid", 10) is False


# ---------------------------------------------------------------------------
# Low-Level
# ---------------------------------------------------------------------------
def test_first_value_handles_annotations_and_empty():
    assert influx_db._first_value(SCORE_CSV) == "125"
    assert influx_db._first_value(USERNAME_CSV) == "Tobias"
    assert influx_db._first_value("") is None
    assert influx_db._first_value(EMPTY_CSV) is None


def test_rows_handles_tables_with_own_headers():
    """Tabellen mit unterschiedlichem Schema kommen als eigene Blöcke."""
    text = SCORE_CSV + "\r\n" + USERNAME_CSV
    rows = list(influx_db._rows(text))
    assert [r["_measurement"] for r in rows] == ["endscore", "PPMaster"]
    assert [r["_value"] for r in rows] == ["125", "Tobias"]


def test_escapers():
    assert influx_db._esc_q('A"B\\C') == r'A\"B\\C'
    assert influx_db._esc_tag("a b,c=d") == r"a\ b\,c\=d"
    assert influx_db._esc_str('x"y\\z') == r'x\"y\\z'
