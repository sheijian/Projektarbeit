"""Karten und Kartenstapel für Blackjack."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List


SUITS = ("spades", "hearts", "diamonds", "clubs")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")

SUIT_SYMBOLS = {
    "spades":   "♠",   # ♠
    "hearts":   "♥",   # ♥
    "diamonds": "♦",   # ♦
    "clubs":    "♣",   # ♣
}

RED_SUITS = {"hearts", "diamonds"}


@dataclass(frozen=True)
class Card:
    """Eine einzelne Spielkarte."""

    rank: str
    suit: str

    def __post_init__(self) -> None:
        if self.rank not in RANKS:
            raise ValueError(f"Ungültiger Rang: {self.rank}")
        if self.suit not in SUITS:
            raise ValueError(f"Ungültige Farbe: {self.suit}")

    @property
    def is_red(self) -> bool:
        return self.suit in RED_SUITS

    @property
    def symbol(self) -> str:
        return SUIT_SYMBOLS[self.suit]

    @property
    def blackjack_value(self) -> int:
        """Grundwert der Karte für Blackjack (Ass = 11, Bild = 10)."""
        if self.rank == "A":
            return 11
        if self.rank in ("J", "Q", "K"):
            return 10
        return int(self.rank)

    def __str__(self) -> str:
        return f"{self.rank}{self.symbol}"


class Deck:
    """Kartenstapel aus einem oder mehreren Decks."""

    def __init__(self, num_decks: int = 6, rng: random.Random | None = None) -> None:
        if num_decks < 1:
            raise ValueError("Mindestens ein Deck benötigt")
        self.num_decks = num_decks
        self._rng = rng or random.Random()
        self._cards: List[Card] = []
        # Ab wie vielen verbleibenden Karten neu gemischt wird (¼ des Schuhs).
        self._reshuffle_at = (52 * num_decks) // 4
        self.shuffle()

    # ------------------------------------------------------------------
    def shuffle(self) -> None:
        self._cards = [
            Card(rank, suit)
            for _ in range(self.num_decks)
            for suit in SUITS
            for rank in RANKS
        ]
        self._rng.shuffle(self._cards)

    def draw(self) -> Card:
        if not self._cards:
            self.shuffle()
        return self._cards.pop()

    def maybe_reshuffle(self) -> bool:
        """Mischt neu, wenn der Schuh zu weit heruntergespielt wurde."""
        if len(self._cards) <= self._reshuffle_at:
            self.shuffle()
            return True
        return False

    def __len__(self) -> int:
        return len(self._cards)
