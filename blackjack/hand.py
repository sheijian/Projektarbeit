"""Blackjack-Hand mit Punktebewertung, Split- und Double-Zuständen."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from .cards import Card


@dataclass
class Hand:
    """Eine Spielhand mit Einsatz und Blackjack-Wertung.

    Jede Karte hat einen `deal_at`-Zeitpunkt (monotonic), ab dem sie sichtbar
    sein soll. Die Logik selbst ist synchron - die Zeitstempel dienen nur der
    GUI, damit Karten einzeln ausgeteilt aussehen.
    """

    cards: List[Card] = field(default_factory=list)
    deal_times: List[float] = field(default_factory=list)
    bet: int = 0
    doubled: bool = False
    stood: bool = False
    surrendered: bool = False
    from_split: bool = False
    split_aces: bool = False

    def __post_init__(self) -> None:
        # Falls beim Konstruieren Karten übergeben wurden, aber keine deal_times,
        # sind die Karten sofort sichtbar.
        if len(self.deal_times) < len(self.cards):
            now = time.monotonic()
            missing = len(self.cards) - len(self.deal_times)
            self.deal_times.extend([now] * missing)

    # ------------------------------------------------------------------
    # Grundoperationen
    # ------------------------------------------------------------------
    def add(self, card: Card, deal_at: Optional[float] = None) -> None:
        self.cards.append(card)
        self.deal_times.append(
            deal_at if deal_at is not None else time.monotonic()
        )

    def clear(self) -> None:
        self.cards.clear()
        self.deal_times.clear()
        self.bet = 0
        self.doubled = False
        self.stood = False
        self.surrendered = False
        self.from_split = False
        self.split_aces = False

    def visible_count(self, now: Optional[float] = None) -> int:
        """Anzahl der Karten, die zum Zeitpunkt `now` bereits sichtbar sind."""
        if now is None:
            now = time.monotonic()
        return sum(1 for t in self.deal_times if t <= now)

    def all_revealed(self, now: Optional[float] = None) -> bool:
        return self.visible_count(now) == len(self.cards)

    # ------------------------------------------------------------------
    # Bewertung
    # ------------------------------------------------------------------
    @property
    def value(self) -> int:
        """Bester Blackjack-Wert (Asse werden bei Bedarf von 11 auf 1 gezählt)."""
        return self._value_of(self.cards)

    @staticmethod
    def _value_of(cards: List[Card]) -> int:
        total = sum(c.blackjack_value for c in cards)
        aces = sum(1 for c in cards if c.rank == "A")
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return total

    def visible_value(self, now: Optional[float] = None) -> int:
        """Wert nur über die bereits sichtbaren Karten - für die GUI."""
        return self._value_of(self.cards[: self.visible_count(now)])

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
