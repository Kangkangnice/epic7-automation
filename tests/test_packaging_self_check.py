"""打包自检必须真的留下报告：路径落在数据目录，写不进去必须报错退出。

回归点（2026-11-19 审查 A2）：``packaging/entry.py`` 在路线循环里用模板根覆盖了
数据根，报告写进不存在的 ``<模板根>/runtime_logs``，``OSError`` 被 ``pass`` 吞掉，
于是「输出通过、退出 0、报告不存在」；``packaging/build.py`` 的冒烟恰好去数据目录
取报告，必然取不到。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
ENTRY = REPO / "packaging" / "entry.py"


def _load_entry():
    """进程内加载 ``packaging/entry.py``，好让用例替换掉发行版状态判定。"""
    spec = importlib.util.spec_from_file_location("packaging_entry_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_self_check(data_dir: Path) -> subprocess.CompletedProcess[str]:
    # 子进程的编码由这里**显式固定**，不依赖当前终端有没有设 PYTHONIOENCODING：
    # 否则中文报告在 GBK 终端下会被按 UTF-8 解、断言随机红（2026-11-19 复验遇到）。
    env = dict(
        os.environ,
        EPIC7_DATA_DIR=str(data_dir),
        PYTHONIOENCODING="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(ENTRY), "--self-check"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_report_lands_in_the_requested_data_directory(tmp_path: Path):
    result = run_self_check(tmp_path)

    report = tmp_path / "runtime_logs" / "self_check.txt"
    assert result.returncode == 0, result.stdout + result.stderr
    assert report.is_file(), f"自检没有留下报告：{report}\n{result.stdout}"
    assert "结果：通过" in report.read_text(encoding="utf-8")


def test_unwritable_report_path_returns_non_zero_with_reason(tmp_path: Path):
    # 让 ``runtime_logs`` 本身可写、只有报告那个文件名被目录占住 —— 这样
    # 「目录可写」这一项仍然通过，单独验证「报告写不进去必须失败」。
    logs = tmp_path / "runtime_logs"
    logs.mkdir()
    (logs / "self_check.txt").mkdir()

    result = run_self_check(tmp_path)

    assert result.returncode != 0
    assert "自检报告写入" in result.stdout
    assert "结果：通过" not in result.stdout


def test_absent_marker_is_reported_as_a_release_fact(tmp_path: Path, monkeypatch):
    """声明不含 E7auto 的发行版：自检记一行「通过」的构成说明，不当缺件失败。

    回归点：三态判定之前只有「目录在不在」两态，不含 E7auto 的公开候选
    会把「故意不含」判成缺件、自检永远不过；反过来漏拷也会被当成不含而放过。
    """
    from auto_game_unified.desktop import chaos_bridge

    entry = _load_entry()
    monkeypatch.setenv("EPIC7_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(chaos_bridge, "vendor_state", lambda vendor=None: "absent")

    assert entry._self_check() == 0

    text = (tmp_path / "runtime_logs" / "self_check.txt").read_text(encoding="utf-8")
    assert "发行版构成：本发行版不含次元探查" in text
    assert "结果：通过" in text
    # 构成说明与「第三方代码可用」互斥，不能同时出现。
    assert "e7auto 可导入" not in text
