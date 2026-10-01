"""Zentrale Konfiguration für das Arcade-Board, die GUI und die Netz-Endpunkte."""

from dataclasses import dataclass
from typing import Dict


# ---------------------------------------------------------------------------
# RFID-Reader hinter dem ESP32
# ---------------------------------------------------------------------------
# Der RFID-Reader meldet sich über HTTP; standardmäßig unter dieser URL.
# Kann über `--rfid-url` auf der Kommandozeile überschrieben werden.
DEFAULT_RFID_URL = "http://10.0.244.81/status"


# ---------------------------------------------------------------------------
# Arcade-Board: welcher K-Anschluss löst welche Aktion aus?
# ---------------------------------------------------------------------------
K_ACTIONS: Dict[str, str] = {
    "K1": "hit",
    "K2": "stand",
    "K3": "double",
    "K4": "split",
}


# ---------------------------------------------------------------------------
# USB-Encoder (EG STARTS Zero Delay)
# ---------------------------------------------------------------------------
# Jede K-Buchse entspricht einer Button-Nummer am Gamepad. Falls die Firmware
# andere Nummern vergibt, hier anpassen - `python -m scripts.find_buttons`
# zeigt die aktuellen Zuordnungen live im Terminal.
K_JOY_BUTTONS: Dict[str, int] = {
    "K1": 0,
    "K2": 1,
    "K3": 2,
    "K4": 3,
}


def build_button_joy(
    k_buttons: Dict[str, int] = K_JOY_BUTTONS,
    k_actions: Dict[str, str] = K_ACTIONS,
) -> Dict[str, int]:
    """Aktion -> USB-Button-Index aus der K1..K4-Belegung."""
    return {action: k_buttons[k] for k, action in k_actions.items()}


BUTTON_JOY: Dict[str, int] = build_button_joy()


# Wenn mehrere USB-Gamepads angesteckt sind, wählt diese Nummer den Encoder.
JOY_INDEX: int = 0


# ---------------------------------------------------------------------------
# Tastatur-Fallback (greift immer zusätzlich zum USB-Encoder)
# ---------------------------------------------------------------------------
KEYBOARD_FALLBACK: Dict[str, str] = {
    "hit":    "h",
    "stand":  "s",
    "double": "d",
    "split":  "p",
}


# ---------------------------------------------------------------------------
# Spiel-Defaults
# ---------------------------------------------------------------------------
DEFAULT_MIN_BET = 10
DEFAULT_BET = 25


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
WINDOW_SIZE = (1280, 800)
FPS = 30

CARD_WIDTH = 110
CARD_HEIGHT = 160
CARD_RADIUS = 10


@dataclass(frozen=True)
class Palette:
    background: tuple = (7, 89, 47)
    table_edge: tuple = (2, 55, 28)
    card_face:  tuple = (250, 249, 244)
    card_back:  tuple = (25, 55, 120)
    card_back_pattern: tuple = (200, 210, 240)
    text_light: tuple = (240, 240, 240)
    text_dark:  tuple = (25, 25, 25)
    red:        tuple = (190, 25, 35)
    black:      tuple = (20, 20, 20)
    accent:     tuple = (235, 195, 70)
    danger:     tuple = (220, 70, 70)
    success:    tuple = (70, 200, 120)


PALETTE = Palette()
