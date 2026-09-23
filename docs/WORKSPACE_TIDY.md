# 工作区根目录待清理清单

> 本文件由 `tools/report_workspace_tidy.py` 生成，**只读扫描，没有删除或移动任何文件**。

- 扫描目录：`D:\AI\codex\auto_game`（工作区根）
- 根目录文件：**199 个，合计 23.7 MB**
- 根目录子目录：见「子目录」一节
- 生成时间：2026-09-23 08:24

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
| **L0 可删** | 根目录 `_*` 探针脚本与输出（类别 A1–A6） | 175 | 为定位具体问题临时产出，结论已进正式代码/文档 | 确认后可整批删 |
| **L0 可删** | 空目录 + 根 `runtime_logs` | 3 | `_walk`、`docs` 是空的；根 `runtime_logs` 只有 1 个临时文本 | 确认后可删 |
| **L1 需你确认** | `templates_用户修改版_20260829` | 16 | 与仓库版本**全部不一致**，疑似 08-29 手工改过但没进仓库 | **先看图再决定**，见下 |
| **L2 需你确认** | `templates_backup_20260829_1854` | 114 | 改版前的模板快照，仓库已有 92 张与它一致 | 可留作回滚点，或移入归档 |
| **L3 别当垃圾** | 根 `tools/` | 16 | PC 客户端截图工具链，**含正式脚本** | 建议搬进仓库，不是删 |
| **L4 需你确认** | 顶层截图与 ROI 切片（类别 B）、根目录散落脚本（类别 C） | 23 | 体积占大头；脚本位置不对 | 看一眼再删 |

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
| `.pytest_cache` | 5 | 139.5 KB | pytest 缓存 | 跑测试留下的缓存，可再生。删了下次跑测试会重建。 |
| `.tools` | 15 | 24.4 MB | 工具缓存（待确认） | 24.4 MB，体积最大。疑为外部工具/解释器的缓存目录，删前先确认是谁在用。 |
| `.trae` | 1 | 10.1 KB | IDE 配置 | 外部 IDE（Trae）的工程配置，与自动化项目无关，可留可删看你还用不用。 |
| `.workbuddy` | 27 | 339.1 KB | ⛔ 绝对不要删 | WorkBuddy 的项目数据与记忆目录（memory/、skills/ 等）。删掉会丢项目长期记忆与技能，它不是缓存。 |
| `_walk` | 0 | 0 B | 空目录 | 可直接删。目录名为空，0 个文件。 |
| `docs` | 0 | 0 B | 空目录 | 工作区根的 docs/ 是空的；真正的文档目录是 auto_game_unified/docs/。可直接删。 |
| `runtime_logs` | 66 | 25.0 MB | 临时输出 | 只有 1 个 _ls_slot.txt；真正的运行日志目录是 auto_game_unified/runtime_logs/。 |
| `templates_backup_20260829_1854` | 114 | 3.1 MB | 模板历史快照 | 19 个条目 / 114 个文件。与仓库当前模板：相同 92、不一致 16、仓库已删 6。 |
| `templates_用户修改版_20260829` | 16 | 252.2 KB | 疑似未合并的手工改动 | 16 张，与仓库版本全部不一致，且与该备份目录里的版本完全一致。 |
| `tools` | 16 | 4.8 MB | PC 客户端截图工具链 | 16 个条目 / 4.8 MB，含正式脚本，见下方专节。 |

## 根目录文件明细

### A1 · OCR / 模板调参中间图（81 个，3.8 MB）

跑 OCR 与模板增强时批量导出的 bw/inv/otsu 版本，全部可再生

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_crop_autocfg_fail.png` | 14.4 KB | 2026-09-22 09:46 |
| `_crop_autocfg_fixture.png` | 14.3 KB | 2026-09-22 09:46 |
| `_crop_btns.png` | 22.9 KB | 2026-08-18 10:11 |
| `_crop_lhold.png` | 17.9 KB | 2026-08-18 10:11 |
| `_crop_lprice.png` | 41.6 KB | 2026-08-18 10:11 |
| `_crop_rhold.png` | 23.5 KB | 2026-08-18 10:11 |
| `_crop_rprice.png` | 48.2 KB | 2026-08-18 10:11 |
| `_crop_title.png` | 18.5 KB | 2026-08-18 10:11 |
| `_debug_offer_left.png` | 109.3 KB | 2026-08-18 11:11 |
| `_debug_offer_right.png` | 114.1 KB | 2026-08-18 11:11 |
| `_fix_BODY_inv.png` | 24.5 KB | 2026-08-18 10:41 |
| `_fix_BODY_otsu.png` | 24.3 KB | 2026-08-18 10:41 |
| `_fix_BTN_BUY_inv.png` | 4.4 KB | 2026-08-18 10:42 |
| `_fix_BTN_BUY_otsu.png` | 4.2 KB | 2026-08-18 10:42 |
| `_fix_BTN_CANCEL_inv.png` | 21.7 KB | 2026-08-18 10:42 |
| `_fix_BTN_CANCEL_otsu.png` | 21.6 KB | 2026-08-18 10:41 |
| `_fix_L_HOLD_inv.png` | 53.3 KB | 2026-08-18 10:41 |
| `_fix_L_HOLD_otsu.png` | 53.3 KB | 2026-08-18 10:41 |
| `_fix_L_PRICE_inv.png` | 13.9 KB | 2026-08-18 10:41 |
| `_fix_L_PRICE_otsu.png` | 13.8 KB | 2026-08-18 10:41 |
| `_fix_NOTE_inv.png` | 12.4 KB | 2026-08-18 10:41 |
| `_fix_NOTE_otsu.png` | 12.2 KB | 2026-08-18 10:41 |
| `_fix_R_HOLD_inv.png` | 34.0 KB | 2026-08-18 10:41 |
| `_fix_R_HOLD_otsu.png` | 33.8 KB | 2026-08-18 10:41 |
| `_fix_R_PRICE_inv.png` | 14.5 KB | 2026-08-18 10:41 |
| `_fix_R_PRICE_otsu.png` | 14.2 KB | 2026-08-18 10:41 |
| `_fix_TITLE_inv.png` | 10.5 KB | 2026-08-18 10:41 |
| `_fix_TITLE_otsu.png` | 10.3 KB | 2026-08-18 10:41 |
| `_fixture_sizes.py` | 1.1 KB | 2026-09-16 19:35 |
| `_ocr.ps1` | 3 B | 2026-08-17 21:52 |
| `_ocr_BODY_bw.png` | 8.9 KB | 2026-08-18 10:11 |
| `_ocr_BODY_inv.png` | 9.0 KB | 2026-08-18 10:11 |
| `_ocr_BTN_BUY_bw.png` | 1.5 KB | 2026-08-18 10:11 |
| `_ocr_BTN_BUY_inv.png` | 1.6 KB | 2026-08-18 10:11 |
| `_ocr_BTN_CANCEL_bw.png` | 1.9 KB | 2026-08-18 10:11 |
| `_ocr_BTN_CANCEL_inv.png` | 1.9 KB | 2026-08-18 10:11 |
| `_ocr_L_COUNT_bw.png` | 3.1 KB | 2026-08-18 10:11 |
| `_ocr_L_COUNT_inv.png` | 3.2 KB | 2026-08-18 10:11 |
| `_ocr_L_HOLD_bw.png` | 6.8 KB | 2026-08-18 10:11 |
| `_ocr_L_HOLD_inv.png` | 6.9 KB | 2026-08-18 10:11 |
| `_ocr_L_PRICE_bw.png` | 14.2 KB | 2026-08-18 10:11 |
| `_ocr_L_PRICE_inv.png` | 14.3 KB | 2026-08-18 10:11 |
| `_ocr_NOTE_bw.png` | 6.1 KB | 2026-08-18 10:11 |
| `_ocr_NOTE_inv.png` | 6.1 KB | 2026-08-18 10:11 |
| `_ocr_R_COUNT_bw.png` | 3.1 KB | 2026-08-18 10:11 |
| `_ocr_R_COUNT_inv.png` | 3.1 KB | 2026-08-18 10:11 |
| `_ocr_R_HOLD_bw.png` | 8.3 KB | 2026-08-18 10:11 |
| `_ocr_R_HOLD_inv.png` | 8.3 KB | 2026-08-18 10:11 |
| `_ocr_R_PRICE_bw.png` | 15.2 KB | 2026-08-18 10:11 |
| `_ocr_R_PRICE_inv.png` | 15.3 KB | 2026-08-18 10:11 |
| `_ocr_TITLE_bw.png` | 5.9 KB | 2026-08-18 10:11 |
| `_ocr_TITLE_inv.png` | 6.1 KB | 2026-08-18 10:11 |
| `_ocr_body_line.png` | 13.7 KB | 2026-08-18 09:40 |
| `_ocr_btn_adaptive.png` | 12.7 KB | 2026-08-18 09:10 |
| `_ocr_btn_gray.png` | 96.7 KB | 2026-08-18 09:10 |
| `_ocr_btn_otsu.png` | 8.3 KB | 2026-08-18 09:10 |
| `_ocr_buy_btn_area.png` | 3.8 KB | 2026-08-18 09:40 |
| `_ocr_cancel_btn_area.png` | 4.0 KB | 2026-08-18 09:40 |
| `_ocr_footer_note.png` | 6.8 KB | 2026-08-18 09:40 |
| `_ocr_full_adaptive.png` | 171.2 KB | 2026-08-18 09:10 |
| `_ocr_full_gray.png` | 1.6 MB | 2026-08-18 09:10 |
| `_ocr_full_otsu.png` | 135.5 KB | 2026-08-18 09:10 |
| `_ocr_hero.ps1` | 2.3 KB | 2026-08-18 22:41 |
| `_ocr_offer_adaptive.png` | 52.2 KB | 2026-08-18 09:10 |
| `_ocr_offer_gray.png` | 437.7 KB | 2026-08-18 09:10 |
| `_ocr_offer_left_full.png` | 27.5 KB | 2026-08-18 09:40 |
| `_ocr_offer_left_hold.png` | 6.6 KB | 2026-08-18 09:40 |
| `_ocr_offer_left_price.png` | 18.9 KB | 2026-08-18 09:40 |
| `_ocr_offer_otsu.png` | 35.3 KB | 2026-08-18 09:10 |
| `_ocr_offer_right_full.png` | 25.4 KB | 2026-08-18 09:40 |
| `_ocr_offer_right_hold.png` | 4.7 KB | 2026-08-18 09:40 |
| `_ocr_offer_right_price.png` | 19.3 KB | 2026-08-18 09:40 |
| `_ocr_probe.py` | 1.4 KB | 2026-09-16 19:31 |
| `_ocr_title_adaptive.png` | 18.6 KB | 2026-08-18 09:10 |
| `_ocr_title_gray.png` | 153.5 KB | 2026-08-18 09:10 |
| `_ocr_title_line.png` | 4.6 KB | 2026-08-18 09:40 |
| `_ocr_title_otsu.png` | 13.3 KB | 2026-08-18 09:10 |
| `_t__crop3_banner.tsv` | 1.1 KB | 2026-08-17 21:56 |
| `_t__crop3_br.tsv` | 1.5 KB | 2026-08-17 21:56 |
| `_t__crop_live_banner.tsv` | 3.2 KB | 2026-08-17 21:56 |
| `_t__crop_live_br.tsv` | 1.8 KB | 2026-08-17 21:56 |

### A2 · 一次性探针脚本（`_*.py`）（39 个，103.6 KB）

为定位某个具体问题临时写的脚本，结论已进入正式代码或文档

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_a1.py` | 2.2 KB | 2026-09-17 20:12 |
| `_a2.py` | 1.5 KB | 2026-09-17 20:13 |
| `_a3.py` | 1.7 KB | 2026-09-17 20:14 |
| `_a4.py` | 1.6 KB | 2026-09-17 20:15 |
| `_analyze_level_row.py` | 1.3 KB | 2026-08-18 23:09 |
| `_annotate_grid.py` | 1.2 KB | 2026-08-18 22:31 |
| `_capture_episode.py` | 1.9 KB | 2026-08-16 21:04 |
| `_capture_hero.py` | 901 B | 2026-08-18 22:30 |
| `_card_color_probe.py` | 2.8 KB | 2026-09-16 20:09 |
| `_diag2.py` | 3.3 KB | 2026-09-22 19:14 |
| `_diag3.py` | 2.3 KB | 2026-09-22 19:15 |
| `_diag4.py` | 3.9 KB | 2026-09-22 19:17 |
| `_diag5.py` | 3.8 KB | 2026-09-22 19:17 |
| `_diag6.py` | 4.0 KB | 2026-09-22 19:18 |
| `_diag7.py` | 4.4 KB | 2026-09-22 19:19 |
| `_diag8.py` | 3.5 KB | 2026-09-22 19:23 |
| `_diag_47873.py` | 4.2 KB | 2026-09-22 21:46 |
| `_diag_both.py` | 5.0 KB | 2026-09-22 21:45 |
| `_diag_deep.py` | 2.8 KB | 2026-09-22 19:04 |
| `_diag_dump.py` | 2.1 KB | 2026-09-22 19:05 |
| `_diag_pcap.py` | 3.7 KB | 2026-09-22 19:02 |
| `_diag_poster_score.py` | 2.5 KB | 2026-08-26 23:34 |
| `_diag_rigorous.py` | 5.8 KB | 2026-09-22 20:05 |
| `_diag_stuck_state.py` | 3.5 KB | 2026-08-26 23:58 |
| `_find_confirm.py` | 1.5 KB | 2026-08-18 23:33 |
| `_img_probe.py` | 1.2 KB | 2026-09-16 19:18 |
| `_layout_probe.py` | 4.6 KB | 2026-09-16 20:20 |
| `_make_template.py` | 2.5 KB | 2026-09-16 19:32 |
| `_overlay_level_up_cards.py` | 2.2 KB | 2026-09-16 20:23 |
| `_prep.py` | 3 B | 2026-08-17 21:54 |
| `_resume_probe.py` | 2.6 KB | 2026-09-17 21:35 |
| `_resume_probe2.py` | 3.4 KB | 2026-09-17 21:36 |
| `_resume_probe3.py` | 1.4 KB | 2026-09-17 21:37 |
| `_survivor_probe.py` | 3.4 KB | 2026-09-16 21:35 |
| `_survivor_region_view.py` | 2.7 KB | 2026-09-16 21:37 |
| `_survivor_timing.py` | 3.4 KB | 2026-09-16 23:03 |
| `_verify_episode.py` | 879 B | 2026-08-16 21:12 |
| `_verify_fixes.py` | 2.3 KB | 2026-08-19 08:20 |
| `_verify_theory.py` | 1.6 KB | 2026-08-19 08:10 |

### A3 · 探针输出文本（`_*.txt` / `_*.tsv`）（29 个，56.5 KB）

探针脚本的 stdout 落盘

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_a1.txt` | 3.4 KB | 2026-09-17 20:12 |
| `_a2.txt` | 3.4 KB | 2026-09-17 20:13 |
| `_a3.txt` | 194 B | 2026-09-17 20:14 |
| `_a4.txt` | 771 B | 2026-09-17 20:15 |
| `_cap.txt` | 485 B | 2026-09-16 20:28 |
| `_del.txt` | 1.6 KB | 2026-09-17 20:55 |
| `_diag4.txt` | 611 B | 2026-09-22 19:17 |
| `_diag5.txt` | 2.2 KB | 2026-09-22 19:17 |
| `_diag6.txt` | 2.1 KB | 2026-09-22 19:18 |
| `_diag7.txt` | 1.7 KB | 2026-09-22 19:19 |
| `_diag8.txt` | 1.1 KB | 2026-09-22 19:23 |
| `_diag_47873.txt` | 3.1 KB | 2026-09-22 21:46 |
| `_diag_both.txt` | 8.2 KB | 2026-09-22 21:46 |
| `_diag_deep.txt` | 1.3 KB | 2026-09-22 19:04 |
| `_diag_dump.txt` | 1.4 KB | 2026-09-22 19:05 |
| `_diag_out.txt` | 3.9 KB | 2026-09-17 23:39 |
| `_diag_pcap.txt` | 611 B | 2026-09-22 19:03 |
| `_diag_rigorous.txt` | 1.4 KB | 2026-09-22 20:05 |
| `_diag_scan.txt` | 500 B | 2026-09-22 19:01 |
| `_diagscan.txt` | 645 B | 2026-09-14 20:41 |
| `_dry2.txt` | 300 B | 2026-09-16 23:38 |
| `_mv.txt` | 153 B | 2026-09-16 23:05 |
| `_r1.txt` | 3.6 KB | 2026-09-16 23:35 |
| `_r2.txt` | 104 B | 2026-09-16 23:36 |
| `_r3.txt` | 1.3 KB | 2026-09-16 23:37 |
| `_t6.txt` | 0 B | 2026-09-16 23:16 |
| `_timing.txt` | 815 B | 2026-09-16 23:03 |
| `_verify_tool_check.txt` | 824 B | 2026-09-16 19:51 |
| `_wb_run.txt` | 10.9 KB | 2026-09-22 09:44 |

### A4 · 其他临时图（`_*.png`）（26 个，2.9 MB）

裁剪/标注用的中间图

| 文件 | 体积 | 时间 |
| --- | --- | --- |
| `_wb_br_full.png` | 652.6 KB | 2026-09-21 22:50 |
| `_wb_btn_strip.png` | 124.5 KB | 2026-09-21 22:28 |
| `_wb_btn_team_config.png` | 71.4 KB | 2026-09-21 22:28 |
| `_wb_btn_team_select.png` | 19.1 KB | 2026-09-21 22:28 |
| `_wb_btn_worldboss_home.png` | 17.9 KB | 2026-09-21 22:28 |
| `_wb_btn_worldboss_home_exhausted.png` | 15.3 KB | 2026-09-21 22:28 |
| `_wb_cand_select_team.png` | 11.9 KB | 2026-09-21 22:29 |
| `_wb_count_big_worldboss_home.png` | 83.7 KB | 2026-09-21 22:32 |
| `_wb_count_big_worldboss_home_exhausted.png` | 58.9 KB | 2026-09-21 22:32 |
| `_wb_count_strip.png` | 83.7 KB | 2026-09-21 22:32 |
| `_wb_count_worldboss_home.png` | 8.4 KB | 2026-09-21 22:32 |
| `_wb_count_worldboss_home_exhausted.png` | 6.6 KB | 2026-09-21 22:32 |
| `_wb_lr_full.png` | 342.0 KB | 2026-09-21 22:50 |
| `_wb_pt_battle_result_1036.png` | 5.1 KB | 2026-09-21 22:51 |
| `_wb_pt_level_reward_994.png` | 6.8 KB | 2026-09-21 22:51 |
| `_wb_pt_team_config_1034.png` | 6.7 KB | 2026-09-21 22:51 |
| `_wb_pt_team_config_1036.png` | 7.6 KB | 2026-09-21 22:51 |
| `_wb_pt_team_select_1038.png` | 10.2 KB | 2026-09-21 22:51 |
| `_wb_pt_worldboss_home_1052.png` | 8.5 KB | 2026-09-21 22:51 |
| `_wb_res_battle_result.png` | 29.9 KB | 2026-09-21 22:29 |
| `_wb_res_level_reward.png` | 14.0 KB | 2026-09-21 22:29 |
| `_wb_res_strip.png` | 43.9 KB | 2026-09-21 22:29 |
| `_wb_selbtn.png` | 25.8 KB | 2026-09-21 22:29 |
| `_wb_tc_full.png` | 531.8 KB | 2026-09-21 22:50 |
| `_wb_titles_strip.png` | 298.9 KB | 2026-09-21 22:28 |
| `_wb_ts_full.png` | 518.1 KB | 2026-09-21 22:50 |

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
