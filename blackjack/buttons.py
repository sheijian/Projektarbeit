"""Arcade-Taster über GPIO mit Tastatur-Fallback für den PC.

Die Klasse `ButtonHandler` erzeugt für jede Aktion ein Event auf einer
Queue, sobald der zugehörige Taster gedrückt wurde. Ist `RPi.GPIO` nicht
installiert oder das Programm läuft nicht auf einem Pi, wird ein
Keyboard-Fallback über pygame verwendet.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import pygame

from .config import BUTTON_PINS, KEYBOARD_FALLBACK

log = logging.getLogger(__name__)


try:
    import RPi.GPIO as GPIO  # type: ignore
    HAS_GPIO = True
except Exception:   # ImportError oder RuntimeError außerhalb des Pi
    GPIO = None      # type: ignore
    HAS_GPIO = False


# ---------------------------------------------------------------------------
class ButtonHandler:
    """Kapselt die vier Arcade-Taster."""

    DEBOUNCE_MS = 180

    def __init__(self, use_gpio: Optional[bool] = None) -> None:
        self.events: "queue.Queue[str]" = queue.Queue()
        self._last_press: dict[str, float] = {a: 0.0 for a in BUTTON_PINS}
        self._use_gpio = HAS_GPIO if use_gpio is None else (use_gpio and HAS_GPIO)
        self._stop = threading.Event()

        if self._use_gpio:
            self._setup_gpio()
            log.info("ButtonHandler: GPIO aktiv")
        else:
            log.info("ButtonHandler: Tastatur-Fallback aktiv (H/S/D/P)")

        # Fallback über pygame-Events. Für GPIO ist das zusätzlich
        # praktisch, damit man das Spiel auch mit Tastatur bedienen kann.
        self._key_map = {
            self._to_pygame_key(v): action
            for action, v in KEYBOARD_FALLBACK.items()
        }

    # ------------------------------------------------------------------
    def _to_pygame_key(self, ch: str) -> int:
        return getattr(pygame, f"K_{ch.lower()}")

    # ------------------------------------------------------------------
    def _setup_gpio(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for action, pin in BUTTON_PINS.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            # Interrupt auf fallende Flanke (Taster nach GND).
            GPIO.add_event_detect(
                pin,
                GPIO.FALLING,
                callback=lambda _pin, a=action: self._on_press(a),
                bouncetime=self.DEBOUNCE_MS,
            )

    # ------------------------------------------------------------------
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

    def poll(self) -> Optional[str]:
        """Nicht-blockierend die nächste Aktion holen."""
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        if self._use_gpio:
            GPIO.cleanup(list(BUTTON_PINS.values()))
