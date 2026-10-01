"""Tests für den HTTP-RFID-Extraktor (ESP32-Status)."""

from blackjack.rfid import _extract_scan, _normalize_id


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
