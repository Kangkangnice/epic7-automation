"""无控制台地启动桌面助手 —— 桌面图标/快捷方式走的就是这里。

## 为什么要单独一个入口

Windows 上 Python 有两个解释器：

- ``python.exe``：**自带控制台窗口**（那个黑窗），从终端、脚本、快捷方式启动都会先弹一个；
- ``pythonw.exe``：**不创建任何窗口**，专门给图形界面程序用。

助手是 Tkinter 图形程序，``desktop/`` 包里**没有任何** ``print`` / ``sys.stdout`` /
``sys.stderr`` 用法，所以那个黑窗纯属多余。更麻烦的是黑窗和程序是**绑定**的：
用户关掉黑窗，Windows 会把助手一起结束掉 —— 实机反馈就是「一关终端，助手就没了」。

## 这个文件干的三件事

1. **先**把 ``stdout`` / ``stderr`` 接到 ``runtime_logs/desktop_launch.log``。
   双击启动时 ``sys.stdout`` 可能是 ``None``，任何一处不小心往里写都会直接抛异常，
   所以这一步必须发生在**导入助手之前**。
2. 把工作区根放进 ``sys.path``。
3. 调 ``desktop.app.main()``。

⚠️ 别把 ``from auto_game_unified.desktop.app import main`` 提到模块顶层 ——
那就把「重定向标准流」和「导入助手」的顺序反过来了（有些库在导入期就会写日志）。

## 怎么用

- 桌面图标（推荐）：目标 ``D:\\anaconda\\pythonw.exe``，参数就是这个文件；
- 命令行：``D:\\anaconda\\pythonw.exe auto_game_unified\\desktop\\launch_hidden.py``
- **原来的启动方式照旧可用**：``python -u -m auto_game_unified.desktop``
  —— 终端里能看到报错，调试时用这个。
"""

from __future__ import annotations

from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = PACKAGE_DIR.parent
LOG_PATH = PACKAGE_DIR / "runtime_logs" / "desktop_launch.log"

# 这个日志只用来兜住「启动就失败」这种看不到的情况，不需要留历史，超过就滚动一份。
_MAX_LOG_BYTES = 1 * 1024 * 1024


def _open_log():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > _MAX_LOG_BYTES:
        LOG_PATH.replace(LOG_PATH.with_suffix(LOG_PATH.suffix + ".1"))
    return LOG_PATH.open("a", encoding="utf-8", errors="replace")


def main() -> int:
    """重定向标准流后启动助手，返回它的退出码。"""
    log = _open_log()
    sys.stdout = log
    sys.stderr = log
    if str(WORKSPACE) not in sys.path:
        sys.path.insert(0, str(WORKSPACE))

    from auto_game_unified.desktop.app import main as run_app

    try:
        return run_app()
    except BaseException:
        # 无窗口启动时这里没人看得到，必须落进日志，否则故障就是「双击没反应」。
        import traceback

        traceback.print_exc()
        return 1
    finally:
        log.flush()


if __name__ == "__main__":
    raise SystemExit(main())
