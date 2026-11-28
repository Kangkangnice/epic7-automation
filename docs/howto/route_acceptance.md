---
topic: route-release-acceptance
when: 填写、检查或复核路线验收台账时
last_verified: 2026-11-27
review_when: 台账数据格式、证据引用方式或验收工具变化
---

# 路线验收记录与自检

[路线开发与验收](route_change.md)说明验哪些组合、如何判断结果，以及什么条件下可公开支持。本页供验证者和评审者填写、校验记录及打开对应证据。

## 1. 台账按适用范围填写

按路线、后端、客户端及版本、待验提交、设置分支各建一份台账。现有 schema 2 用 `client` 一个字符串，依次填写游戏版本、模拟器与 Android 版本或原生客户端版本、实际截图和输入通道。根对象、每条运行和命令中的 `client` 值一致。`revision` 填助手源码的完整 Git SHA，发布评审另在关联记录保存候选工件名与校验值。原有记录继续按其已有字段阅读。版本、输入通道或工件关联缺失时，把该字段记为未知，保留已知分支与原始定位，放行仍待补证。[什么时候可以稳定发布](route_change.md#6-什么时候可以稳定发布)

## 2. 把业务合同填入台账

按业务页的六项准备 `contract`。入口和设置填 `entry`、`settings`，目标和单位填 `goal`、`unit`，资源上限填 `resources`，回执、终点和提前停止填 `receipt`、`terminal`、`early_stop`。无提前停止条件时使用空列表。普通业务的 `work` 默认为 `business`，只读任务填 `read_only`。收尾豁免使用 `terminal_marker` 指定可观察终点，默认标记为 `收尾=已回到首页`。[验收合同](route_change.md#1-先定义这次交付)

## 3. 对照业务结论填写结果

| 台账结果 `outcome` | 业务结论 | 在基本字段之外补填 |
|---|---|---|
| `completed` | 完成 | 真实回执 `receipt`、合法终点的依据 `terminal.evidence`。自然终点另填 `end_evidence`。 |
| `expected_stop` | 预期停止 | `stop_reason`、正向停止与收尾依据。零工作另填 `zero_work_evidence`。 |
| `failed` | 失败 | `stop_reason`、实得量和已有证据。收尾失败将 `terminal.verified` 填为 `false`。 |
| `unsafe` | 不安全 | 保留现场和已确认消耗。 |
| `interrupted` | 中断 | `stop_reason`、`stopped_at` 和 `state_at_stop`。 |

有首个故障时写 `first_failure`，结果只能为 `failed` 或 `unsafe`。运行场景 `scenario` 可填 `normal`、`alternate`（可完成的账号变体）、`expected_stop` 或 `read_only`。只读用 `work: read_only` 和 `scenario: read_only`，回执写实读数值与原文。普通业务填 `work: business`。退出码 0 后仍要核对回执和终点，退出码 2 只对应预先声明的正常结束。[五种结果和统计口径](route_change.md#一次启动只有一个结论)

## 4. 回放字段与证据

`replay_cases` 填 `normal`、`repeat`、`overlay`、`slow_or_frozen`、`unknown`、`end`。合同有提前停止条件时加 `safe_stop`。每项填实际运行的完整测试节点（含适用的类名）和执行记录引用。记录包含节点、待验提交 SHA 与通过结果。用例覆盖多类时可分别引用。每项修复对应现场状态、预期或禁止的动作、回执或停止条件，以及旧行为失败与待验提交通过的回归证据。[正常实机和异常离线范围](route_change.md#3-从现场到交付)

## 5. 实机记录与自检

每条 `runs` 记录一次独立启动，填写该次的路线、后端、客户端及修订号。账号、环境和运行 ID 用本轮代号。用 `launch` 指定日志与起止时间。引用本次日志的内容要指到其边界内的行号。启动边界重叠的记录须人工核对，核清后才计独立样本。按实际记录请求量、实得量、每种资源的消耗、回执和收尾。把原始画面和脱敏日志与各代号关联起来，对外汇总隐去账号名、余额原图和本地路径。

下例为虚构数据，展示单条运行和一项回放。金额、版本、SHA、路径及行号均为示例。正式台账需填写全部适用回放、本次所有尝试及可打开的证据。

```json
{
  "schema": 2,
  "route": "craft_equipment",
  "backend": "emulator",
  "client": "游戏版本=1.0.0；模拟器=雷电 9.1.23 / Android 9；通道=ADB 截图与输入",
  "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "contract": {
    "entry": "大厅 → 快捷菜单 → 钢铁工坊 → 制作装备",
    "settings": "整理关闭、出售与萃取关闭、每轮制作次数 10",
    "goal": "按请求轮次制作装备",
    "unit": "件",
    "receipt": "制作结果页「制作完毕」且累计件数等于请求轮次×10",
    "terminal": "回到大厅",
    "early_stop": ["讨伐材料不足", "金币不足", "装备背包已满"],
    "resources": [{"name": "金币", "cap": 420000}]
  },
  "replay_cases": [
    {
      "case": "normal",
      "test": "tests/test_epic7_craft_equipment.py::CraftEquipmentMachineTest::test_two_rounds_without_tidy",
      "evidence": "reports/replay/craft-normal.txt"
    }
  ],
  "runs": [
    {
      "id": "run-01",
      "launch": {
        "log": "runtime_logs/epic7_craft_equipment.log",
        "started_at": "2026-11-17 21:58:11",
        "ended_at": "2026-11-17 21:59:21"
      },
      "route": "craft_equipment",
      "backend": "emulator",
      "client": "游戏版本=1.0.0；模拟器=雷电 9.1.23 / Android 9；通道=ADB 截图与输入",
      "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "account": "A",
      "environment": "setup-1",
      "day": "2026-11-17",
      "scenario": "normal",
      "work": "business",
      "requested": "2 轮 × 10 件，共 20 件",
      "target": 20,
      "achieved": 20,
      "outcome": "completed",
      "stop_reason": "",
      "first_failure": "",
      "receipt": "结果页「制作完毕」，状态=完成一遍 cycles=2 件数=20",
      "terminal": {
        "verified": true,
        "evidence": "runtime_logs/epic7_craft_equipment.log#L91"
      },
      "resources": [{"name": "金币", "spent": 420000}],
      "evidence": ["runtime_logs/epic7_craft_equipment.log#L60-L72"]
    }
  ]
}
```

维护者从仓库父目录核对真实台账。用本次候选记录的完整修订和客户端字段替换示例值。

```powershell
$candidateRevision = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$acceptanceClient = '游戏版本=1.0.0；模拟器=雷电 9.1.23 / Android 9；通道=ADB 截图与输入'
python -m auto_game_unified.tools.check_route_acceptance .\acceptance.json --route craft_equipment --backend emulator --client $acceptanceClient --revision $candidateRevision
```

检查器核对证据引用、启动边界、重复记录、用量、终点和结果字段。通过时输出「台账通过，待独立复核」。在 PR 或发布记录保存脱敏汇总、实机证据引用和范围，由领域评审者打开原始证据核对，签明结论。[独立复核条件](route_change.md#6-什么时候可以稳定发布)

### 现状页的实机依据

2026-11-27 模拟器桌面每日编排 07:55:12–08:34:22，工作进程日志 `desktop_worker.log` 第 18571–18572 行确认编排、退出码 0 和无停止请求。段间大厅确认见 `epic7_daily_probe.log` 第 2751–2760 行。原始日志由实机记录保管方留存，可按日期、文件名和行号请求脱敏摘录。游戏版本、模拟器版本、待发修订与工件均未知。

| 路线 | 本次支持的声明与日志定位 |
| --- | --- |
| 世界首领战 | 选择队伍禁用，无宝箱，零场并回大厅。 `epic7_world_boss.log` 第 9289–9323 行。历史 PC 单轮见下文 Git 摘要。 |
| 骑士团捐赠 | 请求一次、支援两次并获奖励、领一项每周任务奖励，回大厅。 `epic7_knights_donation.log` 第 11923–12012 行。 |
| 迷宫强化石 | 两次进入确认框并确认，返回商店并回大厅。逐笔商品身份、实际扣款与交易回执待核。 `epic7_labyrinth_stone.log` 第 14434–14570 行。 |
| 圣域收菜 | 精灵之森先后点了第 1、3 行。第 1 行有领取完成弹窗；第 3 行点击后日志直接进入三行倒计时、未见照料按钮的收尾，第二笔独立回执待核。已回大厅。 `epic7_sanctuary.log` 第 5683–5727 行，领取与终点在第 5698–5713、5727 行。 |
| 成就领取 | 巡检各分类、无可领取项目并回大厅。 `epic7_achievement.log` 第 3060–3100 行。 |
| 宠物领养 | 免费领养一次；用品已购或冷却，未购买用品，回大厅。 `epic7_pet_adoption.log` 第 1700–1756 行。 |
| 支线故事 | 只读巡检确认本期到期并回大厅。 `epic7_side_story.log` 第 6418–6451 行。历史整期实机见下文 Git 摘要。 |

另查[社区签到](../maintenance/community_checkin.md#验收证据)、[竞技场](../SAFETY_MATRIX.md#竞技场桌面实机复核)和[刷书签](../maintenance/shop_refresh.md#验收证据)的正常及异常证据。

| 历史声明 | 可追溯范围与缺口 |
| --- | --- |
| 英雄合成、主线、月塔、活动剧情、月光剧场 | Git `4f6d598:docs/SAFETY_MATRIX.md`「三、实机支持证据表」「五、按组合的验收现状」保留原摘要。英雄合成的模拟器单轮、主线 PC 片段、月塔 PC 单层、活动剧情多段、剧场 PC 首幕均按该摘要的范围引用。各自运行边界、原始回执及候选工件关联待追溯。 |
| 支线故事与世界首领战 | 上述 Git 摘要分别记有 11 月 12 日模拟器整期、11 月 3 日 PC 单轮。原始运行边界与候选关联待追溯；上表的 11 月 27 日只读和零场证据另计。 |
| 主线补星 | [维护手册缺口](../maintenance/story_star.md#六已知缺口)保留 PC 四关及人工停止的范围，Git 旧证据表留有历史复核入口。六章、版本与发行工件待核。 |
| 企鹅批量购买与装备制作 | [企鹅实机摘要](../maintenance/penguin_purchase.md#现行事实)与[装备实机摘要](../maintenance/craft_equipment.md#现行事实)保留单轮及连续业务记录。原始定位从上述 Git 旧证据表及实机记录保管方取得。资源不足、失败收尾和本次发行工件待核。 |

旧记录中的收尾字段次数可能混有异常恢复、同一次启动的多轮和用户停止。发布时按独立启动边界和业务回执逐条重新分级。

## 6. 开发自检

从仓库父目录运行与变更相符的命令。

```powershell
python -m auto_game_unified.tools.doc_review --scenario new-route
python -m auto_game_unified.tools.doc_review --scenario fix-bug
python -m auto_game_unified.tools.doc_review --scenario new-mechanism
python -m auto_game_unified.tools.check --plan --files <仓库相对路径>
python -m auto_game_unified.tools.route_compliance --strict
python -m auto_game_unified.tools.report_rework
```

声明检查用于查契约条目，返工报告按提交和改动范围估算趋势。分析返工时记录基线和统计口径，具体故障沿实际变更和现场证据复盘。[按改动选测试](../../CONTRIBUTING.md#按改动选测试)
