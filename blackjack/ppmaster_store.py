"""InfluxDB-Store für den gemeinsamen PPMaster-Bucket der Spielstationen.

Datenmodell im Bucket:

    endscore,rfidTag=<name>  score=<int>  <timestamp_ms>

Jede Station schreibt am Ende ihres Spieldurchlaufs einen weiteren
``endscore``-Datenpunkt mit dem Nettogewinn dieses Durchlaufs. Das
Startguthaben eines Spielers ist die Summe aller ``endscore``-Werte,
die innerhalb des konfigurierten Zeitrahmens (Default -1h) für diesen
``rfidTag`` im Bucket stehen.

Zusätzlich schreibt der Store am Ende der Session einen ``winrate``-
Punkt (Prozent der gewonnenen Runden, ganzzahlig).

Der Store spricht direkt über die InfluxDB-HTTP-API (Flux-Query und
Line-Protocol-Write) - damit braucht das Projekt kein zusätzliches
Python-Package.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .db_config import INFLUX, InfluxConfig, load_influx_config
from .game import Player
from .store import PlayerNotFound, StoreError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
class PPMasterStore:
    """Guthaben-Store gegen den PPMaster-Bucket in InfluxDB."""

    MEASUREMENT = "endscore"
    WINRATE_MEASUREMENT = "winrate"
    TAG_KEY = "rfidTag"
    FIELD_KEY = "score"
    WINRATE_FIELD = "winrate"

    def __init__(self, config: Optional[InfluxConfig] = None) -> None:
        self.config = config or load_influx_config()
        if not self.config.is_configured:
            raise StoreError(
                "InfluxDB nicht konfiguriert - INFLUX_URL/ORG/BUCKET/"
                "TOKEN_READ/TOKEN_WRITE in .env eintragen (siehe .env.example)."
            )
        self._session = requests.Session()
        # Aktuelles Startguthaben pro Tag, damit wir beim Session-Ende
        # das Netto-Delta wissen (aktuelles Guthaben minus Startguthaben).
        self._start_balances: dict[str, int] = {}
        log.info(
            "PPMasterStore verbunden mit %s (org=%s, bucket=%s, range=%s)",
            self.config.url, self.config.org, self.config.bucket,
            self.config.query_range,
        )

    # ------------------------------------------------------------------
    # Lesen (Flux)
    # ------------------------------------------------------------------
    def get_player(self, rfid_tag: str) -> Player:
        """Summiert alle ``score``-Punkte für diesen Tag als Startguthaben."""
        safe_tag = _escape_flux_string(rfid_tag)
        flux = (
            f'from(bucket: "{self.config.bucket}")\n'
            f'  |> range(start: {self.config.query_range})\n'
            f'  |> filter(fn: (r) => r._measurement == "{self.MEASUREMENT}")\n'
            f'  |> filter(fn: (r) => r.{self.TAG_KEY} == "{safe_tag}")\n'
            f'  |> filter(fn: (r) => r._field == "{self.FIELD_KEY}")\n'
            f'  |> sum()\n'
        )
        try:
            r = self._session.post(
                f"{self.config.url}/api/v2/query",
                params={"org": self.config.org},
                headers={
                    "Authorization": f"Token {self.config.token_read}",
                    "Content-Type": "application/vnd.flux",
                    "Accept": "application/csv",
                },
                data=flux.encode("utf-8"),
                timeout=5,
            )
        except requests.RequestException as e:
            raise StoreError(f"InfluxDB-Query fehlgeschlagen: {e}") from e
        if not r.ok:
            raise StoreError(f"InfluxDB HTTP {r.status_code}: {r.text[:120]}")

        total = _parse_flux_sum_csv(r.text)
        if total is None:
            raise PlayerNotFound(rfid_tag)

        self._start_balances[rfid_tag] = total
        return Player(rfid=rfid_tag, name=rfid_tag, balance=total)

    # ------------------------------------------------------------------
    # Kein Live-Write pro Runde: die Buchhaltung passiert lokal im Game.
    # Der Store bekommt die Deltas mit, um am Session-Ende das kumulierte
    # Netto in den Bucket zu schreiben.
    # ------------------------------------------------------------------
    def apply_delta(self, rfid_tag: str, delta: int) -> Optional[int]:
        # Wir schreiben nichts pro Runde - die Höhe des aktuellen Guthabens
        # verwaltet main.py über das Player-Objekt. Damit bleibt es bei
        # EINEM endscore-Datenpunkt pro Session (der Netto-Delta).
        return None

    # ------------------------------------------------------------------
    # Schreiben (Line-Protocol)
    # ------------------------------------------------------------------
    def finalize_session(
        self,
        rfid_tag: str,
        final_balance: int,
        wins: int,
        plays: int,
    ) -> None:
        """Schreibt einen endscore-Delta und optional die Winrate.

        - ``final_balance`` = aktueller Kontostand des Spielers am Ende
        - Aus dem Cache holen wir das Startguthaben und berechnen den
          Netto-Delta dieses Spieldurchlaufs.
        - Bei ``plays == 0`` wird nichts geschrieben.
        """
        if plays <= 0:
            log.info("finalize_session: keine Runden gespielt - nichts zu schreiben.")
            return

        start = self._start_balances.get(rfid_tag)
        if start is None:
            log.warning(
                "finalize_session: kein Startguthaben für %s bekannt - "
                "nehme final_balance als Delta an",
                rfid_tag,
            )
            delta = final_balance
        else:
            delta = final_balance - start

        winrate = int(round((wins / plays) * 100))
        ts_ms = int(time.time() * 1000)
        safe_tag = _escape_line_protocol_tag(rfid_tag)
        lines = [
            f"{self.MEASUREMENT},{self.TAG_KEY}={safe_tag} "
            f"{self.FIELD_KEY}={int(delta)}i {ts_ms}",
            f"{self.WINRATE_MEASUREMENT},{self.TAG_KEY}={safe_tag} "
            f"{self.WINRATE_FIELD}={winrate}i {ts_ms}",
        ]
        body = "\n".join(lines) + "\n"

        try:
            r = self._session.post(
                f"{self.config.url}/api/v2/write",
                params={
                    "org": self.config.org,
                    "bucket": self.config.bucket,
                    "precision": "ms",
                },
                headers={
                    "Authorization": f"Token {self.config.token_write}",
                    "Content-Type": "text/plain; charset=utf-8",
                },
                data=body.encode("utf-8"),
                timeout=5,
            )
        except requests.RequestException as e:
            log.warning("finalize_session: Schreib-Request fehlgeschlagen: %s", e)
            return
        if not r.ok:
            log.warning(
                "finalize_session: InfluxDB HTTP %s: %s",
                r.status_code, r.text[:120],
            )
            return
        log.info(
            "finalize_session: %s delta=%+d winrate=%d%% (%d/%d)",
            rfid_tag, delta, winrate, wins, plays,
        )
        # Startguthaben aktualisieren, damit eine weitere Session in
        # derselben Programm-Instanz korrekt weiterrechnet.
        self._start_balances[rfid_tag] = final_balance

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------
def _escape_flux_string(value: str) -> str:
    """Escaping für Werte innerhalb eines Flux-Strings (\" und \\)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_line_protocol_tag(value: str) -> str:
    """Escaping für Tag-Werte im Line-Protocol: Kommas, Gleichzeichen und
    Leerzeichen müssen mit Backslash escaped werden."""
    return (
        value.replace("\\", "\\\\")
        .replace(",", r"\,")
        .replace("=", r"\=")
        .replace(" ", r"\ ")
    )


def _parse_flux_sum_csv(text: str) -> Optional[int]:
    """Extrahiert den Summenwert (``_value``) aus einer annotierten Flux-CSV.

    Aufbau einer Flux-Antwort:

        #datatype,...
        #group,...
        #default,...
        ,result,table,_value,...       <- Header (erste Spalte leer)
        ,,0,180,...                    <- Datenzeile(n)

    Es kann mehrere Tabellen (durch Leerzeilen getrennt) geben; wir
    summieren über alle `_value`-Spalten. Wenn keine Datenzeile mit einem
    numerischen Wert vorkommt, gibt die Funktion ``None`` zurück.
    """
    import csv
    import io

    reader = csv.reader(io.StringIO(text))
    value_idx: Optional[int] = None
    total = 0
    saw_row = False
    for row in reader:
        if not row:
            value_idx = None       # nächste Tabelle beginnt
            continue
        first = (row[0] or "").strip()
        if first.startswith("#"):
            value_idx = None       # Annotation → Header muss neu erkannt werden
            continue
        if value_idx is None:
            # Kandidat für Header - hat er eine _value-Spalte?
            try:
                value_idx = row.index("_value")
            except ValueError:
                # Keine Header-Zeile - ignorieren
                pass
            continue
        if value_idx >= len(row):
            continue
        raw = row[value_idx].strip()
        if not raw:
            continue
        try:
            total += int(float(raw))
            saw_row = True
        except ValueError:
            continue
    return total if saw_row else None
