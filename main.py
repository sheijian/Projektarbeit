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

SpieloAutomat (Tag userid, measurement/field):
    endscore_stationen/endscore  Kontostand - nach jeder Hand, daraus
                                 lädt der Login
    durchlauf/live               Guthaben nach jeder Hand (Dashboard)
    durchlauf/endscore           Glücksfaktor (gewonnene / gespielte Hände
                                 in %) - beim Logout bzw. Ende des Durchlaufs
                                 (Chip-Wechsel, RFID-Abmeldung, Programmende)

Logout (Taster K5, Taste L oder LOGOUT auf dem Bildschirm antippen):
speichert Kontostand + Glückswert und meldet den RFID-User am ESP32 ab.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
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

# Wartezeit, bevor ein Login nach DB-Fehler automatisch wiederholt wird.
LOGIN_RETRY_SECONDS = 5.0


# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Blackjack-Automat")
    p.add_argument(
        "--rfid-url", metavar="URL", default=DEFAULT_RFID_URL,
        help=f"HTTP-URL des RFID-Readers (Default: {DEFAULT_RFID_URL}).",
    )
    p.add_argument(
        "--logout-url", metavar="URL", default=None,
        help="Logout-Endpunkt des ESP32 (Default: aus --rfid-url abgeleitet, "
             "also .../logout).",
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

        # Lokaler Zwischenspeicher fürs Guthaben. Beim Login wird er mit
        # influx_db.query_balance befüllt; liefert die DB nichts, bekommt
        # die UID --starting-balance.
        self.store = LocalPlayerStore(
            auto_register=True,
            auto_balance=args.starting_balance,
        )
        log.info(
            "Store: LocalPlayerStore (auto_register=True, auto_balance=%d)",
            args.starting_balance,
        )

        # Zeige klar an, ob die InfluxDB-Verbindung bereit ist.
        if influx_db.INFLUX_TOKEN_READ:
            log.info(
                "InfluxDB: %s (org=%s) - Startguthaben = Summe aus %s; "
                "%s: Kontostand %s/%s, Dashboard %s/%s + %s/%s; "
                "Username aus %s",
                influx_db.INFLUX_URL, influx_db.INFLUX_ORG,
                ", ".join(influx_db.STATION_BUCKETS), influx_db.SCORE_BUCKET,
                influx_db.KONTO_MEASUREMENT, influx_db.KONTO_FIELD,
                influx_db.MEASUREMENT, influx_db.FIELD_LIVE,
                influx_db.MEASUREMENT, influx_db.FIELD_GLUECK,
                influx_db.USERNAME_BUCKET,
            )
        else:
            log.warning(
                "InfluxDB nicht konfiguriert - trage INFLUX_TOKEN_READ "
                "und INFLUX_TOKEN_WRITE ganz oben in "
                "blackjack/influx_db.py ein."
            )

        self.game = Game(
            min_bet=args.min_bet,
            on_balance_change=self._on_balance_change,
            on_round_end=self._on_round_end,
        )
        self.gui = BlackjackGUI(self.game)
        self.buttons = ButtonHandler(mode=args.input)

        # (uid, Zeitpunkt) für einen Login, der wegen DB-Fehler wiederholt wird.
        self._login_retry: Optional[tuple[str, float]] = None
        # session_plays beim letzten Glückswert-Write - verhindert, dass ein
        # Durchlauf doppelt gespeichert wird (z. B. Logout zweimal gedrückt).
        self._glueck_saved_plays = 0
        # Run-Nummer des angemeldeten Spielers (vom ESP32), None = unbekannt.
        self._runid: Optional[str] = None

        self._auto_login_pending: Optional[str] = None
        if args.offline and args.auto_login is not None:
            self.rfid: Optional[HTTPRFIDReader] = None
            self._auto_login_pending = args.auto_login
        else:
            self.rfid = HTTPRFIDReader(args.rfid_url, logout_url=args.logout_url)

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
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Bildschirm-Buttons per Maus/Touch (z. B. LOGOUT).
                    action = self.gui.action_at(event.pos)
                    if action is not None:
                        self._dispatch(action)
                else:
                    self.gui.handle_pygame_event(event)
                    self.buttons.handle_pygame_event(event)

            if self.rfid is not None:
                self._process_rfid()
            self._retry_login_if_due()
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
                self._login_retry = None
                self._finish_session()
                self.game.logout()
            else:
                self._login_by_uid(uid)

    def _login_by_uid(self, uid: str) -> None:
        runid = (self.rfid.get_runid(uid)
                 if isinstance(self.rfid, HTTPRFIDReader) else None)
        log.info("RFID gelesen: %s (runid %s)", uid, runid)
        self._login_retry = None
        # Anderer Chip oder neuer Run, während noch jemand spielt ->
        # dessen Durchlauf beenden.
        if self.game.player is not None and (
            self.game.player.rfid != uid or self._runid != runid
        ):
            self._finish_session()
        self._runid = runid

        # 1) Kontostand: letzter Wert aus SpieloAutomat endscore_stationen/
        #    endscore, falls der Spieler in diesem Run schon gespielt hat -
        #    sonst Summe der sechs Stationen in diesem Run.
        try:
            score = influx_db.query_balance(uid, runid)
        except influx_db.DBError as e:
            # Kein Ersatzwert - sonst würde der echte Kontostand nach der
            # ersten Hand überschrieben. Später nochmal versuchen.
            log.warning("Login %s: Datenbank-Fehler (%s) - neuer Versuch "
                        "in %.0f s", uid, e, LOGIN_RETRY_SECONDS)
            self.game.logout()
            self.game.message = "Datenbank nicht erreichbar - neuer Versuch ..."
            self._login_retry = (uid, time.monotonic() + LOGIN_RETRY_SECONDS)
            return
        if score is None:
            log.warning(
                "Keine Punkte für userid=%s (weder Kontostand noch Stationen) "
                "- nehme Fallback %d",
                uid, self.args.starting_balance,
            )
        else:
            self.store.set_balance(uid, score)
        player = self.store.get_player(uid)

        # 2) Anzeigename aus PPMaster, Fallback ESP32.
        name = influx_db.query_username(uid)
        if not name and isinstance(self.rfid, HTTPRFIDReader):
            name = self.rfid.get_name_hint(uid)
            if name:
                log.info("Fallback: ESP32 lieferte username %r", name)
        if name:
            player.name = name

        log.info(
            "Login: userid=%s | runid=%s | name=%s | balance=%d",
            player.rfid, runid, player.name, player.balance,
        )
        self._glueck_saved_plays = 0
        self.game.login(player, default_bet=self.args.default_bet)

    def _retry_login_if_due(self) -> None:
        if self._login_retry is None:
            return
        uid, due = self._login_retry
        if time.monotonic() >= due:
            self._login_by_uid(uid)

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
        self._glueck_saved_plays = 0
        self._runid = None
        self.game.login(player, default_bet=self.args.default_bet)

    def _on_round_end(self, player: Player) -> None:
        """Nach jeder Hand das Guthaben speichern (durchlauf/live +
        endscore_stationen/endscore) - auch für den Fall, dass jemand
        geht, ohne den Logout-Taster zu drücken."""
        self._save(player, live=player.balance)

    def _finish_session(self) -> bool:
        """Durchlauf beenden: Glücksfaktor (durchlauf/endscore) speichern, zwischen den
        Runden auch den Kontostand. Nur wenn in diesem Durchlauf gespielt
        wurde und er noch nicht gespeichert ist."""
        player = self.game.player
        plays = self.game.session_plays
        if player is None or plays == 0 or plays == self._glueck_saved_plays:
            return True
        # Mitten in einer Hand ist der Einsatz schon abgezogen - dann den
        # Kontostand nicht anfassen (steht seit der letzten Hand).
        live = player.balance if self.game.can_logout else None
        if not self._save(player, live=live, glueck=self.game.luck_percent):
            return False
        self._glueck_saved_plays = plays
        return True

    def _save(
        self,
        player: Player,
        live: Optional[int] = None,
        glueck: Optional[int] = None,
    ) -> bool:
        """Schreibt Guthaben und/oder Glücksfaktor nach SpieloAutomat.

        Ohne Schreib-Token (Offline-Test) gibt es nichts zu speichern -
        dann ``True``, damit der Logout trotzdem funktioniert.
        """
        if not influx_db.INFLUX_TOKEN_WRITE:
            log.warning("Nicht gespeichert (Guthaben=%s, Glück=%s): "
                        "INFLUX_TOKEN_WRITE fehlt in blackjack/influx_db.py",
                        live, glueck)
            return True
        try:
            return influx_db.write_spielstand(
                player.rfid, live=live, glueck=glueck, runid=self._runid,
            )
        except Exception as e:
            log.warning("write_spielstand fehlgeschlagen: %s", e)
            return False

    def _logout(self) -> None:
        """Logout-Taster: Durchlauf speichern (Kontostand + Glückswert),
        dann RFID-User am ESP32 abmelden. Schlägt ein Schritt fehl, bleibt
        der Spieler angemeldet und kann es nochmal versuchen."""
        player = self.game.player
        if player is None:
            self.game.message = "Kein Spieler angemeldet"
            return
        if not self.game.can_logout:
            self.game.message = "Erst die Runde zu Ende spielen"
            return
        # Nur speichern, wenn wirklich gespielt wurde - sonst würde z. B. ein
        # (falsches) Startguthaben als Kontostand festgeschrieben und hätte
        # ab dann Vorrang vor allen Stationspunkten.
        if not self._finish_session():
            self.game.message = "Speichern fehlgeschlagen - nochmal Logout"
            return
        if self.rfid is not None and not self.rfid.logout():
            self.game.message = "RFID-Logout fehlgeschlagen - nochmal Logout"
            return
        glueck = self.game.luck_percent
        log.info("Logout: userid=%s | name=%s | %d Hände, %d gewonnen | "
                 "Guthaben=%d | Glück=%s",
                 player.rfid, player.name, self.game.session_plays,
                 self.game.session_wins, player.balance,
                 "-" if glueck is None else f"{glueck} %")
        self.game.logout()
        self.game.message = f"Tschüss {player.name}! Guthaben: {player.balance}"
        if glueck is not None:
            self.game.message += f"  Glück: {glueck} %"

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
        if action == "logout":
            self._logout()
            return
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
        # Laufenden Durchlauf abschließen (Glückswert speichern).
        try:
            self._finish_session()
        except Exception:  # pragma: no cover
            pass
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
