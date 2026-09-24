"""Player-Store-Abstraktion.

Der Rest der Anwendung hängt nur an dieser Schnittstelle - so kann derselbe
Code entweder gegen die HTTP-API laufen oder gegen einen lokalen In-Memory-
Store (Offline-Modus, z. B. für Tests ohne Server und ohne RFID-Hardware).
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, Optional, Protocol

from .config import MOCK_RFID_KEYS
from .game import Player


log = logging.getLogger(__name__)


class PlayerNotFound(Exception):
    """UID/Name ist dem Store unbekannt."""


class StoreError(Exception):
    """Allgemeiner Store-Fehler (z. B. Verbindungsproblem)."""


# ---------------------------------------------------------------------------
class PlayerStore(Protocol):
    """Gemeinsame Schnittstelle für API-Client und lokalen Store."""

    def get_player(self, rfid_uid: str) -> Player: ...
    def apply_delta(self, rfid_uid: str, delta: int) -> Optional[int]: ...


# ---------------------------------------------------------------------------
class LocalPlayerStore:
    """In-Memory-Player-Datenbank für den Offline-Modus.

    Beim Instanziieren werden drei Testspieler angelegt, deren UIDs zu den
    Mock-RFID-Chips (Tasten 1/2/3) passen. So lässt sich die komplette
    Anwendung auch ohne API-Server und ohne RFID-Hardware testen.
    """

    DEFAULT_PLAYERS = (
        (MOCK_RFID_KEYS["1"], "Alice",   500),
        (MOCK_RFID_KEYS["2"], "Bob",     250),
        (MOCK_RFID_KEYS["3"], "Charlie", 1000),
    )

    def __init__(
        self,
        players: Iterable[tuple[str, str, int]] | None = None,
        auto_register: bool = False,
        auto_balance: int = 500,
    ) -> None:
        self._players: Dict[str, Player] = {}
        for rfid, name, balance in (players or self.DEFAULT_PLAYERS):
            self._players[rfid] = Player(rfid=rfid, name=name, balance=balance)
        self._auto_register = auto_register
        self._auto_balance = auto_balance

    # ------------------------------------------------------------------
    def get_player(self, rfid_uid: str) -> Player:
        p = self._players.get(rfid_uid)
        if p is None:
            if self._auto_register:
                p = Player(
                    rfid=rfid_uid,
                    name=f"Gast-{rfid_uid[:8]}",
                    balance=self._auto_balance,
                )
                self._players[rfid_uid] = p
                log.info(
                    "Auto-registriere unbekannten Chip %s mit Guthaben %d",
                    rfid_uid, self._auto_balance,
                )
            else:
                raise PlayerNotFound(rfid_uid)
        # Kopie zurückgeben, damit externe Modifikationen nicht durchsickern.
        return Player(rfid=p.rfid, name=p.name, balance=p.balance)

    def apply_delta(self, rfid_uid: str, delta: int) -> Optional[int]:
        if rfid_uid not in self._players:
            log.warning("apply_delta: unbekannter Spieler %s", rfid_uid)
            return None
        p = self._players[rfid_uid]
        new_balance = p.balance + delta
        if new_balance < 0:
            log.warning("apply_delta: Guthaben würde negativ (%s)", new_balance)
            return None
        p.balance = new_balance
        return new_balance

    # ------------------------------------------------------------------
    def find_by_name(self, name: str) -> Optional[Player]:
        """Bequemer Zugriff für den Auto-Login (Offline-Modus)."""
        lower = name.lower()
        for p in self._players.values():
            if p.name.lower() == lower:
                return Player(rfid=p.rfid, name=p.name, balance=p.balance)
        return None

    def all_players(self) -> list[Player]:
        return [
            Player(rfid=p.rfid, name=p.name, balance=p.balance)
            for p in self._players.values()
        ]
