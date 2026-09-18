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

### Produktivbetrieb (RFID + InfluxDB)

```bash
# einmalig: .env mit Zugangsdaten füllen und Test-Spieler seeden
cp .env.example .env
python -m scripts.seed_players

# Spiel starten (Store 'influx' wird automatisch gewählt)
python main.py
```

### Entwicklung mit lokalem Mock-Server

```bash
# Mock-API-Server in einem zweiten Terminal
python -m server.mock_api

# Spiel mit RFID-Reader und lokalem HTTP-Mock
python main.py --store api --api http://localhost:5000
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

Das verwendete Arcade-Board (**EG STARTS Zero-Delay-Encoder**) wird per
USB an den Pi angeschlossen und meldet sich dort als HID-Gamepad. Die
vier Taster-Anschlüsse sind mit **K1, K2, K3, K4** beschriftet und
bekommen vom Board jeweils eine feste Button-Nummer zugeteilt.

Standardmäßig wählt die Anwendung die beste verfügbare Eingabe
automatisch (`--input auto`): USB-Gamepad → GPIO → Tastatur.
Explizit setzen kannst du sie mit

```bash
python main.py --input usb        # USB-Encoder (Standard für das Board)
python main.py --input gpio       # Taster direkt am Pi-Header
python main.py --input keyboard   # nur Tastatur (H/S/D/P)
```

Welche Button-Nummern K1..K4 beim USB-Encoder haben, kannst du in einer
halben Minute selbst herausfinden:

```bash
python -m scripts.find_buttons
```

Ein kleines Fenster öffnet sich; K1..K4 der Reihe nach drücken → die
angezeigten Nummern in `blackjack/config.py` unter `K_JOY_BUTTONS`
eintragen. Analog für den GPIO-Modus mit `scripts/find_pins.py`.

Welche Aktion an welchem physischen Anschluss hängt, legt `K_ACTIONS`
fest. Tauschen (z. B. Stand auf K1 statt K2) geht dort in einer Zeile,
ohne die Kabel zu berühren.

| Aktion   | Anschluss (Default) | Tastatur |
|----------|---------------------|----------|
| Hit      | K1                  | `H`      |
| Stand    | K2                  | `S`      |
| Double   | K3                  | `D`      |
| Split    | K4                  | `P`      |

Zusätzliche Tasten:

| Aktion            | Tastatur       |
|-------------------|----------------|
| Vollbild an/aus   | `F11`          |
| Spiel beenden     | `Esc`          |

Das Spielfeld hat eine feste logische Auflösung von 1280×800 und wird
beim Zeichnen mit erhaltenem Seitenverhältnis auf das aktuelle Fenster
skaliert - im Vollbild bleibt es also mittig und korrekt proportioniert.

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

## Guthaben-Datenbank

Es gibt drei mögliche Backends für das Guthaben, auswählbar über
`--store`:

| Backend            | Wofür                                          |
|--------------------|--------------------------------------------------|
| `influx` (Default) | **InfluxDB 2.x / InfluxDB Cloud** - Produktiv    |
| `api`              | HTTP-Mock (`server/mock_api.py`) für Entwicklung |
| `local`            | In-Memory, kein Server - reines Offline-Testen  |

Ohne Argument wählt die Anwendung `influx`, wenn eine `.env`-Datei mit
gültigen Zugangsdaten existiert, sonst `api`. `--offline` ist die
Kurzform für `--store local`.

### InfluxDB einrichten (nur einmal)

1. Kopiere `.env.example` nach `.env` und trage die vier Werte ein, die
   ihr aus dem InfluxDB-Portal bekommen habt:

   ```bash
   cp .env.example .env
   # dann .env in einem Editor öffnen:
   #   INFLUX_URL       = <URL des InfluxDB-Servers>
   #   INFLUX_ORG_ID    = <Organisations-ID>
   #   INFLUX_BUCKET    = <Bucket-Name>
   #   INFLUX_BUCKET_ID = <Bucket-ID>
   #   INFLUX_TOKEN     = <API-Token mit Read+Write auf dem Bucket>
   ```

2. Die drei Test-Spieler (Alice, Bob, Charlie) einmalig in die Datenbank
   schreiben:

   ```bash
   python -m scripts.seed_players
   ```

3. Spiel wie gewohnt starten:

   ```bash
   python main.py
   ```

`.env` ist über `.gitignore` vom Commit ausgeschlossen - die Zugangsdaten
bleiben also lokal.

### Datenmodell in InfluxDB

Jede Guthaben-Änderung wird als eigener Datenpunkt geschrieben, so dass
in InfluxDB automatisch ein komplettes Buchungsjournal entsteht:

```
measurement: wallet
  tags:   rfid, name
  fields: balance
```

Der aktuelle Kontostand eines Spielers ist der Wert des letzten Punkts
mit passendem `rfid`-Tag.

### HTTP-API-Backend (Entwicklung)

Der Client erwartet folgende Endpunkte, die vom Mock-Server implementiert
sind:

| Methode | Pfad                       | Beschreibung                       |
|---------|----------------------------|------------------------------------|
| GET     | `/players/<rfid_uid>`      | Liefert `{name, balance}`          |
| POST    | `/players/<rfid_uid>/balance` | Body `{delta: int}` – verändert Guthaben |
