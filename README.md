# Blackjack – Projektarbeit

Blackjack-Automat mit:

- Grafischer Oberfläche in **pygame** (gezeichnete Spielkarten, Vollbild-tauglich)
- Fünf **Arcade-Tastern** (Hit / Stand / Double / Split / Logout) über einen
  USB-Encoder (EG STARTS Zero Delay) sowie Tastatur-Fallback
  `H` / `S` / `D` / `P` / `L`
- **RFID-Reader hinter einem ESP32** als HTTP-Statusseite
  (Default: `http://10.0.244.81/status`)
- **InfluxDB-Bucket** (`SpieloAutomat`) – beim Chip-Auflegen wird der
  letzte Blackjack-Endwert geladen bzw. beim ersten Spiel die Summe der
  sechs anderen Stationen als Startguthaben; nach jeder Hand wird der
  neue Endwert gespeichert

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

### Datenbank-Zugriffe (`blackjack/influx_db.py`)

Alle InfluxDB-Zugriffe stehen in einer einzigen Datei:

| Funktion                               | Zweck                                                              |
|----------------------------------------|--------------------------------------------------------------------|
| `query_username(user_id)`              | Anzeigename aus Bucket **PPMaster** (last)                         |
| `query_balance(user_id)`               | Kontostand für den Login aus **SpieloAutomat** (siehe unten)       |
| `write_endwert(user_id, wert, name)`   | Nach jeder Hand: Blackjack-Endwert nach **SpieloAutomat**          |

Im Bucket `SpieloAutomat` liegen pro `user_id` zwei getrennte Werte,
die sich gegenseitig nie überschreiben:

| Measurement / Field  | Bedeutung                             | Wer schreibt?                   |
|----------------------|---------------------------------------|---------------------------------|
| `endscore` / `score` | **Startguthaben** = Summe der sechs Stationen | nur der Aggregator (alle 5 s) |
| `blackjack` / `endwert` | **Endwert** nach der letzten Blackjack-Hand | nur Blackjack (nach jeder Hand + beim Logout) |

Beim Chip-Auflegen gilt: **Endwert, falls vorhanden – sonst
Startguthaben.** Wer schon Blackjack gespielt hat, landet also immer bei
seinem Blackjack-Endwert, egal was der Aggregator inzwischen schreibt.
Beides kommt aus einer einzigen Abfrage:

```flux
from(bucket: "SpieloAutomat")
  |> range(start: 0)
  |> filter(fn: (r) => r.user_id == "<uuid>")
  |> filter(fn: (r) =>
       (r._measurement == "blackjack" and r._field == "endwert") or
       (r._measurement == "endscore" and r._field == "score"))
  |> last()
```

Beim Schreiben schicken Blackjack und Aggregator **keinen Zeitstempel**
mit – InfluxDB setzt die Serverzeit. Die Uhr des Pi geht ohne
Internet/NTP falsch; Datenpunkte mit Pi-Zeit landeten z. B. am 19.09.
und waren im Data Explorer mit „Past 1h“ unsichtbar.

Endwerte prüfen (Data Explorer → Script Editor):

```flux
from(bucket: "SpieloAutomat")
  |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "blackjack" and r._field == "endwert")
  |> last()
```

### Logout-Taster (K5 / Taste `L`)

Zwischen zwei Runden meldet der Logout-Taster den Spieler ab:

1. Kontostand als Endwert nach `SpieloAutomat` (`blackjack` / `endwert`)
   schreiben,
2. RFID-User am ESP32 abmelden: `GET http://10.0.244.81/logout`
   (abgeleitet aus `--rfid-url`, überschreibbar mit `--logout-url`),
3. Spieler im Spiel abmelden – „Tschüss …! Endwert: …“.

Schlägt Schritt 1 oder 2 fehl, bleibt der Spieler angemeldet und kann
nochmal drücken. Mitten in einer Hand ist Logout gesperrt. Zusätzlich
wird der Endwert nach jeder Hand gespeichert – falls jemand geht, ohne
Logout zu drücken.

## Score-Aggregator (Hintergrund-Dienst)

Die sechs anderen Spielstationen speichern ihre Endscores jeweils in
einem eigenen Bucket mit unterschiedlichem Schema:

| Bucket              | Measurement           | Field          | Tag       |
|---------------------|-----------------------|----------------|-----------|
| HeisserDraht        | Endscore              | Endscore       | userID    |
| Ampelsequenz        | endscore              | score          | rfidTag   |
| TimerStrike         | endscore              | score          | user_id   |
| Wurfgenauigkeit     | spieler_ergebnisse    | gesamtpunkte   | user_id   |
| Whackamole          | endscore              | score          | rfidTag   |
| Gedaechtnistest     | endscore              | endscore       | user_id   |

Das Skript `scripts/score_aggregator.py` läuft dauerhaft auf dem Pi,
pollt alle 5 Sekunden diese Buckets, summiert pro `user_id` und
schreibt die Summe als Startguthaben nach `SpieloAutomat`
(measurement `endscore`, field `score`, tag `user_id`) – allerdings nur
für User, deren Summe sich seit dem letzten Write geändert hat. Den
Blackjack-Endwert (`blackjack` / `endwert`) fasst er nie an.

### Manuell starten (zum Testen)

```bash
python -m scripts.score_aggregator --verbose     # Dauerlauf
python -m scripts.score_aggregator --once        # ein Durchlauf
```

### Als Dienst dauerhaft laufen lassen

```bash
sudo cp scripts/blackjack-aggregator.service /etc/systemd/system/
# in der Service-Datei User= und WorkingDirectory= an den eigenen
# Pfad anpassen (admin + ~/Documents/Projektarbeit-... als Default)
sudo systemctl daemon-reload
sudo systemctl enable --now blackjack-aggregator.service
journalctl -u blackjack-aggregator -f            # Logs mitlesen
```

Der Token muss Lese-Zugriff auf alle sechs Quell-Buckets und Schreib-
Zugriff auf `SpieloAutomat` haben. Trage ihn – wie beim Blackjack-
Programm selbst – ganz oben in `blackjack/influx_db.py` ein.

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
