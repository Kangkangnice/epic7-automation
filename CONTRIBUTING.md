# 参与贡献

欢迎提交 Issue 和 Pull Request。本项目是**个人维护的免费开源工具**，评审以「长期能不能维护」为准，不以「功能多不多」为准。

## 先读这三份

| 想做什么 | 先读 |
|---|---|
| 新增一条自动化路线 | [docs/EXTENDING.md](docs/EXTENDING.md) |
| 修改识别、点击、导航、重试逻辑 | [AGENTS.md](AGENTS.md) 与 [docs/TRANSITION_CONTRACTS.md](docs/TRANSITION_CONTRACTS.md) |
| 只是使用、遇到报错 | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) 与 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |

## 本项目接受什么

- 修复某条路线在真实游戏画面上认不出 / 点错 / 卡住的问题（**必须附现场帧**）；
- 新增一条「每天都要做、很枯燥」的 PVE 日常路线；
- 游戏改版后的模板更新与判据修复；
- 桌面界面、日志、诊断、文档的改进。

## 本项目不接受什么

- **PVP 自动对战**。本项目定位是 PVE 视觉辅助；
- 读取游戏内存、修改客户端文件、改网络数据包、反检测或绕过游戏安全机制；
- 自动购买钻石 / 人民币等付费货币的路径（现有路线里凡是涉及付费货币的分支都是**永久禁止**或**只取消不购买**）；
- 上传日志、截图、遥测到任何服务器的功能（本项目默认完全本地运行）；
- 「顺便重构一下」的大范围改动。评审会要求拆成可独立验证的小步。

## 本地环境

- Windows 64 位；
- Python 3.10 及以上；
- 仓库目录必须叫 `auto_game_unified`，并且**从它的父目录**运行：

```powershell
cd D:\AI\codex\auto_game
python -m pip install -r auto_game_unified\requirements-dev.txt
python -u -m auto_game_unified.desktop
```

直接跑 `auto_game_unified/main.py` 会因为包导入路径失败，这是预期行为，不是 bug。

## 跑测试

```powershell
cd D:\AI\codex\auto_game\auto_game_unified
python -m pytest -q
python -m compileall -q .
python -m ruff check .
python -m mypy
```

提交门禁是仓库自带的 `tools/check.py`，它按**改动范围**决定跑什么：

| 改了什么 | 跑什么 | 大约多久 |
|---|---|---|
| 只有文档 / `.github/` / 图片 | 只做编译检查 | 几秒 |
| 单条路线的模块与它的测试 | 该路线的测试 | 1~2 分钟 |
| **共享模块**（`core/`、`desktop/`、`main.py`、`modes.py`、`navigation.py` 等） | **全量** | 约 14 分钟 |

装钩子（每个 clone 各装一次）：

```powershell
python auto_game_unified/tools/check.py --install-hook
```

**提交那一次由钩子跑，不要手工先跑一遍再提交** —— 同一份暂存内容、同一套测试，会白等一次全量。手工跑 `check.py` 只用于开发中途想看结果。

`git commit --no-verify` **默认禁止**：钩子是这套流程里唯一的强制关卡。

## 打包（改动了打包配置才需要）

```powershell
python packaging/build.py
```

它会做四件事：PyInstaller 目录版打包 → 确认 spec 剔掉的 videoio ffmpeg 二进制
真没进产物 → 跑一次 `Epic7AutoAssistant.exe --self-check`（检查产物目录可写、
模板在不在、十五条路线能不能全部加载）→ 打免安装 ZIP 并写 `SHA256SUMS.txt`。
产物在 `packaging/dist/`（已 gitignore，不进历史）。

`--no-build` 复用已有目录版，只重打 ZIP；`--skip-smoke` 跳过自检。

**默认只出免安装版**（2026-10-20 起，用户拍板）：用户解压 ZIP、双击 `Epic7AutoAssistant.exe`
就能跑。想要安装包再加 `--installer`，那一步要 **Inno Setup 6**，没装就自动跳过。单独编也可以：

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "/DMyAppVersion=0.1.0" packaging\installer.iss
```

在 Git Bash 里调 ISCC 必须加 `MSYS2_ARG_CONV_EXCL='*'`，否则 `/D...` 会被当成路径转换，
报 `You may not specify more than one script filename`。

四个容易踩的点：

- 打包版的运行产物写在 `%LOCALAPPDATA%\Epic7AutoAssistant`，源码运行仍写在仓库目录 ——
  规则在 `core/data_paths.py`，别在别处再写一份；
- `modes.py` 的加载期自查要用 `inspect.getsource` 读源码，所以 spec 里
  `module_collection_mode={"auto_game_unified": "py"}` **不能改成压 pyc**，
  否则打包版一启动就 `OSError: could not get source code`；
- `installer.iss` 必须是 **UTF-8 带 BOM**，否则 Inno 按 ANSI 读，中文全乱码；
- `packaging/languages/ChineseSimplified.isl` **不要删**。Inno 官方发行版不带简体中文，
  这份是从 issrc 的 `Files/Languages/Unofficial/` 取的第三方翻译，`installer.iss`
  的 `[Languages]` 直接引它。删了脚本编不过。

安装版的行为（改 `installer.iss` 前先确认这几点仍然成立）：

- **按用户安装、不提权**：`PrivilegesRequired=lowest` 时 `{autopf}` 自动展开成
  `%LOCALAPPDATA%\Programs\Epic7AutoAssistant`，全程不弹 UAC，非管理员账户也能装。
  想装到 `Program Files` 得显式传 `/ALLUSERS`；
- **卸载保留用户数据**：`%LOCALAPPDATA%\Epic7AutoAssistant` 下的日志与诊断不删，
  那是用户自己的运行记录；
- 打完包至少走一遍「装 → 跑 `--self-check` → 卸」，别只看 ISCC 返回 0 就当成能用。

## 新增一条路线的准入条件

缺任何一样都算没做完：

1. **模板**：放进 `games/epic7/templates/<路线>/`，从当前客户端真实画面裁切，基准画布 `1982 x 1132`；
2. **区域**：每个模板都必须有搜索区域，禁止整屏盲找；
3. **判据**：能证伪 —— 要说得清「靠哪一维把外观相似、语义不同的页面/按钮分开」，不是把阈值调小一点；
4. **夹具**：真机帧放进 `tests/fixtures/epic7_<路线>/`，每个页面至少一张正样本，另附能区分相邻页面的负样本；
5. **状态机与 Runner**：优先复用 `runner_base` / `transactional_runner_base` / `battle_controls` / `pre_battle` / `global_popups`，不要自己再造一套；
6. **测试**：覆盖页面唯一性、转场契约、资源耗尽与失败关闭；
7. **登记**：`modes.py`、`desktop/catalog.py`、`navigation.py`、`tools/check.py` 的 `ROUTE_KEYWORDS` 四处都要登记。

**失败关闭是底线**：认不出的页面不许猜、不许连点、不许「等超时算过」。认不出就保存诊断并停下，退出码 `1`。

## 素材规范

- 模板**不许包含会变的内容**：玩家昵称、体力数值、金币钻石余额、时间、随机角色名；
- 判据型模板**没有「可选」这一档** —— 文件缺失必须让程序在加载期就报错，不能静默降级；
- 新增或替换图片，`git add` 之后、提交之前跑一次无损压缩：

```powershell
python tools/compress_images.py --staged --apply
git add <刚压过的文件>
```

不要拿它「顺手压一遍存量」：历史里的旧 blob 一个不少，`git clone` 反而更大。

## 提交信息

采用 `类型(范围): 一句话`，正文用中文写清「为什么改」：

```
fix(epic7): 战斗菜单判页按「哪个标签被选中」分三页 —— 修迷宫强化石误判
feat(desktop): 每日任务面板三分组 + 批量勾选
docs(chore): 竞技场实跑记录更新；README 与手册同步
```

## 提交 PR 前自检

- [ ] 没有提交 `runtime_logs/`、`runtime_diagnostics/` 里的运行产物；
- [ ] 没有提交包含个人信息的截图（昵称、QQ、角色名）；
- [ ] 没有把环境变量、Token、AppSecret 写进代码或文档；
- [ ] 没有删除 `tests/fixtures/` 里被其它测试引用的图；
- [ ] 改了共享模块的话，知道这次提交会跑全量；
- [ ] 文档跟着代码一起改（README / 用户手册 / 路线矩阵）。

## 许可证

提交即表示你同意以 [MIT License](LICENSE) 授权你的贡献。
注意：MIT 只覆盖原创代码，**不覆盖游戏画面与从中裁切的模板**，详见 [NOTICE.md](NOTICE.md)。
