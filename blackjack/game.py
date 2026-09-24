"""Blackjack-Zustandsautomat.

Der Ablauf einer Runde:

    NO_PLAYER  -> RFID scannen, Guthaben laden
        -> BETTING       -> Einsatz per Hit-Taste hochzählen (zyklisch), Stand = Deal
        -> DEALING       -> Karten austeilen (nur GUI-Animation, Logik ist synchron)
        -> PLAYER_TURN   -> Hit / Stand / Double / Split
        -> DEALER_TURN
        -> RESOLVING     -> Gewinn / Verlust
        -> ROUND_OVER    -> Auszahlung, neue Runde möglich
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional, Tuple

from .cards import Deck
from .hand import Hand


class State(Enum):
    NO_PLAYER = auto()
    BETTING = auto()
    DEALING = auto()
    PLAYER_TURN = auto()
    DEALER_TURN = auto()
    RESOLVING = auto()
    ROUND_OVER = auto()


class Outcome(Enum):
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"
    BLACKJACK = "blackjack"


# ---------------------------------------------------------------------------
# Verfügbare Einsatzstufen. Die Hit-Taste zyklt durch die Werte, die zum
# aktuellen Guthaben passen, und startet danach wieder beim kleinsten.
BET_STEPS: Tuple[int, ...] = (10, 25, 50, 100, 250, 500, 1000)


# ---------------------------------------------------------------------------
# Timing (Sekunden) - nur für die GUI-Animation. Die Logik ist synchron.
DEAL_INTERVAL = 0.35        # zwischen zwei Karten beim Austeilen
HIT_DELAY = 0.20            # Verzögerung für eine einzelne Hit-/Double-Karte
DEALER_INTERVAL = 0.55      # zwischen Dealer-Karten
FLIP_DELAY = 0.35           # kleiner Puffer vor dem Aufdecken der Hole-Card


@dataclass
class Player:
    rfid: str
    name: str
    balance: int


@dataclass
class RoundResult:
    hand_index: int
    outcome: Outcome
    bet: int
    payout: int   # das, was der Spieler erhält (Einsatz + Gewinn), 0 bei Verlust

    @property
    def delta(self) -> int:
        return self.payout - self.bet


# ---------------------------------------------------------------------------
class Game:
    """Kapselt eine Blackjack-Runde inklusive Split-Händen und Dealer."""

    def __init__(
        self,
        num_decks: int = 6,
        min_bet: int = 10,
        on_balance_change: Optional[Callable[[Player, int], None]] = None,
    ) -> None:
        self.deck = Deck(num_decks=num_decks)
        self.min_bet = min_bet
        self.player: Optional[Player] = None
        self.hands: List[Hand] = []
        self.dealer: Hand = Hand()
        self.active_hand: int = 0
        self.state: State = State.NO_PLAYER
        self.current_bet: int = 0
        self.results: List[RoundResult] = []
        self.message: str = "Bitte RFID-Chip auflegen"
        self.on_balance_change = on_balance_change
        # Für die Deal-Animation: nächstmöglicher Aufdeck-Zeitpunkt.
        self._next_deal_at: float = 0.0
        # Session-Statistik: wieviele Runden hat der aktuelle Spieler
        # gespielt und wieviele davon mit Netto-Gewinn abgeschlossen.
        self.session_plays: int = 0
        self.session_wins: int = 0

    # ------------------------------------------------------------------
    # Spieler-Session
    # ------------------------------------------------------------------
    def login(self, player: Player, default_bet: int) -> None:
        self.player = player
        self.current_bet = self._closest_bet(default_bet)
        self.hands = []
        self.dealer = Hand()
        self.active_hand = 0
        self.results = []
        self.session_plays = 0
        self.session_wins = 0
        if player.balance < self.min_bet:
            self.state = State.NO_PLAYER
            self.message = "Guthaben zu niedrig"
        else:
            self.state = State.BETTING
            self.message = f"Willkommen {player.name}! Einsatz: {self.current_bet}"

    def logout(self) -> None:
        self.player = None
        self.hands = []
        self.dealer = Hand()
        self.state = State.NO_PLAYER
        self.message = "Bitte RFID-Chip auflegen"
        self.session_plays = 0
        self.session_wins = 0

    # ------------------------------------------------------------------
    # Runden-Start
    # ------------------------------------------------------------------
    def start_round(self) -> None:
        if self.state not in (State.BETTING, State.ROUND_OVER):
            return
        assert self.player is not None
        if self.player.balance < self.current_bet:
            self.message = "Zu wenig Guthaben"
            return

        self.deck.maybe_reshuffle()
        # Einsatz vom Guthaben abziehen (wird bei Auszahlung wieder gutgeschrieben).
        self._change_balance(-self.current_bet)
        self.hands = [Hand(bet=self.current_bet)]
        self.dealer = Hand()
        self.active_hand = 0
        self.results = []
        self.state = State.DEALING
        self.message = "Karten werden ausgeteilt …"

        # Deal-Animation zurücksetzen und die vier Startkarten mit gestaffelten
        # Zeitpunkten registrieren - die GUI blendet sie einzeln ein.
        self._next_deal_at = time.monotonic()
        # Klassisches Deal: Spieler, Dealer, Spieler, Dealer.
        self.hands[0].add(self.deck.draw(), deal_at=self._schedule(DEAL_INTERVAL))
        self.dealer.add(self.deck.draw(),   deal_at=self._schedule(DEAL_INTERVAL))
        self.hands[0].add(self.deck.draw(), deal_at=self._schedule(DEAL_INTERVAL))
        self.dealer.add(self.deck.draw(),   deal_at=self._schedule(DEAL_INTERVAL))

        self._enter_player_turn()

    # ------------------------------------------------------------------
    # Aktionen des Spielers
    # ------------------------------------------------------------------
    def hit(self) -> None:
        if self.state in (State.BETTING, State.ROUND_OVER):
            # Außerhalb einer Runde: Einsatz zyklisch erhöhen.
            self.cycle_bet()
            return
        if self.state != State.PLAYER_TURN:
            return
        hand = self.hands[self.active_hand]
        hand.add(self.deck.draw(), deal_at=self._schedule(HIT_DELAY))
        if hand.is_done:
            self._advance_hand()

    def stand(self) -> None:
        if self.state in (State.BETTING, State.ROUND_OVER):
            # Außerhalb einer Runde startet Stand die nächste Runde.
            self.start_round()
            return
        if self.state != State.PLAYER_TURN:
            return
        self.hands[self.active_hand].stood = True
        self._advance_hand()

    def double(self) -> None:
        if self.state != State.PLAYER_TURN:
            return
        assert self.player is not None
        hand = self.hands[self.active_hand]
        if not hand.can_double:
            self.message = "Double nicht möglich"
            return
        if self.player.balance < hand.bet:
            self.message = "Guthaben zu niedrig für Double"
            return
        self._change_balance(-hand.bet)
        hand.bet *= 2
        hand.doubled = True
        hand.add(self.deck.draw(), deal_at=self._schedule(HIT_DELAY))
        hand.stood = True
        self._advance_hand()

    def split(self) -> None:
        if self.state != State.PLAYER_TURN:
            return
        assert self.player is not None
        hand = self.hands[self.active_hand]
        if not hand.can_split:
            self.message = "Split nicht möglich"
            return
        if self.player.balance < hand.bet:
            self.message = "Guthaben zu niedrig für Split"
            return

        self._change_balance(-hand.bet)
        card_a, card_b = hand.cards
        aces = card_a.rank == "A"

        # Die ursprünglichen Zeitstempel beibehalten, damit die "geteilten"
        # Karten sofort sichtbar bleiben.
        t_a, t_b = hand.deal_times

        new_hand = Hand(
            cards=[card_b], deal_times=[t_b],
            bet=hand.bet, from_split=True, split_aces=aces,
        )
        hand.cards = [card_a]
        hand.deal_times = [t_a]
        hand.from_split = True
        hand.split_aces = aces

        # Neue Karte für beide Hälften ziehen - versetzt aufgedeckt.
        hand.add(self.deck.draw(), deal_at=self._schedule(HIT_DELAY))
        new_hand.add(self.deck.draw(), deal_at=self._schedule(HIT_DELAY))

        self.hands.insert(self.active_hand + 1, new_hand)

        # Splitting von Assen bekommt nur eine weitere Karte pro Hand.
        if aces:
            hand.stood = True
            new_hand.stood = True
            self._advance_hand()
            return

        if hand.is_done:
            self._advance_hand()
        else:
            self.message = f"Hand {self.active_hand + 1}/{len(self.hands)}"

    # ------------------------------------------------------------------
    # Einsatz (zyklische Schaltfläche)
    # ------------------------------------------------------------------
    def cycle_bet(self) -> None:
        """Springt zum nächsten Einsatz aus BET_STEPS. Nach dem größten geht's
        wieder auf den kleinsten - so reicht ein einziger Knopf."""
        if self.state not in (State.BETTING, State.ROUND_OVER) or self.player is None:
            return
        options = self._available_bets()
        if not options:
            self.message = "Guthaben zu niedrig"
            return

        try:
            idx = options.index(self.current_bet)
            next_idx = (idx + 1) % len(options)
        except ValueError:
            # Aktueller Einsatz nicht in der Liste - nimm die kleinste Option.
            next_idx = 0

        self.current_bet = options[next_idx]
        self.message = f"Einsatz: {self.current_bet}"

    def _available_bets(self) -> List[int]:
        assert self.player is not None
        return [b for b in BET_STEPS if self.min_bet <= b <= self.player.balance]

    def _closest_bet(self, wanted: int) -> int:
        """Wählt die BET_STEPS-Stufe, die dem Wunschwert am nächsten kommt."""
        assert self.player is not None
        options = self._available_bets()
        if not options:
            # Fallback: min_bet, auch wenn das Guthaben eigentlich zu niedrig ist.
            return self.min_bet
        return min(options, key=lambda b: abs(b - wanted))

    # ------------------------------------------------------------------
    # Interne Übergänge
    # ------------------------------------------------------------------
    def _schedule(self, interval: float) -> float:
        """Liefert den Zeitpunkt, an dem die nächste Karte aufgedeckt werden soll."""
        now = time.monotonic()
        self._next_deal_at = max(self._next_deal_at, now) + interval
        return self._next_deal_at

    def _enter_player_turn(self) -> None:
        self.state = State.PLAYER_TURN
        self.message = "Dein Zug"
        # Sofortiger Blackjack?
        if self.hands[0].is_blackjack:
            self._advance_hand()

    def _advance_hand(self) -> None:
        for idx in range(self.active_hand, len(self.hands)):
            if not self.hands[idx].is_done:
                self.active_hand = idx
                self.state = State.PLAYER_TURN
                if len(self.hands) > 1:
                    self.message = f"Hand {idx + 1}/{len(self.hands)}"
                else:
                    self.message = "Dein Zug"
                return
        # Alle Hände durch → Dealer.
        self._dealer_turn()

    def _dealer_turn(self) -> None:
        self.state = State.DEALER_TURN
        self.message = "Dealer spielt"

        any_alive = any(not h.is_bust and not h.surrendered for h in self.hands)
        all_blackjack = all(
            h.is_blackjack or h.is_bust or h.surrendered for h in self.hands
        )
        if any_alive and not all_blackjack:
            # kleiner Puffer, damit die Hole-Card sichtbar aufgedeckt aussieht.
            self._schedule(FLIP_DELAY)
            # Dealer zieht bis mindestens 17 (Stand auf Soft 17).
            while self.dealer.value < 17:
                self.dealer.add(
                    self.deck.draw(),
                    deal_at=self._schedule(DEALER_INTERVAL),
                )
        self._resolve()

    def _resolve(self) -> None:
        self.state = State.RESOLVING
        self.results = []
        dealer_value = self.dealer.value
        dealer_bj = self.dealer.is_blackjack
        dealer_bust = self.dealer.is_bust

        for idx, hand in enumerate(self.hands):
            outcome, payout = self._settle(hand, dealer_value, dealer_bj, dealer_bust)
            self.results.append(RoundResult(idx, outcome, hand.bet, payout))
            if payout > 0:
                self._change_balance(payout)

        # Session-Statistik: eine Runde weiter, Sieg bei Netto-Delta > 0.
        self.session_plays += 1
        if sum(r.delta for r in self.results) > 0:
            self.session_wins += 1

        self.state = State.ROUND_OVER
        self.message = self._summary_message()

    def _settle(
        self, hand: Hand, dealer_value: int, dealer_bj: bool, dealer_bust: bool
    ) -> tuple[Outcome, int]:
        if hand.surrendered:
            return Outcome.LOSE, hand.bet // 2
        if hand.is_bust:
            return Outcome.LOSE, 0
        if hand.is_blackjack and not dealer_bj:
            return Outcome.BLACKJACK, hand.bet + int(hand.bet * 1.5)
        if dealer_bj and not hand.is_blackjack:
            return Outcome.LOSE, 0
        if dealer_bust or hand.value > dealer_value:
            return Outcome.WIN, hand.bet * 2
        if hand.value < dealer_value:
            return Outcome.LOSE, 0
        return Outcome.PUSH, hand.bet

    def _summary_message(self) -> str:
        if not self.results:
            return ""
        delta = sum(r.delta for r in self.results)
        if delta > 0:
            return f"Gewonnen: +{delta}"
        if delta < 0:
            return f"Verloren: {delta}"
        return "Unentschieden"

    # ------------------------------------------------------------------
    # GUI-Helfer
    # ------------------------------------------------------------------
    def all_cards_revealed(self, now: Optional[float] = None) -> bool:
        """True, wenn alle Karten aller Hände und des Dealers sichtbar sind."""
        hands = [self.dealer, *self.hands]
        return all(h.all_revealed(now) for h in hands)

    def _change_balance(self, delta: int) -> None:
        if self.player is None:
            return
        self.player.balance += delta
        if self.on_balance_change is not None:
            self.on_balance_change(self.player, delta)
