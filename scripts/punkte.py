"""Zeigt, welche Punkte Blackjack für einen Spieler aus der DB lädt.

Aufruf (auf dem Pi, im Projektordner):

    python -m scripts.punkte <userid>

Gibt die Punkte jeder Station, die Summe (Startguthaben), den
Blackjack-Endwert aus SpieloAutomat und den Wert aus, mit dem der
Spieler beim nächsten Einloggen startet.
"""

from __future__ import annotations

import logging
import sys

from blackjack import influx_db


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    uid = sys.argv[1].strip()
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if not influx_db.INFLUX_TOKEN_READ:
        print("INFLUX_TOKEN_READ fehlt in blackjack/influx_db.py")
        return 1

    schema = f"{influx_db.MEASUREMENT}/{influx_db.FIELD}, Tag {influx_db.TAG}"
    print(f"userid {uid}  ({schema})\n")
    try:
        points = influx_db.query_station_points(uid)
        endwert = influx_db.query_endwert(uid)
    except influx_db.DBError as e:
        print(f"Datenbank-Fehler: {e}")
        return 1

    for bucket in influx_db.STATION_BUCKETS:
        value = points.get(bucket)
        print(f"  {bucket:<18} {'-' if value is None else value:>6}")
    print(f"  {'= Startguthaben':<18} {sum(points.values()):>6}\n")
    print(f"  Blackjack-Endwert ({influx_db.SCORE_BUCKET}): "
          f"{'noch keiner' if endwert is None else endwert}")

    if endwert is not None:
        start = f"{endwert} (Blackjack-Endwert)"
    elif points:
        start = f"{sum(points.values())} (Startguthaben)"
    else:
        start = "keine Daten -> --starting-balance"
    print(f"  Nächster Login startet mit: {start}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
