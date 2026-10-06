"""Score-Aggregator - läuft dauerhaft auf dem Raspberry Pi.

Pollt im festen Intervall (Default 5 s) die sechs Spielstationen-Buckets,
summiert pro ``user_id`` die Endscores und schreibt den Gesamtscore in
den gemeinsamen Bucket ``SpieloAutomat``. Von dort wird der Wert von
jedem Blackjack-Login über ``influx_db.query_points`` gelesen.

Aufruf (zum Testen):

    python -m scripts.score_aggregator --verbose

Als Dienst im Hintergrund: siehe scripts/blackjack-aggregator.service.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections import defaultdict
from typing import Dict, List, Tuple

import requests

from blackjack.influx_db import (
    POINTS_BUCKET,
    POINTS_FIELD,
    POINTS_MEASUREMENT,
    POINTS_TAG,
    _effective_config,
    _escape_line_protocol_tag,
    parse_flux_grouped_sum,
)


log = logging.getLogger("score_aggregator")


# ---------------------------------------------------------------------------
# Die sechs Quell-Buckets der anderen Gruppen.
#   (bucket, measurement, field, tag_name)
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
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--interval", type=float, default=5.0,
        help="Sekunden zwischen zwei Durchläufen (Default 5).",
    )
    p.add_argument(
        "--range", default="0",
        help="Flux-Range für die Summierung (z. B. '-1h', Default: 0 = seit "
             "Beginn).",
    )
    p.add_argument(
        "--once", action="store_true",
        help="Nur ein Durchlauf, dann beenden (für Tests / Debugging).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
def query_bucket_sums(
    session: requests.Session,
    cfg,
    bucket: str,
    measurement: str,
    field: str,
    tag_name: str,
    range_: str = "0",
) -> Dict[str, int]:
    """Summiert pro ``tag_name``-Wert alle Punkte eines Buckets."""
    flux = (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: {range_})\n'
        f'  |> filter(fn: (r) => r._measurement == "{measurement}")\n'
        f'  |> filter(fn: (r) => r._field == "{field}")\n'
        f'  |> group(columns: ["{tag_name}"])\n'
        f'  |> sum()\n'
    )
    try:
        r = session.post(
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
        log.warning("Bucket %s: Query fehlgeschlagen: %s", bucket, e)
        return {}
    if not r.ok:
        log.warning("Bucket %s: HTTP %s: %s",
                    bucket, r.status_code, r.text[:120])
        return {}
    sums = parse_flux_grouped_sum(r.text, tag_name)
    log.debug("Bucket %s: %d User", bucket, len(sums))
    return sums


# ---------------------------------------------------------------------------
def write_totals(
    session: requests.Session,
    cfg,
    totals: Dict[str, int],
) -> bool:
    """Schreibt pro user_id einen endscore-Datenpunkt in SpieloAutomat."""
    if not totals:
        return True
    ts_ms = int(time.time() * 1000)
    lines = []
    for uid, score in totals.items():
        safe_uid = _escape_line_protocol_tag(uid)
        lines.append(
            f"{POINTS_MEASUREMENT},{POINTS_TAG}={safe_uid} "
            f"{POINTS_FIELD}={int(score)}i {ts_ms}"
        )
    body = "\n".join(lines) + "\n"
    try:
        r = session.post(
            f"{cfg.url}/api/v2/write",
            params={
                "org": cfg.org,
                "bucket": POINTS_BUCKET,
                "precision": "ms",
            },
            headers={
                "Authorization": f"Token {cfg.token_write}",
                "Content-Type": "text/plain; charset=utf-8",
            },
            data=body.encode("utf-8"),
            timeout=5,
        )
    except requests.RequestException as e:
        log.warning("SpieloAutomat-Write fehlgeschlagen: %s", e)
        return False
    if not r.ok:
        log.warning("SpieloAutomat-Write HTTP %s: %s",
                    r.status_code, r.text[:120])
        return False
    log.info("SpieloAutomat: %d User-Scores aktualisiert", len(totals))
    return True


# ---------------------------------------------------------------------------
def collect_totals(
    session: requests.Session,
    cfg,
    range_: str,
) -> Dict[str, int]:
    """Fragt alle sechs Buckets ab und addiert pro user_id."""
    totals: Dict[str, int] = defaultdict(int)
    for bucket, meas, field, tag in SOURCE_BUCKETS:
        for uid, score in query_bucket_sums(
            session, cfg, bucket, meas, field, tag, range_=range_,
        ).items():
            uid = uid.strip()
            if uid:
                totals[uid] += score
    return dict(totals)


# ---------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = _effective_config()
    if not cfg.is_configured:
        log.error(
            "InfluxDB nicht konfiguriert. INFLUX_TOKEN_READ und "
            "INFLUX_TOKEN_WRITE in blackjack/influx_db.py (oder in .env) "
            "setzen."
        )
        return 1
    log.info(
        "Aggregator startet - %s, Intervall %.1fs, range=%s",
        cfg.url, args.interval, args.range,
    )

    sess = requests.Session()
    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        log.info("Signal %s empfangen - beende", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Cache: nur schreiben, wenn sich der Score eines Users geändert hat.
    last_scores: Dict[str, int] = {}

    while not stop["flag"]:
        try:
            totals = collect_totals(sess, cfg, args.range)
            changed = {
                uid: score for uid, score in totals.items()
                if last_scores.get(uid) != score
            }
            if changed:
                if write_totals(sess, cfg, changed):
                    last_scores.update(changed)
            else:
                log.debug("Nichts verändert (%d User überwacht)", len(totals))
        except Exception as e:  # pragma: no cover
            log.exception("Aggregator-Fehler: %s", e)

        if args.once:
            break

        # schlafen, aber zwischendurch auf Stop-Signal reagieren.
        for _ in range(int(args.interval * 10)):
            if stop["flag"]:
                break
            time.sleep(0.1)

    sess.close()
    log.info("Aggregator beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
