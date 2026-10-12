"""Zeigt, welche Punkte Blackjack für einen Spieler aus der DB lädt.

Aufruf (auf dem Pi, im Projektordner):

    python -m scripts.punkte <userid>                  # Punkte + Endwert
    python -m scripts.punkte --schema                  # echtes DB-Schema
    python -m scripts.punkte <userid> --reset-endwert  # Endwert löschen

Ohne Option: Punkte jeder Station, Summe (Startguthaben), Blackjack-
Endwert aus SpieloAutomat und der Wert, mit dem der Spieler beim
nächsten Einloggen startet.

``--schema`` listet für jeden Bucket, welche measurement/field/tags dort
wirklich stehen - so sieht man, ob eine Station ein anderes Schema
schreibt als vereinbart.

``--reset-endwert`` löscht den Blackjack-Endwert des Spielers; danach
startet er wieder mit dem Startguthaben (zum Zurücksetzen von
Testspielern).
"""

from __future__ import annotations

import argparse
import logging
import sys

from blackjack import influx_db


def show_points(uid: str) -> int:
    schemas = ", ".join(f"{m}/{f}" for m, f in influx_db.STATION_SCHEMAS)
    print(f"userid {uid}")
    print(f"Stationen: {schemas}, Tag {' oder '.join(influx_db.STATION_TAGS)}\n")
    points = influx_db.query_station_points(uid)
    endwert = influx_db.query_endwert(uid)

    for bucket in influx_db.STATION_BUCKETS:
        value = points.get(bucket)
        print(f"  {bucket:<18} {'-' if value is None else value:>6}")
    print(f"  {'= Startguthaben':<18} {sum(points.values()):>6}\n")
    print(f"  Blackjack-Endwert ({influx_db.SCORE_BUCKET}/"
          f"{influx_db.MEASUREMENT}/{influx_db.FIELD}): "
          f"{'noch keiner' if endwert is None else endwert}")

    if endwert is not None:
        start = f"{endwert} (Blackjack-Endwert)"
    elif points:
        start = f"{sum(points.values())} (Startguthaben)"
    else:
        start = "keine Daten -> --starting-balance"
    print(f"  Nächster Login startet mit: {start}")
    return 0


def show_schema() -> int:
    for bucket in (*influx_db.STATION_BUCKETS, influx_db.SCORE_BUCKET,
                   influx_db.USERNAME_BUCKET):
        print(f"{bucket}:")
        try:
            rows = influx_db.list_schema(bucket)
        except influx_db.DBError as e:
            print(f"  Fehler: {e}")
            continue
        if not rows:
            print("  (leer)")
        for measurement, field, tags in rows:
            print(f"  measurement={measurement:<20} field={field:<14} "
                  f"tags={', '.join(tags) or '-'}")
    return 0


def reset_endwert(uid: str) -> int:
    if influx_db.delete_endwert(uid):
        print(f"Endwert für {uid} gelöscht - nächster Login startet mit "
              f"dem Startguthaben.")
        return 0
    print("Löschen fehlgeschlagen (Schreib-Token? Log oben beachten).")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description="Punkte eines Spielers prüfen")
    p.add_argument("userid", nargs="?")
    p.add_argument("--schema", action="store_true",
                   help="measurement/field/tags aller Buckets anzeigen")
    p.add_argument("--reset-endwert", action="store_true",
                   help="Blackjack-Endwert des Spielers löschen")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if not influx_db.INFLUX_TOKEN_READ:
        print("INFLUX_TOKEN_READ fehlt in blackjack/influx_db.py")
        return 1
    try:
        if args.schema:
            return show_schema()
        if not args.userid:
            p.print_help()
            return 2
        uid = args.userid.strip()
        if args.reset_endwert:
            return reset_endwert(uid)
        return show_points(uid)
    except influx_db.DBError as e:
        print(f"Datenbank-Fehler: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
