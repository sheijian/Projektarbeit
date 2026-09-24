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

### RFID über einen HTTP-Test-Server

Wenn der RFID-Leser nicht direkt am Pi hängt, sondern über eine kleine
Test-Webseite im Netz erreichbar ist (z. B. `http://10.0.244.31/status`),
gib die URL beim Start mit `--rfid-url` an:

```bash
python main.py --rfid-url http://10.0.244.31/status
```

Das Spiel pollt die Adresse alle 0,5 Sekunden und akzeptiert dabei alle
üblichen Antwortformate:

* JSON mit einem der Schlüssel `uid`, `id`, `card_id`, `rfid`, `tag`
  oder `value` (z. B. `{"uid": "0416AC12"}`)
* JSON mit `{"status": "no_card"}` → gilt als "kein Chip aufgelegt"
* reiner Text, der eine Hex-UID enthält
  (`0416AC12`, `04-16-AC-12`, `AA:BB:CC:DD` …)
* HTML mit einer irgendwo enthaltenen Hex-UID

## Guthaben-Datenbank

Es gibt drei Backends, auswählbar über `--store`:

| Backend               | Wofür                                             |
|-----------------------|----------------------------------------------------|
| `ppmaster` (Default)  | **Gemeinsamer InfluxDB-Bucket** aller Stationen    |
| `api`                 | HTTP-Mock (`server/mock_api.py`) für Entwicklung  |
| `local`               | In-Memory, kein Server - reines Offline-Testen     |

Ohne Argument wählt die Anwendung `ppmaster`, wenn eine `.env`-Datei
mit gültigen Zugangsdaten existiert, sonst `api`. `--offline` ist die
Kurzform für `--store local`.

### PPMaster-Bucket

Beim Chip-Auflegen fragt die Anwendung die Summe aller `endscore`-
Datenpunkte des Spielers **aus der letzten Stunde** ab - das ergibt das
Startguthaben, das er von den anderen Stationen mitbringt. Am Ende der
Session (Chip abheben oder Programm beenden) werden zwei neue
Datenpunkte geschrieben:

```
endscore,rfidTag=<name> score=<netto-delta>     <timestamp_ms>
winrate,rfidTag=<name>  winrate=<prozent>       <timestamp_ms>
```

Wichtig: gespeichert wird der **Netto-Delta** dieses Spieldurchlaufs
(aktuelles Guthaben minus Startguthaben), nicht der neue Kontostand
selbst - damit die Summe über alle Datenpunkte weiterhin das korrekte
Guthaben ergibt und keine Punkte doppelt gezählt werden.

### Einrichtung

`.env.example` liegt bei; die tatsächliche `.env` wird von `.gitignore`
ausgeschlossen. Zugangsdaten (URL/Org/Bucket/Tokens) trägt jeder lokal
in `.env` ein. Danach startet man einfach:

```bash
python main.py --rfid-url http://10.0.244.31/status
```

Der Store meldet sich mit `PPMasterStore verbunden mit ...` im Log,
sobald `.env` sinnvoll gefüllt ist.

### HTTP-API-Backend (Entwicklung)

Der Client erwartet folgende Endpunkte, die vom Mock-Server implementiert
sind:

| Methode | Pfad                       | Beschreibung                       |
|---------|----------------------------|------------------------------------|
| GET     | `/players/<rfid_uid>`      | Liefert `{name, balance}`          |
| POST    | `/players/<rfid_uid>/balance` | Body `{delta: int}` – verändert Guthaben |
