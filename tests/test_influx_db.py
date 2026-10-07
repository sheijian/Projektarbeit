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

EMPTY_CSV = (
    "#datatype,string,long,string\r\n"
    "#group,false,false,false\r\n"
    "#default,_result,,\r\n"
    ",result,table,_value\r\n"
)


# ---------------------------------------------------------------------------
# query_score
# ---------------------------------------------------------------------------
def test_query_score_parses_last_value():
    sess = _FakeSession(_Response(text=SCORE_CSV))
    with _test_env(sess):
        assert influx_db.query_score(
            "7c3ed021-5099-4d46-9283-002adf814597",
        ) == 125
    call = sess.calls[0]
    assert call["url"] == "http://example.local/api/v2/query"
    assert call["params"] == {"org": "o"}
    assert call["headers"]["Authorization"] == "Token tr"
    assert 'from(bucket: "SpieloAutomat")' in call["body"]
    assert 'r._measurement == "endscore"' in call["body"]
    assert 'r._field == "score"' in call["body"]
    assert 'r.user_id == "7c3ed021-5099-4d46-9283-002adf814597"' in call["body"]


def test_query_score_returns_none_on_empty():
    with _test_env(_FakeSession(_Response(text=EMPTY_CSV))):
        assert influx_db.query_score("unknown") is None


def test_query_score_returns_none_when_not_configured():
    old = influx_db.INFLUX_TOKEN_READ
    influx_db.INFLUX_TOKEN_READ = ""
    try:
        assert influx_db.query_score("uid") is None
    finally:
        influx_db.INFLUX_TOKEN_READ = old


def test_query_score_returns_none_on_http_error():
    with _test_env(_FakeSession(
        _Response(ok=False, status_code=401, text="unauthorized"),
    )):
        assert influx_db.query_score("uid") is None


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
# write_score
# ---------------------------------------------------------------------------
def test_write_score_sends_line_protocol():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_score("abc-uid", 40) is True
    call = sess.calls[0]
    assert call["url"] == "http://example.local/api/v2/write"
    assert call["params"] == {
        "org": "o", "bucket": "SpieloAutomat", "precision": "ms",
    }
    assert call["headers"]["Authorization"] == "Token tw"
    line = call["body"].strip()
    assert line.startswith("endscore,user_id=abc-uid score=40i ")
    assert "username" not in line


def test_write_score_adds_username_field():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_score(
            "7c3ed021-5099-4d46-9283-002adf814597", 125,
            username="Tobias",
        )
    line = sess.calls[0]["body"].strip()
    assert line.startswith(
        "endscore,user_id=7c3ed021-5099-4d46-9283-002adf814597 "
        'score=125i,username="Tobias" '
    )


def test_write_score_escapes_quotes_in_username():
    sess = _FakeSession()
    with _test_env(sess):
        assert influx_db.write_score("uid-x", 10, username='A"B\\C')
    line = sess.calls[0]["body"]
    assert r'username="A\"B\\C"' in line


def test_write_score_returns_false_when_not_configured():
    old = influx_db.INFLUX_TOKEN_WRITE
    influx_db.INFLUX_TOKEN_WRITE = ""
    try:
        assert influx_db.write_score("uid", 10) is False
    finally:
        influx_db.INFLUX_TOKEN_WRITE = old


def test_write_score_returns_false_on_http_error():
    with _test_env(_FakeSession(writes_ok=False)):
        assert influx_db.write_score("uid", 10) is False


# ---------------------------------------------------------------------------
# Low-Level
# ---------------------------------------------------------------------------
def test_first_value_handles_annotations_and_empty():
    assert influx_db._first_value(SCORE_CSV) == "125"
    assert influx_db._first_value("") is None
    assert influx_db._first_value(EMPTY_CSV) is None


def test_escapers():
    assert influx_db._esc_q('A"B\\C') == r'A\"B\\C'
    assert influx_db._esc_tag("a b,c=d") == r"a\ b\,c\=d"
    assert influx_db._esc_str('x"y\\z') == r'x\"y\\z'
