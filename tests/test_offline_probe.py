"""离线探针：只观察停止信号，正常到点退 0，收到 stop.signal 退 130。"""

from __future__ import annotations

from pathlib import Path

from auto_game_unified import main as cli


def test_probe_ends_normally_without_a_stop_file(tmp_path: Path, capsys):
    assert cli._run_offline_probe(0.05, tmp_path / "stop.signal") == 0
    assert "正常结束" in capsys.readouterr().out


def test_probe_exits_130_when_the_stop_file_exists(tmp_path: Path, capsys):
    stop = tmp_path / "stop.signal"
    stop.write_text("stop\n", encoding="utf-8")

    assert cli._run_offline_probe(30, stop) == 130
    assert "收到停止请求" in capsys.readouterr().out
