"""Blackjack-Automat – Einstiegspunkt.

Verkabelt Spiellogik, GUI, Arcade-Taster, Guthaben-Store und den
HTTP-RFID-Reader des ESP32 zu einer kompletten Anwendung.

Beispiele:

    # Standard: ESP32-RFID + PPMaster-Bucket (wenn .env konfiguriert)
    python main.py

    # Spielen ohne RFID/DB (Alice wird automatisch angemeldet)
    python main.py --offline

    # Alternative RFID-URL
    python main.py --rfid-url http://192.168.1.42/status
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import pygame

from blackjack.buttons import ButtonHandler
from blackjack.config import DEFAULT_BET, DEFAULT_MIN_BET, DEFAULT_RFID_URL
from blackjack.game import Game, Player
from blackjack.gui import BlackjackGUI
from blackjack.rfid import HTTPRFIDReader
from blackjack.store import LocalPlayerStore, PlayerNotFound, PlayerStore, StoreError


log = logging.getLogger("blackjack")


# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Blackjack-Automat")
    p.add_argument(
        "--store", choices=("auto", "ppmaster", "local"), default="auto",
        help="Guthaben-Backend. 'auto' nimmt ppmaster (wenn .env konfiguriert), "
             "sonst local. 'local' = In-Memory (Offline-Modus).",
    )
    p.add_argument(
        "--rfid-url", metavar="URL", default=DEFAULT_RFID_URL,
        help=f"HTTP-URL des RFID-Readers (Default: {DEFAULT_RFID_URL}).",
    )
    p.add_argument(
        "--offline", action="store_true",
        help="Kurzform für --store local --no-rfid (Alice wird auto-angemeldet).",
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
        "--auto-register", action="store_true",
        help="Nur mit --store local: unbekannte RFID-UIDs werden als "
             "frischer Gast mit Startguthaben angelegt (praktisch für "
             "Reader-Tests ohne DB).",
    )
    p.add_argument(
        "--auto-register-balance", type=int, default=500,
        help="Startguthaben für auto-registrierte Gäste (Default 500).",
    )
    p.add_argument(
        "--starting-balance", type=int, default=0,
        help="PPMaster: Startguthaben wenn der Spieler noch keine "
             "endscore-Punkte in der letzten Stunde hat (Default 0).",
    )
    p.add_argument(
        "--lookup-by", choices=("name", "uid"), default="name",
        help="PPMaster: Mit welchem Wert wird in der DB nach dem Spieler "
             "gesucht? 'name' = Anzeigename (Default, passt zum Beispiel "
             "'rfidTag=Alice'), 'uid' = user_id vom RFID-Chip.",
    )
    p.add_argument("--min-bet", type=int, default=DEFAULT_MIN_BET)
    p.add_argument("--default-bet", type=int, default=DEFAULT_BET)
    p.add_argument(
        "--input", choices=("auto", "usb", "keyboard"), default="auto",
        help="Eingabequelle für die Arcade-Taster (Default: auto - USB, sonst Tastatur).",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.store: PlayerStore = self._build_store(args)

        self.game = Game(
            min_bet=args.min_bet,
            on_balance_change=self._on_balance_change,
        )
        self.gui = BlackjackGUI(self.game)
        self.buttons = ButtonHandler(mode=args.input)

        # Im Offline-Modus mit Auto-Login brauchen wir keinen RFID-Reader.
        self._auto_login_pending: Optional[str] = None
        if args.offline and args.auto_login is not None:
            self.rfid: Optional[HTTPRFIDReader] = None
            self._auto_login_pending = args.auto_login
        else:
            self.rfid = HTTPRFIDReader(args.rfid_url)

    # ------------------------------------------------------------------
    def _build_store(self, args: argparse.Namespace) -> PlayerStore:
        store_kind = "local" if args.offline else args.store

        if store_kind == "auto":
            store_kind = self._auto_store_kind()

        if store_kind == "local":
            log.info(
                "Store: LocalPlayerStore (Offline-Modus, auto_register=%s)",
                args.auto_register,
            )
            return LocalPlayerStore(
                auto_register=args.auto_register,
                auto_balance=args.auto_register_balance,
            )

        from blackjack.ppmaster_store import PPMasterStore
        log.info("Store: PPMasterStore")
        return PPMasterStore(starting_balance=args.starting_balance)

    def _auto_store_kind(self) -> str:
        """Nimmt PPMaster wenn .env konfiguriert ist, sonst local."""
        try:
            from blackjack.db_config import INFLUX
            if INFLUX.is_configured:
                return "ppmaster"
        except Exception:
            pass
        return "local"

    # ------------------------------------------------------------------
    def run(self) -> int:
        # Auto-Login erst nach dem ersten Frame, damit die GUI schon steht.
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
                self._finalize_current_session()
                self.game.logout()
            else:
                self._login_by_uid(uid)

    def _login_by_uid(self, uid: str) -> None:
        log.info("RFID gelesen: %s", uid)

        hint = None
        if isinstance(self.rfid, HTTPRFIDReader):
            hint = self.rfid.get_name_hint(uid)

        # Mit welchem Wert fragen wir die DB ab?
        #   --lookup-by name (Default): den Anzeigenamen, falls bekannt;
        #     Fallback uid, falls der Reader keinen Namen mitliefert.
        #   --lookup-by uid: immer die UUID vom RFID-Chip.
        if self.args.lookup_by == "uid":
            lookup_key = uid
        else:
            lookup_key = hint if hint else uid

        try:
            player = self.store.get_player(lookup_key)
        except PlayerNotFound:
            self.game.logout()
            self.game.message = f"Unbekannter Chip: {lookup_key}"
            return
        except StoreError as e:
            log.warning("Store-Fehler: %s", e)
            self.game.logout()
            self.game.message = "Datenbank nicht erreichbar"
            return

        # Anzeigename im HUD ist der lesbare Name, falls vorhanden.
        if hint:
            player.name = hint

        self.game.login(player, default_bet=self.args.default_bet)

    def _auto_login(self, name: str) -> None:
        assert isinstance(self.store, LocalPlayerStore)
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

    def _finalize_current_session(self) -> None:
        """Schreibt Endscore + Winrate in den Bucket (nur bei PPMasterStore)."""
        if self.game.player is None:
            return
        if not hasattr(self.store, "finalize_session"):
            return
        if self.game.session_plays <= 0:
            return
        try:
            self.store.finalize_session(   # type: ignore[attr-defined]
                self.game.player.rfid,
                self.game.player.balance,
                self.game.session_wins,
                self.game.session_plays,
            )
        except Exception as e:
            log.warning("finalize_session fehlgeschlagen: %s", e)

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
        """Callback aus dem Game – Delta an den Store zurückspiegeln."""
        new_balance = self.store.apply_delta(player.rfid, delta)
        if new_balance is not None:
            player.balance = new_balance

    # ------------------------------------------------------------------
    def _shutdown(self) -> None:
        self._finalize_current_session()

        try:
            self.buttons.close()
        except Exception:  # pragma: no cover
            pass
        if self.rfid is not None:
            try:
                self.rfid.close()
            except Exception:  # pragma: no cover
                pass
        close_fn = getattr(self.store, "close", None)
        if callable(close_fn):
            try:
                close_fn()
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
