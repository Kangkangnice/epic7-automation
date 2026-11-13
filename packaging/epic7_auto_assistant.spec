# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 目录版（onedir）打包配置。

用法（由 ``packaging/build.py`` 调用）::

    python -m PyInstaller --noconfirm --clean packaging/epic7_auto_assistant.spec

为什么是 onedir 而不是 onefile：onefile 每次启动都要把几十兆解压到临时目录，
首次启动慢、杀毒软件更容易拦，模板路径也多一层临时目录的不确定性。
体积代价换来的是「双击就能开」，这一档不值得省。

⚠️ 模板必须落在 ``auto_game_unified/games/epic7/templates``：
``desktop_qt/app.py`` 的 ``TEMPLATE_ROOT`` 由 ``__file__`` 往上两级算出来，
打包后 ``__file__`` 在 ``_internal/auto_game_unified/desktop_qt/app.py``，
往上两级正好是 ``_internal/auto_game_unified``。改这里的 dest 之前先算一遍。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO = Path(SPECPATH).resolve().parent
WORKSPACE = REPO.parent

# ⚠️ Qt / Fluent 界面（2026-11-09 起是**唯一**界面）自带一套字体图标与样式资源，
# PyInstaller 不会自动收进包 —— 少了它们的表现是「窗口能开，但所有图标都是空白」。
_QFLUENT_DATAS = collect_data_files("qfluentwidgets")
_QFLUENT_MODULES = collect_submodules("qfluentwidgets")

a = Analysis(
    [str(REPO / "packaging" / "entry.py")],
    pathex=[str(WORKSPACE)],
    binaries=[],
    datas=[
        (
            str(REPO / "games" / "epic7" / "templates"),
            "auto_game_unified/games/epic7/templates",
        ),
        # 次元探查：第三方 chaos 源码、配置与模板整包原样随助手分发。
        (str(WORKSPACE / "vendor" / "e7auto"), "vendor/e7auto"),
    ]
    + _QFLUENT_DATAS,
    hiddenimports=(
        list(_QFLUENT_MODULES)
        + collect_submodules("winrt")
        + ["yaml", "win32gui", "win32api", "win32con", "pywintypes"]
    ),
    hookspath=[],
    runtime_hooks=[],
    # ⚠️ 整个包按**源码**收集，不压成 pyc。
    # 理由：modes.py 的加载期自查用 ``inspect.getsource`` 读路线源码（「结论门槛
    # 有没有被 super() 接回去」这类结构性规矩只能从源码看）。压成 pyc 后源码不存在，
    # 打包版一启动就 OSError: could not get source code —— 2026-10-19 实测撞到。
    # 代价是多带约 1.5 MB 的 .py，本项目是 MIT 开源的，没有「藏源码」这个需求。
    module_collection_mode={"auto_game_unified": "py"},
    # 测试、夹具、开发缓存一律不进包：安装包只需要「跑起来必需」的东西。
    # 不排除 unittest 之类的标准库：省不了几兆，但一旦某个依赖在 import 期用到它，
    # 故障会藏在「只在打包版出现」的那一类里，排查成本远高于这点体积。
    #
    # ⚠️ 以前这里排除了 ``auto_game_unified.desktop_qt`` + ``PySide6`` +
    # ``qfluentwidgets``，理由是「默认界面只用 tkinter，Qt 是可选入口」。
    # 2026-11-09 删掉 Tk 界面之后这条理由不存在了 —— 再排除就是打出一个没有
    # 界面、双击即崩的包。**别再按旧体积预算把 Qt 加回排除列表。**
    excludes=[
        "auto_game_unified.tests",
        "pytest",
        "_pytest",
        # 其余 Qt 绑定不用，留着排除能少几十兆。
        "PyQt5",
        "PyQt6",
        "PySide2",
        "shiboken2",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ⚠️ 剔掉 OpenCV 的 videoio ffmpeg 后端（两个 DLL，原始共 51.9 MB）—— 2026-10-20 加。
#
# 事实依据：全仓库搜 `VideoCapture` / `VideoWriter` **零命中**，我们用 cv2 只做
# `imread` / `matchTemplate`。这两个 DLL 是 PyInstaller 按「整个 cv2 目录」收集
# 时顺带拖进来的。删掉之后实测跑过一次 ``--self-check``：**结果通过**，
# 305 张模板、15 条路线全部加载，退出码 0。
#
# 收益：免安装版 88.0 MB → 63.3 MB（压缩后省 24.7 MB）。
#
# ⚠️ 别顺手把整个 ``cv2/`` 都过滤掉 —— `cv2.pyd`（71.5 MB）是真正的 OpenCV 本体，
# 少了它程序起不来。这里只按文件名前缀剔 videoio 那两个。
# `build.py` 的打包冒烟里有一条断言守着「它们真的不在产物里」，别绕过它。
_VIDEOIO_FFMPEG_PREFIX = "opencv_videoio_ffmpeg"


def _is_videoio_ffmpeg(entry) -> bool:
    return _VIDEOIO_FFMPEG_PREFIX in Path(entry[0]).name


a.binaries = [entry for entry in a.binaries if not _is_videoio_ffmpeg(entry)]
a.datas = [entry for entry in a.datas if not _is_videoio_ffmpeg(entry)]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Epic7AutoAssistant",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Epic7AutoAssistant",
)
