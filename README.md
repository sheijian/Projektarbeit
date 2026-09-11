# Blackjack – Projektarbeit

Blackjack-Automat mit:

- Grafischer Oberfläche in **pygame** (gezeichnete Spielkarten, sehen aus wie ein normales Kartenspiel)
- Vier **Arcade-Tastern** (Hit / Stand / Double / Split) über **GPIO** auf einem Raspberry Pi
- **RFID-Scanner** (MFRC522) zum Identifizieren des Spielers
- **REST-API** zum Abrufen und Zurückschreiben des Guthabens aus einer Datenbank
- Optionalem **Mock-Server** und Tastatur-Fallback, damit die gesamte Anwendung auch auf einem
  normalen PC (ohne echte Hardware) getestet werden kann

## Verzeichnisstruktur

```
Projektarbeit/
├── main.py                 # Einstiegspunkt
├── requirements.txt
├── blackjack/
│   ├── cards.py            # Card, Deck
│   ├── hand.py             # Hand mit Blackjack-Wertung
│   ├── game.py             # Zustandsautomat des Spiels
│   ├── render.py           # Zeichnen einer Spielkarte in pygame
│   ├── gui.py              # Hauptfenster / Rendering
│   ├── buttons.py          # Arcade-Taster (GPIO + Tastatur-Fallback)
│   ├── rfid.py             # RFID-Reader (MFRC522 + Mock)
│   ├── api.py              # HTTP-Client für das Guthaben
│   └── config.py           # Konfiguration (Pins, API-URL, ...)
├── server/
│   └── mock_api.py         # Flask-Mock-Server zum Testen
└── tests/
    ├── test_hand.py
    └── test_game.py
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Auf einem Raspberry Pi zusätzlich `RPi.GPIO` und `mfrc522` installieren.
Ohne diese Pakete fällt die Anwendung automatisch auf Tastatur- und Mock-RFID
zurück, so dass sie am Entwicklungs-PC läuft.

## Starten

```bash
# Mock-API-Server in einem zweiten Terminal
python -m server.mock_api

# Spiel
python main.py --api http://localhost:5000
```

## Steuerung

| Aktion   | Arcade-Taste (GPIO-Pin) | Tastatur |
|----------|-------------------------|----------|
| Hit      | GPIO 17                 | `H`      |
| Stand    | GPIO 27                 | `S`      |
| Double   | GPIO 22                 | `D`      |
| Split    | GPIO 23                 | `P`      |

Der RFID-Chip wird beim Auflegen automatisch gelesen. Im Mock-Modus
kann mit `1`, `2`, `3` ein Test-Chip simuliert werden.

## API

Der Client erwartet folgende Endpunkte:

| Methode | Pfad                       | Beschreibung                       |
|---------|----------------------------|------------------------------------|
| GET     | `/players/<rfid_uid>`      | Liefert `{name, balance}`          |
| POST    | `/players/<rfid_uid>/balance` | Body `{delta: int}` – verändert Guthaben |

Der mitgelieferte Mock-Server (`server/mock_api.py`) implementiert beides
gegen eine SQLite-Datenbank.
