"""Arcade-Taster-Handler.

Drei mögliche Eingabequellen:

* ``usb``      – der Zero-Delay-Encoder wird per USB als HID-Gamepad erkannt.
                Jeder Taster meldet sich als Button-Down-Event in pygame
                (``JOYBUTTONDOWN``). Das ist die Standardvariante für das
                verwendete EG-STARTS-Board.
* ``gpio``     – die Taster hängen direkt am 40-Pin-Header eines Raspberry Pi.
                Benötigt ``RPi.GPIO`` und läuft nur auf dem Pi.
* ``keyboard`` – reine Tastatur-Bedienung (Fallback für die Entwicklung).

Im Modus ``auto`` (Default) wird automatisch die beste verfügbare Quelle
gewählt: erst USB-Gamepad, dann GPIO, sonst Tastatur.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Dict, Optional

import pygame

from .config import BUTTON_JOY, BUTTON_PINS, JOY_INDEX, KEYBOARD_FALLBACK

log = logging.getLogger(__name__)


try:
    import RPi.GPIO as GPIO  # type: ignore
    HAS_GPIO = True
except Exception:   # ImportError oder RuntimeError außerhalb des Pi
    GPIO = None      # type: ignore
    HAS_GPIO = False


InputMode = str    # "usb" | "gpio" | "keyboard" | "auto"
VALID_MODES = ("auto", "usb", "gpio", "keyboard")


# ---------------------------------------------------------------------------
class ButtonHandler:
    """Kapselt die vier Arcade-Taster."""

    DEBOUNCE_MS = 180

    def __init__(self, mode: InputMode = "auto") -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Ungültiger input-Modus: {mode}")

        self.events: "queue.Queue[str]" = queue.Queue()
        self._last_press: Dict[str, float] = {a: 0.0 for a in BUTTON_PINS}
        self._stop = threading.Event()

        # Tastatur-Belegung ist immer aktiv (auch parallel zu USB/GPIO).
        self._key_map = {
            self._to_pygame_key(v): action
            for action, v in KEYBOARD_FALLBACK.items()
        }

        self._mode = self._resolve_mode(mode)

        # Joystick: von USB-Modus initialisiert und in pygame-Events verarbeitet.
        self._joy: Optional[pygame.joystick.Joystick] = None
        self._joy_map: Dict[int, str] = {}

        if self._mode == "usb":
            self._setup_usb()
        elif self._mode == "gpio":
            self._setup_gpio()

        log.info("ButtonHandler: Modus '%s' aktiv (Tastatur zusätzlich)",
                 self._mode)

    # ------------------------------------------------------------------
    # Auto-Erkennung
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
        if self._has_usb_gamepad():
            return "usb"
        if HAS_GPIO:
            return "gpio"
        return "keyboard"

    # ------------------------------------------------------------------
    # USB-Gamepad
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
        if JOY_INDEX >= count:
            log.warning("JOY_INDEX %d nicht vorhanden (nur %d Geräte), nehme 0",
                        JOY_INDEX, count)
            idx = 0
        else:
            idx = JOY_INDEX

        self._joy = pygame.joystick.Joystick(idx)
        self._joy.init()
        log.info("USB-Gamepad: %s (%d Buttons)",
                 self._joy.get_name(), self._joy.get_numbuttons())

        # Button-Nummer → Aktion
        self._joy_map = {btn: action for action, btn in BUTTON_JOY.items()}

    # ------------------------------------------------------------------
    # GPIO
    # ------------------------------------------------------------------
    def _setup_gpio(self) -> None:
        if not HAS_GPIO:
            log.warning("GPIO-Modus gewählt, aber RPi.GPIO nicht verfügbar - "
                        "falle auf Tastatur zurück")
            self._mode = "keyboard"
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for action, pin in BUTTON_PINS.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                pin,
                GPIO.FALLING,
                callback=lambda _pin, a=action: self._on_press(a),
                bouncetime=self.DEBOUNCE_MS,
            )

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
        # Tastatur immer
        if event.type == pygame.KEYDOWN and event.key in self._key_map:
            self._on_press(self._key_map[event.key])
            return
        # USB-Gamepad
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
        if self._mode == "gpio" and HAS_GPIO:
            GPIO.cleanup(list(BUTTON_PINS.values()))
        if self._joy is not None:
            try:
                self._joy.quit()
            except Exception:  # pragma: no cover
                pass

    # ------------------------------------------------------------------
    @property
    def mode(self) -> InputMode:
        return self._mode
