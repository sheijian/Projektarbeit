"""Blackjack-Hand mit Punktebewertung, Split- und Double-Zuständen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .cards import Card


@dataclass
class Hand:
    """Eine Spielhand mit Einsatz und Blackjack-Wertung."""

    cards: List[Card] = field(default_factory=list)
    bet: int = 0
    doubled: bool = False
    stood: bool = False
    surrendered: bool = False
    from_split: bool = False
    split_aces: bool = False

    # ------------------------------------------------------------------
    # Grundoperationen
    # ------------------------------------------------------------------
    def add(self, card: Card) -> None:
        self.cards.append(card)

    def clear(self) -> None:
        self.cards.clear()
        self.bet = 0
        self.doubled = False
        self.stood = False
        self.surrendered = False
        self.from_split = False
        self.split_aces = False

    # ------------------------------------------------------------------
    # Bewertung
    # ------------------------------------------------------------------
    @property
    def value(self) -> int:
        """Bester Blackjack-Wert (Asse werden bei Bedarf von 11 auf 1 gezählt)."""
        total = sum(c.blackjack_value for c in self.cards)
        aces = sum(1 for c in self.cards if c.rank == "A")
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return total

    @property
    def is_soft(self) -> bool:
        """True, wenn ein Ass als 11 zählt (also ohne Bust downgraden)."""
        total = sum(c.blackjack_value for c in self.cards)
        aces = sum(1 for c in self.cards if c.rank == "A")
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return aces > 0 and total <= 21 and any(c.rank == "A" for c in self.cards)

    @property
    def is_bust(self) -> bool:
        return self.value > 21

    @property
    def is_blackjack(self) -> bool:
        # Nur eine "natürliche" 21 aus den ersten zwei Karten zählt als Blackjack.
        return (
            len(self.cards) == 2
            and self.value == 21
            and not self.from_split
        )

    @property
    def can_double(self) -> bool:
        return len(self.cards) == 2 and not self.doubled and not self.stood

    @property
    def can_split(self) -> bool:
        if len(self.cards) != 2 or self.doubled or self.stood:
            return False
        a, b = self.cards
        # Split auf gleichem Wert (also z. B. auch 10 und Bube).
        return a.blackjack_value == b.blackjack_value

    @property
    def is_done(self) -> bool:
        return self.stood or self.is_bust or self.surrendered or self.value == 21

    # ------------------------------------------------------------------
    def __str__(self) -> str:
        cards = " ".join(str(c) for c in self.cards)
        return f"[{cards}] = {self.value}"
