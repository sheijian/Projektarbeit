"""Legt in der InfluxDB die drei Test-Spieler an (Alice, Bob, Charlie).

Voraussetzung: `.env` mit gültigen InfluxDB-Zugangsdaten (siehe .env.example).

Aufruf:

    python -m scripts.seed_players

Nach dem Seeden können die Test-Spieler über die Mock-RFID-Tasten 1/2/3
angemeldet werden - oder über ihre RFID-Chips, sofern die Chip-UIDs in
`blackjack/config.py::MOCK_RFID_KEYS` entsprechend eingetragen sind.
"""

from __future__ import annotations

import sys

from blackjack.config import MOCK_RFID_KEYS
from blackjack.influx_store import InfluxPlayerStore
from blackjack.store import StoreError


DEFAULT_SEED = [
    (MOCK_RFID_KEYS["1"], "Alice",   500),
    (MOCK_RFID_KEYS["2"], "Bob",     250),
    (MOCK_RFID_KEYS["3"], "Charlie", 1000),
]


def main() -> int:
    try:
        store = InfluxPlayerStore()
    except StoreError as e:
        print(f"Fehler beim Verbinden: {e}", file=sys.stderr)
        return 1

    try:
        for rfid, name, balance in DEFAULT_SEED:
            store.seed_player(rfid, name, balance)
            print(f"OK  {name:8s} rfid={rfid} balance={balance}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
