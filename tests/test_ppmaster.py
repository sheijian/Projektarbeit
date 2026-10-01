"""Tests für die reinen Helfer des PPMasterStore.

Die HTTP-Aufrufe selbst werden hier nicht getestet - nur die Bausteine,
die ohne Netzwerk funktionieren müssen (Flux-CSV-Parser, Escaping,
Session-Statistik im Game).
"""

import random

from blackjack.cards import Card
from blackjack.db_config import InfluxConfig
from blackjack.game import Game, Player
from blackjack.ppmaster_store import (
    PPMasterStore,
    _escape_flux_string,
    _escape_line_protocol_tag,
    _parse_flux_sum_csv,
)
from tests.test_game import StackedDeck


_TEST_CFG = InfluxConfig(
    url="http://example.local",
    org="o",
    bucket="b",
    bucket_id="bi",
    token_read="tr",
    token_write="tw",
)


def C(rank, suit="spades"):
    return Card(rank, suit)


# ---------------------------------------------------------------------------
# Line-Protocol / Flux-Escaping
# ---------------------------------------------------------------------------
def test_escape_line_protocol_tag_spaces_and_commas():
    assert _escape_line_protocol_tag("Alice, the great player") \
        == r"Alice\,\ the\ great\ player"


def test_escape_line_protocol_tag_equals():
    assert _escape_line_protocol_tag("Bob=One") == r"Bob\=One"


def test_escape_flux_string_quotes():
    assert _escape_flux_string('Alice "AA"') == r'Alice \"AA\"'


# ---------------------------------------------------------------------------
# Flux-CSV-Parser: liest den `_value` aus einer `|> sum()`-Antwort
# ---------------------------------------------------------------------------
FLUX_CSV_TWO_TABLES = (
    "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,long,string,string,string\r\n"
    "#group,false,false,true,true,false,true,true,true\r\n"
    "#default,_result,,,,,,,\r\n"
    ",result,table,_start,_stop,_value,_field,_measurement,rfidTag\r\n"
    ",,0,2026-09-17T00:00:00Z,2026-09-17T01:00:00Z,180,score,endscore,Alice\r\n"
)


def test_parse_flux_sum_extracts_value():
    assert _parse_flux_sum_csv(FLUX_CSV_TWO_TABLES) == 180


def test_parse_flux_sum_empty_returns_none():
    csv_only_headers = (
        "#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,long,string,string,string\r\n"
        "#group,false,false,true,true,false,true,true,true\r\n"
        "#default,_result,,,,,,,\r\n"
        ",result,table,_start,_stop,_value,_field,_measurement,rfidTag\r\n"
    )
    assert _parse_flux_sum_csv(csv_only_headers) is None


def test_parse_flux_sum_completely_empty():
    assert _parse_flux_sum_csv("") is None


def test_parse_flux_sum_sums_multiple_tables():
    csv = (
        "#datatype,string,long,long\r\n"
        "#group,false,false,false\r\n"
        "#default,_result,,\r\n"
        ",result,table,_value\r\n"
        ",,0,100\r\n"
        ",,1,80\r\n"
    )
    assert _parse_flux_sum_csv(csv) == 180


# ---------------------------------------------------------------------------
# Session-Statistik im Game
# ---------------------------------------------------------------------------
def make_game(sequence):
    g = Game()
    g.deck = StackedDeck(sequence)
    return g


def test_session_counts_wins_and_plays():
    # Runde 1: Spieler K,9 (19), Dealer 6,10 → Dealer zieht Q (26 bust) → WIN
    seq = [
        C("K"), C("6"), C("9"), C("10"), C("Q"),
    ]
    game = make_game(seq)
    game.login(Player("uid", "Alice", 500), default_bet=25)
    game.start_round()
    game.stand()
    assert game.session_plays == 1
    assert game.session_wins == 1


def test_session_counts_bust_as_no_win():
    seq = [C("K"), C("6"), C("Q"), C("10"), C("J")]  # Spieler bust
    game = make_game(seq)
    game.login(Player("uid", "Bob", 500), default_bet=25)
    game.start_round()
    game.hit()
    assert game.session_plays == 1
    assert game.session_wins == 0


def test_session_push_is_no_win():
    seq = [C("K"), C("K"), C("Q"), C("Q")]  # beide 20 → push
    game = make_game(seq)
    game.login(Player("uid", "Carol", 500), default_bet=25)
    game.start_round()
    game.stand()
    assert game.session_plays == 1
    assert game.session_wins == 0


def test_session_reset_on_logout():
    seq = [C("K"), C("6"), C("9"), C("10"), C("Q")]
    game = make_game(seq)
    game.login(Player("uid", "Alice", 500), default_bet=25)
    game.start_round()
    game.stand()
    assert game.session_plays == 1
    game.logout()
    assert game.session_plays == 0
    assert game.session_wins == 0


# ---------------------------------------------------------------------------
# Startguthaben wenn der Spieler noch keine Punkte im Bucket hat
# ---------------------------------------------------------------------------
class _FakeStore(PPMasterStore):
    """Umgeht den HTTP-Call, damit wir die get_player()-Logik testen können."""

    def __init__(self, sum_result, starting_balance=0):
        # Minimaler Setup ohne __init__ des Elterns.
        self.config = _TEST_CFG
        self.starting_balance = starting_balance
        self._session = None
        self._start_balances = {}
        self._sum_result = sum_result

    def _sum_score(self, rfid_tag):
        return self._sum_result


def test_get_player_returns_starting_balance_when_bucket_empty():
    store = _FakeStore(sum_result=None, starting_balance=250)
    player = store.get_player("Jonathan")
    assert player.rfid == "Jonathan"
    assert player.balance == 250
    # Für finalize_session wird der Start als Baseline gemerkt.
    assert store._start_balances["Jonathan"] == 250


def test_get_player_defaults_to_zero_without_starting_balance():
    store = _FakeStore(sum_result=None)
    player = store.get_player("NeuerSpieler")
    assert player.balance == 0


def test_get_player_uses_db_sum_when_present():
    store = _FakeStore(sum_result=180, starting_balance=1000)
    player = store.get_player("Alice")
    # DB hat Punkte - das Startguthaben wird NICHT addiert.
    assert player.balance == 180
    assert store._start_balances["Alice"] == 180
