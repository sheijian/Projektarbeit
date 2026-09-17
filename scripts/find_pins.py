"""Hilfsskript zum Herausfinden, welche BCM-GPIO-Pins zu den K1..K4-
Beschriftungen des Arcade-Boards gehören.

Das Skript setzt sämtliche GPIO-Pins auf Eingang mit Pull-Up und meldet
laufend, welcher Pin gerade gegen Masse gezogen wird (also welcher Taster
gedrückt ist). So kannst du auf dem Raspberry Pi:

    sudo python -m scripts.find_pins

... starten, dann K1 drücken -> es erscheint z. B. "GPIO 17 low",
K2 drücken -> "GPIO 27 low", usw. Diese vier Nummern trägst du in
`blackjack/config.py` unter K_PINS ein.

Mit Strg+C beenden.
"""

from __future__ import annotations

import sys
import time


# GPIO-Pins, die auf dem 40-Pin-Header überhaupt als IO nutzbar sind.
# (Ohne die SPI-/I2C-/UART-Standardpins, um Fehlmeldungen zu vermeiden.)
CANDIDATE_PINS = [
    4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
]


def main() -> int:
    try:
        import RPi.GPIO as GPIO
    except Exception as e:
        print("Konnte RPi.GPIO nicht laden:", e, file=sys.stderr)
        print("Dieses Skript läuft nur auf dem Raspberry Pi.", file=sys.stderr)
        return 1

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in CANDIDATE_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    print("Bereit. Drücke der Reihe nach K1, K2, K3, K4.")
    print("Beenden mit Strg+C.\n")

    last_state = {pin: GPIO.input(pin) for pin in CANDIDATE_PINS}
    try:
        while True:
            for pin in CANDIDATE_PINS:
                state = GPIO.input(pin)
                if state != last_state[pin]:
                    if state == 0:
                        print(f"GPIO {pin:2d} LOW  (Taster gedrückt)")
                    else:
                        print(f"GPIO {pin:2d} HIGH (Taster losgelassen)")
                    last_state[pin] = state
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nEnde.")
    finally:
        GPIO.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
