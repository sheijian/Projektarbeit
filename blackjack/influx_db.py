"""Alle InfluxDB-Zugriffe des Blackjack-Automaten.

Alle Spielstationen speichern einheitlich:

    Bucket <Station>  measurement "durchlauf"  field "endscore"  tag "userid"

Unser eigener Bucket ``SpieloAutomat`` (measurement "durchlauf", tag
"userid") hat drei Fields:

    live       aktueller Kontostand - nach jeder Hand
    stationen  Summe der Stationspunkte, die in ``live`` schon stecken
               (immer zusammen mit live geschrieben)
    endscore   Glückswert = gewonnene Hände / gespielte Hände in %
               - einmal pro Durchlauf (Login bis Logout)

Guthaben beim Login = live + (Stationspunkte jetzt - stationen), d. h.
Punkte, die nach dem letzten Blackjack-Spiel an einer Station dazukamen,
werden dazugerechnet - ohne etwas doppelt zu zählen.

    query_balance(userid)        -> Startwert | None   Guthaben für den Login
    query_spielstand(userid)     -> {field: wert}      live/stationen/endscore
    query_station_points(userid) -> {bucket: punkte}   die sechs Stationen
    query_username(userid)       -> str | None         Anzeigename (PPMaster)
    write_spielstand(userid, live, glueck, stationen) -> bool
    delete_spielstand(userid)    -> bool         SpieloAutomat-Daten löschen
    list_schema(bucket)          -> [(measurement, field, tags)]  Diagnose

Zugangsdaten (URL, Org, Tokens) stehen oben als Konstanten. Trage die
Tokens direkt in dieser Datei ein - die Datei ist der einzige Ort, an
dem DB-Credentials liegen.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple

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

# Was die Stationen TATSÄCHLICH schreiben: Vereinbart ist
# durchlauf/endscore/userid, in der DB stand am 12.10. aber z. B. bei
# Gedaechtnistest noch endscore/score mit Tag user_id. Die Abfrage
# akzeptiert beides - so zählen alte und neue Durchläufe.
STATION_SCHEMAS = (("durchlauf", "endscore"), ("endscore", "score"))
# Tag-Namen der RFID-ID - "rfidTag"/"userID" hatten Whackamole,
# Ampelsequenz und HeisserDraht früher.
STATION_TAGS    = ("userid", "user_id", "rfidTag", "userID")

# Die sechs Spielstationen - ihre Summe ist das Startguthaben.
STATION_BUCKETS = (
    "HeisserDraht",
    "Ampelsequenz",
    "TimerStrike",
    "Wurfgenauigkeit",
    "Whackamole",
    "Gedaechtnistest",
)

# Unser Bucket - schreibt NUR Blackjack (measurement/tag wie oben).
SCORE_BUCKET = "SpieloAutomat"
FIELD_LIVE      = "live"       # Kontostand, daraus startet der nächste Login
FIELD_STATIONEN = "stationen"  # Stationspunkte, die in live schon stecken
FIELD_GLUECK    = FIELD        # "endscore" = Glückswert in % (0..100)

# PPMaster speichert pro RFID-Chip den Anzeigenamen (gefüllt vom ESP32).
USERNAME_BUCKET      = "PPMaster"
USERNAME_MEASUREMENT = "PPMaster"
USERNAME_FIELD       = "username"
# Tag der RFID-ID - der ESP32 hat von "user_id" auf "userid" umgestellt,
# die Abfrage akzeptiert beide (ältere Datenpunkte haben noch user_id).
USERNAME_TAGS        = ("userid", "user_id")

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
class Startwert(NamedTuple):
    """Ergebnis von ``query_balance``."""
    balance: int      # Guthaben für diesen Login
    stationen: int    # aktuelle Summe der Stationspunkte (Basis für live)
    quelle: str       # Erklärung für Log/Diagnose


def query_balance(userid: str) -> Optional[Startwert]:
    """Guthaben für den Login.

    - Schon Blackjack gespielt: letzter Kontostand (``live``) plus alle
      Stationspunkte, die seitdem dazugekommen sind.
    - Noch nie Blackjack: Summe der Stationspunkte (Startguthaben).
    - Gar keine Daten: ``None``.

    Wirft ``DBError``, wenn die DB nicht antwortet - dann darf auf keinen
    Fall ein Ersatzwert genommen werden, sonst würde der echte Kontostand
    nach der ersten Hand überschrieben.
    """
    if not _is_configured():
        log.warning("query_balance: InfluxDB nicht konfiguriert")
        return None
    points = query_station_points(userid)
    stationen = sum(points.values())
    stand = query_spielstand(userid)
    live = stand.get(FIELD_LIVE)

    if live is not None:
        basis = stand.get(FIELD_STATIONEN)
        if basis is None:
            # Alter Datenpunkt ohne "stationen": annehmen, dass alle
            # bisherigen Stationspunkte schon im Kontostand stecken.
            neu = 0
            quelle = f"live {live} (alter Datenpunkt ohne stationen)"
        else:
            neu = max(0, stationen - basis)
            quelle = (f"live {live} + {neu} neue Stationspunkte "
                      f"(jetzt {stationen}, beim letzten Spiel {basis})")
        start = Startwert(live + neu, stationen, quelle)
    elif points:
        start = Startwert(stationen, stationen, f"Startguthaben aus {points}")
    else:
        log.info("query_balance: keine Punkte für userid=%s", userid)
        return None
    log.info("query_balance: userid=%s -> %d (%s)",
             userid, start.balance, start.quelle)
    return start


def query_spielstand(userid: str) -> Dict[str, int]:
    """Letzte Werte von live/stationen/endscore aus SpieloAutomat (nur die
    vorhandenen). Wirft ``DBError``."""
    fields = (FIELD_LIVE, FIELD_STATIONEN, FIELD_GLUECK)
    field_match = " or ".join(f'r._field == "{f}"' for f in fields)
    flux = (
        f'from(bucket: "{SCORE_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}" and '
        f'r.{TAG} == "{_esc_q(userid)}")\n'
        f'  |> filter(fn: (r) => {field_match})\n'
        f'  |> last()\n'
    )
    stand: Dict[str, int] = {}
    for row in _rows(_run_query(flux)):
        field, value = row.get("_field"), _to_int(row.get("_value") or None)
        if field in fields and value is not None:
            stand[field] = value
    return stand


def query_station_points(userid: str) -> Dict[str, int]:
    """Punkte pro Station (Summe aller Durchläufe, siehe STATION_SCHEMAS).
    Stationen ohne Daten fehlen im Ergebnis. Ein noch nicht angelegter
    Bucket zählt als 0, jeder andere Fehler wirft ``DBError``."""
    points: Dict[str, int] = {}
    for bucket in STATION_BUCKETS:
        flux = (
            f'from(bucket: "{bucket}")\n'
            f'  |> range(start: 0)\n'
            f'  |> filter(fn: (r) => {_schema_match(STATION_SCHEMAS)})\n'
            f'  |> filter(fn: (r) => {_tag_match(STATION_TAGS, userid)})\n'
            # int und float dürfen beim group() nicht gemischt werden.
            f'  |> toFloat()\n'
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


def query_username(userid: str) -> Optional[str]:
    """Letzter ``username`` für ``userid`` aus PPMaster."""
    if not _is_configured():
        return None
    flux = (
        f'from(bucket: "{USERNAME_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{USERNAME_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{USERNAME_FIELD}")\n'
        f'  |> filter(fn: (r) => {_tag_match(USERNAME_TAGS, userid)})\n'
        # Beide Tag-Varianten zusammenführen, dann den neuesten Namen nehmen.
        f'  |> group()\n'
        f'  |> sort(columns: ["_time"])\n'
        f'  |> last()\n'
    )
    try:
        name = _first_value(_run_query(flux))
    except DBError:
        return None
    if name is None:
        log.info("query_username: kein Datenpunkt für userid=%s in %s",
                 userid, USERNAME_BUCKET)
        return None
    log.info("query_username: userid=%s -> %r", userid, name)
    return name


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------
def write_spielstand(
    userid: str,
    live: Optional[int] = None,
    glueck: Optional[int] = None,
    stationen: Optional[int] = None,
) -> bool:
    """Schreibt Kontostand (``live`` + ``stationen``) und/oder Glückswert
    (``endscore``) in einen Datenpunkt nach SpieloAutomat::

        durchlauf,userid=<id> live=<konto>i,stationen=<summe>i,endscore=<glück>i
    """
    if not INFLUX_URL or not INFLUX_ORG or not INFLUX_TOKEN_WRITE:
        log.warning("write_spielstand: INFLUX_TOKEN_WRITE fehlt in influx_db.py")
        return False
    fields = []
    if live is not None:
        fields.append(f"{FIELD_LIVE}={int(live)}i")
        if stationen is not None:
            fields.append(f"{FIELD_STATIONEN}={int(stationen)}i")
    if glueck is not None:
        fields.append(f"{FIELD_GLUECK}={int(glueck)}i")
    if not fields:
        return True

    # Ohne Zeitstempel - InfluxDB setzt die Serverzeit.
    line = f"{MEASUREMENT},{TAG}={_esc_tag(userid)} {','.join(fields)}\n"
    log.debug("write_spielstand -> %s/api/v2/write LINE: %s",
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
        log.warning("write_spielstand: Netzwerkfehler %s", e)
        return False
    if not r.ok:
        log.warning("write_spielstand HTTP %s: %s | LINE: %s",
                    r.status_code, r.text[:200], line.strip())
        return False
    log.info("write_spielstand OK: %s %s", SCORE_BUCKET, line.strip())
    return True


def delete_spielstand(userid: str) -> bool:
    """Löscht Kontostand (live) und Glückswerte (endscore) eines Spielers
    in SpieloAutomat - danach startet er wieder mit dem Startguthaben
    (für Testspieler)."""
    if not INFLUX_URL or not INFLUX_ORG or not INFLUX_TOKEN_WRITE:
        log.warning("delete_spielstand: INFLUX_TOKEN_WRITE fehlt in influx_db.py")
        return False
    body = {
        "start": "1970-01-01T00:00:00Z",
        "stop": "2100-01-01T00:00:00Z",
        "predicate": f'_measurement="{MEASUREMENT}" AND '
                     f'{TAG}="{_esc_q(userid)}"',
    }
    try:
        r = _get_session().post(
            f"{INFLUX_URL}/api/v2/delete",
            params={"org": INFLUX_ORG, "bucket": SCORE_BUCKET},
            headers={
                "Authorization": f"Token {INFLUX_TOKEN_WRITE}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body).encode("utf-8"),
            timeout=10,
        )
    except requests.RequestException as e:
        log.warning("delete_spielstand: Netzwerkfehler %s", e)
        return False
    if not r.ok:
        log.warning("delete_spielstand HTTP %s: %s", r.status_code, r.text[:200])
        return False
    log.info("delete_spielstand OK: %s userid=%s", SCORE_BUCKET, userid)
    return True


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------
_STANDARD_COLUMNS = {
    "", "result", "table", "_start", "_stop", "_time", "_value",
    "_field", "_measurement",
}


def list_schema(bucket: str) -> List[Tuple[str, str, Tuple[str, ...]]]:
    """Welche (measurement, field, tags) es in einem Bucket wirklich gibt.
    Wirft ``DBError``."""
    flux = (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: 0)\n'
        f'  |> limit(n: 1)\n'
    )
    found = set()
    for row in _rows(_run_query(flux)):
        tags = tuple(sorted(
            k for k, v in row.items() if k not in _STANDARD_COLUMNS and v
        ))
        found.add((row.get("_measurement", ""), row.get("_field", ""), tags))
    return sorted(found)


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


def _schema_match(pairs) -> str:
    """Flux-Bedingung "eins der (measurement, field)-Paare passt"."""
    return " or ".join(
        f'(r._measurement == "{m}" and r._field == "{f}")' for m, f in pairs
    )


def _tag_match(tags, value: str) -> str:
    """Flux-Bedingung "einer der Tags hat diesen Wert" - ``exists``, weil
    nicht jeder Datenpunkt jeden Tag hat."""
    v = _esc_q(value)
    return " or ".join(f'(exists r.{t} and r.{t} == "{v}")' for t in tags)


def _esc_q(s: str) -> str:
    """Escaping für Werte in Flux-Strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _esc_tag(s: str) -> str:
    """Escaping für Tag-Werte im Line-Protocol."""
    return (s.replace("\\", "\\\\")
             .replace(",", r"\,")
             .replace("=", r"\=")
             .replace(" ", r"\ "))
