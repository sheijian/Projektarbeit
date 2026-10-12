"""Alle InfluxDB-Zugriffe des Blackjack-Automaten.

Alle Spielstationen speichern einheitlich:

    Bucket <Station>  measurement "durchlauf"  field "endscore"  tag "userid"

Unser eigener Bucket ``SpieloAutomat`` hat dasselbe Schema - dort steht
der Blackjack-Endwert, zuordenbar über die ``userid``.

    query_balance(userid)        -> int | None   Kontostand für den Login
    query_endwert(userid)        -> int | None   Blackjack-Endwert (SpieloAutomat)
    query_station_points(userid) -> {bucket: punkte}  (die sechs Stationen)
    query_username(userid)       -> str | None   Anzeigename (PPMaster)
    write_endwert(userid, wert)  -> bool         Endwert nach SpieloAutomat

Zugangsdaten (URL, Org, Tokens) stehen oben als Konstanten. Trage die
Tokens direkt in dieser Datei ein - die Datei ist der einzige Ort, an
dem DB-Credentials liegen.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Dict, Iterator, Optional

import requests


log = logging.getLogger(__name__)


# ===========================================================================
# InfluxDB-Zugangsdaten
# ===========================================================================
# WICHTIG: Die Datei nicht mit echten Tokens committen - sonst stehen die
# Tokens im öffentlichen Git-Repo.
# ===========================================================================
INFLUX_URL         = "http://10.0.244.254:8086"
INFLUX_ORG         = "FIT244"

# <<< HIER DEN LESE-TOKEN EINFÜGEN >>>
INFLUX_TOKEN_READ  = ""

# <<< HIER DEN SCHREIB-TOKEN EINFÜGEN >>>
INFLUX_TOKEN_WRITE = ""


# ===========================================================================
# Schema
# ===========================================================================
# Einheitlich in allen Buckets (sechs Stationen + SpieloAutomat).
MEASUREMENT = "durchlauf"
FIELD       = "endscore"      # int
TAG         = "userid"

# Die sechs Spielstationen - ihre Summe ist das Startguthaben.
STATION_BUCKETS = (
    "HeisserDraht",
    "Ampelsequenz",
    "TimerStrike",
    "Wurfgenauigkeit",
    "Whackamole",
    "Gedaechtnistest",
)

# Unser Bucket: hier steht der Blackjack-Endwert. Schreibt NUR Blackjack.
SCORE_BUCKET = "SpieloAutomat"

# PPMaster speichert pro RFID-Chip den Anzeigenamen (gefüllt vom ESP32).
USERNAME_BUCKET      = "PPMaster"
USERNAME_MEASUREMENT = "PPMaster"
USERNAME_FIELD       = "username"
USERNAME_TAG         = "user_id"

# Beim Schreiben schicken wir KEINEN Zeitstempel mit - InfluxDB setzt dann
# seine Serverzeit. Die Uhr des Raspberry Pi geht ohne Internet/NTP falsch
# (Datenpunkte landeten z. B. am 19.09. statt heute) und tauchen dann im
# Data Explorer ("Past 1h") nicht auf.
# ===========================================================================


class DBError(Exception):
    """InfluxDB nicht erreichbar oder Abfrage fehlgeschlagen."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _is_configured() -> bool:
    return bool(INFLUX_URL and INFLUX_ORG and INFLUX_TOKEN_READ)


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------
def query_balance(user_id: str) -> Optional[int]:
    """Kontostand für den Login.

    Hat der Spieler schon Blackjack gespielt, ist das sein Endwert aus
    SpieloAutomat - sonst die Summe seiner Punkte aus den sechs Stationen
    (Startguthaben). ``None``, wenn es nirgends Daten gibt.

    Wirft ``DBError``, wenn die DB nicht antwortet - dann darf auf keinen
    Fall ein Ersatzwert genommen werden, sonst würde der echte Endwert
    nach der ersten Hand überschrieben.
    """
    if not _is_configured():
        log.warning("query_balance: InfluxDB nicht konfiguriert")
        return None
    endwert = query_endwert(user_id)
    if endwert is not None:
        log.info("query_balance: userid=%s -> %d (Blackjack-Endwert)",
                 user_id, endwert)
        return endwert
    points = query_station_points(user_id)
    if not points:
        log.info("query_balance: keine Punkte für userid=%s", user_id)
        return None
    total = sum(points.values())
    log.info("query_balance: userid=%s -> %d (Startguthaben aus %s)",
             user_id, total, points)
    return total


def query_endwert(user_id: str) -> Optional[int]:
    """Letzter Blackjack-Endwert aus SpieloAutomat. Wirft ``DBError``."""
    flux = (
        f'from(bucket: "{SCORE_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and '
        f'r._field == "{FIELD}")\n'
        f'  |> filter(fn: (r) => r.{TAG} == "{_esc_q(user_id)}")\n'
        f'  |> last()\n'
    )
    return _to_int(_first_value(_run_query(flux)))


def query_station_points(user_id: str) -> Dict[str, int]:
    """Punkte pro Station (Summe aller Durchläufe). Stationen ohne Daten
    fehlen im Ergebnis. Ein noch nicht angelegter Bucket zählt als 0,
    jeder andere Fehler wirft ``DBError``."""
    points: Dict[str, int] = {}
    for bucket in STATION_BUCKETS:
        flux = (
            f'from(bucket: "{bucket}")\n'
            f'  |> range(start: 0)\n'
            f'  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and '
            f'r._field == "{FIELD}")\n'
            f'  |> filter(fn: (r) => r.{TAG} == "{_esc_q(user_id)}")\n'
            f'  |> group()\n'
            f'  |> sum()\n'
        )
        try:
            value = _to_int(_first_value(_run_query(flux)))
        except DBError as e:
            if e.status == 404:
                log.warning("Bucket %s nicht gefunden - zählt als 0", bucket)
                continue
            raise
        if value is not None:
            points[bucket] = value
    return points


def query_username(user_id: str) -> Optional[str]:
    """Letzter ``username`` für ``user_id`` aus PPMaster."""
    if not _is_configured():
        return None
    flux = (
        f'from(bucket: "{USERNAME_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{USERNAME_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{USERNAME_FIELD}")\n'
        f'  |> filter(fn: (r) => r.{USERNAME_TAG} == "{_esc_q(user_id)}")\n'
        f'  |> last()\n'
    )
    try:
        name = _first_value(_run_query(flux))
    except DBError:
        return None
    if name is None:
        log.info("query_username: kein Datenpunkt für user_id=%s in %s",
                 user_id, USERNAME_BUCKET)
        return None
    log.info("query_username: user_id=%s -> %r", user_id, name)
    return name


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------
def write_endwert(user_id: str, endwert: int) -> bool:
    """Schreibt den Blackjack-Endwert nach SpieloAutomat
    (``durchlauf,userid=<id> endscore=<wert>``)."""
    if not INFLUX_URL or not INFLUX_ORG or not INFLUX_TOKEN_WRITE:
        log.warning("write_endwert: INFLUX_TOKEN_WRITE fehlt in influx_db.py")
        return False

    # Ohne Zeitstempel - InfluxDB setzt die Serverzeit.
    line = f"{MEASUREMENT},{TAG}={_esc_tag(user_id)} {FIELD}={int(endwert)}i\n"
    log.debug("write_endwert -> %s/api/v2/write LINE: %s",
              INFLUX_URL, line.strip())

    try:
        r = _get_session().post(
            f"{INFLUX_URL}/api/v2/write",
            params={"org": INFLUX_ORG, "bucket": SCORE_BUCKET, "precision": "ms"},
            headers={
                "Authorization": f"Token {INFLUX_TOKEN_WRITE}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            data=line.encode("utf-8"),
            timeout=5,
        )
    except requests.RequestException as e:
        log.warning("write_endwert: Netzwerkfehler %s", e)
        return False
    if not r.ok:
        log.warning("write_endwert HTTP %s: %s | LINE: %s",
                    r.status_code, r.text[:200], line.strip())
        return False
    log.info("write_endwert OK: %s/%s userid=%s endscore=%d",
             SCORE_BUCKET, MEASUREMENT, user_id, endwert)
    return True


# ---------------------------------------------------------------------------
# HTTP + Parser-Helfer
# ---------------------------------------------------------------------------
def _run_query(flux: str) -> str:
    """Schickt eine Flux-Abfrage, liefert die CSV-Antwort. Wirft ``DBError``."""
    log.debug("Flux:\n%s", flux)
    try:
        r = _get_session().post(
            f"{INFLUX_URL}/api/v2/query",
            params={"org": INFLUX_ORG},
            headers={
                "Authorization": f"Token {INFLUX_TOKEN_READ}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux.encode("utf-8"),
            timeout=5,
        )
    except requests.RequestException as e:
        log.warning("Flux-Query: Netzwerkfehler %s", e)
        raise DBError(f"Netzwerkfehler: {e}") from e
    if not r.ok:
        log.warning("Flux-Query HTTP %s: %s", r.status_code, r.text[:200])
        raise DBError(f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)
    log.debug("Flux-Antwort (%d bytes): %s", len(r.text), r.text[:300])
    return r.text


def _rows(csv_text: str) -> Iterator[Dict[str, str]]:
    """Datenzeilen einer annotierten Flux-CSV als ``{spalte: wert}``.
    Kommen mehrere Tabellen mit eigenem Header, wird jeder beachtet."""
    header: Optional[list] = None
    for row in csv.reader(io.StringIO(csv_text)):
        if not row or (row[0] or "").strip().startswith("#"):
            header = None
            continue
        if header is None:
            header = row
            continue
        yield dict(zip(header, (cell.strip() for cell in row)))


def _first_value(csv_text: str) -> Optional[str]:
    """Erste ``_value``-Zelle aus einer annotierten Flux-CSV. ``None``
    wenn keine Datenzeile."""
    for row in _rows(csv_text):
        if row.get("_value"):
            return row["_value"]
    return None


def _to_int(value: Optional[str]) -> Optional[int]:
    """``"125"`` / ``"125.0"`` -> 125. Unlesbare Werte wirft ``DBError``."""
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        raise DBError(f"nicht-numerischer Wert {value!r}") from None


def _esc_q(s: str) -> str:
    """Escaping für Werte in Flux-Strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _esc_tag(s: str) -> str:
    """Escaping für Tag-Werte im Line-Protocol."""
    return (s.replace("\\", "\\\\")
             .replace(",", r"\,")
             .replace("=", r"\=")
             .replace(" ", r"\ "))
