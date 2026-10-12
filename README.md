# Blackjack – Projektarbeit

Blackjack-Automat mit:

- Grafischer Oberfläche in **pygame** (gezeichnete Spielkarten, Vollbild-tauglich)
- Fünf **Arcade-Tastern** (Hit / Stand / Double / Split / Logout) über einen
  USB-Encoder (EG STARTS Zero Delay) sowie Tastatur-Fallback
  `H` / `S` / `D` / `P` / `L`
- **RFID-Reader hinter einem ESP32** als HTTP-Statusseite
  (Default: `http://10.0.244.81/status`)
- **InfluxDB** – beim Chip-Auflegen wird der letzte Blackjack-Endwert aus
  `SpieloAutomat` geladen bzw. beim ersten Spiel die Summe der sechs
  Stationen als Startguthaben; nach jeder Hand und beim Logout wird der
  neue Endwert gespeichert
- **Logout** per Taster K5, Taste `L` oder LOGOUT-Button auf dem
  Bildschirm (Maus/Touch)

## Verzeichnisstruktur

```
Projektarbeit/
├── main.py                      # Einstiegspunkt
├── .env                         # Zugangsdaten (lokal, nicht committet)
├── .env.example
├── requirements.txt
├── blackjack/
│   ├── cards.py                 # Card, Deck
│   ├── hand.py                  # Hand mit Blackjack-Wertung
│   ├── game.py                  # Zustandsautomat
│   ├── render.py                # Spielkarten rendern
│   ├── gui.py                   # pygame-Fenster
│   ├── buttons.py               # USB-Encoder + Tastatur-Fallback
│   ├── rfid.py                  # HTTP-RFID-Reader (ESP32)
│   ├── store.py                 # PlayerStore-Interface + LocalPlayerStore
│   ├── influx_db.py             # alle InfluxDB-Zugriffe + Zugangsdaten
│   └── config.py                # K-Belegung, Default-URL, Palette
├── scripts/
│   ├── find_buttons.py          # Zeigt USB-Button-Nummern an
│   └── punkte.py                # Zeigt die DB-Punkte eines Spielers
└── tests/
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Einrichten

`.env.example` nach `.env` kopieren und die PPMaster-Zugangsdaten
eintragen (die `.env` selbst steht in `.gitignore`):

```bash
cp .env.example .env
# dann .env öffnen und INFLUX_URL / INFLUX_ORG / INFLUX_BUCKET /
# INFLUX_TOKEN_READ / INFLUX_TOKEN_WRITE eintragen.
```

## Starten

```bash
# Normalbetrieb: ESP32-RFID + PPMaster-Bucket
python main.py

# Offline testen (Alice wird sofort angemeldet, keine DB nötig)
python main.py --offline

# Alternative RFID-URL
python main.py --rfid-url http://192.168.1.42/status

# Reader-Test mit festem Startguthaben pro unbekanntem Chip
python main.py --starting-balance 1000
```

## Ablauf

### Beim Chip-Auflegen

Der ESP32-Reader meldet unter seiner Statusseite:

```json
{"status":"logged_in","user_id":"d83751ae-...","username":"Jonathan","run_id":"0","time":4}
```

Nur wenn `status == "logged_in"` wird der Spieler eingeloggt. Die
`user_id` wird dann an `blackjack/influx_db.query_username(uid)` gegeben,
das die DB nach dem **tatsächlichen Anzeigenamen** fragt (das Field
`username` aus dem Measurement `PPMaster`). Dieser Name steht
anschließend im HUD als "Spieler: Jonathan". Als Fallback wird der
`username`-Wert aus der ESP32-Antwort verwendet.

### Datenbank (`blackjack/influx_db.py`)

Alle Buckets nutzen dasselbe Schema:

| Bucket            | Measurement | Field      | Tag (RFID) | Inhalt                      |
|-------------------|-------------|------------|------------|-----------------------------|
| HeisserDraht      | `durchlauf` | `endscore` | `userid`   | Punkte je Durchlauf         |
| Ampelsequenz      | `durchlauf` | `endscore` | `userid`   | Punkte je Durchlauf         |
| TimerStrike       | `durchlauf` | `endscore` | `userid`   | Punkte je Durchlauf         |
| Wurfgenauigkeit   | `durchlauf` | `endscore` | `userid`   | Punkte je Durchlauf         |
| Whackamole        | `durchlauf` | `endscore` | `userid`   | Punkte je Durchlauf         |
| Gedaechtnistest   | `durchlauf` | `endscore` | `userid`   | Punkte je Durchlauf         |
| **SpieloAutomat** | `durchlauf` | `endscore` | `userid`   | **Blackjack-Endwert**       |

Bucket-Namen und Schema stehen oben in `blackjack/influx_db.py`
(`STATION_BUCKETS`, `MEASUREMENT`, `FIELD`, `TAG`).

**Beim Chip-Auflegen** (`query_balance`):

1. Gibt es in `SpieloAutomat` schon einen Endwert für die `userid`?
   → Spieler startet genau dort (Blackjack-Endwert).
2. Sonst: Summe aller Durchläufe aus den sechs Stations-Buckets
   → Startguthaben. Ein noch nicht angelegter Bucket zählt als 0.
3. Gar keine Daten → `--starting-balance`.

Antwortet die Datenbank nicht, wird **kein** Ersatzwert genommen (sonst
würde der echte Endwert nach der ersten Hand überschrieben) – das Spiel
zeigt „Datenbank nicht erreichbar“ und versucht es alle 5 s erneut.

**Gespeichert** wird der Endwert (`write_endwert`) nach jeder Hand und
beim Logout als `durchlauf,userid=<id> endscore=<wert>` in
`SpieloAutomat`. Nur Blackjack schreibt dorthin.

Beim Schreiben wird **kein Zeitstempel** mitgeschickt – InfluxDB setzt
die Serverzeit. Die Uhr des Pi geht ohne Internet/NTP falsch;
Datenpunkte mit Pi-Zeit landeten z. B. am 19.09. und waren im Data
Explorer mit „Past 1h“ unsichtbar.

**Punkte eines Spielers prüfen** (auf dem Pi):

```bash
python -m scripts.punkte 7c3ed021-5099-4d46-9283-002adf814597
```

zeigt die Punkte je Station, das Startguthaben, den Blackjack-Endwert
und womit der Spieler beim nächsten Login startet.

### Logout (Taster K5, Taste `L` oder LOGOUT antippen)

Zwischen zwei Runden meldet Logout den Spieler ab:

1. Kontostand als Endwert nach `SpieloAutomat` schreiben,
2. RFID-User am ESP32 abmelden: `GET http://10.0.244.81/logout`
   (abgeleitet aus `--rfid-url`, überschreibbar mit `--logout-url`),
3. Spieler im Spiel abmelden – „Tschüss …! Endwert: …“.

Schlägt Schritt 1 oder 2 fehl, bleibt der Spieler angemeldet und kann
nochmal drücken. Mitten in einer Hand ist Logout gesperrt. Alle Buttons
der Aktionsleiste lassen sich auch per Maus/Touchscreen antippen.

## Steuerung

Das Arcade-Board (EG-STARTS-USB-Encoder) nutzt die Buchsen K1..K5. Die
Zuordnung Buchse → Aktion liegt in `blackjack/config.py` unter
`K_ACTIONS` (Default: K1=Hit, K2=Stand, K3=Double, K4=Split,
K5=Logout). Die Button-Nummern des Encoders (Default K5 = Button 4)
findest du mit:

```bash
python -m scripts.find_buttons
```

| Aktion            | Encoder   | Tastatur |
|-------------------|-----------|----------|
| Hit / Einsatz +   | K1        | `H`      |
| Stand / Deal      | K2        | `S`      |
| Double            | K3        | `D`      |
| Split             | K4        | `P`      |
| Logout            | K5        | `L`      |
| Vollbild an/aus   | –         | `F11`    |
| Spiel beenden     | –         | `Esc`    |

**Vor der Runde** ist die Hit-Taste "Einsatz +" (zyklt durch 10, 25,
50, 100, 250, 500, 1000; nach dem größten wieder beim kleinsten),
die Stand-Taste startet die Runde ("Deal"). Während des Spielzugs
gilt die normale Blackjack-Belegung.
