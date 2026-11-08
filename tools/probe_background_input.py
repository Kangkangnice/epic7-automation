"""探针：验证《第七史诗》PC 客户端是否接受「后台鼠标消息 + 移动系统光标」。

## 为什么需要「移动系统光标」这一步

一条龙的后台点击不是只发消息，而是 **SetCursorPos(真实光标) + PostMessage(点击消息)**：

- 只发 `PostMessage(WM_MOUSEMOVE)`：消息进了窗口队列，但**系统光标没动**。
  游戏若每帧用 `GetCursorPos` 轮询光标位置（GLFW 的 `glfwGetCursorPos` 正是这么做的，
  本客户端导入了 `GetCursorPos`/`SetCursorPos`/`RegisterRawInputDevices`），
  它看到的还是旧位置 —— 表现就是「消息发出去了，界面毫无反应」。
- `SetCursorPos` **不需要窗口在前台**，它只移动系统光标、不改变前后台。
  所以「光标挪过去 + 消息投递 + 假装激活」三者齐备，才有后台点击的可能。

## 安全性

1. 必须显式给坐标（--point 画布x,画布y），没有默认危险目标；
2. `--variant hover` 只移动光标 + 发移动消息，**不按下、不松开**，连点击都不算；
3. 结束时一定把光标挪回原位（try/finally），并核对是否挪回；
4. `--require-idle` 检查「最近 1.5 秒用户没碰键鼠」且「两帧画面静止」，否则直接退出；
5. 每次发送前后抓帧存盘，用像素差判定到底生效没有，不靠肉眼；
6. 不抢前台（若游戏自己抢，会被检测并写进报告）。

## 用法（仓库根 D:\\AI\\codex\\auto_game 下）

    # 1) 最安全：只 hover，看游戏有没有 hover 高亮/提示
    python auto_game_unified/tools/probe_background_input.py --point 1093,196 --variant hover --require-idle

    # 2) 三种变体一次跑完（hover / 直接点 / 假装激活再点）
    python auto_game_unified/tools/probe_background_input.py --point 1093,196 --variant all --require-idle

    # 3) 关掉「移动系统光标」，单独看纯 PostMessage 是否被处理
    python auto_game_unified/tools/probe_background_input.py --point 1093,196 --variant hover --no-set-cursor

    # 4) 用户正在玩：有界等待「空闲 + 画面静止」后自动测，多个候选点一次扫完。
    #    无人值守只允许 hover（绝不点击）；等不到就一条消息都不发，安全退出。
    python auto_game_unified/tools/probe_background_input.py --point "1500,90;1093,196;960,1000" --variant hover --require-idle --wait-idle 180

    # 5) 测「后台滚轮」能不能让列表滚动。
    #    这是刷书签 / 骑士团支援列表卡住的那一步：后台拖拽发出去列表纹丝不动。
    #    先把游戏停在可滚动的列表上（例如秘密商店），再点一下别的窗口让游戏退到后台。
    python auto_game_unified/tools/probe_background_input.py --point 900,600 --variant wheel --require-idle
    python auto_game_unified/tools/probe_background_input.py --point 900,600 --variant wheel-activate --require-idle

## 判定口径

hover 只证明「窗口收了消息 + 游戏读了真实光标位置」（按钮高亮 / 提示浮层）。
它**不等于**点击一定生效 —— 点击还要一次「打开一个能原样关掉的页面」的真机复现，
那一步必须用户明确配合，不能无人值守自动做。
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from auto_game_unified.core.pc_window import LEGACY_TOP, Epic7PcWindow  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_ACTIVATE = 0x0006
WA_ACTIVE = 1
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
WM_MOUSEWHEEL = 0x020A
# 向下滚 = 看清列表后面的内容；一次三步，等于玩家拨三格滚轮。
WHEEL_DELTA = -120
WHEEL_STEPS = 3


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def make_lparam(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (kernel32.GetTickCount() - info.dwTime) / 1000.0


def cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def client_origin(hwnd: int) -> tuple[int, int]:
    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def frame_diff(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float(delta.mean()), float((delta.max(axis=2) > 12).mean() * 100.0)


def describe(hwnd: int) -> dict:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    return {
        "hwnd": hwnd,
        "window_rect": [rect.left, rect.top, rect.right, rect.bottom],
        "client_size": [client.right, client.bottom],
        "client_origin_screen": list(client_origin(hwnd)),
        "foreground": user32.GetForegroundWindow() == hwnd,
        "minimized": bool(user32.IsIconic(hwnd)),
        "dpi": int(user32.GetDpiForWindow(hwnd)) if hasattr(user32, "GetDpiForWindow") else None,
        "cursor": list(cursor_pos()),
        "idle_seconds": round(idle_seconds(), 2),
    }


def send(
    hwnd: int,
    client: tuple[int, int],
    variant: str,
    *,
    set_cursor: bool,
) -> list[str]:
    """按变体发送消息，返回实际发出的动作名（便于日志）。"""
    x, y = client
    origin_x, origin_y = client_origin(hwnd)
    lparam = make_lparam(x, y)
    sent: list[str] = []

    if set_cursor:
        user32.SetCursorPos(origin_x + x, origin_y + y)
        sent.append("SetCursorPos")
        time.sleep(0.02)

    if variant == "hover":
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        sent.append("PostMessage(WM_MOUSEMOVE)")
        return sent

    if variant.startswith("wheel"):
        # 滚轮是**纯消息**事件，不需要「按住不放」这个状态 —— 这恰好是拖拽
        # 在后台做不成的原因（见模块顶部）。所以它是后台滚动的首选方案。
        # ⚠️ 两处口径与鼠标移动消息不同：
        #   ① lParam 用**屏幕**坐标，不是客户区坐标；
        #   ② wParam 高 16 位是有符号增量（-120 向下 / +120 向上），低位是键状态。
        if variant == "wheel-activate":
            user32.SendMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
            sent.append("SendMessage(WM_ACTIVATE)")
            time.sleep(0.01)
        screen_lparam = make_lparam(origin_x + x, origin_y + y)
        for _ in range(WHEEL_STEPS):
            user32.PostMessageW(
                hwnd, WM_MOUSEWHEEL, (WHEEL_DELTA & 0xFFFF) << 16, screen_lparam
            )
            sent.append(f"PostMessage(WM_MOUSEWHEEL,{WHEEL_DELTA})")
            time.sleep(0.12)
        return sent

    if variant == "activate":
        user32.SendMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        sent.append("SendMessage(WM_ACTIVATE)")
        time.sleep(0.01)

    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    sent.append("PostMessage(WM_MOUSEMOVE)")
    time.sleep(0.01)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    sent.append("PostMessage(WM_LBUTTONDOWN)")
    time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    sent.append("PostMessage(WM_LBUTTONUP)")
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--point",
        required=True,
        help="画布坐标 x,y（1982x1132 口径）；多个候选点用 ; 分隔，逐个 hover",
    )
    parser.add_argument(
        "--variant",
        default="hover",
        choices=["hover", "click", "activate", "wheel", "wheel-activate", "all"],
        help=(
            "hover=只移动；click=移动+点击；activate=移动+假装激活+点击；"
            "wheel=只发滚轮消息（测列表能不能后台滚）；"
            "wheel-activate=假装激活后发滚轮；all=依次测三种点击"
        ),
    )
    parser.add_argument("--no-set-cursor", action="store_true", help="不移动系统光标，只发消息")
    parser.add_argument("--require-idle", action="store_true", help="用户 1.5 秒内没操作且画面静止才继续")
    parser.add_argument(
        "--wait-idle",
        type=float,
        default=0.0,
        help="有界等待『用户空闲 + 画面静止 + 游戏仍在后台』再开测（秒）；仅允许配合 hover",
    )
    parser.add_argument("--allow-foreground", action="store_true", help="允许游戏在前台时测试（默认拒绝）")
    parser.add_argument("--out", default="", help="输出目录，默认 probe/out")
    args = parser.parse_args()

    try:
        points = [
            (int(x), int(y))
            for x, y in (part.split(",") for part in args.point.split(";"))
        ]
    except ValueError:
        print("--point 格式应为 x,y 或 x1,y1;x2,y2")
        return 2
    for canvas_x, canvas_y in points:
        client_x, client_y = canvas_x, canvas_y - LEGACY_TOP
        if not (0 <= client_x < 1920 and 0 <= client_y < 1080):
            print(f"坐标越界：canvas=({canvas_x},{canvas_y}) → client=({client_x},{client_y})")
            return 2

    # ⚠️ 无人值守时绝不点击：自动等待 + 真实点击会让「用户不在电脑前」时
    # 游戏自己换页面/花资源，这是安全红线，不是保守。
    if args.wait_idle > 0 and args.variant != "hover":
        print("--wait-idle 只允许配合 --variant hover（无人值守绝不点击）")
        return 2
    if len(points) > 1 and args.variant != "hover":
        print("多个候选点只允许配合 --variant hover（一次只在一个点点击）")
        return 2

    window = Epic7PcWindow()
    hwnd = window._find_window()
    if not hwnd:
        print("没找到游戏窗口（标题应为『第七史诗』）")
        return 2

    info_before = describe(hwnd)
    print("窗口状态:", json.dumps(info_before, ensure_ascii=False))
    if info_before["minimized"]:
        print("窗口已最小化：客户区为 0，无法测试后台消息。请先还原窗口。")
        return 2
    if info_before["foreground"] and not args.allow_foreground:
        print("游戏当前在前台 —— 无法区分『消息生效』和『真鼠标生效』。")
        print("请先点一下别的窗口让游戏退到后台，或加 --allow-foreground 强制测（不推荐）。")
        return 2

    if args.wait_idle > 0:
        deadline = time.monotonic() + args.wait_idle
        print(
            f"等待空闲窗口（最多 {args.wait_idle:.0f} 秒）："
            "用户停手 + 画面静止 + 游戏仍在后台"
        )
        while True:
            state = describe(hwnd)
            if (
                state["idle_seconds"] >= 1.5
                and not state["foreground"]
                and not state["minimized"]
            ):
                try:
                    a = window.capture()
                    time.sleep(0.8)
                    b = window.capture()
                except Exception as error:
                    print(f"等待中抓帧失败（继续等）：{error}")
                else:
                    mean_diff, changed = frame_diff(a, b)
                    if mean_diff <= 1.0 and changed <= 2.0:
                        print(
                            f"等到空闲窗口：idle={state['idle_seconds']:.1f}s "
                            f"画面差异={mean_diff:.2f}/{changed:.2f}%"
                        )
                        break
            if time.monotonic() >= deadline:
                print("等待超时：没出现安全的空闲窗口，本次一条消息都没发。")
                return 3
            time.sleep(1.0)

    if args.require_idle:
        if info_before["idle_seconds"] < 1.5 and args.wait_idle <= 0:
            print(f"检测到你 {info_before['idle_seconds']:.1f} 秒前还在操作键鼠，为免误伤已退出。")
            return 2
        a = window.capture()
        time.sleep(0.8)
        b = window.capture()
        mean_diff, changed = frame_diff(a, b)
        if mean_diff > 1.0 or changed > 2.0:
            print(f"画面仍在变化（差异 {mean_diff:.2f}，变动像素 {changed:.2f}%），判定你还在操作，已退出。")
            return 2
        print("空闲检查通过：画面静止。")

    out_dir = (
        Path(args.out)
        if args.out
        else Path(__file__).resolve().parents[1] / "runtime_diagnostics" / "probe_background_input"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    variants = ["hover", "click", "activate"] if args.variant == "all" else [args.variant]
    report: list[dict] = []
    saved_cursor = cursor_pos()

    try:
        for index, (canvas_x, canvas_y) in enumerate(points):
            # 等待期间用户可能把游戏切回前台：那时真鼠标自己就会 hover，
            # 结果会被误读成「后台消息生效」—— 发现就停，宁可没有结论。
            if describe(hwnd)["foreground"] and not args.allow_foreground:
                print("游戏已切到前台，停止验证（避免把真鼠标 hover 当成后台消息生效）")
                break
            client_x, client_y = canvas_x, canvas_y - LEGACY_TOP
            for variant in variants:
                tag = f"{index}_{variant}"
                before = window.capture()
                before_path = out_dir / f"probe_{tag}_before.png"
                cv2.imwrite(str(before_path), cv2.cvtColor(before, cv2.COLOR_RGB2BGR))

                sent = send(
                    hwnd,
                    (client_x, client_y),
                    variant,
                    set_cursor=not args.no_set_cursor,
                )
                time.sleep(0.6)

                after = window.capture()
                after_path = out_dir / f"probe_{tag}_after.png"
                cv2.imwrite(str(after_path), cv2.cvtColor(after, cv2.COLOR_RGB2BGR))

                mean_diff, changed = frame_diff(before, after)
                info_after = describe(hwnd)
                item = {
                    "point_index": index,
                    "variant": variant,
                    "sent": sent,
                    "canvas": [canvas_x, canvas_y],
                    "client": [client_x, client_y],
                    "frame_mean_diff": round(mean_diff, 3),
                    "changed_pixel_percent": round(changed, 2),
                    "changed": mean_diff > 1.0 or changed > 2.0,
                    "foreground_before": info_before["foreground"],
                    "foreground_after": info_after["foreground"],
                    "cursor_moved": info_after["cursor"] != info_before["cursor"],
                    "before": str(before_path),
                    "after": str(after_path),
                }
                report.append(item)
                print(json.dumps(item, ensure_ascii=False))
                if item["changed"]:
                    print("↑ 这一次有画面变化，请在 after 图里确认是不是 hover 高亮")
                time.sleep(0.8)
    finally:
        user32.SetCursorPos(saved_cursor[0], saved_cursor[1])
        restored = cursor_pos()
        print("光标已还原:", restored == saved_cursor, f"(原 {saved_cursor} → 现 {restored})")

    report_path = out_dir / "probe_background_input.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
