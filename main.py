"""Blackjack-Automat – Einstiegspunkt.

Verkabelt Spiellogik, GUI, Arcade-Taster, RFID-Reader und HTTP-API zu einer
kompletten Anwendung.

Beispiel:

    python main.py --api http://localhost:5000
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import pygame

from blackjack.api import APIError, BalanceAPI, PlayerNotFound
from blackjack.buttons import ButtonHandler
from blackjack.config import DEFAULT_API_URL, DEFAULT_BET, DEFAULT_MIN_BET
from blackjack.game import Game, Player
from blackjack.gui import BlackjackGUI
from blackjack.rfid import RFIDReader


log = logging.getLogger("blackjack")


# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Blackjack-Automat")
    p.add_argument("--api", default=DEFAULT_API_URL, help="Basis-URL der Guthaben-API")
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
        self.api = BalanceAPI(args.api)

        self.game = Game(
            min_bet=args.min_bet,
            on_balance_change=self._on_balance_change,
        )
        self.gui = BlackjackGUI(self.game)
        self.buttons = ButtonHandler(use_gpio=None if not args.no_gpio else False)
        self.rfid = RFIDReader(use_hardware=None if not args.no_rfid else False)

    # ------------------------------------------------------------------
    def run(self) -> int:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    self.buttons.handle_pygame_event(event)
                    self.rfid.handle_pygame_event(event)

            self._process_rfid()
            self._process_buttons()
            self.gui.tick()

        self._shutdown()
        return 0

    # ------------------------------------------------------------------
    def _process_rfid(self) -> None:
        while True:
            has_event, uid = self.rfid.poll()
            if not has_event:
                return
            if uid is None:
                log.info("RFID entfernt")
                self.game.logout()
            else:
                self._login(uid)

    def _login(self, uid: str) -> None:
        log.info("RFID gelesen: %s", uid)
        try:
            player = self.api.get_player(uid)
        except PlayerNotFound:
            self.game.logout()
            self.game.message = f"Unbekannter Chip: {uid}"
            return
        except APIError as e:
            log.warning("API-Fehler: %s", e)
            self.game.logout()
            self.game.message = "API nicht erreichbar"
            return
        self.game.login(player, default_bet=self.args.default_bet)

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
        """Callback aus dem Game – Delta an die API zurückspiegeln."""
        new_balance = self.api.apply_delta(player.rfid, delta)
        if new_balance is not None:
            # Server ist die Quelle der Wahrheit.
            player.balance = new_balance

    # ------------------------------------------------------------------
    def _shutdown(self) -> None:
        try:
            self.buttons.close()
        except Exception:  # pragma: no cover
            pass
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
