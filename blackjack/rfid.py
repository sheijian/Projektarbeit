"""RFID-Reader-Anbindung.

Es gibt drei Backends, die über die gleiche kleine Schnittstelle
(``poll()`` / ``handle_pygame_event()`` / ``close()``) angesprochen
werden:

* ``RFIDReader``      – direkt über ein am Pi angeschlossenes MFRC522-Modul
                          (oder Tastatur-Mock 1/2/3, falls Hardware fehlt).
* ``HTTPRFIDReader``  – pollt eine HTTP-Testseite, hinter der ein separater
                          RFID-Leser sitzt. Praktisch für Netzwerktests, bei
                          denen der Leser nicht am Pi selbst hängt.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Optional

import requests

from .config import MOCK_RFID_KEYS

log = logging.getLogger(__name__)


try:
    import pygame  # type: ignore
    HAS_PYGAME = True
except Exception:
    pygame = None    # type: ignore
    HAS_PYGAME = False


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
    def handle_pygame_event(self, event) -> None:
        """Für den Mock-Modus: 1/2/3 simulieren Chips, 0 hebt den Chip ab."""
        if self._use_hw or not HAS_PYGAME or event.type != pygame.KEYDOWN:
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


# ---------------------------------------------------------------------------
# HTTP-basierter RFID-Reader
# ---------------------------------------------------------------------------
# Reguladrer Ausdruck, mit dem wir Kandidaten f\u00fcr eine RFID-UID aus
# Freitext filtern. UIDs bestehen \u00fcblicherweise aus mindestens 6 Hex-
# Zeichen. Wir akzeptieren optional Bindestriche/Doppelpunkte/Leerzeichen
# als Trenner und stripen sie sp\u00e4ter.
_UID_RE = re.compile(r"([0-9A-Fa-f](?:[\s:\-]?[0-9A-Fa-f]){5,31})")


def _extract_uid(payload) -> Optional[str]:
    """Findet eine RFID-UID in einer HTTP-Antwort.

    Unterst\u00fctzt die \u00fcblichen Formate:

    * JSON mit einem der Schl\u00fcssel ``uid`` / ``id`` / ``card_id`` /
      ``rfid`` / ``tag`` / ``value``
    * Plain-Text, der nur aus einer Hex-UID besteht
    * HTML/Text, in dem irgendwo eine Hex-UID vorkommt

    Liefert die UID in Gro\u00dfbuchstaben ohne Trennzeichen oder ``None``.
    """
    # 1) JSON
    if isinstance(payload, dict):
        # Erst die \u00fcblichen "kein Chip"-Marker abfangen.
        status = str(payload.get("status", "")).lower()
        if status in ("none", "no_card", "empty", "idle"):
            return None
        for key in ("uid", "id", "card_id", "cardid", "rfid", "tag", "value"):
            if key in payload and payload[key] not in (None, "", 0):
                return _normalize_uid(str(payload[key]))
        return None

    # 2) Text
    text = str(payload).strip()
    if not text:
        return None

    # Ganz einfacher Fall: die Response ist nur die UID.
    normalized = _normalize_uid(text)
    if normalized and all(c in "0123456789ABCDEF" for c in normalized):
        return normalized

    # Sonst per Regex im Text suchen (HTML, "UID: xx" etc.).
    m = _UID_RE.search(text)
    if m:
        return _normalize_uid(m.group(1))
    return None


def _normalize_uid(raw: str) -> str:
    return re.sub(r"[\s:\-]", "", raw).strip().upper()


class HTTPRFIDReader:
    """RFID-Reader \u00fcber HTTP-Polling einer Test-Seite.

    Der Konstruktor startet einen Hintergrundthread, der die konfigurierte
    URL zyklisch abfragt und Chip-Wechsel in dieselbe Event-Queue legt wie
    der MFRC522-Reader.
    """

    POLL_INTERVAL = 0.5     # Sekunden zwischen Abfragen
    IDLE_TIMEOUT = 3.0      # Sekunden ohne Karte \u2192 "abgemeldet"

    def __init__(self, url: str, timeout: float = 2.0) -> None:
        self.url = url
        self.timeout = timeout

        self.events: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop = threading.Event()
        self._last_uid: Optional[str] = None
        self._last_seen: float = 0.0

        self._session = requests.Session()
        self._thread = threading.Thread(
            target=self._loop, name="rfid-http", daemon=True,
        )
        self._thread.start()
        log.info("HTTPRFIDReader aktiv (%s)", url)

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            uid = self._fetch_uid()
            self._process_uid(uid)
            self._stop.wait(self.POLL_INTERVAL)

    def _fetch_uid(self) -> Optional[str]:
        try:
            r = self._session.get(self.url, timeout=self.timeout)
        except requests.RequestException as e:
            log.debug("HTTP-RFID Verbindungsfehler: %s", e)
            return None
        if not r.ok:
            log.debug("HTTP-RFID HTTP %s", r.status_code)
            return None

        # Erst JSON versuchen, sonst als Text weiterreichen.
        try:
            data = r.json()
            return _extract_uid(data)
        except ValueError:
            return _extract_uid(r.text)

    def _process_uid(self, uid: Optional[str]) -> None:
        now = time.monotonic()
        if uid is None:
            if self._last_uid is not None and now - self._last_seen > self.IDLE_TIMEOUT:
                self._last_uid = None
                self.events.put(None)
            return
        self._last_seen = now
        if uid != self._last_uid:
            self._last_uid = uid
            self.events.put(uid)

    # ------------------------------------------------------------------
    # Gleiche Schnittstelle wie RFIDReader
    # ------------------------------------------------------------------
    def handle_pygame_event(self, event) -> None:
        # Kein Mock n\u00f6tig: die echte HTTP-Quelle l\u00e4uft.
        return

    def poll(self) -> tuple[bool, Optional[str]]:
        try:
            uid = self.events.get_nowait()
        except queue.Empty:
            return False, None
        return True, uid

    def close(self) -> None:
        self._stop.set()
        try:
            self._session.close()
        except Exception:  # pragma: no cover
            pass
