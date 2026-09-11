"""RFID-Reader-Anbindung.

Ein Hintergrundthread liest zyklisch die UID vom MFRC522-Modul und legt sie
in eine Queue. Ist das Modul nicht verfügbar, wird ein Tastatur-basierter
Mock verwendet: die Tasten `1`, `2`, `3` simulieren jeweils einen anderen
RFID-Chip (siehe `config.MOCK_RFID_KEYS`).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import pygame

from .config import MOCK_RFID_KEYS

log = logging.getLogger(__name__)


try:
    from mfrc522 import SimpleMFRC522  # type: ignore
    HAS_RFID = True
except Exception:
    SimpleMFRC522 = None                # type: ignore
    HAS_RFID = False


# ---------------------------------------------------------------------------
class RFIDReader:
    """Liefert UIDs von RFID-Chips über eine Queue."""

    POLL_INTERVAL = 0.3         # Sekunden zwischen Reader-Aufrufen
    IDLE_TIMEOUT = 3.0          # Sekunden ohne Karte → "abgemeldet"

    def __init__(self, use_hardware: Optional[bool] = None) -> None:
        self.events: "queue.Queue[Optional[str]]" = queue.Queue()
        self._use_hw = HAS_RFID if use_hardware is None else (use_hardware and HAS_RFID)
        self._stop = threading.Event()
        self._last_uid: Optional[str] = None
        self._last_seen: float = 0.0

        if self._use_hw:
            self._reader = SimpleMFRC522()
            self._thread = threading.Thread(
                target=self._loop, name="rfid-reader", daemon=True
            )
            self._thread.start()
            log.info("RFIDReader: MFRC522 aktiv")
        else:
            log.info("RFIDReader: Mock aktiv (Tasten 1/2/3)")

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        assert self._reader is not None
        while not self._stop.is_set():
            try:
                uid = self._reader.read_id_no_block()
            except Exception as e:
                log.warning("MFRC522 read fehlgeschlagen: %s", e)
                uid = None
            self._process_uid(uid)
            time.sleep(self.POLL_INTERVAL)

    def _process_uid(self, uid_int: Optional[int]) -> None:
        now = time.monotonic()
        if uid_int is None:
            if self._last_uid is not None and now - self._last_seen > self.IDLE_TIMEOUT:
                self._last_uid = None
                self.events.put(None)   # Chip entfernt
            return
        uid = f"{uid_int:08X}"
        self._last_seen = now
        if uid != self._last_uid:
            self._last_uid = uid
            self.events.put(uid)

    # ------------------------------------------------------------------
    def handle_pygame_event(self, event: pygame.event.Event) -> None:
        """Für den Mock-Modus: 1/2/3 simulieren Chips, 0 hebt den Chip ab."""
        if self._use_hw or event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
            key = chr(event.key)
            uid = MOCK_RFID_KEYS[key]
            if uid != self._last_uid:
                self._last_uid = uid
                self.events.put(uid)
        elif event.key == pygame.K_0:
            if self._last_uid is not None:
                self._last_uid = None
                self.events.put(None)

    def poll(self) -> tuple[bool, Optional[str]]:
        """Liefert (hat_event, uid_oder_none)."""
        try:
            uid = self.events.get_nowait()
        except queue.Empty:
            return False, None
        return True, uid

    def close(self) -> None:
        self._stop.set()
