"""Hilfsskript zum Herausfinden der USB-Button-Nummern.

Der EG-STARTS-Encoder (und die meisten Zero-Delay-Boards) meldet sich per
USB als HID-Gamepad. Jede der K1..K4-Buchsen entspricht einer bestimmten
Button-Nummer, die je nach Firmware unterschiedlich sein kann.

Aufruf:

    python -m scripts.find_buttons

Ein kleines pygame-Fenster öffnet sich. Drücke der Reihe nach K1, K2, K3
und K4 - im Terminal erscheint jeweils die zugehörige Button-Nummer. Trage
diese vier Zahlen in `blackjack/config.py` unter ``K_JOY_BUTTONS`` ein.

Mit Strg+C oder über das Fensterkreuz beenden.
"""

from __future__ import annotations

import sys

import pygame


def main() -> int:
    pygame.init()
    pygame.joystick.init()

    count = pygame.joystick.get_count()
    if count == 0:
        print("Kein USB-Gamepad gefunden.", file=sys.stderr)
        print("Ist das Board eingesteckt und wird es vom System erkannt?",
              file=sys.stderr)
        return 1

    print(f"Gefundene Gamepads: {count}")
    joys = []
    for i in range(count):
        j = pygame.joystick.Joystick(i)
        j.init()
        joys.append(j)
        print(f"  [{i}] {j.get_name()!r} - {j.get_numbuttons()} Buttons, "
              f"{j.get_numaxes()} Achsen")

    # Ein Fenster ist nötig, damit pygame Events zustellt.
    screen = pygame.display.set_mode((360, 120))
    pygame.display.set_caption("find_buttons - K1..K4 drücken")
    font = pygame.font.SysFont("dejavusans", 18, bold=True)

    last: str = "Warte auf Tastendruck …"
    print("\nDrücke der Reihe nach K1, K2, K3, K4. Beenden mit Strg+C.")

    try:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.JOYBUTTONDOWN:
                    joy_id = event.joy if hasattr(event, "joy") else event.instance_id
                    msg = f"Joystick {joy_id}, Button {event.button}"
                    print(msg)
                    last = msg
                elif event.type == pygame.JOYAXISMOTION:
                    if abs(event.value) > 0.5:
                        # Joystick-Achse: nur wenn du versehentlich den
                        # Stick statt eines Buttons drückst.
                        print(f"Joystick {event.joy} Achse {event.axis} = "
                              f"{event.value:+.2f}")

            screen.fill((20, 20, 30))
            surf = font.render(last, True, (240, 240, 240))
            screen.blit(surf, surf.get_rect(center=screen.get_rect().center))
            pygame.display.flip()
            pygame.time.wait(20)
    except KeyboardInterrupt:
        print("\nEnde.")
    finally:
        for j in joys:
            j.quit()
        pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
