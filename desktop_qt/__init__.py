"""Qt / Fluent 版桌面界面（可选入口）。

不在此处直接 import ``app`` —— 那样会在没装 PySide6 的环境里把整个包拖崩。
真正启动时才由 ``__main__`` / ``main()`` 延迟导入。
"""

from __future__ import annotations


def main() -> int:
    from auto_game_unified.desktop_qt.app import main as _main

    return _main()
