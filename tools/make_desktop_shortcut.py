"""在桌面生成「第七史诗自动助手」的无窗口启动图标。

## 为什么需要这个脚本

助手是 Tkinter 图形程序，但用 ``python.exe`` 启动会自带一个**控制台黑窗**，
而黑窗和程序是绑定的：关掉黑窗，Windows 会连带把助手一起结束掉
（用户实机反馈就是「一关终端，助手就没了」）。

日常使用应该走 ``desktop/launch_hidden.py`` + ``pythonw.exe``：**不创建任何窗口**。
桌面图标指的正是这个组合。图标本身是机器本地的东西、不进仓库，
所以把「怎么建」也留在仓库里，桌面重置或换机器时可以一键重建。

## 用法

```
python auto_game_unified\\tools\\make_desktop_shortcut.py            # 建/覆盖桌面图标
python auto_game_unified\\tools\\make_desktop_shortcut.py --dir D:\\desktop
python auto_game_unified\\tools\\make_desktop_shortcut.py --name 第七史诗助手
python auto_game_unified\\tools\\make_desktop_shortcut.py --icon D:\\某程序.exe,0
python auto_game_unified\\tools\\make_desktop_shortcut.py --remove   # 只删图标
```

默认解释器取 ``sys.executable`` 同目录下的 ``pythonw.exe``（即跑本脚本的那个环境），
所以别用别的 Python 跑它。需要 ``pywin32``（Anaconda 自带）。

**图标**：不指定时会优先用**游戏本体** ``EpicSeven.exe`` 的图标（存在就用，见
``GAME_ICON``）；用 Python 自带图标太丑，用户明确反馈过。想换就传 ``--icon 路径[,序号]``。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parents[1]
LAUNCHER = PACKAGE_DIR / "desktop" / "launch_hidden.py"
WORKSPACE = PACKAGE_DIR.parent
DEFAULT_NAME = "第七史诗助手"
DESCRIPTION = "第七史诗自动助手（无终端窗口启动）"

# 游戏本体的可执行文件。用它当图标是因为「第七史诗」这个图标用户一眼就认得，
# 而 Python 自带的图标太丑（用户 2026-09-23 明确反馈）。
GAME_ICON = Path(r"D:\AppData\Games\EpicSeven\EpicSeven.exe")


def desktop_dir() -> Path:
    """读注册表拿**真实**桌面路径（可能被重定向，例如 ``D:\\desktop``）。"""
    import winreg

    key = (
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    )
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
        raw, _ = winreg.QueryValueEx(handle, "Desktop")
    return Path(str(raw)).expanduser()


def pythonw_beside(executable: Path) -> Path:
    """取与当前解释器同目录的 ``pythonw.exe``（同环境，不会串版本）。"""
    return executable.with_name("pythonw.exe")


def pick_icon(requested: str | None) -> str:
    """决定图标：``--icon`` > 游戏本体 > 目标程序自带。"""
    if requested:
        return requested
    if GAME_ICON.exists():
        return f"{GAME_ICON},0"
    return ""  # 空串 = 用目标程序自带的图标


def build(link_path: Path, arguments: str, working_dir: Path, icon: str) -> Path:
    """创建（或覆盖）快捷方式，返回 ``.lnk`` 路径。

    ``link_path`` 是 ``.lnk`` 文件本身的位置，真正的启动目标写在 ``TargetPath`` 里 ——
    两者别搞混。
    """
    import win32com.client  # 延迟导入：只在真要建图标时才需要 pywin32

    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortCut(str(link_path))
    link.TargetPath = str(pythonw_beside(Path(sys.executable)).resolve())
    link.Arguments = arguments
    link.WorkingDirectory = str(working_dir)
    link.Description = DESCRIPTION
    link.WindowStyle = 1
    link.IconLocation = icon
    link.save()
    return link_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=None, help="图标放哪个目录")
    parser.add_argument("--name", default=DEFAULT_NAME, help="图标显示名")
    parser.add_argument(
        "--icon",
        default=None,
        help="图标来源，形如 路径.exe[,序号]；不传则优先用游戏本体图标",
    )
    parser.add_argument("--remove", action="store_true", help="只删图标")
    args = parser.parse_args(argv)

    folder = args.dir or desktop_dir()
    link_path = folder / f"{args.name}.lnk"

    if args.remove:
        if link_path.exists():
            link_path.unlink()
            print(f"已删除 {link_path}")
        else:
            print(f"本来就不存在：{link_path}")
        return 0

    if not folder.is_dir():
        print(f"目录不存在：{folder}")
        return 1
    if not LAUNCHER.is_file():
        print(f"找不到无窗口启动入口：{LAUNCHER}")
        return 1
    pythonw = pythonw_beside(Path(sys.executable))
    if not pythonw.exists():
        print(f"找不到 pythonw.exe：{pythonw}（它和 python.exe 同目录，正常都在一起）")
        return 1

    icon = pick_icon(args.icon)
    build(link_path, f'"{LAUNCHER}"', WORKSPACE, icon)
    print(f"已创建 {link_path}")
    print(f"  目标：{pythonw}")
    print(f"  参数：\"{LAUNCHER}\"")
    print(f"  起始位置：{WORKSPACE}")
    print(f"  图标：{icon or '（目标程序自带）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
