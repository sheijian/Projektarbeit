"""Tests für die K1..K4 -> GPIO- und USB-Button-Zuordnung."""

from blackjack.config import (
    BUTTON_JOY,
    BUTTON_PINS,
    K_ACTIONS,
    K_JOY_BUTTONS,
    K_PINS,
    build_button_joy,
    build_button_pins,
)


def test_default_button_pins_match_k_mapping():
    # Aktion → Anschluss → GPIO
    for k, action in K_ACTIONS.items():
        assert BUTTON_PINS[action] == K_PINS[k]


def test_all_actions_have_a_pin():
    assert set(BUTTON_PINS) == {"hit", "stand", "double", "split"}


def test_swapping_k_actions_swaps_pins():
    # K1 <-> K2 tauschen: hit landet auf dem K2-Pin, stand auf K1.
    custom = {"K1": "stand", "K2": "hit", "K3": "double", "K4": "split"}
    pins = build_button_pins(K_PINS, custom)
    assert pins["hit"] == K_PINS["K2"]
    assert pins["stand"] == K_PINS["K1"]


def test_can_override_k_pins():
    custom_k = {"K1": 5, "K2": 6, "K3": 13, "K4": 19}
    pins = build_button_pins(custom_k, K_ACTIONS)
    assert pins["hit"] == 5
    assert pins["stand"] == 6
    assert pins["double"] == 13
    assert pins["split"] == 19


def test_default_button_joy_match_k_mapping():
    for k, action in K_ACTIONS.items():
        assert BUTTON_JOY[action] == K_JOY_BUTTONS[k]


def test_all_actions_have_a_joy_button():
    assert set(BUTTON_JOY) == {"hit", "stand", "double", "split"}


def test_swapping_k_actions_swaps_joy_buttons():
    custom = {"K1": "stand", "K2": "hit", "K3": "double", "K4": "split"}
    joy = build_button_joy(K_JOY_BUTTONS, custom)
    assert joy["hit"] == K_JOY_BUTTONS["K2"]
    assert joy["stand"] == K_JOY_BUTTONS["K1"]


def test_can_override_k_joy_buttons():
    custom = {"K1": 4, "K2": 5, "K3": 6, "K4": 7}
    joy = build_button_joy(custom, K_ACTIONS)
    assert joy == {"hit": 4, "stand": 5, "double": 6, "split": 7}
