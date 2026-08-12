import unittest

from auto_game_unified.core.hotkey import WindowsPStopHotkey


class WindowsPStopHotkeyTests(unittest.TestCase):
    def test_pressed_only_on_each_up_to_down_edge(self):
        states = iter([0, 0x8000, 0x8000, 0, 0x8000])
        queried_keys: list[int] = []

        def get_key_state(key: int) -> int:
            queried_keys.append(key)
            return next(states)

        hotkey = WindowsPStopHotkey(get_key_state=get_key_state)

        self.assertEqual(
            [False, True, False, False, True],
            [hotkey.pressed() for _ in range(5)],
        )
        self.assertEqual([0x50] * 5, queried_keys)


if __name__ == "__main__":
    unittest.main()
