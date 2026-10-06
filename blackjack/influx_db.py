"""Alle InfluxDB-Zugriffe des Blackjack-Automaten.

Hier liegt die komplette Datenbank-Logik an einem Ort - jede künftige
Abfrage oder Schreib-Operation gehört in diese Datei.

Datenmodell im Bucket:

    PPMaster,user_id=<uuid>  username="<name>"  <timestamp>

Weitere Measurements (Punkte, Winrate etc.) folgen später - die
entsprechenden Platzhalter stehen am Ende der Datei.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Optional

import requests

from .db_config import INFLUX, InfluxConfig, load_influx_config


log = logging.getLogger(__name__)


# ===========================================================================
# InfluxDB-Zugangsdaten
# ===========================================================================
# Hier kannst du Server/Bucket/Tokens direkt eintragen. Die Werte unten
# gewinnen gegenüber einer evtl. vorhandenen .env-Datei (sofern sie
# nicht leer sind).
#
# WICHTIG: Wenn du die Tokens hier einträgst, pass auf, dass du die
# Datei NICHT mit echten Tokens committest - sonst stehen sie im
# öffentlichen Git-Repo. Entweder vor dem Commit wieder leer machen
# oder stattdessen die .env-Lösung benutzen (siehe .env.example).
# ===========================================================================
INFLUX_URL         = "http://10.0.244.254:8086"
INFLUX_ORG         = "FIT244"
INFLUX_BUCKET      = "PPMaster"
INFLUX_BUCKET_ID   = "0a38c021dbad8b0c"

# <<< HIER DEN LESE-TOKEN EINFÜGEN >>>
INFLUX_TOKEN_READ  = ""

# <<< HIER DEN SCHREIB-TOKEN EINFÜGEN >>>
INFLUX_TOKEN_WRITE = ""
# ===========================================================================


def _effective_config() -> InfluxConfig:
    """Nimmt die Konstanten oben, wenn sie gefüllt sind - sonst .env.

    So kann man wahlweise den Token direkt in dieser Datei eintragen oder
    (sauberer) in .env - beides funktioniert, Code gewinnt.
    """
    env = INFLUX
    read_token  = INFLUX_TOKEN_READ  or env.token_read
    write_token = INFLUX_TOKEN_WRITE or env.token_write
    return InfluxConfig(
        url=INFLUX_URL or env.url,
        org=INFLUX_ORG or env.org,
        bucket=INFLUX_BUCKET or env.bucket,
        bucket_id=INFLUX_BUCKET_ID or env.bucket_id,
        token_read=read_token,
        token_write=write_token,
    )


# ---------------------------------------------------------------------------
# HTTP-Session (lazy)
# ---------------------------------------------------------------------------
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


# ---------------------------------------------------------------------------
# Username-Abfrage
# ---------------------------------------------------------------------------
# Measurement/Field passen zum Beispiel-Export der PPMaster-Datenbank:
#   ,_result,0,...,_time,_value,_field,_measurement
#   ,_result,0,...,...,Jonathan,username,PPMaster
USERNAME_MEASUREMENT = "PPMaster"
USERNAME_FIELD = "username"
USERNAME_TAG = "user_id"


POINTS_BUCKET = "SpieloAutomat"
POINTS_MEASUREMENT = "endscore"
POINTS_FIELD = "score"
POINTS_TAG = "user_id"


def query_points(
    user_id: str,
    cfg: Optional[InfluxConfig] = None,
    session: Optional[requests.Session] = None,
) -> Optional[int]:
    """Liest den aktuellen Gesamt-Score aus dem SpieloAutomat-Bucket.

    Die Werte dort werden vom Aggregator (``scripts/score_aggregator.py``)
    aus den sechs anderen Spielstationen-Buckets zusammengerechnet.
    """
    cfg = cfg or _effective_config()
    if not cfg.is_configured:
        return None

    safe_id = _escape_flux_string(user_id)
    flux = (
        f'from(bucket: "{POINTS_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{POINTS_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{POINTS_FIELD}")\n'
        f'  |> filter(fn: (r) => r.{POINTS_TAG} == "{safe_id}")\n'
        f'  |> last()\n'
    )
    log.debug("Influx query_points:\n%s", flux)
    text = _run_query(flux, cfg, session)
    if text is None:
        return None
    raw = _parse_flux_first_value(text)
    if raw is None:
        log.info("Influx query_points(%s) -> noch kein Score", user_id)
        return None
    try:
        points = int(float(raw))
    except ValueError:
        log.warning("Influx query_points: ungültiger Wert %r", raw)
        return None
    log.info("Influx query_points(%s) -> %d", user_id, points)
    return points


# ---------------------------------------------------------------------------
# Username
# ---------------------------------------------------------------------------
def query_username(
    user_id: str,
    cfg: Optional[InfluxConfig] = None,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """Liest den Anzeigenamen zu einer RFID-UID aus dem PPMaster-Bucket.

    Liefert ``None``, wenn kein Datenpunkt gefunden wurde oder die
    Datenbank nicht konfiguriert / erreichbar ist. Fehler sind nicht
    fatal - der Aufrufer kann auf den Namen vom ESP32-Reader zurück-
    fallen.
    """
    cfg = cfg or _effective_config()
    if not cfg.is_configured:
        log.debug(
            "query_username: InfluxDB nicht konfiguriert "
            "(INFLUX_TOKEN_READ in blackjack/influx_db.py leer?)"
        )
        return None

    safe_id = _escape_flux_string(user_id)
    flux = (
        f'from(bucket: "{cfg.bucket}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{USERNAME_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{USERNAME_FIELD}")\n'
        f'  |> filter(fn: (r) => r.{USERNAME_TAG} == "{safe_id}")\n'
        f'  |> last()\n'
    )
    log.debug("Influx query_username:\n%s", flux)

    text = _run_query(flux, cfg, session)
    if text is None:
        return None

    name = _parse_flux_first_value(text)
    log.info(
        "Influx query_username(%s) -> %r", user_id, name,
    )
    return name


# ---------------------------------------------------------------------------
# Session-Ende
# ---------------------------------------------------------------------------
def write_session_end(
    user_id: str,
    delta: int,
    wins: int,
    plays: int,
    cfg: Optional[InfluxConfig] = None,
    session: Optional[requests.Session] = None,
) -> None:
    """TODO: Endscore + Winrate nach Session-Ende in den Bucket schreiben.

    Platzhalter - sobald wir uns darauf einigen, in welchen Bucket die
    Blackjack-Session-Ergebnisse zurückfließen sollen, kommt hier das
    passende Line-Protocol-Write hin. Bis dahin wird nur geloggt, damit
    man im Spiel sieht was geschrieben würde.
    """
    log.info(
        "write_session_end TODO: user_id=%s delta=%+d wins=%d plays=%d",
        user_id, delta, wins, plays,
    )


# ---------------------------------------------------------------------------
# HTTP-Helfer
# ---------------------------------------------------------------------------
def _run_query(
    flux: str,
    cfg: InfluxConfig,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """Führt eine Flux-Query aus und liefert die rohe CSV-Antwort.

    Netzwerk- und HTTP-Fehler werden nur geloggt - der Aufrufer bekommt
    ``None`` zurück und kann entsprechend reagieren.
    """
    sess = session or _get_session()
    try:
        r = sess.post(
            f"{cfg.url}/api/v2/query",
            params={"org": cfg.org},
            headers={
                "Authorization": f"Token {cfg.token_read}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux.encode("utf-8"),
            timeout=5,
        )
    except requests.RequestException as e:
        log.warning("Influx-Query fehlgeschlagen: %s", e)
        return None
    if not r.ok:
        log.warning("Influx HTTP %s: %s", r.status_code, r.text[:120])
        return None
    log.debug("Influx-Antwort (%d bytes): %s", len(r.text), r.text[:300])
    return r.text


# ---------------------------------------------------------------------------
# Flux-CSV-Parser und Escaping
# ---------------------------------------------------------------------------
def parse_flux_grouped_sum(text: str, tag_name: str) -> dict[str, int]:
    """Parst eine Flux-CSV mit mehreren Tabellen (eine pro Tag-Wert).

    Liefert ``{tag_value: aggregierte_summe}`` - mehrfaches Auftauchen
    desselben Tag-Werts wird addiert, nicht überschrieben.
    """
    result: dict[str, int] = {}
    reader = csv.reader(io.StringIO(text))
    value_idx: Optional[int] = None
    tag_idx: Optional[int] = None
    for row in reader:
        if not row:
            value_idx = tag_idx = None
            continue
        first = (row[0] or "").strip()
        if first.startswith("#"):
            value_idx = tag_idx = None
            continue
        if value_idx is None or tag_idx is None:
            # Header-Kandidat.
            try:
                value_idx = row.index("_value")
            except ValueError:
                value_idx = None
            try:
                tag_idx = row.index(tag_name)
            except ValueError:
                tag_idx = None
            continue
        if value_idx >= len(row) or tag_idx >= len(row):
            continue
        tag_val = row[tag_idx].strip()
        raw = row[value_idx].strip()
        if not tag_val or not raw:
            continue
        try:
            result[tag_val] = result.get(tag_val, 0) + int(float(raw))
        except ValueError:
            continue
    return result


def _parse_flux_first_value(text: str) -> Optional[str]:
    """Extrahiert den ersten ``_value`` aus einer annotierten Flux-CSV.

    Der Wert wird 1:1 als String zurückgegeben (Datentyp-Interpretation
    liegt beim Aufrufer). Liefert ``None``, wenn keine Datenzeile mit
    einer ``_value``-Spalte vorhanden ist.
    """
    reader = csv.reader(io.StringIO(text))
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
        if value_idx >= len(row):
            continue
        raw = row[value_idx].strip()
        if raw:
            return raw
    return None


def _escape_flux_string(value: str) -> str:
    """Escaping für Werte innerhalb eines Flux-Strings (\" und \\)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Noch für später: Line-Protocol-Escape (Punkte-Schreiben)
# ---------------------------------------------------------------------------
def _escape_line_protocol_tag(value: str) -> str:
    """Escaping für Tag-Werte im Line-Protocol: Kommas, Gleichzeichen und
    Leerzeichen müssen mit Backslash escaped werden."""
    return (
        value.replace("\\", "\\\\")
        .replace(",", r"\,")
        .replace("=", r"\=")
        .replace(" ", r"\ ")
    )
