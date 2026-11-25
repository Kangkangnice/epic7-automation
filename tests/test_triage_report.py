import json
from pathlib import Path
from zipfile import ZipFile

from auto_game_unified.tools.triage_report import main


def _archive(tmp_path: Path, report: dict) -> Path:
    path = tmp_path / "E7-20261123-2315-A3F9.zip"
    prefix = "E7-20261123-2315-A3F9"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"{prefix}/report.json",
            json.dumps(report, ensure_ascii=False),
        )
    return path


def test_prints_the_one_page_conclusion(tmp_path, capsys):
    report = {
        "short_code": "A3F9",
        "product_version": "0.1.0",
        "backend": "pc",
        "pc_input_mode": "background",
        "exit_code": 1,
        "failed_route": "story",
        "last_output": "连按 2 次 ESC 没反应",
        "failure": {
            "action": "enter_battle",
            "source": "story_battle_menu",
            "targets": ["battle"],
            "attempt": 3,
            "conclusion": "timeout",
            "evidence_dir": "20261123_120000_123456_failure",
        },
        "top_scores": [
            {
                "atom": "story_home",
                "score": 0.97,
                "threshold": 0.9,
                "observed": True,
            },
            {
                "atom": "story_battle_title",
                "score": 0.62,
                "threshold": 0.9,
                "observed": False,
            },
        ],
        "frames": ["frames/failure.png"],
        "logs": ["logs/epic7_story.log"],
        "frames_compressed": False,
        "note": "",
    }
    code = main([str(_archive(tmp_path, report))])
    output = capsys.readouterr().out

    assert code == 0
    assert "诊断包 A3F9" in output
    assert "退出码 1 · 失败路线 story" in output
    assert "失败动作 enter_battle" in output
    assert "0.970 >= 0.900  observed  story_home" in output
    assert "0.620 <  0.900  miss      story_battle_title" in output
    assert "frames/failure.png" in output
    assert "logs/epic7_story.log" in output


def test_missing_report_is_reported_without_a_traceback(tmp_path, capsys):
    path = tmp_path / "E7-20261123-2315-BBBB.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("E7-20261123-2315-BBBB/README.txt", "x")

    code = main([str(path)])
    output = capsys.readouterr().out

    assert code == 2
    assert "包内没有 report.json" in output


def test_missing_archive_is_reported(tmp_path, capsys):
    code = main([str(tmp_path / "不存在.zip")])
    assert code == 2
    assert "找不到诊断包" in capsys.readouterr().out
