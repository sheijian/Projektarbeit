"""Tests für den UID-Extractor des HTTP-RFID-Readers."""

from blackjack.rfid import _extract_scan, _extract_uid, _normalize_id, _normalize_uid


# ---------------------------------------------------------------------------
# JSON-Antworten
# ---------------------------------------------------------------------------
def test_json_with_uid_key():
    assert _extract_uid({"uid": "0416AC12"}) == "0416AC12"


def test_json_with_id_key():
    assert _extract_uid({"id": "04D3A177"}) == "04D3A177"


def test_json_with_dashes():
    assert _extract_uid({"card_id": "04-16-AC-12"}) == "0416AC12"


def test_json_with_colons_and_lowercase():
    assert _extract_uid({"rfid": "aa:bb:cc:dd"}) == "AABBCCDD"


def test_json_status_no_card():
    assert _extract_uid({"status": "no_card"}) is None
    assert _extract_uid({"status": "idle"}) is None
    assert _extract_uid({"status": "logged_out"}) is None


# ---------------------------------------------------------------------------
# Antwortformat des tatsächlichen Test-Servers
# ---------------------------------------------------------------------------
def test_actual_test_server_response():
    """Genau das Format, das der Test-Server 10.0.244.31 liefert."""
    payload = {
        "status": "logged_in",
        "user_id": "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca",
        "username": "Jonathan",
        "run_id": "5",
        "time": 70,
    }
    assert _extract_uid(payload) == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"


def test_uuid_keeps_dashes_and_lowercase():
    """UUIDs dürfen NICHT normalisiert werden - sonst passt der Tag in
    InfluxDB nicht mehr."""
    payload = {"user_id": "B807DEE3-A666-4AA6-B5BD-F2D1EA0B7DCA"}
    assert _extract_uid(payload) == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"


def test_uuid_in_plain_text():
    text = "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"
    assert _extract_uid(text) == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"


def test_uuid_in_html():
    html = "<p>Angemeldet: b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca</p>"
    assert _extract_uid(html) == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"


# ---------------------------------------------------------------------------
# Anzeigename (username) mitextrahieren
# ---------------------------------------------------------------------------
def test_extract_scan_returns_uid_and_username():
    payload = {
        "status": "logged_in",
        "user_id": "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca",
        "username": "Jonathan",
    }
    uid, name = _extract_scan(payload)
    assert uid == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"
    assert name == "Jonathan"


def test_extract_scan_alternative_name_keys():
    for key in ("user_name", "name", "display_name", "player_name"):
        payload = {"user_id": "abc-def", key: "Alice"}
        _uid, name = _extract_scan(payload)
        assert name == "Alice", f"expected Alice via key {key}"


def test_extract_scan_no_name_present():
    payload = {"user_id": "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"}
    uid, name = _extract_scan(payload)
    assert uid == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"
    assert name is None


def test_extract_scan_text_has_no_name():
    uid, name = _extract_scan("b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca")
    assert uid == "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"
    assert name is None


def test_extract_scan_status_no_card():
    assert _extract_scan({"status": "logged_out"}) == (None, None)


def test_json_empty_uid():
    assert _extract_uid({"uid": ""}) is None
    assert _extract_uid({"uid": None}) is None


# ---------------------------------------------------------------------------
# Text-Antworten
# ---------------------------------------------------------------------------
def test_plain_text_uid():
    assert _extract_uid("0416AC12") == "0416AC12"


def test_plain_text_with_whitespace():
    assert _extract_uid("  04 16 ac 12  \n") == "0416AC12"


def test_html_containing_uid():
    html = "<html><body>Aktuelle Karte: <b>04-16-AC-12</b></body></html>"
    assert _extract_uid(html) == "0416AC12"


def test_empty_text():
    assert _extract_uid("") is None
    assert _extract_uid("   ") is None


def test_text_without_uid():
    assert _extract_uid("Keine Karte aufgelegt") is None


# ---------------------------------------------------------------------------
# Normalisierung
# ---------------------------------------------------------------------------
def test_normalize_uid_strips_separators_and_uppercases():
    assert _normalize_uid("04-16:ac 12") == "0416AC12"
    assert _normalize_uid("abcdef") == "ABCDEF"
