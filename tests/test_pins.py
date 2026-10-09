"""Tests für die K1..K4 -> USB-Button-Zuordnung."""

from blackjack.config import (
    BUTTON_JOY,
    K_ACTIONS,
    K_JOY_BUTTONS,
    build_button_joy,
)


def test_all_actions_have_a_joy_button():
    assert set(BUTTON_JOY) == {"hit", "stand", "double", "split", "logout"}


def test_logout_on_k5_and_key_l():
    from blackjack.config import KEYBOARD_FALLBACK
    assert K_ACTIONS["K5"] == "logout"
    assert BUTTON_JOY["logout"] == K_JOY_BUTTONS["K5"]
    assert KEYBOARD_FALLBACK["logout"] == "l"
    # Jede Taste nur einmal belegt.
    assert len(set(KEYBOARD_FALLBACK.values())) == len(KEYBOARD_FALLBACK)


def test_default_button_joy_match_k_mapping():
    for k, action in K_ACTIONS.items():
        assert BUTTON_JOY[action] == K_JOY_BUTTONS[k]


def test_swapping_k_actions_swaps_joy_buttons():
    custom = {"K1": "stand", "K2": "hit", "K3": "double", "K4": "split"}
    joy = build_button_joy(K_JOY_BUTTONS, custom)
    assert joy["hit"] == K_JOY_BUTTONS["K2"]
    assert joy["stand"] == K_JOY_BUTTONS["K1"]


def test_can_override_k_joy_buttons():
    custom = {"K1": 4, "K2": 5, "K3": 6, "K4": 7, "K5": 8}
    joy = build_button_joy(custom, K_ACTIONS)
    assert joy == {"hit": 4, "stand": 5, "double": 6, "split": 7, "logout": 8}
