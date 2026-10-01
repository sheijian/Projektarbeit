"""Arcade-Taster-Handler (USB-Encoder + Tastatur-Fallback).

Der EG-STARTS-Encoder hängt per USB am Rechner und meldet sich als
HID-Gamepad. Jeder Taster erzeugt in pygame ein ``JOYBUTTONDOWN``-Event.
Die Zuordnung Button-Index → Aktion kommt aus `config.BUTTON_JOY`
(gebildet aus `K_JOY_BUTTONS` + `K_ACTIONS`).

Zusätzlich ist immer eine Tastatur-Steuerung verfügbar
(H/S/D/P - siehe `config.KEYBOARD_FALLBACK`), damit das Spiel auch ohne
Encoder bedient werden kann.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Dict, Optional

import pygame

from .config import BUTTON_JOY, JOY_INDEX, KEYBOARD_FALLBACK

log = logging.getLogger(__name__)


InputMode = str    # "usb" | "keyboard" | "auto"
VALID_MODES = ("auto", "usb", "keyboard")


# ---------------------------------------------------------------------------
class ButtonHandler:
    """Kapselt die vier Arcade-Taster."""

    DEBOUNCE_MS = 180

    def __init__(self, mode: InputMode = "auto") -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Ungültiger input-Modus: {mode}")

        self.events: "queue.Queue[str]" = queue.Queue()
        self._last_press: Dict[str, float] = {a: 0.0 for a in BUTTON_JOY}
        self._stop = threading.Event()

        # Tastatur-Belegung ist immer aktiv.
        self._key_map = {
            self._to_pygame_key(v): action
            for action, v in KEYBOARD_FALLBACK.items()
        }

        self._mode = self._resolve_mode(mode)
        self._joy: Optional[pygame.joystick.Joystick] = None
        self._joy_map: Dict[int, str] = {}

        if self._mode == "usb":
            self._setup_usb()

        log.info(
            "ButtonHandler: Modus '%s' aktiv (Tastatur zusätzlich)",
            self._mode,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _has_usb_gamepad() -> bool:
        try:
            if not pygame.get_init():
                pygame.init()
            pygame.joystick.init()
            return pygame.joystick.get_count() > 0
        except Exception:
            return False

    def _resolve_mode(self, requested: InputMode) -> InputMode:
        if requested != "auto":
            return requested
        return "usb" if self._has_usb_gamepad() else "keyboard"

    # ------------------------------------------------------------------
    def _setup_usb(self) -> None:
        if not pygame.get_init():
            pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count == 0:
            log.warning("USB-Modus gewählt, aber kein Gamepad gefunden - "
                        "falle auf Tastatur zurück")
            self._mode = "keyboard"
            return
        idx = JOY_INDEX if JOY_INDEX < count else 0
        self._joy = pygame.joystick.Joystick(idx)
        self._joy.init()
        log.info("USB-Gamepad: %s (%d Buttons)",
                 self._joy.get_name(), self._joy.get_numbuttons())
        self._joy_map = {btn: action for action, btn in BUTTON_JOY.items()}

    # ------------------------------------------------------------------
    def _to_pygame_key(self, ch: str) -> int:
        return getattr(pygame, f"K_{ch.lower()}")

    def _on_press(self, action: str) -> None:
        now = time.monotonic()
        if now - self._last_press[action] < self.DEBOUNCE_MS / 1000:
            return
        self._last_press[action] = now
        self.events.put(action)
        log.debug("Taster: %s", action)

    # ------------------------------------------------------------------
    def handle_pygame_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in self._key_map:
            self._on_press(self._key_map[event.key])
            return
        if self._mode == "usb" and event.type == pygame.JOYBUTTONDOWN:
            action = self._joy_map.get(event.button)
            if action:
                self._on_press(action)
            else:
                log.debug("Unbenutzter Joystick-Button: %d", event.button)

    def poll(self) -> Optional[str]:
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        if self._joy is not None:
            try:
                self._joy.quit()
            except Exception:  # pragma: no cover
                pass

    @property
    def mode(self) -> InputMode:
        return self._mode
