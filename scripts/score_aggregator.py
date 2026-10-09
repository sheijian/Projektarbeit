"""Score-Aggregator - läuft dauerhaft auf dem Raspberry Pi.

Pollt alle 5 Sekunden die sechs Spielstationen-Buckets, summiert pro
``user_id`` und schreibt die Summe als Startguthaben nach
``SpieloAutomat`` (endscore/score) - aber nur für User, deren Summe sich
seit dem letzten Write geändert hat.

Den Blackjack-Endwert (blackjack/endwert) fasst der Aggregator nie an.

Aufruf:
    python -m scripts.score_aggregator            # Dauerlauf
    python -m scripts.score_aggregator --once     # ein Durchlauf
    python -m scripts.score_aggregator --verbose  # alles mitloggen

Als Hintergrund-Dienst: siehe scripts/blackjack-aggregator.service.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import requests

from blackjack.influx_db import (
    INFLUX_ORG,
    INFLUX_TOKEN_READ,
    INFLUX_TOKEN_WRITE,
    INFLUX_URL,
    SCORE_BUCKET,
    SCORE_FIELD,
    SCORE_MEASUREMENT,
    SCORE_TAG,
    _esc_tag,
)


log = logging.getLogger("aggregator")


# ---------------------------------------------------------------------------
# Die sechs Quell-Buckets (bucket, measurement, field, tag_name).
# ---------------------------------------------------------------------------
SOURCE_BUCKETS: List[Tuple[str, str, str, str]] = [
    ("HeisserDraht",     "Endscore",            "Endscore",      "userID"),
    ("Ampelsequenz",     "endscore",            "score",         "rfidTag"),
    ("TimerStrike",      "endscore",            "score",         "user_id"),
    ("Wurfgenauigkeit",  "spieler_ergebnisse",  "gesamtpunkte",  "user_id"),
    ("Whackamole",       "endscore",            "score",         "rfidTag"),
    ("Gedaechtnistest",  "endscore",            "endscore",      "user_id"),
]


# ---------------------------------------------------------------------------
def collect_totals(session: requests.Session) -> Dict[str, int]:
    """Fragt alle sechs Buckets ab und addiert pro user_id."""
    totals: Dict[str, int] = defaultdict(int)
    for bucket, meas, field, tag in SOURCE_BUCKETS:
        flux = (
            f'from(bucket: "{bucket}")\n'
            f'  |> range(start: 0)\n'
            f'  |> filter(fn: (r) => r._measurement == "{meas}")\n'
            f'  |> filter(fn: (r) => r._field == "{field}")\n'
            f'  |> group(columns: ["{tag}"])\n'
            f'  |> sum()\n'
        )
        try:
            r = session.post(
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
            log.warning("Bucket %s: Netzwerkfehler %s", bucket, e)
            continue
        if not r.ok:
            log.warning("Bucket %s: HTTP %s: %s",
                        bucket, r.status_code, r.text[:120])
            continue
        for uid, score in _parse_grouped(r.text, tag).items():
            uid = uid.strip()
            if uid:
                totals[uid] += score
        log.debug("Bucket %s: %d Punkte-Zeilen", bucket, len(r.text.splitlines()))
    return dict(totals)


def write_totals(
    session: requests.Session,
    totals: Dict[str, int],
) -> bool:
    """Schreibt pro user_id das Startguthaben nach SpieloAutomat."""
    if not totals:
        return True
    ts_ms = int(time.time() * 1000)
    lines = [
        f"{SCORE_MEASUREMENT},{SCORE_TAG}={_esc_tag(uid)} "
        f"{SCORE_FIELD}={int(score)}i {ts_ms}"
        for uid, score in totals.items()
    ]
    body = "\n".join(lines) + "\n"
    try:
        r = session.post(
            f"{INFLUX_URL}/api/v2/write",
            params={"org": INFLUX_ORG, "bucket": SCORE_BUCKET, "precision": "ms"},
            headers={
                "Authorization": f"Token {INFLUX_TOKEN_WRITE}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            data=body.encode("utf-8"),
            timeout=5,
        )
    except requests.RequestException as e:
        log.warning("Write-Request fehlgeschlagen: %s", e)
        return False
    if not r.ok:
        log.warning("SpieloAutomat-Write HTTP %s: %s",
                    r.status_code, r.text[:200])
        return False
    log.info("SpieloAutomat: %d User aktualisiert", len(totals))
    return True


def run_once(
    session: requests.Session,
    last_written: Dict[str, int],
) -> Optional[Dict[str, int]]:
    """Ein Durchlauf: Summen holen und nur geänderte User schreiben.

    ``last_written`` merkt sich pro user_id das zuletzt geschriebene
    Startguthaben und wird nach erfolgreichem Write aktualisiert. Liefert
    die geschriebenen Summen (``None`` bei Write-Fehler).
    """
    totals = collect_totals(session)
    changed = {
        uid: score for uid, score in totals.items()
        if last_written.get(uid) != score
    }
    if not changed:
        log.debug("Keine Änderungen (%d User).", len(totals))
        return {}
    if not write_totals(session, changed):
        return None
    last_written.update(changed)
    return changed


def _parse_grouped(csv_text: str, tag_name: str) -> Dict[str, int]:
    """Parst eine Flux-CSV mit group+sum, liefert {tag_value: _value}."""
    import csv
    import io

    result: Dict[str, int] = {}
    reader = csv.reader(io.StringIO(csv_text))
    value_idx = tag_idx = None
    for row in reader:
        if not row:
            value_idx = tag_idx = None
            continue
        if (row[0] or "").strip().startswith("#"):
            value_idx = tag_idx = None
            continue
        if value_idx is None or tag_idx is None:
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


# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not INFLUX_URL or not INFLUX_TOKEN_READ or not INFLUX_TOKEN_WRITE:
        log.error("InfluxDB nicht konfiguriert. Trage URL/Tokens in "
                  "blackjack/influx_db.py ganz oben ein.")
        return 1

    log.info("Aggregator startet - %s, Intervall %.1fs", INFLUX_URL, args.interval)
    sess = requests.Session()
    stop = {"flag": False}
    signal.signal(signal.SIGINT,  lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

    last_written: Dict[str, int] = {}
    while not stop["flag"]:
        try:
            run_once(sess, last_written)
        except Exception as e:  # pragma: no cover
            log.exception("Aggregator-Fehler: %s", e)

        if args.once:
            break
        for _ in range(int(args.interval * 10)):
            if stop["flag"]:
                break
            time.sleep(0.1)

    sess.close()
    log.info("Aggregator beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
