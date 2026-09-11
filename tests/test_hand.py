"""Tests für die Blackjack-Wertung."""

from blackjack.cards import Card
from blackjack.hand import Hand


def h(*cards: str) -> Hand:
    """Kurzschreibweise: 'Ah', '10s', 'Kd', 'T' wird auf '10' gemappt."""
    result = Hand()
    for spec in cards:
        rank = spec[:-1]
        if rank == "T":
            rank = "10"
        suit = {"s": "spades", "h": "hearts", "d": "diamonds", "c": "clubs"}[spec[-1]]
        result.add(Card(rank, suit))
    return result


def test_number_cards_sum():
    hand = h("5s", "7d")
    assert hand.value == 12
    assert not hand.is_bust
    assert not hand.is_blackjack


def test_face_cards_count_as_ten():
    hand = h("Ks", "Qs")
    assert hand.value == 20


def test_ace_counts_as_eleven_when_it_fits():
    hand = h("Ah", "6c")
    assert hand.value == 17
    assert hand.is_soft


def test_ace_downgrades_to_avoid_bust():
    hand = h("Ah", "6c", "Jd")
    assert hand.value == 17
    assert not hand.is_bust
    assert not hand.is_soft


def test_two_aces():
    hand = h("Ah", "As")
    assert hand.value == 12
    assert hand.is_soft


def test_bust():
    hand = h("Ks", "9c", "5d")
    assert hand.value == 24
    assert hand.is_bust


def test_blackjack_only_from_first_two():
    natural = h("Ah", "Ks")
    assert natural.is_blackjack

    three_card_21 = h("5s", "6h", "Th")
    assert three_card_21.value == 21
    assert not three_card_21.is_blackjack


def test_can_split_on_equal_value():
    assert h("Ts", "Jh").can_split
    assert h("8s", "8h").can_split
    assert not h("9s", "8h").can_split


def test_can_double_only_on_two_cards():
    assert h("5s", "6h").can_double
    hand = h("5s", "6h", "Kc")
    assert not hand.can_double
