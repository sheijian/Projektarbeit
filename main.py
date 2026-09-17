"""Blackjack-Automat – Einstiegspunkt.

Verkabelt Spiellogik, GUI, Arcade-Taster, Player-Store und - falls verwendet -
RFID-Reader zu einer kompletten Anwendung.

Beispiele:

    # Online mit API-Server und RFID-Reader (Produktivbetrieb):
    python main.py --api http://localhost:5000

    # Offline testen ohne Server und ohne RFID:
    python main.py --offline

    # Offline mit RFID-Mock (Tasten 1/2/3):
    python main.py --offline --no-auto-login
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import pygame

from blackjack.api import APIError, BalanceAPI
from blackjack.buttons import ButtonHandler
from blackjack.config import DEFAULT_API_URL, DEFAULT_BET, DEFAULT_MIN_BET
from blackjack.game import Game, Player
from blackjack.gui import BlackjackGUI
from blackjack.rfid import RFIDReader
from blackjack.store import LocalPlayerStore, PlayerNotFound, PlayerStore, StoreError


log = logging.getLogger("blackjack")


# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Blackjack-Automat")
    p.add_argument(
        "--api", default=DEFAULT_API_URL,
        help="Basis-URL der Guthaben-API (nur ohne --offline)",
    )
    p.add_argument(
        "--offline", action="store_true",
        help="Weder API noch RFID nutzen - Spieler wird lokal verwaltet.",
    )
    p.add_argument(
        "--auto-login", metavar="NAME", default="Alice",
        help="Im Offline-Modus: sofort mit diesem Spieler anmelden "
             "(Default: Alice). Mit --no-auto-login deaktivieren.",
    )
    p.add_argument(
        "--no-auto-login", dest="auto_login", action="store_const", const=None,
        help="Offline-Modus mit RFID-Mock (Tasten 1/2/3) statt Auto-Login.",
    )
    p.add_argument("--min-bet", type=int, default=DEFAULT_MIN_BET)
    p.add_argument("--default-bet", type=int, default=DEFAULT_BET)
    p.add_argument("--no-gpio", action="store_true", help="GPIO-Taster ignorieren")
    p.add_argument("--no-rfid", action="store_true", help="MFRC522-Modul ignorieren")
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
        self.buttons = ButtonHandler(use_gpio=None if not args.no_gpio else False)

        # Im Offline-Modus mit Auto-Login brauchen wir gar keinen RFID-Reader,
        # sonst starten wir ihn (mit Hardware oder als Mock).
        self._auto_login_pending: Optional[str] = None
        if args.offline and args.auto_login is not None:
            self.rfid = None
            self._auto_login_pending = args.auto_login
        else:
            self.rfid = RFIDReader(
                use_hardware=None if not args.no_rfid else False,
            )

    # ------------------------------------------------------------------
    def _build_store(self, args: argparse.Namespace) -> PlayerStore:
        if args.offline:
            log.info("Store: LocalPlayerStore (Offline-Modus)")
            return LocalPlayerStore()
        log.info("Store: BalanceAPI (%s)", args.api)
        return BalanceAPI(args.api)

    # ------------------------------------------------------------------
    def run(self) -> int:
        # Auto-Login erst nachdem die GUI läuft, damit der Willkommensbildschirm
        # kurz sichtbar ist. Wird nach dem ersten Frame ausgelöst.
        first_frame = True

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    self.buttons.handle_pygame_event(event)
                    if self.rfid is not None:
                        self.rfid.handle_pygame_event(event)

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
                log.info("RFID entfernt")
                self.game.logout()
            else:
                self._login_by_uid(uid)

    def _login_by_uid(self, uid: str) -> None:
        log.info("RFID gelesen: %s", uid)
        try:
            player = self.store.get_player(uid)
        except PlayerNotFound:
            self.game.logout()
            self.game.message = f"Unbekannter Chip: {uid}"
            return
        except (APIError, StoreError) as e:
            log.warning("Store-Fehler: %s", e)
            self.game.logout()
            self.game.message = "Datenbank nicht erreichbar"
            return
        self.game.login(player, default_bet=self.args.default_bet)

    def _auto_login(self, name: str) -> None:
        """Offline-Modus: Spieler ohne RFID sofort anmelden."""
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
            # Der Store ist die Quelle der Wahrheit.
            player.balance = new_balance

    # ------------------------------------------------------------------
    def _shutdown(self) -> None:
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
