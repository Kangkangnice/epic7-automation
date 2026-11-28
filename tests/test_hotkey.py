import unittest

from auto_game_unified.core.hotkey import STOP_HOLD_SECONDS, WindowsPStopHotkey


class WindowsPStopHotkeyTests(unittest.TestCase):
    def test_short_tap_does_not_trigger_stop(self):
        states = iter([0, 0x8000, 0x8000, 0, 0x8000, 0])
        times = iter([0.0, 0.2, 0.5, 0.8])
        queried_keys: list[int] = []

        def get_key_state(key: int) -> int:
            queried_keys.append(key)
            return next(states)

        hotkey = WindowsPStopHotkey(
            get_key_state=get_key_state,
            hold_seconds=STOP_HOLD_SECONDS,
            monotonic=lambda: next(times),
        )

        self.assertEqual(
            [False, False, False, False, False, False],
            [hotkey.pressed() for _ in range(6)],
        )
        self.assertEqual([0x50] * 6, queried_keys)

    def test_long_press_triggers_once_per_hold(self):
        # monotonic() is called only when the key is down.
        # calls 1(up), 2(down→t=1.0,_pressed_since=1.0), 3(down→t=1.45), 4(down→t=1.85)
        # call 5(up), 6(down→t=3.1,_pressed_since=3.1), 7(down→t=3.95)
        states = iter([0, 0x8000, 0x8000, 0x8000, 0, 0x8000, 0x8000])
        times = iter([1.0, 1.45, 1.85, 3.1, 3.95])

        hotkey = WindowsPStopHotkey(
            get_key_state=lambda _key: next(states),
            hold_seconds=0.8,
            monotonic=lambda: next(times),
        )

        # call 1: up → False (no monotonic call)
        # call 2: first down, t=1.0 → _pressed_since=1.0, hold>0 → False
        # call 3: still down, t=1.45 → 0.45s < 0.8 → False
        # call 4: still down, t=1.85 → 0.85s >= 0.8 → True (fires, _fired=True)
        # call 5: up → False, resets _fired and _pressed_since
        # call 6: first down again, t=3.1 → _pressed_since=3.1, hold>0 → False
        # call 7: still down, t=3.95 → 0.85s >= 0.8 → True (fires again)
        self.assertEqual(
            [False, False, False, True, False, False, True],
            [hotkey.pressed() for _ in range(7)],
        )


if __name__ == "__main__":
    unittest.main()
