import ctypes
import os
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pc_window import Epic7PcWindow, _is_process_elevated


def foreground_details(window: Epic7PcWindow) -> str:
    hwnd = window._user32.GetForegroundWindow()
    title_len = window._user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(title_len + 1)
    window._user32.GetWindowTextW(hwnd, title, title_len + 1)
    pid = ctypes.c_ulong()
    window._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return f"foreground={hwnd} pid={pid.value} title={title.value!r}"


status = ROOT / "runtime_logs" / "pc_activation_diagnostic.txt"
window = Epic7PcWindow()
try:
    game = window._find_window()
    lines = [
        f"self_pid={os.getpid()} elevated={_is_process_elevated(os.getpid())}",
        f"game_hwnd={game}",
        foreground_details(window),
    ]
    try:
        activated = window.activate()
        lines.append(f"activate=ok hwnd={activated}")
    except Exception as error:
        lines.append(f"activate=error {type(error).__name__}: {error}")
    lines.append(foreground_details(window))
    status.write_text("\n".join(lines) + "\n", encoding="utf-8")
except Exception:
    status.write_text(traceback.format_exc(), encoding="utf-8")
    raise
