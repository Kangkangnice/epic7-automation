"""打包入口：只做两件事 —— 能自检、能启动桌面界面。

打包版是 ``console=False``（不给用户弹黑窗），所以自检结果不能只靠 ``print``：
它同时写进 ``<运行产物根>/runtime_logs/self_check.txt``，并用退出码表示成败。
``packaging/build.py`` 打完包就靠这两样东西做冒烟验证。

用法::

    Epic7AutoAssistant.exe --self-check
"""

from __future__ import annotations

import sys
from pathlib import Path

# 源码直接跑 ``python packaging/entry.py`` 时，工作区还没进 sys.path。
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _self_check() -> int:
    from auto_game_unified.core.data_paths import data_root
    from auto_game_unified.desktop.app import TEMPLATE_ROOT
    from auto_game_unified.desktop.catalog import PRODUCT_NAME, PRODUCT_VERSION, ROUTES
    from auto_game_unified.desktop.preflight import validate_route_templates

    lines: list[str] = []
    failures = 0

    def record(passed: bool, title: str, detail: str) -> None:
        nonlocal failures
        if not passed:
            failures += 1
        lines.append(f"[{'通过' if passed else '失败'}] {title}：{detail}")

    header = f"{PRODUCT_NAME} {PRODUCT_VERSION} 自检"
    lines.append(header)
    lines.append(f"Python {sys.version.split()[0]}  frozen={bool(getattr(sys, 'frozen', False))}")
    lines.append(f"程序目录 {Path(sys.executable).parent}")

    root = data_root()
    try:
        (root / "runtime_logs").mkdir(parents=True, exist_ok=True)
        probe = root / "runtime_logs" / ".self_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record(True, "运行产物目录可写", str(root))
    except OSError as error:
        record(False, "运行产物目录可写", f"{root}：{error}")

    if TEMPLATE_ROOT.is_dir():
        count = len(list(TEMPLATE_ROOT.rglob("*.png")))
        record(count > 0, "模板目录", f"{TEMPLATE_ROOT}（{count} 张）")
    else:
        record(False, "模板目录", f"不存在：{TEMPLATE_ROOT}")

    broken: list[str] = []
    for route in ROUTES:
        try:
            validate_route_templates(route.mode, TEMPLATE_ROOT)
        except Exception as error:  # noqa: BLE001 —— 报清是哪条路线加载不了
            broken.append(f"{route.label}：{error}")
    record(
        not broken,
        "路线模板加载",
        f"{len(ROUTES)} 条全部可加载" if not broken else "；".join(broken),
    )

    lines.append(f"结果：{'通过' if failures == 0 else f'{failures} 项失败'}")
    report = "\n".join(lines) + "\n"
    try:
        (root / "runtime_logs" / "self_check.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    print(report, flush=True)
    return 0 if failures == 0 else 1


def main() -> int:
    if "--self-check" in sys.argv[1:]:
        return _self_check()

    from auto_game_unified.desktop.app import main as run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
