"""Tests für den zyklischen Einsatz-Knopf und die Deal-Timestamps."""

import time

from blackjack.cards import Card
from blackjack.game import BET_STEPS, Game, Player, State
from tests.test_game import C, StackedDeck, make_game


# ---------------------------------------------------------------------------
# Zyklischer Einsatz
# ---------------------------------------------------------------------------
def test_hit_in_betting_cycles_through_bets():
    game = Game()
    game.login(Player("uid", "Tester", 300), default_bet=10)
    assert game.state == State.BETTING
    assert game.current_bet == 10

    # Bei balance=300 sind nur Stufen 10, 25, 50, 100, 250 nutzbar.
    expected_cycle = [b for b in BET_STEPS if b <= 300]
    assert expected_cycle == [10, 25, 50, 100, 250]

    seen = [game.current_bet]
    for _ in range(len(expected_cycle) * 2):
        game.hit()
        seen.append(game.current_bet)

    # Nach genau einer Runde muss der niedrigste Einsatz wieder erreicht sein.
    assert seen[0] == 10
    assert seen[len(expected_cycle)] == 10
    # Und die Reihenfolge entspricht BET_STEPS.
    assert seen[: len(expected_cycle)] == expected_cycle


def test_cycle_bet_wraps_to_smallest():
    game = Game()
    game.login(Player("uid", "Tester", 1000), default_bet=10)
    game.current_bet = 1000
    game.cycle_bet()
    assert game.current_bet == 10


def test_cycle_bet_skips_bets_over_balance():
    game = Game()
    game.login(Player("uid", "Tester", 60), default_bet=10)
    # Bei balance=60 gibt es nur 10, 25, 50 - kein 100+
    cycle = []
    for _ in range(6):
        cycle.append(game.current_bet)
        game.hit()
    assert set(cycle) <= {10, 25, 50}
    assert 100 not in cycle


def test_stand_in_betting_starts_the_round():
    game = make_game([C("K"), C("6"), C("9"), C("10")])
    game.login(Player("uid", "Tester", 100), default_bet=25)
    assert game.state == State.BETTING
    game.stand()
    # Nach dem "DEAL" via Stand-Taste sind wir mitten in einer Runde.
    assert game.state == State.PLAYER_TURN
    assert len(game.hands[0].cards) == 2


# ---------------------------------------------------------------------------
# Deal-Timestamps: Karten haben unterschiedliche deal_at-Zeiten
# ---------------------------------------------------------------------------
def test_start_round_stages_deal_times():
    game = make_game([C("K"), C("6"), C("9"), C("10")])
    game.login(Player("uid", "Tester", 100), default_bet=25)
    game.start_round()
    # Spielerhand hat zwei aufsteigende deal_times.
    p = game.hands[0]
    assert len(p.deal_times) == 2
    assert p.deal_times[0] < p.deal_times[1]
    # Dealer ebenfalls.
    d = game.dealer
    assert len(d.deal_times) == 2
    assert d.deal_times[0] < d.deal_times[1]
    # Die vier Stempel entstehen abwechselnd (Spieler, Dealer, Spieler, Dealer),
    # also muss deal_times[0] Spieler < deal_times[0] Dealer < ... gelten.
    assert p.deal_times[0] < d.deal_times[0] < p.deal_times[1] < d.deal_times[1]


def test_hit_card_is_scheduled_after_all_prior():
    game = make_game([C("K"), C("6"), C("9"), C("10"), C("5")])
    game.login(Player("uid", "Tester", 100), default_bet=25)
    game.start_round()
    last_time = game.hands[0].deal_times[-1]
    game.hit()
    assert game.hands[0].deal_times[-1] > last_time


def test_all_cards_revealed_after_wait():
    game = make_game([C("K"), C("6"), C("9"), C("10")])
    game.login(Player("uid", "Tester", 100), default_bet=25)
    game.start_round()
    # Direkt nach start_round liegen die deal_times in der Zukunft.
    assert not game.all_cards_revealed()
    # Nach ausreichend "Zeit" (indem wir die Vergleichs-Zeit vorspulen)
    # sind alle Karten sichtbar.
    future = max(game.dealer.deal_times[-1], game.hands[0].deal_times[-1]) + 0.01
    assert game.all_cards_revealed(future)
