"""Alle InfluxDB-Zugriffe des Blackjack-Automaten.

Drei Funktionen, mehr nicht:

    query_score(user_id)                     -> int | None  (aus SpieloAutomat)
    query_username(user_id)                  -> str | None  (aus PPMaster)
    write_score(user_id, score, name, delta) -> bool        (nach SpieloAutomat)

Zugangsdaten (URL, Org, Tokens) stehen oben als Konstanten. Trage die
Tokens direkt in dieser Datei ein - die Datei ist der einzige Ort, an
dem DB-Credentials liegen.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from typing import Optional

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

# SpieloAutomat ist unser gemeinsamer Punkte-Bucket (vom Aggregator
# dauerhaft befüllt + von Blackjack nach jeder Hand aktualisiert).
SCORE_BUCKET      = "SpieloAutomat"
SCORE_MEASUREMENT = "endscore"
SCORE_FIELD       = "score"       # int
SCORE_NAME_FIELD  = "username"    # str (zusätzlich im selben Datenpunkt)
SCORE_TAG         = "user_id"

# Gewinn/Verlust jeder Blackjack-Hand, ebenfalls in SpieloAutomat. Der
# Aggregator summiert diese Deltas zu den Punkten der sechs Stationen -
# sonst würde er den Blackjack-Stand alle paar Sekunden mit der reinen
# Stationssumme überschreiben.
DELTA_MEASUREMENT = "blackjack"
DELTA_FIELD       = "delta"       # int, z. B. -10 oder +25
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
def query_score(user_id: str) -> Optional[int]:
    """Letzter ``score`` für ``user_id`` aus SpieloAutomat."""
    if not _is_configured():
        log.warning("query_score: InfluxDB nicht konfiguriert")
        return None
    flux = (
        f'from(bucket: "{SCORE_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{SCORE_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{SCORE_FIELD}")\n'
        f'  |> filter(fn: (r) => r.{SCORE_TAG} == "{_esc_q(user_id)}")\n'
        f'  |> last()\n'
    )
    raw = _run_query(flux)
    if raw is None:
        return None
    value = _first_value(raw)
    if value is None:
        log.info("query_score: kein Datenpunkt für user_id=%s in %s",
                 user_id, SCORE_BUCKET)
        return None
    try:
        score = int(float(value))
    except ValueError:
        log.warning("query_score: nicht-numerischer Wert %r", value)
        return None
    log.info("query_score: user_id=%s -> %d", user_id, score)
    return score


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
def write_score(
    user_id: str,
    score: int,
    username: Optional[str] = None,
    delta: Optional[int] = None,
) -> bool:
    """Schreibt den aktuellen Kontostand nach SpieloAutomat.

    ``username`` ist optional; wenn gesetzt, kommt im selben Datenpunkt
    ein zweites Field ``username`` dazu.

    ``delta`` ist der Blackjack-Gewinn/-Verlust seit dem letzten Write.
    Wenn gesetzt, geht im selben Request ein ``blackjack``-Datenpunkt
    mit, den der Aggregator in die Gesamtsumme einrechnet.
    """
    if not INFLUX_URL or not INFLUX_ORG or not INFLUX_TOKEN_WRITE:
        log.warning("write_score: INFLUX_TOKEN_WRITE fehlt in influx_db.py")
        return False

    ts_ms = int(time.time() * 1000)
    fields = [f"{SCORE_FIELD}={int(score)}i"]
    if username:
        fields.append(f'{SCORE_NAME_FIELD}="{_esc_str(username)}"')
    line = (
        f"{SCORE_MEASUREMENT},{SCORE_TAG}={_esc_tag(user_id)} "
        f"{','.join(fields)} {ts_ms}\n"
    )
    if delta is not None:
        line += (
            f"{DELTA_MEASUREMENT},{SCORE_TAG}={_esc_tag(user_id)} "
            f"{DELTA_FIELD}={int(delta)}i {ts_ms}\n"
        )
    log.debug("write_score -> %s/api/v2/write LINES: %s",
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
        log.warning("write_score: Netzwerkfehler %s", e)
        return False
    if not r.ok:
        log.warning("write_score HTTP %s: %s | LINE: %s",
                    r.status_code, r.text[:200], line.strip())
        return False
    log.info("write_score OK: user_id=%s score=%d delta=%s username=%r",
             user_id, score, delta, username)
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


def _first_value(csv_text: str) -> Optional[str]:
    """Erste ``_value``-Zelle aus einer annotierten Flux-CSV. ``None``
    wenn keine Datenzeile."""
    reader = csv.reader(io.StringIO(csv_text))
    value_idx: Optional[int] = None
    for row in reader:
        if not row:
            value_idx = None
            continue
        first = (row[0] or "").strip()
        if first.startswith("#"):
            value_idx = None
            continue
        if value_idx is None:
            try:
                value_idx = row.index("_value")
            except ValueError:
                pass
            continue
        if value_idx < len(row):
            v = row[value_idx].strip()
            if v:
                return v
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
