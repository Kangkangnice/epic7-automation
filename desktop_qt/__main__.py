"""``python -m auto_game_unified.desktop_qt`` 的入口。

依赖缺失时给一句能直接照做的提示，而不是甩一段 ImportError traceback。
"""

from __future__ import annotations

try:
    from auto_game_unified.desktop_qt.app import main
except ImportError as error:
    raise SystemExit(
        "界面依赖不完整，需先执行：\n"
        "  python -m pip install -r auto_game_unified\\requirements.txt\n"
        f"原始错误：{error}"
    ) from error


if __name__ == "__main__":
    raise SystemExit(main())
