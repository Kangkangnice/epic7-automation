# 工作区根目录待清理清单

> 本文件由 `tools/report_workspace_tidy.py` 生成，**只读扫描，没有删除或移动任何文件**。

- 扫描目录：`D:\AI\codex\auto_game`（工作区根）
- 根目录文件：**35 个，合计 16.9 MB**
- 根目录子目录：见「子目录」一节
- 生成时间：2026-09-27 22:23

## 先说一句要紧的

工作区根 `D:\AI\codex\auto_game` **不是 git 仓库**，仓库根是 `auto_game_unified/`。
所以这些文件全都没有版本记录 —— 删掉就真没了，没有 `git checkout` 可以捞回来。
这也是为什么本清单只清点、不动手。

还有一条要先说：根目录下的 **`.workbuddy/` 绝对不能删**。
它是项目数据与记忆目录（`memory/`、`skills/` 等），不是缓存；
删掉会丢项目长期记忆和已沉淀的经验，没有任何办法恢复。

## 风险分级

| 级别 | 对象 | 数量 | 说明 | 建议 |
| --- | --- | --- | --- | --- |
| **⚠️ 别删** | 根目录 `_*` 探针脚本与输出（类别 A1–A6） | 11 | 看着像临时产物，但**剩下这批已被代码 / 测试 / 文档 / 记忆按名字引用**（2026-09-23 定性为「引用中，保留」） | 删前必须 grep 引用，见下 |
| **L0 可删** | 空目录 + 根 `runtime_logs` | 468 | `_walk`、`docs` 是空的；根 `runtime_logs` 里有 466 个临时文件（含子目录） | 确认后可删 |
| **L1 需你确认** | `templates_用户修改版_20260829` | 16 | 与仓库版本**全部不一致**，疑似 08-29 手工改过但没进仓库 | **先看图再决定**，见下 |
| **L2 需你确认** | `templates_backup_20260829_1854` | 114 | 改版前的模板快照，仓库已有 92 张与它一致 | 可留作回滚点，或移入归档 |
| **L3 别当垃圾** | 根 `tools/` | 16 | PC 客户端截图工具链，**含正式脚本** | 建议搬进仓库，不是删 |
| **L4 需你确认** | 顶层截图与 ROI 切片（类别 B）、根目录散落脚本（类别 C） | 23 | 体积占大头；脚本位置不对 | 看一眼再删 |

## ⚠️ 根目录 `_*` 探针**不是**垃圾（2026-09-23 定性，别再当 L0 删）

`.gitignore` 里对它们写着「跑完即弃」，所以早先的清单把它们整批标成「可删」。
**这个判级是错的**：保留下来的这 10 个被**代码 / 测试 / 文档 / 记忆**按名字引用
（`_layout_probe.py`、`_ocr_probe.py`、`_img_probe.py`、`_card_color_probe.py`、
`_survivor_probe.py`、`_survivor_region_view.py`、`_survivor_timing.py`、
`_fixture_sizes.py`、`_diag_stuck_state.py`、`_del.txt`）——
删了会让注释里的「实测脚本」变成**死链接**。

**做法**：先 grep 引用再删；清理走回收站；目录「先删文件再 rmdir」。
完整保留清单与判据见 `.workbuddy/memory/2026-09-23.md` 的「清理判据」一节。

上面 10 个之外，后来还多了 `_knight_probe.py` —— 它没有被别处引用，但本身是
**带 CLI 的可复用实机探针**（`shot` / `click` / `swipe` / `back` / `where`），
与 `_survivor_probe.py` 同类，同样建议留着。

## L1：那 16 张「用户修改版」模板要紧在哪

`templates_用户修改版_20260829/` 里的 16 张图，与仓库当前版本**一张都不相同**，
而与同级的 `templates_backup_20260829_1854/` 里的版本**完全一致**。
仓库里这些图的最后一次提交是 `e07bd9a`（08-21），而这批图的文件时间是 08-29 18:34–18:52。

两种可能，需要你看图判断：

1. **这批手工改动没进仓库** → 那它是有效工作，应该对比后合并，不能删；
2. **当时试过手工重新抠图，效果不好又退回了原版** → 那它只是过程产物，可以删。

按项目里的视觉锚点经验，手工重新抠的模板很容易丢掉「排他性」，
所以第二种解释更可能 —— 但这是**推测**，需要你确认。**在你确认之前我不动它。**

| 相对路径 | 与仓库 | 与备份 |
| --- | --- | --- |
| `hero/filter_button.png` | 不一致 | 是 |
| `hero/filter_star3_selected.png` | 不一致 | 是 |
| `hero/filter_star3_unselected.png` | 不一致 | 是 |
| `hero/imprint_button_grey.png` | 不一致 | 是 |
| `hero/imprint_button_normal.png` | 不一致 | 是 |
| `story/auto.png` | 不一致 | 是 |
| `story/auto_off.png` | 不一致 | 是 |
| `story/auto_on.png` | 不一致 | 是 |
| `story/next_stage.png` | 不一致 | 是 |
| `story/prepare_battle.png` | 不一致 | 是 |
| `story/results_confirm.png` | 不一致 | 是 |
| `story/select_team.png` | 不一致 | 是 |
| `story/skip.png` | 不一致 | 是 |
| `story/stamina_material.png` | 不一致 | 是 |
| `story/start_mission.png` | 不一致 | 是 |
| `story/watch_story.png` | 不一致 | 是 |

## L3：根 `tools/` 里有什么

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `__pycache__` | <dir> |  |
| `_debug_current_screen.png` | 1.9 MB | 2026-08-19 22:17 |
| `_lobby_right_nav.png` | 73.1 KB | 2026-08-19 23:16 |
| `_pc_template_audit.py` | 855 B | 2026-08-19 22:55 |
| `_recapture_region.py` | 1.3 KB | 2026-08-19 22:41 |
| `_smoke_pc_capture.py` | 725 B | 2026-08-19 22:26 |
| `_smoke_pc_frame.png` | 2.8 MB | 2026-08-19 23:17 |
| `_verify_lobby_match.py` | 1.5 KB | 2026-08-19 23:15 |
| `capture_pc_templates.py` | 19.7 KB | 2026-08-19 22:36 |
| `capture_single.py` | 1.5 KB | 2026-08-19 22:06 |
| `fill_pc_placeholders.py` | 2.0 KB | 2026-08-19 21:49 |
| `measure_pc_window.py` | 2.4 KB | 2026-08-19 21:43 |

`capture_pc_templates.py`（19.7 KB）是 PC 客户端的模板采集脚本，
`measure_pc_window.py`、`fill_pc_placeholders.py`、`capture_single.py` 也是正式工具。
仓库内 `auto_game_unified/tools/` 目前只有 `capture_fixture.py`、`check.py`、`check_evidence.py`、
`refit_text_anchor.py` 等，**没有 PC 采集这一套**。
所以建议是搬进仓库并纳入版本管理，而不是删。

## 子目录

| 目录 | 文件数 | 体积 | 性质 | 说明 |
| --- | --- | --- | --- | --- |
| `.pytest_cache` | 5 | 125.8 KB | pytest 缓存 | 跑测试留下的缓存，可再生。删了下次跑测试会重建。 |
| `.tools` | 15 | 24.4 MB | 本地工具环境（保留） | adb（`platform-tools`）等本地工具链。`docs/superpowers/specs/2026-08-12-repository-cleanup-and-human-ai-workflow-design.md` 已定性：「`.tools/` 和 `.workbuddy/` 属于本地工具环境，保留在工作区但不纳入 Git 仓库」。**不是缓存，别删。** |
| `.trae` | 1 | 10.1 KB | IDE 配置 | 外部 IDE（Trae）的工程配置，与自动化项目无关，可留可删看你还用不用。 |
| `.workbuddy` | 42 | 808.9 KB | ⛔ 绝对不要删 | WorkBuddy 的项目数据与记忆目录（memory/、skills/ 等）。删掉会丢项目长期记忆与技能，它不是缓存。 |
| `_fribbels_sample` | 28 | 567.5 KB | 待确认 | 未归类，需人工判断 |
| `runtime_logs` | 466 | 211.3 MB | 临时输出（含调研帧集） | 排查期间写的临时脚本与输出（工作区根不是仓库，不被 git 跟踪）；真正的运行日志目录是 auto_game_unified/runtime_logs/。⚠️ 目前里头还有 `knights/` 一批骑士团调研的**真机帧**，删前先确认是否还要回看。 |
| `templates_backup_20260829_1854` | 114 | 3.1 MB | 模板历史快照 | 19 个条目 / 114 个文件。与仓库当前模板：相同 92、不一致 16、仓库已删 6。 |
| `templates_用户修改版_20260829` | 16 | 252.2 KB | 疑似未合并的手工改动 | 16 张，与仓库版本全部不一致，且与该备份目录里的版本完全一致。 |
| `tools` | 16 | 4.8 MB | PC 客户端截图工具链 | 16 个条目 / 4.8 MB，含正式脚本，见下方专节。 |

## 根目录文件明细

### A1 · OCR / 模板调参中间图（2 个，2.4 KB）

跑 OCR 与模板增强时批量导出的 bw/inv/otsu 版本，全部可再生

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_fixture_sizes.py` | 1.1 KB | 2026-09-16 19:35 |
| `_ocr_probe.py` | 1.4 KB | 2026-09-16 19:31 |

### A2 · 一次性探针脚本（`_*.py`）（8 个，23.6 KB）

为定位某个具体问题临时写的脚本，结论已进入正式代码或文档

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_card_color_probe.py` | 2.8 KB | 2026-09-16 20:09 |
| `_diag_stuck_state.py` | 3.5 KB | 2026-08-26 23:58 |
| `_img_probe.py` | 1.2 KB | 2026-09-16 19:18 |
| `_knight_probe.py` | 1.9 KB | 2026-09-24 19:42 |
| `_layout_probe.py` | 4.6 KB | 2026-09-16 20:20 |
| `_survivor_probe.py` | 3.4 KB | 2026-09-16 21:35 |
| `_survivor_region_view.py` | 2.7 KB | 2026-09-16 21:37 |
| `_survivor_timing.py` | 3.4 KB | 2026-09-16 23:03 |

### A3 · 探针输出文本（`_*.txt` / `_*.tsv`）（1 个，1.6 KB）

探针脚本的 stdout 落盘

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_del.txt` | 1.6 KB | 2026-09-17 20:55 |

### B · 顶层截图与 ROI 切片（12 个，16.8 MB）

模拟器/PC 客户端整屏截图与局部切片，体积占大头

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `current_state.png` | 2.2 MB | 2026-08-19 11:20 |
| `hi_strip.png` | 270.0 KB | 2026-08-19 10:44 |
| `pc_current_frame.png` | 1.5 MB | 2026-08-19 20:11 |
| `pc_dryrun_frame.png` | 2.4 MB | 2026-08-19 20:23 |
| `pc_lobby_fixed.png` | 2.5 MB | 2026-08-19 20:30 |
| `pc_lobby_raw_fixed.png` | 2.3 MB | 2026-08-19 20:30 |
| `pc_norm_lobby.png` | 2.3 MB | 2026-08-19 20:29 |
| `pc_raw_lobby.png` | 2.3 MB | 2026-08-19 20:29 |
| `roi_friendship_ticket_offer.png` | 232.7 KB | 2026-08-18 08:07 |
| `roi_no_ticket.png` | 86.8 KB | 2026-08-18 08:07 |
| `roi_ticket_purchase_button.png` | 49.7 KB | 2026-08-18 08:07 |
| `temp_screenshot.png` | 767.4 KB | 2026-08-17 21:40 |

### C · 根目录散落脚本（11 个，28.7 KB）

没有 `_` 前缀但同样是一次性脚本，位置不对（正式脚本应在 tools/）

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `.py` | 4.9 KB | 2026-08-17 20:54 |
| `analyze_assist_auto.py` | 3.1 KB | 2026-08-16 00:57 |
| `run_final.py` | 2.6 KB | 2026-08-18 11:40 |
| `run_fix.py` | 1.8 KB | 2026-08-18 10:41 |
| `run_ocr.py` | 2.5 KB | 2026-08-18 09:10 |
| `run_ocr2.py` | 3.6 KB | 2026-08-18 10:11 |
| `tmp_match.py` | 1.6 KB | 2026-08-18 08:07 |
| `tmp_ocr.py` | 528 B | 2026-08-18 07:50 |
| `tmp_ocr_crops.py` | 3.3 KB | 2026-08-18 09:40 |
| `tmp_winocr.ps1` | 2.4 KB | 2026-08-18 08:37 |
| `write_ps1.py` | 2.5 KB | 2026-08-18 08:37 |

### E · 根目录文档（1 个，7.1 KB）

一次修复的交接说明，内容可能值得并入 docs/

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `远征修复交接说明.md` | 7.1 KB | 2026-08-27 07:43 |

## 确认后建议怎么清

按项目里「先备份、再分批、走回收站」的习惯：

1. 先整目录复制一份备份，确认备份可读；
2. 只处理你确认过的类别，每批不超过 10 个文件；
3. 走回收站而不是直接删；
4. 每批做完再验一次仓库 `git status` 与全量测试，确认没误伤。

## 本次没有做的事

- 没有删除、移动、重命名任何文件；
- 没有改动 `templates_用户修改版_20260829` 与 `templates_backup_20260829_1854`；
- 没有把根 `tools/` 搬进仓库（搬动会影响脚本里的相对路径，需要单独一轮改）。
