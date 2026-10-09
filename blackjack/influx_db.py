"""Alle InfluxDB-Zugriffe des Blackjack-Automaten.

Drei Funktionen, mehr nicht:

    query_balance(user_id)               -> int | None  (aus SpieloAutomat)
    query_username(user_id)              -> str | None  (aus PPMaster)
    write_endwert(user_id, wert, name)   -> bool        (nach SpieloAutomat)

Zugangsdaten (URL, Org, Tokens) stehen oben als Konstanten. Trage die
Tokens direkt in dieser Datei ein - die Datei ist der einzige Ort, an
dem DB-Credentials liegen.
"""

from __future__ import annotations

import csv
import io
import logging
import time
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
# Schema: Zuordnung Bucket + Measurement + Field + Tag
# ===========================================================================
# PPMaster speichert pro RFID-Chip den Anzeigenamen (gefüllt vom ESP32).
USERNAME_BUCKET      = "PPMaster"
USERNAME_MEASUREMENT = "PPMaster"
USERNAME_FIELD       = "username"
USERNAME_TAG         = "user_id"

# SpieloAutomat ist unser Punkte-Bucket. Pro user_id liegen dort zwei
# getrennte Werte, die sich gegenseitig nie überschreiben:
#
#   endscore/score     Startguthaben = Summe der sechs Stationen.
#                      Schreibt NUR der Aggregator (alle 5 s).
#   blackjack/endwert  Kontostand nach der letzten Blackjack-Hand.
#                      Schreibt NUR Blackjack.
#
# Beim Login gilt: Endwert, falls vorhanden - sonst Startguthaben.
SCORE_BUCKET      = "SpieloAutomat"
SCORE_TAG         = "user_id"
SCORE_MEASUREMENT = "endscore"    # Startguthaben (Aggregator)
SCORE_FIELD       = "score"       # int

ENDWERT_MEASUREMENT = "blackjack"   # Blackjack-Endwert
ENDWERT_FIELD       = "endwert"     # int
ENDWERT_NAME_FIELD  = "username"    # str (zusätzlich im selben Datenpunkt)
# ===========================================================================


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
    """Kontostand für den Login aus SpieloAutomat.

    Hat der Spieler schon Blackjack gespielt, ist das sein Endwert -
    sonst das Startguthaben vom Aggregator. Beides kommt aus EINER
    Abfrage: Fällt sie aus, gibt es ``None`` und es kann nie passieren,
    dass statt eines vorhandenen Endwerts das Startguthaben genommen wird.
    """
    if not _is_configured():
        log.warning("query_balance: InfluxDB nicht konfiguriert")
        return None
    flux = (
        f'from(bucket: "{SCORE_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r.{SCORE_TAG} == "{_esc_q(user_id)}")\n'
        f'  |> filter(fn: (r) =>\n'
        f'       (r._measurement == "{ENDWERT_MEASUREMENT}" and '
        f'r._field == "{ENDWERT_FIELD}") or\n'
        f'       (r._measurement == "{SCORE_MEASUREMENT}" and '
        f'r._field == "{SCORE_FIELD}"))\n'
        f'  |> last()\n'
    )
    raw = _run_query(flux)
    if raw is None:
        return None
    values = {
        row.get("_measurement"): row.get("_value") for row in _rows(raw)
    }
    for measurement, label in (
        (ENDWERT_MEASUREMENT, "Blackjack-Endwert"),
        (SCORE_MEASUREMENT, "Startguthaben"),
    ):
        value = values.get(measurement)
        if not value:
            continue
        try:
            balance = int(float(value))
        except ValueError:
            log.warning("query_balance: nicht-numerischer Wert %r", value)
            return None
        log.info("query_balance: user_id=%s -> %d (%s)",
                 user_id, balance, label)
        return balance
    log.info("query_balance: kein Datenpunkt für user_id=%s in %s",
             user_id, SCORE_BUCKET)
    return None


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
    raw = _run_query(flux)
    if raw is None:
        return None
    name = _first_value(raw)
    if name is None:
        log.info("query_username: kein Datenpunkt für user_id=%s in %s",
                 user_id, USERNAME_BUCKET)
        return None
    log.info("query_username: user_id=%s -> %r", user_id, name)
    return name


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------
def write_endwert(
    user_id: str,
    endwert: int,
    username: Optional[str] = None,
) -> bool:
    """Schreibt den Blackjack-Endwert nach SpieloAutomat (blackjack/endwert).

    Dieses Measurement schreibt nur Blackjack - der Aggregator fasst es
    nie an. ``username`` ist optional; wenn gesetzt, kommt im selben
    Datenpunkt ein zweites Field ``username`` dazu.
    """
    if not INFLUX_URL or not INFLUX_ORG or not INFLUX_TOKEN_WRITE:
        log.warning("write_endwert: INFLUX_TOKEN_WRITE fehlt in influx_db.py")
        return False

    fields = [f"{ENDWERT_FIELD}={int(endwert)}i"]
    if username:
        fields.append(f'{ENDWERT_NAME_FIELD}="{_esc_str(username)}"')
    line = (
        f"{ENDWERT_MEASUREMENT},{SCORE_TAG}={_esc_tag(user_id)} "
        f"{','.join(fields)} {int(time.time() * 1000)}\n"
    )
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
    log.info("write_endwert OK: user_id=%s endwert=%d username=%r",
             user_id, endwert, username)
    return True


# ---------------------------------------------------------------------------
# HTTP + Parser-Helfer
# ---------------------------------------------------------------------------
def _run_query(flux: str) -> Optional[str]:
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
        return None
    if not r.ok:
        log.warning("Flux-Query HTTP %s: %s", r.status_code, r.text[:200])
        return None
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


def _esc_q(s: str) -> str:
    """Escaping für Werte in Flux-Strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _esc_tag(s: str) -> str:
    """Escaping für Tag-Werte im Line-Protocol."""
    return (s.replace("\\", "\\\\")
             .replace(",", r"\,")
             .replace("=", r"\=")
             .replace(" ", r"\ "))


def _esc_str(s: str) -> str:
    """Escaping für String-Field-Werte im Line-Protocol."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
