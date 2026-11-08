"""无控制台启动 Qt / Fluent 预览界面 —— 「新外观」快捷方式走这里。

## 为什么不复用 desktop/launch_hidden.py

那个文件里写死 ``from auto_game_unified.desktop.app import main``，
是老 Tk 界面的专属入口；``desktop/__main__.py`` 里的 ``EPIC7_UI=qt`` 分支
它根本不走。改它会动到用户每天都在点的那个图标 —— 不值得。
所以新外观单独一个入口，两个图标互不干扰。

## 为什么要自己重定向标准流

``pythonw.exe`` 下 ``sys.stdout`` / ``sys.stderr`` 可能是 ``None``，
而 qfluentwidgets 导入期就会往 stdout 打一行提示、Qt 平台插件出错会往
stderr 写。不先接管，双击就是「什么都没发生」，连错在哪都查不到。
和老入口同一个规矩：**重定向必须发生在 import 界面之前**。
"""

from __future__ import annotations

from pathlib import Path
import sys
import traceback

PACKAGE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = PACKAGE_DIR.parent

if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))


def _default_log_path() -> Path:
    from auto_game_unified.core.data_paths import data_root

    return data_root() / "runtime_logs" / "desktop_qt_launch.log"


LOG_PATH = _default_log_path()
_MAX_LOG_BYTES = 1 * 1024 * 1024


def _open_log():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > _MAX_LOG_BYTES:
        LOG_PATH.replace(LOG_PATH.with_suffix(LOG_PATH.suffix + ".1"))
    return LOG_PATH.open("a", encoding="utf-8", errors="replace")


def main() -> int:
    log = _open_log()
    sys.stdout = log
    sys.stderr = log
    print("=== Qt 界面启动 ===", flush=True)
    try:
        from auto_game_unified.desktop_qt.app import main as run_app
    except BaseException:
        traceback.print_exc()
        log.flush()
        return 1
    try:
        return run_app()
    except BaseException:
        # 无窗口启动时没人看得到，必须落进日志，否则故障就是「双击没反应」。
        traceback.print_exc()
        return 1
    finally:
        log.flush()


if __name__ == "__main__":
    raise SystemExit(main())
