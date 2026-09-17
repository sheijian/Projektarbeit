"""Zentrale Konfiguration für Pins, Farben und API."""

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# Arcade-Board: welcher physische Anschluss löst welche Spiel-Aktion aus?
# ---------------------------------------------------------------------------
# Auf dem verwendeten Arcade-Board sind die Taster-Anschlüsse mit K1..K4
# beschriftet. Die Zuordnung "Anschluss -> Aktion" ist frei wählbar - im
# Zweifel einfach die Kabel anders aufstecken oder hier tauschen.
K_ACTIONS: Dict[str, str] = {
    "K1": "hit",
    "K2": "stand",
    "K3": "double",
    "K4": "split",
}


# ---------------------------------------------------------------------------
# USB-Modus (Zero-Delay-Encoder wie EG STARTS)
# ---------------------------------------------------------------------------
# Das Board wird per USB als HID-Gamepad erkannt. Jede K-Belegung entspricht
# einer Button-Nummer. Die Reihenfolge kann sich je nach Firmware unter-
# scheiden. Mit `python -m scripts.find_buttons` kannst du die tatsächlichen
# Nummern in wenigen Sekunden ermitteln und hier eintragen.
K_JOY_BUTTONS: Dict[str, int] = {
    "K1": 0,
    "K2": 1,
    "K3": 2,
    "K4": 3,
}


# ---------------------------------------------------------------------------
# GPIO-Modus (falls die Taster direkt am 40-Pin-Header des Pi hängen)
# ---------------------------------------------------------------------------
K_PINS: Dict[str, int] = {
    "K1": 17,
    "K2": 27,
    "K3": 22,
    "K4": 23,
}


def build_button_pins(
    k_pins: Dict[str, int] = K_PINS,
    k_actions: Dict[str, str] = K_ACTIONS,
) -> Dict[str, int]:
    """Aktion -> GPIO-Pin aus der K1..K4-Belegung."""
    return {action: k_pins[k] for k, action in k_actions.items()}


def build_button_joy(
    k_buttons: Dict[str, int] = K_JOY_BUTTONS,
    k_actions: Dict[str, str] = K_ACTIONS,
) -> Dict[str, int]:
    """Aktion -> USB-Joystick-Button-Index aus der K1..K4-Belegung."""
    return {action: k_buttons[k] for k, action in k_actions.items()}


BUTTON_PINS: Dict[str, int] = build_button_pins()
BUTTON_JOY:  Dict[str, int] = build_button_joy()


# Wenn mehrere USB-Gamepads angesteckt sind, wählt diese Nummer den
# Encoder aus (0 = das erste erkannte Gerät).
JOY_INDEX: int = 0


# Tastatur-Fallback, wenn kein GPIO verfügbar ist.
KEYBOARD_FALLBACK: Dict[str, str] = {
    "hit":    "h",
    "stand":  "s",
    "double": "d",
    "split":  "p",
}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
DEFAULT_API_URL = "http://localhost:5000"
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
    background: tuple = (7, 89, 47)          # Filzgrün
    table_edge: tuple = (2, 55, 28)
    card_face:  tuple = (250, 249, 244)      # elfenbein
    card_back:  tuple = (25, 55, 120)
    card_back_pattern: tuple = (200, 210, 240)
    text_light: tuple = (240, 240, 240)
    text_dark:  tuple = (25, 25, 25)
    red:        tuple = (190, 25, 35)
    black:      tuple = (20, 20, 20)
    accent:     tuple = (235, 195, 70)       # gold
    danger:     tuple = (220, 70, 70)
    success:    tuple = (70, 200, 120)


PALETTE = Palette()


# ---------------------------------------------------------------------------
# RFID-Mock: welche UIDs entsprechen welchen Spielern
# ---------------------------------------------------------------------------
MOCK_RFID_KEYS: Dict[str, str] = {
    "1": "0416AC12",
    "2": "04D3A177",
    "3": "0491BB55",
}
