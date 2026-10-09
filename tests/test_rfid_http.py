"""Tests für den HTTP-RFID-Extraktor (ESP32-Status)."""

from blackjack import rfid as rfid_mod
from blackjack.rfid import HTTPRFIDReader, _extract_scan, _normalize_id


# ---------------------------------------------------------------------------
# Logins (status == "logged_in")
# ---------------------------------------------------------------------------
def test_logged_in_returns_uid_and_username():
    payload = {
        "status": "logged_in",
        "user_id": "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb",
        "username": "Jonathan",
        "run_id": "0",
        "time": 4,
    }
    uid, name = _extract_scan(payload)
    assert uid == "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb"
    assert name == "Jonathan"


def test_uppercase_uuid_is_lowercased():
    payload = {
        "status": "logged_in",
        "user_id": "D83751AE-8DFB-4A4B-BFBC-79BDCC54CDEB",
        "username": "Jonathan",
    }
    uid, _name = _extract_scan(payload)
    assert uid == "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb"


def test_alternative_name_keys():
    for key in ("user_name", "name", "display_name"):
        payload = {"status": "logged_in", "user_id": "abc-def", key: "Alice"}
        _uid, name = _extract_scan(payload)
        assert name == "Alice", f"expected Alice via key {key}"


# ---------------------------------------------------------------------------
# Nicht-Logins (alles außer "logged_in")
# ---------------------------------------------------------------------------
def test_idle_returns_none():
    payload = {"status": "idle", "user_id": "", "username": "", "run_id": ""}
    assert _extract_scan(payload) == (None, None)


def test_logged_out_returns_none():
    payload = {
        "status": "logged_out",
        "user_id": "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb",
        "username": "Jonathan",
    }
    # Selbst wenn Felder gefüllt sind, zählt nur status == logged_in.
    assert _extract_scan(payload) == (None, None)


def test_missing_status_returns_none():
    assert _extract_scan({"user_id": "abc", "username": "X"}) == (None, None)


def test_non_dict_payload_returns_none():
    assert _extract_scan("just a string") == (None, None)
    assert _extract_scan(None) == (None, None)
    assert _extract_scan(42) == (None, None)


def test_empty_user_id_returns_none():
    payload = {"status": "logged_in", "user_id": "", "username": "x"}
    uid, _name = _extract_scan(payload)
    assert uid is None


# ---------------------------------------------------------------------------
# Normalisierung
# ---------------------------------------------------------------------------
def test_normalize_id_passes_uuid_through_lowercase():
    assert _normalize_id("D83751AE-8DFB-4A4B-BFBC-79BDCC54CDEB") \
        == "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb"


def test_normalize_id_strips_whitespace():
    assert _normalize_id("  abc  ") == "abc"


# ---------------------------------------------------------------------------
# Logout am ESP32
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.ok = status_code < 400


def _reader():
    return HTTPRFIDReader("http://10.0.244.81/status", autostart=False)


def _events(reader):
    out = []
    while True:
        has, uid = reader.poll()
        if not has:
            return out
        out.append(uid)


def _with_requests(get=None, post=None):
    """Ersetzt requests.get/post im rfid-Modul, liefert die Aufrufliste."""
    calls = []
    old_get, old_post = rfid_mod.requests.get, rfid_mod.requests.post

    def fake_get(url, timeout=None):
        calls.append(("GET", url))
        return get or _Resp()

    def fake_post(url, timeout=None):
        calls.append(("POST", url))
        return post or _Resp()

    rfid_mod.requests.get, rfid_mod.requests.post = fake_get, fake_post
    return calls, lambda: (
        setattr(rfid_mod.requests, "get", old_get),
        setattr(rfid_mod.requests, "post", old_post),
    )


def test_logout_url_derived_from_status_url():
    assert _reader().logout_url == "http://10.0.244.81/logout"
    r = HTTPRFIDReader("http://x/status", logout_url="http://y/abmelden",
                       autostart=False)
    assert r.logout_url == "http://y/abmelden"


def test_logout_calls_esp32_and_allows_relogin():
    reader = _reader()
    uid = "d83751ae-8dfb-4a4b-bfbc-79bdcc54cdeb"
    reader._process_uid(uid)
    assert _events(reader) == [uid]

    calls, restore = _with_requests()
    try:
        assert reader.logout() is True
    finally:
        restore()
    assert calls == [("GET", "http://10.0.244.81/logout")]

    # ESP32 meldet kurz noch den alten User -> darf nicht neu einloggen.
    reader._process_uid(uid)
    assert _events(reader) == []
    # ... und auch kein "abgemeldet"-Event, das Spiel ist schon raus.
    reader._process_uid(None)
    assert _events(reader) == []
    # Chip wieder auflegen -> neuer Login.
    reader._process_uid(uid)
    assert _events(reader) == [uid]


def test_logout_failure_keeps_state():
    reader = _reader()
    reader._process_uid("abc")
    _events(reader)
    calls, restore = _with_requests(get=_Resp(500))
    try:
        assert reader.logout() is False
    finally:
        restore()
    # Weiterhin derselbe User - kein neues Event.
    reader._process_uid("abc")
    assert _events(reader) == []


def test_logout_falls_back_to_post_on_405():
    reader = _reader()
    calls, restore = _with_requests(get=_Resp(405))
    try:
        assert reader.logout() is True
    finally:
        restore()
    assert [m for m, _ in calls] == ["GET", "POST"]
