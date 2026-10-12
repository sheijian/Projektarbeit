"""Zeigt, welche Punkte Blackjack für einen Spieler aus der DB lädt.

Aufruf (auf dem Pi, im Projektordner):

    python -m scripts.punkte <userid>            # Punkte, Kontostand, Glück
    python -m scripts.punkte --schema            # echtes DB-Schema
    python -m scripts.punkte <userid> --reset    # Spielstand löschen

Ohne Option: Punkte jeder Station, Summe (Startguthaben), letzter
Kontostand (live) und Glückswert (endscore) aus SpieloAutomat und der
Wert, mit dem der Spieler beim nächsten Einloggen startet.

``--schema`` listet für jeden Bucket, welche measurement/field/tags dort
wirklich stehen - so sieht man, ob eine Station ein anderes Schema
schreibt als vereinbart.

``--reset`` löscht Kontostand und Glückswerte des Spielers in
SpieloAutomat; danach startet er wieder mit dem Startguthaben (zum
Zurücksetzen von Testspielern).
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
    stand = influx_db.query_spielstand(uid)

    for bucket in influx_db.STATION_BUCKETS:
        value = points.get(bucket)
        print(f"  {bucket:<18} {'-' if value is None else value:>6}")
    print(f"  {'= Stationspunkte':<18} {sum(points.values()):>6}\n")

    def show(field: str, label: str, unit: str = "") -> None:
        value = stand.get(field)
        text = "noch keiner" if value is None else f"{value}{unit}"
        print(f"  {label:<44} {text}")

    where = f"{influx_db.SCORE_BUCKET}/{influx_db.MEASUREMENT}"
    show(influx_db.FIELD_LIVE, f"Kontostand ({where}/{influx_db.FIELD_LIVE})")
    show(influx_db.FIELD_STATIONEN, "  davon Stationspunkte (stationen)")
    show(influx_db.FIELD_GLUECK, f"Glückswert ({influx_db.FIELD_GLUECK}, "
         f"letzter Durchlauf)", " %")

    start = influx_db.query_balance(uid)
    if start is None:
        print("\n  Nächster Login startet mit: keine Daten -> --starting-balance")
    else:
        print(f"\n  Nächster Login startet mit: {start.balance}")
        print(f"    ({start.quelle})")
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


def reset(uid: str) -> int:
    if influx_db.delete_spielstand(uid):
        print(f"Spielstand für {uid} gelöscht - nächster Login startet mit "
              f"dem Startguthaben.")
        return 0
    print("Löschen fehlgeschlagen (Schreib-Token? Log oben beachten).")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description="Punkte eines Spielers prüfen")
    p.add_argument("userid", nargs="?")
    p.add_argument("--schema", action="store_true",
                   help="measurement/field/tags aller Buckets anzeigen")
    p.add_argument("--reset", action="store_true",
                   help="Kontostand + Glückswerte des Spielers löschen")
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
        if args.reset:
            return reset(uid)
        return show_points(uid)
    except influx_db.DBError as e:
        print(f"Datenbank-Fehler: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
