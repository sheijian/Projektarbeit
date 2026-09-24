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
# Hex-RFID-UID (mind. 6 Zeichen) mit optionalen Trennern - Bindestriche
# werden hier entfernt.
_UID_RE = re.compile(r"([0-9A-Fa-f](?:[\s:\-]?[0-9A-Fa-f]){5,31})")
# UUID (8-4-4-4-12) - wird als "User-ID" so \u00fcbernommen, wie sie ist.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# JSON-Statuswerte, die als "keine Karte aufgelegt / abgemeldet" gelten.
_NEGATIVE_STATUS = {
    "none", "no_card", "empty", "idle", "logged_out", "loggedout",
    "unknown", "waiting",
}
# JSON-Statuswerte, die als "Karte aufgelegt / eingeloggt" gelten und die
# Extraktion des ID-Feldes ausl\u00f6sen.
_POSITIVE_STATUS = {
    "logged_in", "loggedin", "ok", "success", "present", "detected", "active",
}


# Reihenfolge z\u00e4hlt: das erste passende Feld gewinnt.
_ID_KEYS = (
    "user_id", "userid", "uid", "id",
    "card_id", "cardid", "rfid", "tag", "value",
)


def _extract_uid(payload) -> Optional[str]:
    """Findet die User- oder Karten-UID in einer HTTP-Antwort.

    Unterst\u00fctzt:

    * JSON mit einem der \u00fcblichen Schl\u00fcssel (``user_id``, ``uid``,
      ``id``, ``card_id``, ``rfid`` \u2026) sowie den Statusfeldern
      ``logged_in`` / ``logged_out``.
    * Plain-Text, der nur aus einer UUID oder Hex-UID besteht.
    * HTML/Text, in dem irgendwo eine UUID oder Hex-UID vorkommt.

    UUIDs (36-stellig mit Bindestrichen) werden **unver\u00e4ndert** in
    Kleinbuchstaben zur\u00fcckgegeben, damit sie zum Format eures Test-Servers
    und der Datenbank passen. Hex-RFID-UIDs werden weiterhin von Trennern
    befreit und in Gro\u00dfbuchstaben normalisiert.
    """
    # 1) JSON
    if isinstance(payload, dict):
        status = str(payload.get("status", "")).lower()
        if status in _NEGATIVE_STATUS:
            return None
        # Wenn ein bekannter Positiv-Status ODER \u00fcberhaupt kein Status
        # gesetzt ist, versuchen wir die ID zu extrahieren.
        if status and status not in _POSITIVE_STATUS:
            log.debug("HTTP-RFID: unbekannter status=%r, versuche trotzdem ID", status)
        for key in _ID_KEYS:
            if key in payload and payload[key] not in (None, "", 0):
                return _normalize_id(str(payload[key]))
        return None

    # 2) Text
    text = str(payload).strip()
    if not text:
        return None

    m = _UUID_RE.search(text)
    if m:
        return m.group(0).lower()

    # Als N\u00e4chstes: reiner Hex-Text ohne Trenner - direkt akzeptieren.
    normalized = _normalize_uid_hex(text)
    if normalized and all(c in "0123456789ABCDEF" for c in normalized):
        return normalized

    m = _UID_RE.search(text)
    if m:
        return _normalize_uid_hex(m.group(1))
    return None


def _looks_like_uuid(value: str) -> bool:
    return bool(_UUID_RE.fullmatch(value.strip()))


def _normalize_id(raw: str) -> str:
    """UUIDs bleiben (in Kleinbuchstaben) erhalten; alles andere wird als
    Hex-UID behandelt und normalisiert."""
    trimmed = raw.strip()
    if _looks_like_uuid(trimmed):
        return trimmed.lower()
    return _normalize_uid_hex(trimmed)


def _normalize_uid_hex(raw: str) -> str:
    return re.sub(r"[\s:\-]", "", raw).strip().upper()


# Alias f\u00fcr Abw\u00e4rtskompatibilit\u00e4t (fr\u00fchere Tests / externer Code).
_normalize_uid = _normalize_id


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
                log.info("HTTP-RFID: Karte %s entfernt", self._last_uid)
                self._last_uid = None
                self.events.put(None)
            return
        self._last_seen = now
        if uid != self._last_uid:
            log.info("HTTP-RFID: neue ID %s", uid)
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
