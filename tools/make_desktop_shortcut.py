"""在桌面生成「第七史诗自动助手」的无窗口启动图标。

## 为什么需要这个脚本

助手是 Qt 图形程序，但用 ``python.exe`` 启动会自带一个**控制台黑窗**，
而黑窗和程序是绑定的：关掉黑窗，Windows 会连带把助手一起结束掉
（用户实机反馈就是「一关终端，助手就没了」）。

日常使用应该走 ``desktop_qt/launch.py`` + ``pythonw.exe``：**不创建任何窗口**。
桌面图标指的正是这个组合。图标本身是机器本地的东西、不进仓库，
所以把「怎么建」也留在仓库里，桌面重置或换机器时可以一键重建。

## 用法

```
python auto_game_unified\\tools\\make_desktop_shortcut.py            # 建/覆盖桌面图标
python auto_game_unified\\tools\\make_desktop_shortcut.py --dir D:\\desktop
python auto_game_unified\\tools\\make_desktop_shortcut.py --name 第七史诗助手
python auto_game_unified\\tools\\make_desktop_shortcut.py --icon D:\\某程序.exe,0
python auto_game_unified\\tools\\make_desktop_shortcut.py --no-admin   # 不要提权
python auto_game_unified\\tools\\make_desktop_shortcut.py --python D:\\AI\\codex\\auto_game\\.venv\\Scripts\\python.exe
python auto_game_unified\\tools\\make_desktop_shortcut.py --remove   # 只删图标
```

默认解释器取 ``sys.executable`` 同目录下的 ``pythonw.exe``（即跑本脚本的那个环境），
所以别用别的 Python 跑它。需要 ``pywin32``（Anaconda 自带）。

⚠️ 这个环境**必须装好** ``requirements.txt``（含 PySide6）。用一个没装 Qt 的
Python 跑这里，建出来的图标双击会直接报 ModuleNotFoundError。
想「用 A 环境的 pywin32 建图标、但让图标跑 B 环境」就传 ``--python B\\python.exe``
（2026-11-09 起桌面图标指向工作区的正式 ``.venv``，不再依赖临时测量环境）。

**图标**：不指定时会优先用**游戏本体** ``EpicSeven.exe`` 的图标（存在就用，见
``GAME_ICON``）；用 Python 自带图标太丑，用户明确反馈过。想换就传 ``--icon 路径[,序号]``。

**管理员**：默认勾上「以管理员身份运行」，因为 PC 客户端和游戏本体都以管理员运行，
助手不提权就会被 UIPI 拦掉 ``SendInput``（详见项目记忆「PC 客户端」一节）。
不想要就传 ``--no-admin``。⚠️ 这个开关**不在** ``WScript.Shell`` 的接口里，
只能建完之后直接改 ``.lnk`` 文件的字节，见 ``set_run_as_admin()``。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parents[1]
LAUNCHER = PACKAGE_DIR / "desktop_qt" / "launch.py"
WORKSPACE = PACKAGE_DIR.parent
DEFAULT_NAME = "第七史诗助手"
DESCRIPTION = "第七史诗自动助手（无终端窗口启动）"

# 助手自己的图标（深色金边放大镜）。**放在仓库里**，不再引用别的项目目录 ——
# 2026-11-09 之前桌面图标指向 `similar_auto_project/qt_ui/preview.ico`，
# 那个目录一删图标就变白板。
APP_ICON = PACKAGE_DIR / "desktop_qt" / "app.ico"

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
    """决定图标：``--icon`` > 仓库里的 ``app.ico`` > 游戏本体 > 目标程序自带。

    助手图标优先于游戏图标：两个图标长得一样，用户就分不清点哪个（2026-11-09
    去掉「新外观（预览）」后缀之后，剩下的只有这一个图标，更要能一眼认出来）。
    """
    if requested:
        return requested
    if APP_ICON.exists():
        return str(APP_ICON)
    if GAME_ICON.exists():
        return f"{GAME_ICON},0"
    return ""  # 空串 = 用目标程序自带的图标


# `.lnk` 里「以管理员身份运行」的开关位置。
#
# ⚠️ 它**不在** ``WScript.Shell`` 的接口里，只能落到文件字节上：
# ``ShellLinkHeader`` 的 ``LinkFlags`` 是偏移 0x14 起的 4 字节，``0x15`` 是它的
# 第二个字节，掩码 **0x20** 置位 = 需要提权。
# （2026-09-23 我把掩码写成 0x40，于是把「本来就是管理员」的旧图标误判成「不是」，
# 还顺手改错了一条本来对的笔记 —— 别再动这个数。）
ADMIN_FLAG_OFFSET = 0x15
ADMIN_FLAG_MASK = 0x20


def set_run_as_admin(link_path: Path, enabled: bool) -> None:
    """改写 ``.lnk`` 里「以管理员身份运行」那一位。

    必须在 ``link.save()`` **之后**调用：``save()`` 是 ``WScript.Shell`` 写的，
    它不认识这一位，先改会被覆盖掉。
    """
    data = bytearray(link_path.read_bytes())
    if enabled:
        data[ADMIN_FLAG_OFFSET] |= ADMIN_FLAG_MASK
    else:
        data[ADMIN_FLAG_OFFSET] &= ~ADMIN_FLAG_MASK
    link_path.write_bytes(bytes(data))


def build(
    link_path: Path,
    *,
    pythonw: Path,
    launcher: Path,
    working_dir: Path,
    icon: str,
    admin: bool,
) -> Path:
    """创建（或覆盖）快捷方式，返回 ``.lnk`` 路径。

    ``link_path`` 是 ``.lnk`` 文件本身的位置，真正的启动目标写在 ``TargetPath`` 里 ——
    两者别搞混。
    """
    import win32com.client  # 延迟导入：只在真要建图标时才需要 pywin32

    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortCut(str(link_path))
    link.TargetPath = str(pythonw.resolve())
    link.Arguments = f'"{launcher}"'
    link.WorkingDirectory = str(working_dir)
    link.Description = DESCRIPTION
    link.WindowStyle = 1
    link.IconLocation = icon
    link.save()
    set_run_as_admin(link_path, admin)
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
    parser.add_argument(
        "--no-admin",
        dest="admin",
        action="store_false",
        help="不勾「以管理员身份运行」（默认勾上：PC 客户端要求提权）",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="用哪个解释器跑助手（默认=跑本脚本的这个）。指到别的环境时，"
        "那个环境必须已经装好 requirements.txt —— 否则图标双击会报 ModuleNotFoundError。",
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
    interpreter = Path(args.python) if args.python else Path(sys.executable)
    pythonw = pythonw_beside(interpreter)
    if not pythonw.exists():
        print(f"找不到 pythonw.exe：{pythonw}（它和 python.exe 同目录，正常都在一起）")
        return 1

    icon = pick_icon(args.icon)
    build(
        link_path,
        pythonw=pythonw,
        launcher=LAUNCHER,
        working_dir=WORKSPACE,
        icon=icon,
        admin=args.admin,
    )
    print(f"已创建 {link_path}")
    print(f"  目标：{pythonw}")
    print(f"  参数：\"{LAUNCHER}\"")
    print(f"  起始位置：{WORKSPACE}")
    print(f"  图标：{icon or '（目标程序自带）'}")
    print(f"  以管理员身份运行：{'是' if args.admin else '否'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
