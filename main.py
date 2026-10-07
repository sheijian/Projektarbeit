"""Blackjack-Automat – Einstiegspunkt.

Verkabelt Spiellogik, GUI, Arcade-Taster, Guthaben-Store, HTTP-RFID-
Reader (ESP32) und die InfluxDB (für den Username-Lookup) zu einer
kompletten Anwendung.

Beispiele:

    # Standard: ESP32-RFID + Username aus InfluxDB
    python main.py

    # Spielen ohne RFID (Alice wird automatisch angemeldet)
    python main.py --offline

    # Alternative RFID-URL
    python main.py --rfid-url http://192.168.1.42/status

    # Live-Reader-Test mit beliebigem Startguthaben
    python main.py --starting-balance 500
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import pygame

from blackjack import influx_db
from blackjack.buttons import ButtonHandler
from blackjack.config import DEFAULT_BET, DEFAULT_MIN_BET, DEFAULT_RFID_URL
from blackjack.game import Game, Player
from blackjack.gui import BlackjackGUI
from blackjack.rfid import HTTPRFIDReader
from blackjack.store import LocalPlayerStore


log = logging.getLogger("blackjack")


# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Blackjack-Automat")
    p.add_argument(
        "--rfid-url", metavar="URL", default=DEFAULT_RFID_URL,
        help=f"HTTP-URL des RFID-Readers (Default: {DEFAULT_RFID_URL}).",
    )
    p.add_argument(
        "--offline", action="store_true",
        help="Kein RFID - Alice wird automatisch angemeldet.",
    )
    p.add_argument(
        "--auto-login", metavar="NAME", default="Alice",
        help="Im Offline-Modus: sofort mit diesem Spieler anmelden "
             "(Default: Alice). Mit --no-auto-login deaktivieren.",
    )
    p.add_argument(
        "--no-auto-login", dest="auto_login", action="store_const", const=None,
        help="Offline-Modus ohne Auto-Login - stattdessen auf RFID warten.",
    )
    p.add_argument(
        "--starting-balance", type=int, default=500,
        help="Startguthaben für unbekannte RFID-UIDs (Default 500). "
             "Solange die Punkte-Abfrage noch nicht an InfluxDB angebunden "
             "ist, bekommt jeder Spieler diesen Betrag.",
    )
    p.add_argument("--min-bet", type=int, default=DEFAULT_MIN_BET)
    p.add_argument("--default-bet", type=int, default=DEFAULT_BET)
    p.add_argument(
        "--input", choices=("auto", "usb", "keyboard"), default="auto",
        help="Eingabequelle für die Arcade-Taster "
             "(Default: auto - USB, sonst Tastatur).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

        # Guthaben wird aktuell lokal verwaltet. Unbekannte UIDs werden
        # mit --starting-balance direkt angelegt - die DB-Punkte-Abfrage
        # steht noch aus (siehe blackjack/influx_db.query_points).
        self.store = LocalPlayerStore(
            auto_register=True,
            auto_balance=args.starting_balance,
        )
        log.info(
            "Store: LocalPlayerStore (auto_register=True, auto_balance=%d)",
            args.starting_balance,
        )

        # Zeige klar an, ob die InfluxDB-Verbindung bereit ist.
        from blackjack.influx_db import _effective_config
        cfg = _effective_config()
        if cfg.is_configured:
            log.info(
                "InfluxDB: %s (org=%s, bucket=%s) - bereit",
                cfg.url, cfg.org, cfg.bucket,
            )
        else:
            log.warning(
                "InfluxDB nicht konfiguriert - Username-Lookup inaktiv. "
                "Trage den Lese-Token in blackjack/influx_db.py (ganz oben, "
                "INFLUX_TOKEN_READ) oder in .env ein."
            )

        self.game = Game(
            min_bet=args.min_bet,
            on_balance_change=self._on_balance_change,
            on_round_end=self._on_round_end,
        )
        self.gui = BlackjackGUI(self.game)
        self.buttons = ButtonHandler(mode=args.input)

        self._auto_login_pending: Optional[str] = None
        if args.offline and args.auto_login is not None:
            self.rfid: Optional[HTTPRFIDReader] = None
            self._auto_login_pending = args.auto_login
        else:
            self.rfid = HTTPRFIDReader(args.rfid_url)

    # ------------------------------------------------------------------
    def run(self) -> int:
        first_frame = True
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    self.gui.handle_pygame_event(event)
                    self.buttons.handle_pygame_event(event)

            if self.rfid is not None:
                self._process_rfid()
            self._process_buttons()
            self.gui.tick()

            if first_frame:
                first_frame = False
                if self._auto_login_pending is not None:
                    self._auto_login(self._auto_login_pending)
                    self._auto_login_pending = None

        self._shutdown()
        return 0

    # ------------------------------------------------------------------
    # RFID
    # ------------------------------------------------------------------
    def _process_rfid(self) -> None:
        assert self.rfid is not None
        while True:
            has_event, uid = self.rfid.poll()
            if not has_event:
                return
            if uid is None:
                log.info("RFID abgemeldet")
                # Der aktuelle Score steht bereits in SpieloAutomat
                # (nach jeder Runde über _on_round_end geschrieben).
                self.game.logout()
            else:
                self._login_by_uid(uid)

    def _login_by_uid(self, uid: str) -> None:
        log.info("RFID gelesen: %s", uid)

        # 1) Punktestand aus dem SpieloAutomat-Bucket.
        points = influx_db.query_points(uid)
        if points is None:
            log.warning(
                "SpieloAutomat kennt user_id=%s nicht - nehme Fallback %d",
                uid, self.args.starting_balance,
            )
        else:
            log.info("SpieloAutomat: user_id=%s -> Score %d", uid, points)
            self.store.set_balance(uid, points)
        player = self.store.get_player(uid)

        # 2) Anzeigename aus dem PPMaster-Bucket.
        name = influx_db.query_username(uid)
        if name:
            log.info("PPMaster: user_id=%s -> username '%s'", uid, name)
        else:
            log.warning("PPMaster kennt user_id=%s nicht", uid)
            if isinstance(self.rfid, HTTPRFIDReader):
                name = self.rfid.get_name_hint(uid)
                if name:
                    log.info("Fallback: ESP32 lieferte username '%s'", name)
        if name:
            player.name = name

        log.info(
            "Login abgeschlossen: name=%s, balance=%d, uid=%s",
            player.name, player.balance, player.rfid,
        )
        self.game.login(player, default_bet=self.args.default_bet)

    def _auto_login(self, name: str) -> None:
        player = self.store.find_by_name(name)
        if player is None:
            available = ", ".join(p.name for p in self.store.all_players())
            self.game.message = (
                f"Spieler '{name}' unbekannt. Verfügbar: {available}"
            )
            log.warning("Auto-Login: Spieler '%s' unbekannt", name)
            return
        log.info("Auto-Login: %s (Guthaben %d)", player.name, player.balance)
        self.game.login(player, default_bet=self.args.default_bet)

    def _on_round_end(self, player: Player) -> None:
        """Wird nach jeder abgeschlossenen Runde aus Game aufgerufen.

        Schreibt den aktuellen Kontostand (und den Anzeigenamen) nach
        SpieloAutomat, damit beides sofort beim nächsten Chip-Scan
        bzw. in jeder Abfrage verfügbar ist.
        """
        # Username nur mitgeben, wenn er ein echter Name ist - der
        # Fallback-Name == UUID (wenn kein Anzeigename gefunden wurde)
        # soll NICHT in das username-Field.
        name = player.name if player.name and player.name != player.rfid else None
        log.info(
            "Runde beendet - schreibe Score %d%s für user_id=%s nach SpieloAutomat",
            player.balance,
            f" + username='{name}'" if name else "",
            player.rfid,
        )
        try:
            ok = influx_db.write_endscore(
                player.rfid, player.balance, username=name,
            )
            if not ok:
                log.warning(
                    "write_endscore hat KEINEN Schreibvorgang durchgeführt - "
                    "Token ok? Schreibrechte auf SpieloAutomat? Siehe DEBUG-Log."
                )
        except Exception as e:
            log.warning("write_endscore nach Runde fehlgeschlagen: %s", e)

    # ------------------------------------------------------------------
    # Taster
    # ------------------------------------------------------------------
    def _process_buttons(self) -> None:
        while True:
            action = self.buttons.poll()
            if action is None:
                return
            self._dispatch(action)

    def _dispatch(self, action: str) -> None:
        if self.game.player is None:
            self.game.message = "Bitte zuerst RFID-Chip auflegen"
            return
        {
            "hit":    self.game.hit,
            "stand":  self.game.stand,
            "double": self.game.double,
            "split":  self.game.split,
        }[action]()

    # ------------------------------------------------------------------
    def _on_balance_change(self, player: Player, delta: int) -> None:
        new_balance = self.store.apply_delta(player.rfid, delta)
        if new_balance is not None:
            player.balance = new_balance

    # ------------------------------------------------------------------
    def _shutdown(self) -> None:
        # Der letzte Scorestand steht bereits nach der letzten Runde in
        # SpieloAutomat - hier ist nichts weiter zu persistieren.
        try:
            self.buttons.close()
        except Exception:  # pragma: no cover
            pass
        if self.rfid is not None:
            try:
                self.rfid.close()
            except Exception:  # pragma: no cover
                pass
        self.gui.close()


# ---------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = App(args)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
