"""Zeichnet Spielkarten mit pygame - Ergebnis sieht aus wie ein echtes Kartenspiel.

Alle Karten werden einmalig als Surface gerendert und im Cache gehalten, damit
das Zeichnen im laufenden Spiel günstig ist.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Optional, Tuple

import pygame

from .cards import Card, RED_SUITS, SUIT_SYMBOLS
from .config import CARD_HEIGHT, CARD_RADIUS, CARD_WIDTH, PALETTE


# Anzahl der Pip-Symbole in der Kartenmitte je Rang.
PIP_LAYOUT: Dict[str, Tuple[Tuple[float, float], ...]] = {
    "A":  ((0.5, 0.5),),
    "2":  ((0.5, 0.22), (0.5, 0.78)),
    "3":  ((0.5, 0.22), (0.5, 0.5), (0.5, 0.78)),
    "4":  ((0.3, 0.22), (0.7, 0.22), (0.3, 0.78), (0.7, 0.78)),
    "5":  ((0.3, 0.22), (0.7, 0.22), (0.5, 0.5), (0.3, 0.78), (0.7, 0.78)),
    "6":  ((0.3, 0.22), (0.7, 0.22), (0.3, 0.5), (0.7, 0.5),
           (0.3, 0.78), (0.7, 0.78)),
    "7":  ((0.3, 0.22), (0.7, 0.22), (0.5, 0.35),
           (0.3, 0.5), (0.7, 0.5), (0.3, 0.78), (0.7, 0.78)),
    "8":  ((0.3, 0.22), (0.7, 0.22), (0.5, 0.35),
           (0.3, 0.5), (0.7, 0.5),
           (0.5, 0.65), (0.3, 0.78), (0.7, 0.78)),
    "9":  ((0.3, 0.2), (0.7, 0.2), (0.3, 0.38), (0.7, 0.38),
           (0.5, 0.5),
           (0.3, 0.62), (0.7, 0.62), (0.3, 0.8), (0.7, 0.8)),
    "10": ((0.3, 0.18), (0.7, 0.18), (0.5, 0.28),
           (0.3, 0.4), (0.7, 0.4),
           (0.3, 0.6), (0.7, 0.6), (0.5, 0.72),
           (0.3, 0.82), (0.7, 0.82)),
}

FACE_INITIALS = {"J": "J", "Q": "Q", "K": "K"}


# ---------------------------------------------------------------------------
def _rounded_rect(surface: pygame.Surface, color, rect, radius: int) -> None:
    pygame.draw.rect(surface, color, rect, border_radius=radius)


def _load_fonts() -> Tuple[pygame.font.Font, pygame.font.Font, pygame.font.Font]:
    """(kleine Ecken, große Pip, sehr große Buchstaben für J/Q/K)."""
    corner = pygame.font.SysFont("dejavusans", 22, bold=True)
    pip = pygame.font.SysFont("dejavusans", 34, bold=True)
    face = pygame.font.SysFont("dejavusans", 64, bold=True)
    return corner, pip, face


_fonts_cache: Optional[Tuple[pygame.font.Font, pygame.font.Font, pygame.font.Font]] = None


def _get_fonts():
    global _fonts_cache
    if _fonts_cache is None:
        _fonts_cache = _load_fonts()
    return _fonts_cache


def _draw_symbol(
    surface: pygame.Surface,
    symbol: str,
    color,
    center: Tuple[int, int],
    font: pygame.font.Font,
    flip: bool = False,
) -> None:
    text = font.render(symbol, True, color)
    if flip:
        text = pygame.transform.flip(text, True, True)
    rect = text.get_rect(center=center)
    surface.blit(text, rect)


def _draw_corner(
    surface: pygame.Surface,
    rank: str,
    symbol: str,
    color,
    font: pygame.font.Font,
    x: int,
    y: int,
    flip: bool = False,
) -> None:
    rank_text = font.render(rank, True, color)
    symbol_text = font.render(symbol, True, color)
    if flip:
        rank_text = pygame.transform.flip(rank_text, True, True)
        symbol_text = pygame.transform.flip(symbol_text, True, True)
    if flip:
        surface.blit(rank_text, (x - rank_text.get_width(), y - rank_text.get_height()))
        surface.blit(
            symbol_text,
            (
                x - symbol_text.get_width(),
                y - rank_text.get_height() - symbol_text.get_height(),
            ),
        )
    else:
        surface.blit(rank_text, (x, y))
        surface.blit(symbol_text, (x, y + rank_text.get_height()))


# ---------------------------------------------------------------------------
def render_card(card: Card) -> pygame.Surface:
    """Rendert eine offene Karte als transparente Surface."""

    return _render_card_cached(card.rank, card.suit)


@lru_cache(maxsize=64)
def _render_card_cached(rank: str, suit: str) -> pygame.Surface:
    corner_font, pip_font, face_font = _get_fonts()
    symbol = SUIT_SYMBOLS[suit]
    color = PALETTE.red if suit in RED_SUITS else PALETTE.black

    surface = pygame.Surface((CARD_WIDTH, CARD_HEIGHT), pygame.SRCALPHA)
    _rounded_rect(surface, PALETTE.card_face, surface.get_rect(), CARD_RADIUS)
    pygame.draw.rect(
        surface, (180, 180, 180), surface.get_rect(),
        width=1, border_radius=CARD_RADIUS,
    )

    # Ecken links oben und rechts unten.
    _draw_corner(surface, rank, symbol, color, corner_font, 6, 4)
    _draw_corner(
        surface, rank, symbol, color, corner_font,
        CARD_WIDTH - 6, CARD_HEIGHT - 4, flip=True,
    )

    # Mittelbereich.
    if rank in PIP_LAYOUT:
        for fx, fy in PIP_LAYOUT[rank]:
            cx = int(CARD_WIDTH * fx)
            cy = int(CARD_HEIGHT * fy)
            flip = fy > 0.5 and rank not in ("A",)
            _draw_symbol(surface, symbol, color, (cx, cy), pip_font, flip=flip)
    elif rank in FACE_INITIALS:
        _draw_symbol(
            surface, FACE_INITIALS[rank], color,
            (CARD_WIDTH // 2, CARD_HEIGHT // 2), face_font,
        )
        # kleines Symbol darunter
        _draw_symbol(
            surface, symbol, color,
            (CARD_WIDTH // 2, int(CARD_HEIGHT * 0.72)), pip_font,
        )
    return surface


# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def render_card_back() -> pygame.Surface:
    """Karten-Rückseite (Rautenmuster)."""

    surface = pygame.Surface((CARD_WIDTH, CARD_HEIGHT), pygame.SRCALPHA)
    _rounded_rect(surface, PALETTE.card_face, surface.get_rect(), CARD_RADIUS)
    inner = surface.get_rect().inflate(-8, -8)
    _rounded_rect(surface, PALETTE.card_back, inner, CARD_RADIUS - 3)

    # Rautenmuster
    step = 14
    for i in range(-CARD_HEIGHT, CARD_WIDTH + CARD_HEIGHT, step):
        pygame.draw.line(
            surface, PALETTE.card_back_pattern,
            (inner.left + i, inner.top),
            (inner.left + i + CARD_HEIGHT, inner.top + CARD_HEIGHT),
            1,
        )
        pygame.draw.line(
            surface, PALETTE.card_back_pattern,
            (inner.left + i, inner.bottom),
            (inner.left + i + CARD_HEIGHT, inner.bottom - CARD_HEIGHT),
            1,
        )

    pygame.draw.rect(
        surface, PALETTE.accent, inner,
        width=2, border_radius=CARD_RADIUS - 3,
    )
    pygame.draw.rect(
        surface, (180, 180, 180), surface.get_rect(),
        width=1, border_radius=CARD_RADIUS,
    )
    return surface
