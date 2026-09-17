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

### Volle Konfiguration (RFID + API)

```bash
# Mock-API-Server in einem zweiten Terminal
python -m server.mock_api

# Spiel mit RFID-Reader und API
python main.py --api http://localhost:5000
```

### Offline-Modus (ohne RFID, ohne API)

Damit das Spiel auch ohne Hardware und ohne Server komplett getestet
werden kann, gibt es einen Offline-Modus. Er nutzt einen In-Memory-
Player-Store, der drei vordefinierte Testspieler enthält
(Alice/Bob/Charlie).

```bash
# sofort mit "Alice" spielen (kein Chip, kein Server nötig)
python main.py --offline

# anderer Testspieler
python main.py --offline --auto-login Bob

# Offline, aber mit simuliertem RFID: Tasten 1/2/3 wechseln Spieler
python main.py --offline --no-auto-login
```

In allen Fällen bleiben die Arcade-Taster bzw. der Tastatur-Fallback
`H` / `S` / `D` / `P` aktiv.

## Steuerung

| Aktion   | Arcade-Taste (GPIO-Pin) | Tastatur |
|----------|-------------------------|----------|
| Hit      | GPIO 17                 | `H`      |
| Stand    | GPIO 27                 | `S`      |
| Double   | GPIO 22                 | `D`      |
| Split    | GPIO 23                 | `P`      |

Während des Spielerzugs bedeuten die vier Taster genau das, was oben
steht. **Zwischen zwei Runden** (vor dem Deal bzw. nach einer Runde)
werden die beiden linken Taster umgewidmet:

| Zustand         | Hit-Taste            | Stand-Taste      |
|-----------------|----------------------|------------------|
| Spielerzug      | Karte ziehen         | Passen           |
| Vor der Runde   | **Einsatz erhöhen** (zyklisch) | **Deal starten** |

Die Einsatzstufen sind 10, 25, 50, 100, 250, 500, 1000. Beim Erreichen der
höchsten Stufe springt der Wert wieder auf 10 - so reicht ein einziger
Knopf für die komplette Einsatz-Bedienung.

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
