# Blackjack – Projektarbeit

Blackjack-Automat mit:

- Grafischer Oberfläche in **pygame** (gezeichnete Spielkarten, Vollbild-tauglich)
- Vier **Arcade-Tastern** (Hit / Stand / Double / Split) über einen USB-Encoder
  (EG STARTS Zero Delay) sowie Tastatur-Fallback `H` / `S` / `D` / `P`
- **RFID-Reader hinter einem ESP32** als HTTP-Statusseite
  (Default: `http://10.0.244.81/status`)
- **InfluxDB-Bucket** (`PPMaster`) als gemeinsame Punktedatenbank aller
  Spielstationen – beim Chip-Auflegen wird die Summe der Endpunkte aus
  der letzten Stunde als Startguthaben geladen, nach dem Durchlauf
  werden Netto-Delta und Winrate zurückgeschrieben

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
│   ├── ppmaster_store.py        # InfluxDB-Store für den PPMaster-Bucket
│   ├── db_config.py             # Lädt .env-Zugangsdaten
│   └── config.py                # K-Belegung, Default-URL, Palette
├── scripts/
│   └── find_buttons.py          # Zeigt USB-Button-Nummern an
└── tests/                       # 64 Tests, alle grün
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

### Datenbank (PPMaster-Bucket in InfluxDB)

Die aktuelle Username-Query:

```flux
from(bucket: "PPMaster")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "PPMaster")
  |> filter(fn: (r) => r._field == "username")
  |> filter(fn: (r) => r.user_id == "<uuid>")
  |> last()
```

Alle weiteren DB-Operationen (Punkte-Abfrage, Endscore + Winrate
schreiben) sind in `blackjack/influx_db.py` als Platzhalter angelegt
(`query_points`, `write_session_end`) - dort kommen die Queries hin,
sobald das Datenmodell dafür feststeht.

## Steuerung

Das Arcade-Board (EG-STARTS-USB-Encoder) hat vier Buchsen K1..K4. Die
Zuordnung Buchse → Aktion liegt in `blackjack/config.py` unter
`K_ACTIONS` (Default: K1=Hit, K2=Stand, K3=Double, K4=Split). Die
Button-Nummern des Encoders findest du mit:

```bash
python -m scripts.find_buttons
```

| Aktion            | Encoder   | Tastatur |
|-------------------|-----------|----------|
| Hit / Einsatz +   | K1        | `H`      |
| Stand / Deal      | K2        | `S`      |
| Double            | K3        | `D`      |
| Split             | K4        | `P`      |
| Vollbild an/aus   | –         | `F11`    |
| Spiel beenden     | –         | `Esc`    |

**Vor der Runde** ist die Hit-Taste "Einsatz +" (zyklt durch 10, 25,
50, 100, 250, 500, 1000; nach dem größten wieder beim kleinsten),
die Stand-Taste startet die Runde ("Deal"). Während des Spielzugs
gilt die normale Blackjack-Belegung.
