"""HTTP-Client für die Guthaben-Datenbank.

Der Server liefert Spieler-Informationen anhand der RFID-UID:

    GET  /players/<uid>              → {"rfid": "...", "name": "...", "balance": 123}
    POST /players/<uid>/balance      Body: {"delta": -25}
                                     → {"balance": 98}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from .game import Player

log = logging.getLogger(__name__)


class PlayerNotFound(Exception):
    """RFID-UID ist der API unbekannt."""


class APIError(Exception):
    """Allgemeiner API-Fehler."""


@dataclass
class BalanceAPI:
    """Dünner Wrapper um requests für das Guthaben."""

    base_url: str
    timeout: float = 3.0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._session = requests.Session()

    # ------------------------------------------------------------------
    def get_player(self, rfid_uid: str) -> Player:
        try:
            r = self._session.get(
                f"{self.base_url}/players/{rfid_uid}", timeout=self.timeout
            )
        except requests.RequestException as e:
            raise APIError(f"Verbindungsfehler: {e}") from e
        if r.status_code == 404:
            raise PlayerNotFound(rfid_uid)
        if not r.ok:
            raise APIError(f"HTTP {r.status_code}: {r.text[:80]}")
        try:
            data = r.json()
            return Player(
                rfid=data["rfid"],
                name=data["name"],
                balance=int(data["balance"]),
            )
        except (KeyError, ValueError) as e:
            raise APIError(f"Ungültige Antwort: {e}") from e

    # ------------------------------------------------------------------
    def apply_delta(self, rfid_uid: str, delta: int) -> Optional[int]:
        try:
            r = self._session.post(
                f"{self.base_url}/players/{rfid_uid}/balance",
                json={"delta": delta},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            log.warning("apply_delta fehlgeschlagen: %s", e)
            return None
        if not r.ok:
            log.warning("apply_delta HTTP %s: %s", r.status_code, r.text[:80])
            return None
        try:
            return int(r.json()["balance"])
        except (KeyError, ValueError):
            return None
