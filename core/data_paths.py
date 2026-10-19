"""运行产物（日志、诊断、导出）写到哪个目录。

为什么不能写安装目录：程序可能被装进 ``Program Files``，那里对普通用户是只读的，
日志一开就抛 ``PermissionError``，用户看到的现象是「双击没反应」。所以打包版必须把
运行产物放到用户目录。

规则（优先级从高到低）：

1. ``EPIC7_DATA_DIR`` —— 显式指定。测试与排障用它，行为完全可预期；
2. 打包运行（PyInstaller 会把 ``sys.frozen`` 置真）—— ``%LOCALAPPDATA%\\Epic7AutoAssistant``；
3. 源码运行 —— 包目录本身，与既有文档、测试、开发流程里的 ``runtime_logs/`` 一致。

目录名继续用 ``runtime_logs`` / ``runtime_diagnostics``：它们是用户手册、诊断导出和
大量测试共同引用的名字，换名字的收益远小于把老路径全部改一遍的风险。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

APP_DIR_NAME = "Epic7AutoAssistant"
DATA_DIR_ENV = "EPIC7_DATA_DIR"


def data_root() -> Path:
    """运行产物的根目录。不创建目录，只回答「在哪」。"""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return _local_app_data() / APP_DIR_NAME
    return package_root()


def package_root() -> Path:
    """``auto_game_unified`` 包目录：模板与代码所在位置。"""
    return Path(__file__).resolve().parents[1]


def _local_app_data() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local)
    return Path.home() / "AppData" / "Local"
