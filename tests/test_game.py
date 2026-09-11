"""Tests für den Blackjack-Zustandsautomaten."""

import random

from blackjack.cards import Card, Deck
from blackjack.game import Game, Outcome, Player, State


class StackedDeck(Deck):
    """Deck, das eine feste Reihenfolge aus dem Stapel liefert (top = letzte)."""

    def __init__(self, cards):
        # cards ist Reihenfolge, in der gezogen wird.
        self.num_decks = 1
        self._rng = random.Random(0)
        self._cards = list(reversed(cards))
        self._reshuffle_at = 0

    def shuffle(self):
        pass

    def maybe_reshuffle(self):
        return False


def make_game(sequence):
    """Erzeugt ein Game mit vorgegebener Kartenreihenfolge."""
    game = Game()
    game.deck = StackedDeck(sequence)
    return game


def C(rank, suit="spades"):
    return Card(rank, suit)


def test_player_wins_when_dealer_busts():
    #      Spieler          Dealer
    # 1.   K                6
    # 2.   9                10
    # Dealer zieht: Q (bust: 26).
    sequence = [C("K"), C("6"), C("9"), C("10"), C("Q")]
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 200), default_bet=50)
    game.start_round()
    game.stand()
    assert game.state == State.ROUND_OVER
    assert game.results[0].outcome == Outcome.WIN
    assert game.player.balance == 250


def test_player_busts_and_loses_bet():
    sequence = [C("K"), C("6"), C("Q"), C("10"), C("J")]  # Spieler 20+J
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 100), default_bet=25)
    game.start_round()
    game.hit()
    assert game.hands[0].is_bust
    assert game.state == State.ROUND_OVER
    assert game.results[0].outcome == Outcome.LOSE
    assert game.player.balance == 75


def test_blackjack_pays_three_to_two():
    sequence = [C("A"), C("9"), C("K"), C("7")]
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 100), default_bet=20)
    game.start_round()
    # Spieler hat Blackjack → sofort in ROUND_OVER.
    assert game.state == State.ROUND_OVER
    r = game.results[0]
    assert r.outcome == Outcome.BLACKJACK
    # 20 Einsatz, Rückzahlung 20 + 30 = 50
    assert r.payout == 50
    assert game.player.balance == 100 - 20 + 50


def test_double_draws_one_card_and_ends_hand():
    #  Spieler:  5, 9  → Double, zieht 7 → 21
    #  Dealer:   K, 8  → 18
    sequence = [C("5"), C("K"), C("9"), C("8"), C("7")]
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 100), default_bet=20)
    game.start_round()
    game.double()
    assert game.state == State.ROUND_OVER
    r = game.results[0]
    assert r.bet == 40
    assert r.outcome == Outcome.WIN
    # Spielverlauf: -20 (Einsatz), -20 (Double), +80 (Auszahlung) = +40
    assert game.player.balance == 140


def test_push_returns_bet():
    # Beide 20.
    sequence = [C("K"), C("K"), C("Q"), C("Q")]
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 100), default_bet=25)
    game.start_round()
    game.stand()
    assert game.results[0].outcome == Outcome.PUSH
    assert game.player.balance == 100


def test_split_creates_two_hands():
    # Beide Startkarten Achten → Split.
    # Erst geteilte Hand 1 bekommt eine 3 (→ 11 → stand),
    # dann Hand 2 bekommt eine 2 (→ 10 → stand).
    # Dealer:  10, 7  → 17
    sequence = [
        C("8"), C("10"),   # Deal Spieler / Dealer
        C("8"), C("7"),    # Deal Spieler / Dealer
        C("3"),            # Nach Split für Hand 1
        C("2"),            # Nach Split für Hand 2
    ]
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 200), default_bet=20)
    game.start_round()
    game.split()
    assert len(game.hands) == 2
    # Hand 1 (Wert 11) → stand
    game.stand()
    # Hand 2 (Wert 10) → stand
    game.stand()
    assert game.state == State.ROUND_OVER
    # Beide unter dem Dealer → zwei Verluste.
    outcomes = [r.outcome for r in game.results]
    assert outcomes == [Outcome.LOSE, Outcome.LOSE]
    # Guthaben: 200 - 20 - 20 = 160
    assert game.player.balance == 160


def test_split_of_aces_gets_only_one_card_each():
    sequence = [
        C("A"), C("9"),
        C("A"), C("8"),
        C("5"),  # Hand 1
        C("6"),  # Hand 2
    ]
    game = make_game(sequence)
    game.login(Player("uid", "Tester", 200), default_bet=20)
    game.start_round()
    game.split()
    # Nach Ass-Split sind beide Hände automatisch fertig.
    assert game.state == State.ROUND_OVER
    # Beide Hände haben nur 2 Karten bekommen.
    for hand in game.hands:
        assert len(hand.cards) == 2


def test_balance_callback_receives_delta():
    seen = []

    def cb(player, delta):
        seen.append(delta)

    game = Game(on_balance_change=cb)
    game.deck = StackedDeck([C("K"), C("K"), C("Q"), C("Q")])
    game.login(Player("uid", "Tester", 100), default_bet=25)
    game.start_round()
    game.stand()  # push
    # -25 (Einsatz) und +25 (Push-Rückzahlung)
    assert sum(seen) == 0
    assert seen[0] == -25
