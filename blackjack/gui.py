"""Hauptfenster und Rendering des Blackjack-Automaten."""

from __future__ import annotations

import math
from typing import List, Optional

import pygame

from .cards import Card
from .config import (
    CARD_HEIGHT,
    CARD_WIDTH,
    FPS,
    PALETTE,
    WINDOW_SIZE,
)
from .game import Game, State, Outcome
from .hand import Hand
from .render import render_card, render_card_back


class BlackjackGUI:
    """Zeichnet den aktuellen Spielzustand."""

    def __init__(self, game: Game) -> None:
        self.game = game
        pygame.init()
        pygame.display.set_caption("Blackjack – Projektarbeit")
        self.screen = pygame.display.set_mode(WINDOW_SIZE)
        self.clock = pygame.time.Clock()

        self.font_hud = pygame.font.SysFont("dejavusans", 22, bold=True)
        self.font_big = pygame.font.SysFont("dejavusans", 44, bold=True)
        self.font_med = pygame.font.SysFont("dejavusans", 26, bold=True)
        self.font_small = pygame.font.SysFont("dejavusans", 16)

    # ------------------------------------------------------------------
    def tick(self) -> None:
        self.clock.tick(FPS)
        self._draw()
        pygame.display.flip()

    def close(self) -> None:
        pygame.quit()

    # ------------------------------------------------------------------
    def _draw(self) -> None:
        self._draw_background()
        self._draw_dealer()
        self._draw_player()
        self._draw_hud()
        self._draw_message()
        self._draw_action_bar()

    # ------------------------------------------------------------------
    def _draw_background(self) -> None:
        self.screen.fill(PALETTE.background)
        w, h = WINDOW_SIZE
        # Tischbogen
        pygame.draw.ellipse(
            self.screen,
            PALETTE.table_edge,
            pygame.Rect(-100, 60, w + 200, h - 120),
            width=6,
        )

    # ------------------------------------------------------------------
    def _draw_dealer(self) -> None:
        game = self.game
        w, _ = WINDOW_SIZE
        y = 120
        label = self.font_med.render("Dealer", True, PALETTE.text_light)
        self.screen.blit(label, (w // 2 - label.get_width() // 2, y - 40))

        hide_hole = game.state in (
            State.DEALING,
            State.PLAYER_TURN,
        ) and len(game.dealer.cards) >= 2

        cards = game.dealer.cards
        self._draw_card_row(cards, w // 2, y, hidden_index=1 if hide_hole else None)

        if game.dealer.cards and not hide_hole:
            score = self.font_med.render(
                str(game.dealer.value), True, PALETTE.accent
            )
            self.screen.blit(
                score,
                (w // 2 - score.get_width() // 2, y + CARD_HEIGHT + 10),
            )

    # ------------------------------------------------------------------
    def _draw_player(self) -> None:
        game = self.game
        w, h = WINDOW_SIZE
        y = h - CARD_HEIGHT - 130

        if not game.hands:
            return

        # Hände horizontal verteilen.
        n = len(game.hands)
        section_w = w // n
        for idx, hand in enumerate(game.hands):
            cx = section_w * idx + section_w // 2
            self._draw_hand(hand, cx, y, active=(idx == game.active_hand))
            # Punktzahl / Einsatz / Ergebnis
            self._draw_hand_footer(hand, idx, cx, y + CARD_HEIGHT + 6)

    def _draw_hand_footer(self, hand: Hand, idx: int, cx: int, y: int) -> None:
        game = self.game
        # Punktzahl
        color = PALETTE.text_light
        if hand.is_bust:
            color = PALETTE.danger
        elif hand.is_blackjack:
            color = PALETTE.accent

        score_txt = f"{hand.value}"
        if hand.is_bust:
            score_txt += " BUST"
        elif hand.is_blackjack:
            score_txt = "BLACKJACK"
        score = self.font_med.render(score_txt, True, color)
        self.screen.blit(score, (cx - score.get_width() // 2, y))

        # Einsatz
        bet_txt = f"Einsatz: {hand.bet}"
        if hand.doubled:
            bet_txt += " (Double)"
        bet = self.font_small.render(bet_txt, True, PALETTE.text_light)
        self.screen.blit(bet, (cx - bet.get_width() // 2, y + 34))

        # Ergebnis
        if game.state == State.ROUND_OVER and idx < len(game.results):
            result = game.results[idx]
            colors = {
                Outcome.WIN:       PALETTE.success,
                Outcome.BLACKJACK: PALETTE.accent,
                Outcome.LOSE:      PALETTE.danger,
                Outcome.PUSH:      PALETTE.text_light,
            }
            labels = {
                Outcome.WIN:       "GEWONNEN",
                Outcome.BLACKJACK: "BLACKJACK 3:2",
                Outcome.LOSE:      "VERLOREN",
                Outcome.PUSH:      "PUSH",
            }
            surf = self.font_med.render(
                labels[result.outcome], True, colors[result.outcome]
            )
            self.screen.blit(surf, (cx - surf.get_width() // 2, y + 56))
            delta_surf = self.font_small.render(
                f"{result.delta:+d}", True, colors[result.outcome]
            )
            self.screen.blit(delta_surf, (cx - delta_surf.get_width() // 2, y + 84))

    # ------------------------------------------------------------------
    def _draw_hand(self, hand: Hand, cx: int, y: int, active: bool) -> None:
        self._draw_card_row(hand.cards, cx, y, highlight=active)

    def _draw_card_row(
        self,
        cards: List[Card],
        cx: int,
        y: int,
        hidden_index: Optional[int] = None,
        highlight: bool = False,
    ) -> None:
        if not cards:
            return
        overlap = 34
        total_w = CARD_WIDTH + (len(cards) - 1) * (CARD_WIDTH - overlap)
        start_x = cx - total_w // 2

        if highlight:
            pygame.draw.rect(
                self.screen,
                PALETTE.accent,
                pygame.Rect(start_x - 8, y - 8,
                            total_w + 16, CARD_HEIGHT + 16),
                width=3,
                border_radius=14,
            )

        for i, card in enumerate(cards):
            x = start_x + i * (CARD_WIDTH - overlap)
            # kleine "Deal"-Animation: fliegen leicht rein.
            offset = int(3 * math.sin((pygame.time.get_ticks() / 250.0) + i))
            if hidden_index is not None and i == hidden_index:
                surf = render_card_back()
            else:
                surf = render_card(card)
            self.screen.blit(surf, (x, y + offset))

    # ------------------------------------------------------------------
    def _draw_hud(self) -> None:
        w, _ = WINDOW_SIZE
        game = self.game
        # Oberer Balken
        pygame.draw.rect(self.screen, PALETTE.table_edge, (0, 0, w, 50))
        if game.player:
            info = f"Spieler: {game.player.name}   Guthaben: {game.player.balance}"
        else:
            info = "Kein Spieler angemeldet"
        surf = self.font_hud.render(info, True, PALETTE.text_light)
        self.screen.blit(surf, (16, 12))

        bet_info = f"Einsatz: {game.current_bet}"
        surf = self.font_hud.render(bet_info, True, PALETTE.accent)
        self.screen.blit(surf, (w - surf.get_width() - 16, 12))

    # ------------------------------------------------------------------
    def _draw_message(self) -> None:
        game = self.game
        if not game.message:
            return
        surf = self.font_big.render(game.message, True, PALETTE.text_light)
        w, _ = WINDOW_SIZE
        rect = surf.get_rect(center=(w // 2, 340))

        bg = pygame.Rect(rect).inflate(40, 20)
        s = pygame.Surface(bg.size, pygame.SRCALPHA)
        s.fill((0, 0, 0, 120))
        self.screen.blit(s, bg.topleft)
        self.screen.blit(surf, rect)

    # ------------------------------------------------------------------
    def _draw_action_bar(self) -> None:
        w, h = WINDOW_SIZE
        y = h - 70
        game = self.game

        actions = [
            ("HIT",    "H", game.state == State.PLAYER_TURN
                              or game.state in (State.BETTING, State.ROUND_OVER)),
            ("STAND",  "S", game.state == State.PLAYER_TURN),
            ("DOUBLE", "D", game.state == State.PLAYER_TURN
                              and self._current_hand()
                              and self._current_hand().can_double),
            ("SPLIT",  "P", game.state == State.PLAYER_TURN
                              and self._current_hand()
                              and self._current_hand().can_split),
        ]

        btn_w = 180
        spacing = 20
        total = len(actions) * btn_w + (len(actions) - 1) * spacing
        x = (w - total) // 2

        for label, key, enabled in actions:
            rect = pygame.Rect(x, y, btn_w, 50)
            color = PALETTE.accent if enabled else (80, 80, 80)
            text_color = PALETTE.text_dark if enabled else (160, 160, 160)
            pygame.draw.rect(self.screen, color, rect, border_radius=10)
            pygame.draw.rect(
                self.screen, PALETTE.table_edge, rect, width=2, border_radius=10,
            )
            surf = self.font_med.render(label, True, text_color)
            self.screen.blit(surf, surf.get_rect(center=rect.center))
            key_surf = self.font_small.render(f"[{key}]", True, text_color)
            self.screen.blit(
                key_surf, (rect.centerx - key_surf.get_width() // 2, rect.bottom - 18),
            )
            x += btn_w + spacing

    def _current_hand(self) -> Optional[Hand]:
        g = self.game
        if not g.hands or g.active_hand >= len(g.hands):
            return None
        return g.hands[g.active_hand]
