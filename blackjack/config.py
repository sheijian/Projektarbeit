"""Zentrale Konfiguration für Pins, Farben und API."""

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# GPIO-Pin-Belegung (BCM-Nummerierung)
# ---------------------------------------------------------------------------
BUTTON_PINS: Dict[str, int] = {
    "hit":    17,
    "stand":  27,
    "double": 22,
    "split":  23,
}


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
