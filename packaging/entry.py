"""打包入口：自检、工作进程、桌面界面三条路。

打包版是 ``console=False``（不给用户弹黑窗），所以自检结果不能只靠 ``print``：
它同时写进 ``<运行产物根>/runtime_logs/self_check.txt``，并用退出码表示成败。
``packaging/build.py`` 打完包就靠这两样东西做冒烟验证。

⚠️ 桌面端跑每日任务时，父进程会把**同一个 exe** 加上 ``--worker`` 再启动一次
（``desktop/worker.py``）：冻结后没有独立的 ``python.exe``，不加这个分支就会把
业务参数送进界面，弹出第二个窗口。``--worker`` 必须放在参数最前面。

用法::

    ArkyAssistant.exe --self-check
    ArkyAssistant.exe --worker --daily --daily-tasks arena:1 ...
    ArkyAssistant.exe
"""

from __future__ import annotations

import sys
from pathlib import Path

# 源码直接跑 ``python packaging/entry.py`` 时，工作区还没进 sys.path。
# parents[2] 才是工作区（entry.py -> packaging -> auto_game_unified -> 工作区）；
# 早期写成 parents[1] 塞进去的是包目录，直跑自检会报
# 「No module named 'auto_game_unified'」，打包后 frozen 分支不走所以一直没暴露。
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _self_check() -> int:
    from auto_game_unified.core.data_paths import data_root, package_root
    from auto_game_unified.desktop.catalog import PRODUCT_NAME, PRODUCT_VERSION, ROUTES
    from auto_game_unified.desktop.preflight import (
        template_root_for_backend,
        validate_route_templates,
    )
    from auto_game_unified.games.epic7.modes import PC_ONLY_ROUTES

    # ⚠️ 这里**不许** import 界面模块来借一个常量：界面已经换成 Qt，导入它会
    # 把 PySide6 一起拉起来（慢，而且自检失败时会淹没真正的原因）。
    # 模板根就是包目录下的固定位置，和 desktop_qt/app.py 里的 TEMPLATE_ROOT 同一个算法。
    TEMPLATE_ROOT = package_root() / "games" / "epic7" / "templates"

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

    # ⚠️ 数据根与模板根是**两个**目录，别复用同一个变量名：以前循环里用
    # ``root = template_root_for_backend(...)`` 覆盖了数据根，报告就写进模板目录
    # （那个 ``runtime_logs`` 不存在），OSError 又被吞掉，于是「自检通过、
    # 报告没有」——``packaging/build.py`` 的冒烟正好去数据目录取报告，必然取不到。
    data_dir = data_root()
    try:
        (data_dir / "runtime_logs").mkdir(parents=True, exist_ok=True)
        probe = data_dir / "runtime_logs" / ".self_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record(True, "运行产物目录可写", str(data_dir))
    except OSError as error:
        record(False, "运行产物目录可写", f"{data_dir}：{error}")

    if TEMPLATE_ROOT.is_dir():
        count = len(list(TEMPLATE_ROOT.rglob("*.png")))
        record(count > 0, "模板目录", f"{TEMPLATE_ROOT}（{count} 张）")
    else:
        record(False, "模板目录", f"不存在：{TEMPLATE_ROOT}")

    broken: list[str] = []
    for route in ROUTES:
        # 两个后端都要能装配模板；PC 专属路线本来就只有 PC 素材，模拟器下不查，
        # 否则会把「设计上就跑不了」误报成产物缺图。
        backends = ("pc",) if route.mode in PC_ONLY_ROUTES else ("emulator", "pc")
        for backend in backends:
            template_dir = template_root_for_backend(TEMPLATE_ROOT, backend)
            try:
                validate_route_templates(route.mode, template_dir)
            except Exception as error:  # noqa: BLE001 —— 报清是哪条路线加载不了
                broken.append(f"{route.label}[{backend}]：{error}")
    record(
        not broken,
        "路线模板加载",
        f"{len(ROUTES)} 条全部可加载" if not broken else "；".join(broken),
    )

    def render(fail_count: int) -> str:
        return "\n".join(
            lines + [f"结果：{'通过' if fail_count == 0 else f'{fail_count} 项失败'}"]
        ) + "\n"

    report = render(failures)
    report_path = data_dir / "runtime_logs" / "self_check.txt"
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
    except OSError as error:
        # 报告写不进去就是**没通过**：调用方（构建冒烟、排障的人）只认这个文件，
        # 静默跳过等于把「没留下证据」当成「一切正常」。
        failures += 1
        lines.append(f"[失败] 自检报告写入：{report_path}：{error}")
        print(render(failures), flush=True)
        return 1
    print(report, flush=True)
    return 0 if failures == 0 else 1


def _use_utf8_stdio() -> None:
    """冻结版窗口程序不认 ``PYTHONIOENCODING``，输出按系统代码页编码。

    桌面端按 UTF-8 读子进程输出（``desktop/worker.py``），不统一就会整屏乱码；
    所以冻结时先把标准输出重设为 UTF-8。源码模式下终端自己决定编码，不动它。
    """
    if not getattr(sys, "frozen", False):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main() -> int:
    argv = sys.argv[1:]
    _use_utf8_stdio()
    if "--self-check" in argv:
        return _self_check()
    # 只认第一个参数：业务参数是界面生成的固定形状，不会把 --worker 塞到后面，
    # 这样也避免把将来的路线参数误当成分流开关删掉。
    if argv[:1] == ["--worker"]:
        from auto_game_unified.main import main as run_cli

        return run_cli(argv[1:])

    from auto_game_unified.desktop_qt.app import main as run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
