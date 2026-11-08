"""在桌面建一个「新外观（Qt / Fluent 预览）」快捷方式，**不动老图标**。

老图标 ``第七史诗自动助手.lnk`` 指向 ``desktop/launch_hidden.py``（写死 Tk）；
这个脚本新建的是另一个名字、另一个目标、另一个 pythonw，两者互不干扰。

新图标默认用 ``similar_auto_project/qt_ui/preview.ico``（深色金边 Q），
和老图标（游戏本体 EpicSeven.exe 的图标）一眼可分 —— 两个图标长得一样，
用户会问「到底点哪个」。preview.ico 不存在时才退回游戏图标。

## 用法（用带 pywin32 的解释器跑，例如 D:\\anaconda\\python.exe）

    python auto_game_unified\\tools\\make_qt_preview_shortcut.py
    python auto_game_unified\\tools\\make_qt_preview_shortcut.py --dir D:\\desktop
    python auto_game_unified\\tools\\make_qt_preview_shortcut.py --admin --force
    python auto_game_unified\\tools\\make_qt_preview_shortcut.py --icon D:\\某图标.ico
    python auto_game_unified\\tools\\make_qt_preview_shortcut.py --remove

⚠️ 默认**不覆盖同名文件**：桌面上已经有同名 .lnk 时会直接退出，要覆盖加 --force。
⚠️ 默认**不提权**：这套界面此刻主要用来看外观、不点击游戏；
   若想在新界面里真跑 PC 客户端任务，加 --admin（UIPI 会拦掉不提权的 SendInput），
   并且需要 --force 覆盖已有图标。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = PACKAGE_DIR.parent
LAUNCHER = PACKAGE_DIR / "desktop_qt" / "launch.py"

# 隔离环境：PySide6 + qfluentwidgets + 项目依赖都齐，且不污染用户的 anaconda。
DEFAULT_PYTHONW = (
    WORKSPACE
    / "similar_auto_project"
    / ".qt_measure"
    / "venv"
    / "Scripts"
    / "pythonw.exe"
)
DEFAULT_DIR = Path(r"D:\desktop\游戏")
DEFAULT_NAME = "第七史诗助手 · 新外观（预览）"
DESCRIPTION = "第七史诗自动助手 · Qt / Fluent 预览界面（无终端窗口启动）"
GAME_ICON = Path(r"D:\AppData\Games\EpicSeven\EpicSeven.exe")
PREVIEW_ICON = WORKSPACE / "similar_auto_project" / "qt_ui" / "preview.ico"

# `.lnk` 的「以管理员身份运行」位（与 make_desktop_shortcut.py 同一套口径）。
ADMIN_FLAG_OFFSET = 0x15
ADMIN_FLAG_MASK = 0x20


def set_run_as_admin(link_path: Path, enabled: bool) -> None:
    data = bytearray(link_path.read_bytes())
    if enabled:
        data[ADMIN_FLAG_OFFSET] |= ADMIN_FLAG_MASK
    else:
        data[ADMIN_FLAG_OFFSET] &= ~ADMIN_FLAG_MASK
    link_path.write_bytes(bytes(data))


def pick_icon(requested: str | None) -> str:
    """图标优先级：命令行 --icon > 预览专属图标 > 游戏本体 > 目标程序自带。"""
    if requested:
        return requested
    if PREVIEW_ICON.exists():
        return str(PREVIEW_ICON)
    if GAME_ICON.exists():
        return f"{GAME_ICON},0"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--pythonw", type=Path, default=DEFAULT_PYTHONW)
    parser.add_argument("--icon", default=None, help="图标来源，形如 路径.ico 或 路径.exe,序号")
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--force", action="store_true", help="允许覆盖同名 .lnk")
    parser.add_argument("--remove", action="store_true", help="只删这个预览图标")
    args = parser.parse_args()

    link_path = args.dir / f"{args.name}.lnk"
    if args.remove:
        if link_path.exists():
            link_path.unlink()
            print(f"已删除：{link_path}")
        else:
            print(f"本来就不存在：{link_path}")
        return 0

    if not args.pythonw.exists():
        print(f"找不到目标解释器：{args.pythonw}")
        print("请先确认隔离环境还在，或用 --pythonw 指定一个装了 PySide6 的 pythonw.exe")
        return 2
    if not LAUNCHER.exists():
        print(f"找不到启动脚本：{LAUNCHER}")
        return 2
    if link_path.exists() and not args.force:
        print(f"同名快捷方式已存在，未改动：{link_path}")
        print("要覆盖请加 --force；要删除请加 --remove")
        return 1

    import win32com.client  # 延迟导入：只有真要建图标时才需要 pywin32

    icon = pick_icon(args.icon)
    args.dir.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortCut(str(link_path))
    link.TargetPath = str(args.pythonw.resolve())
    link.Arguments = f'"{LAUNCHER.resolve()}"'
    link.WorkingDirectory = str(WORKSPACE)
    link.Description = DESCRIPTION
    link.WindowStyle = 1
    link.IconLocation = icon
    link.save()
    set_run_as_admin(link_path, args.admin)

    print(f"已创建：{link_path}")
    print(f"  目标：{args.pythonw.resolve()}")
    print(f"  参数：{link.Arguments}")
    print(f"  工作目录：{WORKSPACE}")
    print(f"  图标：{icon or '（目标程序自带）'}")
    print(f"  以管理员运行：{'是' if args.admin else '否'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
