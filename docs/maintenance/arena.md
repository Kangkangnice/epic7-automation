# 竞技场视觉维护

## 先看哪里

竞技场视觉证据唯一维护入口：`games/epic7/evidence/arena.py`。

模板文件位于 `games/epic7/templates/`；固定截图和流程回放位于 `tests/fixtures/epic7_arena/` 与现有竞技场测试。

## UI 改版时怎么改

1. 从 legacy PNG 同名目录的 `evidence.json` 找到页面结论和证据键名；`config` 指向本文件对应的代码入口。
2. 先替换对应模板文件。
3. 只有按钮位置变化时，才修改 `REGIONS` 中该键的区域。
4. 只有新旧画面外观造成分数变化时，才修改 `THRESHOLDS`；不得为了通过单张截图盲目降低阈值。
5. 页面组合变化时，修改同文件中的 `PageEvidence`，并同时增加反例测试。
6. 运行：`python tools/check_evidence.py --mode arena --screen tests/fixtures/epic7_arena/list.png`。
7. 再运行竞技场专项测试和完整回放。

业务流程和资源安全规则仍在 `games/epic7/arena.py`，不能因为模板失效就先改状态机。

`score` 即使低于 `threshold` 也会保留数值；先比较区域、模板和分差，再决定修改。对手选中页以及普通/快速战斗页使用生产状态机与检查器共享的 evaluator，修改页面组合时两边会同步生效，必须同时跑 fixture 和 Runner 回归。

## 每局战绩（胜 / 负 / 未知）

用户看到的「战绩：胜 2 / 负 1」来自 `games/epic7/arena.py`：

- **判定**：`ArenaStateMachine.observe_outcome` —— `result_victory`（「VICTORY」横幅）命中即胜；
  `result_defeat`（「DEFEAT」横幅）命中即负；`result_rating`（「积分」面板标题）只作兜底；
  三个都不在记「未知」。
- **累计**：`ArenaRunner._record_outcome`，每局在战斗监督宣布到结算页之后读一帧，恰好一次。
- **汇报**：`ArenaRunner.outcome_summary` → `main._notify_live` 的通知行与结束行。

两个横幅（VICTORY / DEFEAT）**占同一块区域**，共用 `ARENA_RESULT_BANNER_REGION` ——
区域一致，两个锚点才是同一把尺子。

⚠️ **两个锚点的依据强度不一样，别当成一回事**：

| 判定 | 依据 | 状态 |
| --- | --- | --- |
| 胜 | `arena_result_victory.png`：`epic7_arena/result.png` 上 1.0000，其余 438 张图最高 0.2724 | **实测过** |
| 负 | `arena_result_defeat.png`：真机输局帧 0.9871~1.0000，赢局帧只有 0.1090~0.1129，全库 227 张夹具最高 0.3828 | **2026-09-25 起实测过** |
| 兜底 | `result_rating`：只在**旧基准夹具**上有效（1.0000），真机 5 张全部 0.3815~0.3899 | ⚠️ **真机上已失效**，只兜「横幅还在淡入」那几帧 |

⚠️ **`result_rating` 在真机上失效这件事，是 2026-09-25 才发现的**：那天实跑 5 局
（3 胜 2 输），报出来是「胜 3（未知 2）」—— 因为「负」当时只有这条推理链，而它断在这里。
那两张被判成「未知」的帧现在就是 `result_defeat` 锚点的素材来源
（模板裁自 `..._unknown_r4.png`，回归夹具用 `..._unknown_r1.png`，**故意不取同一张**）。

认不出时仍然**单列「未知」，绝不并入「负」** —— 宁可显示「未知 1」，
也不报一个没把握的比分（远征结算页、空白帧都走这条路）。

实跑时每局结算画面会落一张盘：`docs/manual_review/arena/<时间戳>_<win|lose|unknown>_r<轮次>.png`
（文件名保持 ASCII —— `cv2.imwrite` 写不了中文路径）。判定和画面对不上的时候，
这就是第一手证据。

**只留最近 `OUTCOME_FRAME_KEEP`（10）张**，多出来的从最旧开始删（`ArenaRunner._prune_outcome_frames`）——
落盘目录在仓库里、会被 git 跟踪，一张全屏 PNG 1~3 MB，不裁会把仓库撑大。裁剪按**文件名**
排序（命名以时间戳开头 ⇒ 字典序即新旧序），所以改命名格式时要一起看；删不掉（用户正在看图）
只跳过、不中断跑图。

换 `arena_result_victory.png` / `arena_result_defeat.png` / `arena_result_rating.png` 时，
除了跑既有回归，**还要跑 `tests/test_arena_outcome.py`** —— 它是唯一守住
「VICTORY 锚点在赢帧上、DEFEAT 锚点在输帧上真的命中」以及「两个横幅互不误命中」的测试。
接力用的 `arena.result_arena` 页是「rating **或** victory **或** defeat」，
单靠它分不出是哪个坏了。

