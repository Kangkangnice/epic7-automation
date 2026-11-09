"""``python -m auto_game_unified.desktop``：启动桌面界面。

⚠️ 2026-11-09 起**只有一套界面**（Qt / Fluent，`desktop_qt/`）。原来的 Tk 界面、
`EPIC7_UI=qt` 这个环境变量开关、以及老的无窗口启动器都已删除 —— 留着它们等于
留两条没人走的岔路，改一次界面就要在两边各确认一遍。

本模块只负责「把包路径挂上去然后转发」，界面本体在 `desktop_qt.app`。
"""

from __future__ import annotations

from auto_game_unified.desktop_qt.app import main

if __name__ == "__main__":
    raise SystemExit(main())
