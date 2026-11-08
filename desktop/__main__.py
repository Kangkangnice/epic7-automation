"""``python -m auto_game_unified.desktop`` 的入口。

默认仍是原来的 Tk 界面（一个字节都没动）。想试 Qt / Fluent 外观时设
``EPIC7_UI=qt``（或直接 ``python -m auto_game_unified.desktop_qt``）。

这样切外观不动任何业务代码，也不影响打包里的默认行为 —— 等 Qt 版对齐完
使用须知 / 更新检查 / 打包配置之后，再把默认值切过来。
"""

from __future__ import annotations

import os

if os.environ.get("EPIC7_UI", "").lower() == "qt":
    try:
        from auto_game_unified.desktop_qt.app import main
    except ImportError as error:
        raise SystemExit(
            "EPIC7_UI=qt 需要 PySide6 与 PySide6-Fluent-Widgets。请先执行：\n"
            "  python -m pip install -r auto_game_unified\\requirements-qt.txt\n"
            f"原始错误：{error}"
        ) from error
else:
    from auto_game_unified.desktop.app import main


if __name__ == "__main__":
    raise SystemExit(main())
