# 远征视觉维护

远征视觉证据入口：`games/epic7/evidence/expedition.py`。

模板位于 `games/epic7/templates/expedition/`；共享战斗自动按钮使用 `../story/auto_off.png`。改版时先替换模板，再按键名修改 `REGIONS` 或 `THRESHOLDS`。

难度三是否已选中、传单是否可出发、公开招募和返回主页属于业务事务判断，仍在 `games/epic7/expedition.py`。不因识别分数下降直接放宽难度或出发条件。

转场或未知页面超时时，原 `*.png` 旁的同名目录包含 `screen.png` 和 `evidence.json`。按其中 `config`、证据键、`region`、实际 `score` 和 `threshold` 维护；低分仍会量化记录。当前命令行检查器未注册远征，修改后运行远征页面与 Runner 测试。

## 「未持有通缉传单」判据：从静默失效到三道关（2026-10-04）

### 事故

传单用完时应该收工（`PostersExhausted`，退出码 2）。这个判据是 `empty_posters`，
而**模板文件从来就没做** —— 它被登记成「可选」，`build_expedition_templates()` 用
`load_optional()` 加载，文件不在就安静地给个 `None`。

后果不是「少认一种画面」，是**收工判据整个失效**：`_posters_action()` 认不出
「没有可用的通缉传单」，于是继续去找那个永远不会出现的出发按钮，一路等到超时。

- **实测发生 6 次**：2026-09-19 ~ 2026-10-03，每次都停在同一个动作
  `open-my-posters`，诊断图 `..._no_transition_open-my-posters.png` 里画面明写
  「未持有通缉传单 / 持有 0/10」。
- **为什么半个月没发现**：测试用假图（`pattern(3)`）顶替这个模板，所以测试全绿；
  而且有一条测试**断言 `templates.empty_posters is None`** —— 把缺陷当成了预期行为。

### 修法

模板从现场帧裁出（`runtime_diagnostics/epic7_expedition/20261003_193135_...`），
只取固定文案「未持有通缉传单。完成讨伐中级以上将有一定几率获得。」——
**零可变内容**，不含「0/10」和倒计时（见 `template_dynamic_content_review.md`）。

三道关（与英雄合成同款）：

| 关 | 位置 | 缺文件时 |
| --- | --- | --- |
| 加载期 | `build_expedition_templates()` 用 `load()` 而非 `load_optional()` | `FileNotFoundError` 点名 |
| 校验期 | 证据画像 `required=True`，`validate_profile()` | 报「模板不存在」 |
| 运行期 | `_locate()` 对**非白名单**的 `None` 抛 `RuntimeError` | 不允许静默返回 `None` |

### 分离度（正负样本全扫）

| | 分数 |
| --- | --- |
| 现场帧（未持有传单） | **1.0000** |
| `posters.png`（**有**传单的列表页） | 0.2379 |
| 全部 16 张远征夹具最高 | 0.2694 |
| 全库 200+ 张夹具过 0.55 的 | **0 张** |

「有传单」只有 0.2379 是重点：证明模板在区分**两种状态**，不是单纯认列表页。

### `defeated_confirm` 已整个删除：**远征没有「输」这回事**（2026-10-04）

⚠️ 这条判据曾经存在，是我的**误判**，现已删除。经过（记下来防复发）：

1. 它登记成「可选模板」，但模板**从来就没做过**，对应动作在真机日志里
   **执行 0 次**（8/30~10/04，3868 行；同期「公开招募结果」走了 36 次）。
2. 我先把它归类为「同一处隐患」，用户当场质疑：「**之前完全没用过呀，也没问题呀**」
   —— 用户是对的。
3. 用户进一步说明机制：**远征打完伤害就直接进结算，没有「输」这回事**，所有情况
   都是同一类，不存在需要单独识别的「战败页」。

⇒ 所以它不是「缺一张图」，是**这条路线上根本没有这个页面**。留着它的代价：
多一个永远为 `None` 的判据、多一处「可选」口子、多一份要维护的假分支。

**删除范围**（一次清干净）：

| 位置 | 处理 |
|---|---|
| `evidence/expedition.py` 的 `REGIONS` / `_TEMPLATE_NAMES` | 删条目 |
| `expedition.py` 的 `ExpeditionTemplates.defeated_confirm` 字段 + 加载 | 删（`load_optional()` 也随之删除，不再需要） |
| `expedition.py::_defeated_action()` | 整个方法删 |
| `expedition.py::next_action()` 开头那 5 行特殊分支 | 删 |
| 三处 `is_in_state()`（OUTCOME / RECRUIT_CONFIRM / RECRUIT_RETURN） | 删 `or` 的那一端 |
| 两处 `_OPTIONAL_TEMPLATES` | **清空**（不是删机制） |

⚠️ **白名单机制保留、内容清空** —— 它是防静默降级的护栏，不能因为没人用就拆掉。
清空之后语义反而更强：**远征一张模板都不许缺席**。测试
`test_every_template_is_now_required` 逐个把模板置 `None`，断言 `_locate` 必须报错
点名（`empty_posters` / `victory_title` / `campfire_idle` 三个锚点轮着来）。

⚠️ **别再把「可选」当成「先这样，以后再补」的口子** —— `empty_posters` 就是这么丢的
（漏判半个月、空等 6 次）。新增锚点必须**同时**补模板文件。


