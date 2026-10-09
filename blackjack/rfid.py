"""RFID-Reader-Anbindung über HTTP (ESP32).

Der RFID-Reader hängt hinter einem ESP32 und stellt eine kleine
Status-Webseite bereit (Default: http://10.0.244.81/status). Die
Antwort hat das Format:

    {"status":"idle",      "user_id":"", "username":"",         "run_id":""}
    {"status":"logged_in", "user_id":"d83751ae-...", "username":"Jonathan", ...}

Nur wenn ``status == "logged_in"`` wird die ``user_id`` zurückgegeben
und ein Login im Spiel ausgelöst. Jeder andere Status (``idle``,
``logged_out``, ...) bedeutet "kein Chip aufgelegt".

Abmelden: ``GET http://10.0.244.81/logout`` (siehe ``HTTPRFIDReader.logout``).
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Dict, Optional
from urllib.parse import urljoin

import requests


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON-Felder
# ---------------------------------------------------------------------------
# Nur dieser Status löst einen Login aus.
POSITIVE_STATUS = "logged_in"

# Bekannte Schlüssel, unter denen der Server die UUID liefert.
_ID_KEYS = ("user_id", "userid", "uid")

# Bekannte Schlüssel, unter denen der Server den Anzeigenamen liefert.
_NAME_KEYS = ("username", "user_name", "name", "display_name")

# UUID-Regex: 8-4-4-4-12.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _normalize_id(raw: str) -> str:
    """UUIDs bleiben in Kleinbuchstaben erhalten; alles andere wird nur gestripped."""
    trimmed = str(raw).strip()
    if _UUID_RE.fullmatch(trimmed):
        return trimmed.lower()
    return trimmed


def _extract_scan(payload) -> tuple[Optional[str], Optional[str]]:
    """Liefert ``(user_id, username)`` aus der JSON-Antwort.

    Beide Werte sind ``None``, wenn der Status nicht ``logged_in`` ist oder
    kein ID-Feld befüllt wurde.
    """
    if not isinstance(payload, dict):
        return None, None
    status = str(payload.get("status", "")).strip().lower()
    if status != POSITIVE_STATUS:
        return None, None

    uid: Optional[str] = None
    for key in _ID_KEYS:
        value = payload.get(key)
        if value not in (None, "", 0):
            uid = _normalize_id(str(value))
            if uid:
                break

    name: Optional[str] = None
    for key in _NAME_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            name = str(value).strip() or None
            if name:
                break

    return uid, name


# ---------------------------------------------------------------------------
class HTTPRFIDReader:
    """Pollt die ESP32-Statusseite und liefert Login-Events."""

    POLL_INTERVAL = 0.5     # Sekunden zwischen Abfragen
    IDLE_TIMEOUT = 3.0      # Sekunden ohne Login → "abgemeldet"

    def __init__(
        self,
        url: str,
        timeout: float = 2.0,
        logout_url: Optional[str] = None,
        autostart: bool = True,
    ) -> None:
        self.url = url
        # .../status -> .../logout
        self.logout_url = logout_url or urljoin(url, "logout")
        self.timeout = timeout

        self.events: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_uid: Optional[str] = None
        self._last_seen: float = 0.0
        # Nach unserem Logout meldet der ESP32 evtl. noch kurz den alten
        # User - diese UID ignorieren, bis einmal "nicht eingeloggt" kam.
        self._ignore_uid: Optional[str] = None
        # Von UID auf zuletzt gesehenen Anzeigenamen (für "Spieler:" im HUD).
        self._names: Dict[str, str] = {}

        self._session = requests.Session()
        self._thread = threading.Thread(
            target=self._loop, name="rfid-http", daemon=True,
        )
        if autostart:
            self._thread.start()
        log.info("HTTPRFIDReader aktiv (%s, Logout: %s)", url, self.logout_url)

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

        try:
            data = r.json()
        except ValueError:
            log.debug("HTTP-RFID: Antwort ist kein JSON (%s)", r.text[:80])
            return None

        uid, name = _extract_scan(data)
        if uid and name:
            self._names[uid] = name
        return uid

    def _process_uid(self, uid: Optional[str]) -> None:
        with self._lock:
            now = time.monotonic()
            if uid is None:
                self._ignore_uid = None
                if self._last_uid is not None and now - self._last_seen > self.IDLE_TIMEOUT:
                    log.info("HTTP-RFID: Login %s abgemeldet", self._last_uid)
                    self._last_uid = None
                    self.events.put(None)
                return
            if uid == self._ignore_uid:
                return
            self._last_seen = now
            if uid != self._last_uid:
                log.info("HTTP-RFID: neue ID %s", uid)
                self._last_uid = uid
                self.events.put(uid)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------
    def get_name_hint(self, uid: str) -> Optional[str]:
        """Zuletzt gesehener Anzeigename zu dieser UID (falls bekannt)."""
        return self._names.get(uid)

    def logout(self) -> bool:
        """Meldet den aktuellen RFID-User am ESP32 ab (``GET <logout_url>``).

        Liefert ``True``, wenn der ESP32 den Logout bestätigt hat. Danach
        löst derselbe Chip beim nächsten Auflegen wieder einen Login aus.
        """
        try:
            # Eigener Request statt self._session - die nutzt der Poll-Thread.
            r = requests.get(self.logout_url, timeout=self.timeout)
            if r.status_code == 405:    # Endpunkt nimmt nur POST an
                r = requests.post(self.logout_url, timeout=self.timeout)
        except requests.RequestException as e:
            log.warning("RFID-Logout %s: Netzwerkfehler %s", self.logout_url, e)
            return False
        if not r.ok:
            log.warning("RFID-Logout %s: HTTP %s", self.logout_url, r.status_code)
            return False
        with self._lock:
            self._ignore_uid = self._last_uid
            self._last_uid = None
        log.info("RFID-Logout OK (%s)", self.logout_url)
        return True

    def handle_pygame_event(self, event) -> None:
        # Kein Keyboard-Mock mehr - die echte HTTP-Quelle läuft.
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
