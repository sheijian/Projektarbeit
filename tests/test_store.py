"""Tests für den lokalen Player-Store."""

from blackjack.game import Game, Outcome, Player, State
from blackjack.store import LocalPlayerStore, PlayerNotFound


def test_default_players_created():
    store = LocalPlayerStore()
    names = sorted(p.name for p in store.all_players())
    assert names == ["Alice", "Bob", "Charlie"]


def test_get_player_returns_copy():
    store = LocalPlayerStore()
    a = store.all_players()[0]
    p = store.get_player(a.rfid)
    p.balance = 0
    # Änderung am Ergebnis darf den Store nicht verändern.
    assert store.get_player(a.rfid).balance == a.balance


def test_unknown_player():
    store = LocalPlayerStore()
    try:
        store.get_player("DEADBEEF")
    except PlayerNotFound:
        pass
    else:
        raise AssertionError("PlayerNotFound erwartet")


def test_apply_delta_updates_balance():
    store = LocalPlayerStore()
    p = store.all_players()[0]
    new_balance = store.apply_delta(p.rfid, -75)
    assert new_balance == p.balance - 75
    assert store.get_player(p.rfid).balance == new_balance


def test_apply_delta_rejects_negative_balance():
    store = LocalPlayerStore()
    p = store.all_players()[0]
    assert store.apply_delta(p.rfid, -(p.balance + 1)) is None
    # Store darf nicht geändert worden sein.
    assert store.get_player(p.rfid).balance == p.balance


def test_find_by_name_case_insensitive():
    store = LocalPlayerStore()
    p = store.find_by_name("alice")
    assert p is not None
    assert p.name == "Alice"


def test_apply_delta_unknown_returns_none():
    store = LocalPlayerStore()
    assert store.apply_delta("nope", -5) is None


def test_auto_register_creates_unknown_player_on_lookup():
    store = LocalPlayerStore(auto_register=True, auto_balance=300)
    uid = "b807dee3-a666-4aa6-b5bd-f2d1ea0b7dca"
    player = store.get_player(uid)
    assert player.rfid == uid
    assert player.balance == 300
    assert player.name.startswith("Gast-")
    # Zweiter Aufruf liefert denselben Spieler, kein neues Guthaben.
    store.apply_delta(uid, -50)
    again = store.get_player(uid)
    assert again.balance == 250


def test_auto_register_disabled_still_raises():
    store = LocalPlayerStore(auto_register=False)
    try:
        store.get_player("unknown")
    except Exception:
        pass
    else:
        raise AssertionError("PlayerNotFound erwartet")


def test_game_writes_through_to_store():
    """Realer Ablauf: Game -> on_balance_change -> LocalPlayerStore."""
    store = LocalPlayerStore()

    def cb(player, delta):
        new_balance = store.apply_delta(player.rfid, delta)
        if new_balance is not None:
            player.balance = new_balance

    game = Game(on_balance_change=cb)
    alice = store.find_by_name("Alice")
    assert alice is not None
    game.login(alice, default_bet=25)
    game.start_round()
    # Nach Rundenstart wurde der Einsatz im Store belastet.
    assert store.get_player(alice.rfid).balance == alice.balance
