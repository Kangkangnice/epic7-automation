"""验证门槛（`tools/check.py`）的护栏。

守的是 2026-09-25 定的规矩：**改多少验多少，小改动不许白跑全量**。

门槛本身会按改动范围选测试，但日常爱敲的 `check.py --vs HEAD` 取的是「工作区相对 HEAD 的
**全部**改动」⇒ 上一轮没提交的共享模块会把判定永久拖成全量（2026-09-25 实测：只想验一行
改动，连跑两次全量 408s / 457s，而局部只要 28.7 秒）。

所以这里守住两件事：

1. 判成全量时**一定会**喊话（为什么全量 + 怎么改成定向）—— 让「白跑 7 分钟」在屏幕上
   变得刺眼；
2. 暂存区为空、退化成「整个工作区判定」时**一定会**提醒 —— 这是白跑的头号成因。

⚠️ 项目里的经验：**没护栏的规矩守不住**（唯一从来没被违反的规矩都带护栏测试）。
下面这些断言针对的是「提示还在、还接在门槛上」，不是措辞本身 —— 措辞可以改，
但别让提示悄悄消失、或者留着函数却把调用删了。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from auto_game_unified.tools.check import (
    WORKSPACE_MODE_NOTICE,
    full_run_notice,
)

CHECK_SOURCE = (Path(__file__).resolve().parents[1] / "tools" / "check.py").read_text(
    encoding="utf-8"
)


class FullRunNoticeTests(unittest.TestCase):
    """判成全量时的喊话。"""

    def test_it_says_why_the_gate_decided_on_a_full_run(self):
        reason = "改了共享模块 main.py"
        self.assertIn(reason, full_run_notice(reason, ["main.py", "tests/test_a.py"]))

    def test_it_offers_the_narrow_command_with_the_changed_files(self):
        notice = full_run_notice("改了共享模块", ["games/epic7/arena.py", "tests/test_a.py"])
        self.assertIn("--files", notice)
        self.assertIn("games/epic7/arena.py", notice)
        self.assertIn("tests/test_a.py", notice)

    def test_it_points_at_the_staged_alternative(self):
        # 「先 git add 再不带参数跑」是挡住并发会话 / 旧改动污染的唯一姿势，必须写进提示。
        self.assertIn("git add", full_run_notice("改了共享模块", ["main.py"]))

    def test_it_stays_useful_when_there_is_nothing_to_name(self):
        notice = full_run_notice("认不出归属", [])
        self.assertIn("--files", notice)
        self.assertIn("<改到的文件>", notice)

    def test_the_notice_is_actually_printed_by_the_gate(self):
        # 只断言「函数还在」不够 —— 留着函数却删掉调用，提示一样不会出现在屏幕上。
        self.assertIn("print(full_run_notice(", CHECK_SOURCE)


class WorkspaceModeNoticeTests(unittest.TestCase):
    """暂存区为空、退化成「整个工作区判定」时的提醒。"""

    def test_it_says_the_whole_workspace_is_being_judged(self):
        self.assertIn("整个工作区", WORKSPACE_MODE_NOTICE)

    def test_it_offers_both_ways_out(self):
        self.assertIn("git add", WORKSPACE_MODE_NOTICE)
        self.assertIn("--files", WORKSPACE_MODE_NOTICE)

    def test_the_notice_is_actually_printed_by_the_gate(self):
        self.assertIn("print(WORKSPACE_MODE_NOTICE", CHECK_SOURCE)


if __name__ == "__main__":
    unittest.main()
