import pytest

from auto_game_unified import launcher


@pytest.mark.parametrize(
    ("choice", "mode", "label"),
    [
        ("1", "story", "主线"),
        ("2", "arena", "竞技场"),
        ("3", "expedition", "远征"),
        ("4", "fodder", "狗粮"),
    ],
)
def test_selects_mode_then_cycles_and_calls_existing_live_entry(
    choice, mode, label
):
    inputs = iter([choice, "3"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 2,
    )

    assert exit_code == 2
    assert calls == [
        [
            "--mode",
            mode,
            "--max-cycles",
            "3",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert "1. 主线" in output
    assert "2. 竞技场" in output
    assert "3. 远征" in output
    assert "4. 狗粮（特别的时间之书 3-7）" in output
    assert f"即将运行：{label}，共 3 次" in output


def test_invalid_values_are_reprompted_in_chinese():
    inputs = iter(["x", "5", "2", "0", "abc", "3"])
    output = []
    calls = []

    exit_code = launcher.run_interactive(
        input_fn=lambda prompt: next(inputs),
        output=output.append,
        run_main=lambda args: calls.append(args) or 0,
    )

    assert exit_code == 0
    assert calls == [
        [
            "--mode",
            "arena",
            "--max-cycles",
            "3",
            "--live",
            "--confirm",
            "RUN",
        ]
    ]
    assert output.count("请输入 1 到 4 之间的功能编号。") == 2
    assert output.count("运行次数必须是正整数。") == 2
