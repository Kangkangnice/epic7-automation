"""打包自检必须真的留下报告：路径落在数据目录，写不进去必须报错退出。

回归点（2026-11-19 审查 A2）：``packaging/entry.py`` 在路线循环里用模板根覆盖了
数据根，报告写进不存在的 ``<模板根>/runtime_logs``，``OSError`` 被 ``pass`` 吞掉，
于是「输出通过、退出 0、报告不存在」；``packaging/build.py`` 的冒烟恰好去数据目录
取报告，必然取不到。
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
ENTRY = REPO / "packaging" / "entry.py"


def run_self_check(data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, EPIC7_DATA_DIR=str(data_dir))
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
