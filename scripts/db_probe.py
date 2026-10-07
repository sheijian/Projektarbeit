"""Diagnose-Skript: prüft Punktzahl- und Username-Abfrage für eine
oder mehrere RFID-UUIDs direkt gegen die InfluxDB.

Nutzt dieselben Funktionen wie Blackjack beim Chip-Scan. Eignet sich,
um zu testen, ob die Zugangsdaten (Token/Schema) passen und ob zu einer
UUID überhaupt Daten in den beiden Buckets stehen.

Beispiele:

    # Mit einer bekannten UUID probieren
    python -m scripts.db_probe 7c3ed021-5099-4d46-9283-002adf814597

    # Mehrere UUIDs auf einmal (Tabellenansicht)
    python -m scripts.db_probe uuid1 uuid2 uuid3

    # Zusätzlich die rohe Flux-Antwort anzeigen
    python -m scripts.db_probe --raw <uuid>
"""

from __future__ import annotations

import argparse
import logging
import sys

import requests

from blackjack.influx_db import (
    POINTS_BUCKET,
    POINTS_FIELD,
    POINTS_MEASUREMENT,
    POINTS_TAG,
    USERNAME_FIELD,
    USERNAME_MEASUREMENT,
    USERNAME_TAG,
    _effective_config,
    _escape_flux_string,
    query_points,
    query_username,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("uuids", nargs="+", help="eine oder mehrere RFID-UUIDs")
    p.add_argument("--raw", action="store_true",
                   help="zusätzlich die rohe Flux-CSV-Antwort anzeigen")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = _effective_config()
    if not cfg.is_configured:
        print("InfluxDB nicht konfiguriert - Token in blackjack/influx_db.py "
              "(oder .env) eintragen.", file=sys.stderr)
        return 1

    print(f"Server : {cfg.url}")
    print(f"Org    : {cfg.org}")
    print(f"Bucket : PPMaster (username) / {POINTS_BUCKET} (score)\n")

    sess = requests.Session()

    for uid in args.uuids:
        print(f"--- {uid} ---")
        name = query_username(uid, cfg=cfg, session=sess)
        print(f"  Username (PPMaster)      : {name!r}")
        points = query_points(uid, cfg=cfg, session=sess)
        print(f"  Score    ({POINTS_BUCKET}) : {points!r}")

        if args.raw:
            print("\n  == Raw username query ==")
            print(_raw_query(sess, cfg, _username_flux(cfg.bucket, uid)))
            print("\n  == Raw score query ==")
            print(_raw_query(sess, cfg, _points_flux(uid)))
        print()
    return 0


def _username_flux(bucket: str, uid: str) -> str:
    safe = _escape_flux_string(uid)
    return (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{USERNAME_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{USERNAME_FIELD}")\n'
        f'  |> filter(fn: (r) => r.{USERNAME_TAG} == "{safe}")\n'
        f'  |> last()\n'
    )


def _points_flux(uid: str) -> str:
    safe = _escape_flux_string(uid)
    return (
        f'from(bucket: "{POINTS_BUCKET}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{POINTS_MEASUREMENT}")\n'
        f'  |> filter(fn: (r) => r._field == "{POINTS_FIELD}")\n'
        f'  |> filter(fn: (r) => r.{POINTS_TAG} == "{safe}")\n'
        f'  |> last()\n'
    )


def _raw_query(sess, cfg, flux):
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
    except Exception as e:
        return f"<Fehler: {e}>"
    return r.text if r.ok else f"HTTP {r.status_code}: {r.text[:300]}"


if __name__ == "__main__":
    sys.exit(main())
