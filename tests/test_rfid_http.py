"""Tests für den UID-Extractor des HTTP-RFID-Readers."""

from blackjack.rfid import _extract_uid, _normalize_uid


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
