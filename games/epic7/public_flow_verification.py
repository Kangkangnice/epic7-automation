"""公共流程的「动作验收」表态清单 + 加载期自查。

## 这是什么，为什么要有它

项目里有一条硬规矩：**每个动作都要长眼睛**
（点/按完必须回头看，确认这一下真的生效了，不能靠等待时间糊）。

惯例的落地在 ``runner_base._require_transition_contract``：路线 Runner 经
``machine.next_action()`` 发的动作，必须带 ``source_page`` + ``target_pages`` /
``in_page_evidence``，缺了直接报错。``modes._assert_transition_stance_declared``
负责让每条路线对这件事**表态**（开开关，或进豁免名单写清理由）。

⚠️ **但那套机制管不到「公共流程」** —— 这是 2026-09-25 实跑翻车暴露的盲区：

``navigation.return_home`` / ``home_return.return_home_v2`` / ``global_popups`` /
``unknown_screen`` 这些模块**同样在发动作、同样需要长眼睛**，但它们的动作
**不经过任何路线的 ``machine.next_action()``**，所以：

- 不用打开 ``_REQUIRE_TRANSITION_CONTRACT``；
- 不用进 ``TRANSITION_EXEMPT``；
- 动作点完不回头 → **不报错、空跑也不拦、加载期自查也不管**。

而 ``return_home_v2`` 2026-09-25 重写时正好丢了老实现的验收，于是实跑出现
「同一层连按两次 ESC」白烧返回预算。**没有任何机制能拦下这个改动。**

## 这个模块干什么

把公共流程也拉进同一套「表态」规矩：

- ``PUBLIC_FLOW_VERIFICATION``：**模块 -> 表态**，每一条要么写清「用什么机制验收」，
  要么写明「为什么不需要」（豁免要写理由，形状与 ``RESUME_EXEMPT`` / ``TRANSITION_EXEMPT`` 一致）。
- ``assert_public_flow_verification_declared()``：加载期自查，遍历
  ``ACTION_BEARING_MODULES``（**实际带动作的公共流程模块，写死在这里**），
  逐个要求在表态表里出现；**两边都写、两边都不写、或写了个不存在的模块，都报错**。
- ``assert_module_inventory_matches()``：**反向护栏** —— 拿真实源码扫一遍，
  确认「带动作的公共流程模块」清单没有漏登记。这条防的是「新写了个公共流程模块，
  忘了加进清单」，因为那种漏登记**不会让任何测试变红**，只会让护栏悄悄失效。

## 边界（刻意不做的）

- **不管路线 Runner**：那是 ``runner_base`` + ``modes`` 的职责，各有各的表。
- **不查判据准不准**：判据准不准要靠拿真夹具跑（各模块自己的测试），
  这里只查「有没有表态」—— 与 ``_assert_resume_declared`` 的定位一致。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

__all__ = [
    "ACTION_BEARING_MODULES",
    "PUBLIC_FLOW_VERIFICATION",
    "PublicFlowVerification",
    "assert_public_flow_verification_declared",
    "assert_module_inventory_matches",
    "route_module_names",
]


@dataclass(frozen=True)
class PublicFlowVerification:
    """一条公共流程的表态。

    ``mechanism`` 与 ``exempt_reason`` **二选一**（都写或都不写都报错）：

    - ``mechanism``：**用什么机制验收动作**。必须写清是哪个判据
      （如 ``StableObservation`` / ``left_page`` / 自带稳定判定）。
    - ``exempt_reason``：**为什么不需要验收**。不许写「暂时没有」这种空话 ——
      豁免的代价是这里失去保护，所以理由要能站住。

    ``actions``：该模块**发动作的行号**（仅作文档用途，便于人对照；
    不参与自动校验 —— 行号会随改动漂移，硬校验会变成噪声）。
    """

    module: str
    mechanism: Optional[str] = None
    exempt_reason: Optional[str] = None
    actions: str = ""


# ---- 实际带动作的公共流程模块（写死，供反向护栏对照） -------------------------
#
# 判定标准：**模块自己直接调用 ``runtime.click/back/swipe``**。
# 只是「被别的模块调用」不算（如 ``finish_home`` 只加载期自查、不发动作）。
#
# ⚠️ 新写一个带动作的公共流程模块，必须同时加到这里和 ``PUBLIC_FLOW_VERIFICATION``；
# 只加一处会被 ``assert_module_inventory_matches`` 拦下。
ACTION_BEARING_MODULES = frozenset(
    {
        "navigation.py",
        "home_return.py",
        "global_popups.py",
    }
)
# ⚠️ 这里原来有 ``unknown_screen.py``（它会「点屏幕中央唤醒」）。2026-09-26
# 那次改动把「点中央」整段删掉了（用户抓包的「眼睛瞎了一直点中间」：点中央没有判据、
# 常常落在列表空白处）⇒ 它现在**不发任何动作**，只剩「等稳定 + 记诊断 + 交还上层」。
# 反向护栏 ``assert_module_inventory_matches`` 会扫源码，所以它必须从这里划掉。


# ---- 表态清单 ----------------------------------------------------------------
#
# 形状刻意与 ``modes.RESUME_EXEMPT`` / ``modes.TRANSITION_EXEMPT`` 一致
# （一份表 + 一句理由 + 加载期自查），因为它们回答的是同一类问题：
# **这块代码对「动作要不要长眼睛」表过态没有。**
PUBLIC_FLOW_VERIFICATION = {
    "navigation.py": PublicFlowVerification(
        module="navigation.py",
        mechanism=(
            "① ``_transition`` 走严格口径 `left_page` + `_CLICK_VERIFY_SECONDS=8`"
            "（导航链上每一跳都走它）；"
            "② ``_dismiss_roadblock`` 里的关弹窗/剧情回退沿用原来的验收；"
            "③ ``return_home`` **自己不再有动作**——2026-09-26 起它整段转发给 "
            "``home_return.return_home_v2``（老循环已删），验收由 v2 的 "
            "``_ActionVerifier`` 负责，见下面 ``home_return.py`` 那条。"
            "⚠️ 老实现的 ``_BACK_RETRY_SECONDS``/``page_or_picture_changed`` 回比"
            "已经不在调用链上，别照着旧描述找它。"
        ),
        actions=(
            "_transition 有多处调用点（导航链每一跳）；"
            "_dismiss_roadblock: 640(_dismiss_global_popup)/685(_recover_story)"
        ),
    ),
    "home_return.py": PublicFlowVerification(
        module="home_return.py",
        mechanism=(
            "**v2 走「动作前记页面身份、动作后等身份确实变了」**："
            "``return_home_v2`` 吃一个 ``observe`` 回调（由 ``main.HomeReturn`` "
            "传 ``navigator.observe(...).name``）；5 处动作全部经 ``_ActionVerifier`` "
            "验收；判「无效」时**不重复同一个动作**，改换路或报错。"
            "无 ``observe`` 时降级为整帧比对 ``_StableTwo``，**并记日志说明降级**。"
        ),
        actions="return_home_v2: 305/329/343/357；_press_esc: 388",
    ),
    "global_popups.py": PublicFlowVerification(
        module="global_popups.py",
        mechanism=(
            "自带「弹窗身份」级验收：点后重截图重新 `_find_popup`，"
            "要求**连续 2 帧命中同一弹窗**才点，弹窗消失即返回；"
            "另有 4 次上限 + 15 秒熔断。⚠️ 身份是**弹窗名**（如 `knights_signin`），"
            "不是 navigation 的页面名 —— 对「关弹窗」这个用途足够（目标就是它消失）。"
        ),
        actions="509: __call__ 关闭各类全局弹窗",
    ),
}


def assert_public_flow_verification_declared() -> None:
    """加载期自查：每个带动作的公共流程模块都必须表态。

    三种失败都会 ``raise``（fail-closed）：

    1. 模块在 ``ACTION_BEARING_MODULES`` 里、却不在 ``PUBLIC_FLOW_VERIFICATION`` 里
       —— **漏表态**（2026-09-25 `return_home_v2` 就是这种情况：新写的流程，
       没有任何机制要求它对验收表态，于是丢了眼睛也没人拦）；
    2. 模块在表态表里、却不在 ``ACTION_BEARING_MODULES`` 里 —— 表与清单不一致；
    3. 一条表态里 ``mechanism`` 与 ``exempt_reason`` **都写或都不写** ——
       两者只能选一个（与 ``RESUME_EXEMPT`` / ``TRANSITION_EXEMPT`` 同一规矩）。

    ⚠️ 只查结构，不跑判据。判据准不准要靠各模块自己的真夹具测试。
    """
    for name in sorted(ACTION_BEARING_MODULES):
        declared = PUBLIC_FLOW_VERIFICATION.get(name)
        if declared is None:
            raise RuntimeError(
                f"公共流程模块 {name} 带有模拟器动作，却没有对「动作验收」表态。"
                "请在 PUBLIC_FLOW_VERIFICATION 里写清「用什么机制验收」"
                "或「为什么不需要验收」；规矩见 docs/TRANSITION_CONTRACTS.md"
                "「公共流程也要长眼睛」。"
            )
    for name, declared in PUBLIC_FLOW_VERIFICATION.items():
        if name not in ACTION_BEARING_MODULES:
            raise RuntimeError(
                f"PUBLIC_FLOW_VERIFICATION 里有 {name}，但它不在 "
                "ACTION_BEARING_MODULES 清单里；两处必须一致。"
            )
        has_mechanism = bool(declared.mechanism)
        has_exempt = bool(declared.exempt_reason)
        if has_mechanism == has_exempt:
            raise RuntimeError(
                f"公共流程 {name} 的验收表态必须**二选一**："
                "写 `mechanism`（用什么机制验收）或 `exempt_reason`（为什么不需要），"
                "不能都写、也不能都不写。"
            )


def route_module_names() -> frozenset[str]:
    """各路线 Runner 所在的**模块文件名**（这些模块由路线级那几张表管，不是公共流程）。

    ⚠️ 从 ``modes.MODE_SPECS`` **派生**，不再手工维护那份清单。
    手工那份在 2026-10-06 加社区签到时就被漏掉了 —— 后果不是「测试漏跑」，而是**反向**的：
    新路线的模块只要碰一下 ``runtime.click`` 就会撞上本模块的反向护栏，被误报成
    「带动作但没登记进 ACTION_BEARING_MODULES」，让人以为公共流程清单少了东西。
    派生之后这类误报不会再出现（``test_public_flow_verification`` 也读同一个函数，
    两处不会各写一份）。

    惰性 import：本模块是纯数据模块，顶层 import ``modes`` 会把整条路线链拉进来。
    """
    from auto_game_unified.games.epic7.modes import MODE_SPECS

    names = set()
    for spec in MODE_SPECS.values():
        module = getattr(spec.runner_type, "__module__", "")
        if module:
            names.add(f"{module.rsplit('.', 1)[-1]}.py")
    return frozenset(names)


def assert_module_inventory_matches(package_dir: Path) -> None:
    """反向护栏：源码里实际带动作的公共流程模块，必须都在 ``ACTION_BEARING_MODULES`` 里。

    ⚠️ 这条防的是**最阴的一种漏**：新写了个公共流程模块、忘了登记。
    那种漏**不会让任何测试变红**，只会让上面那条自查悄悄少管一块代码 ——
    看起来护栏还在，其实已经漏了。所以这里拿真实源码扫一遍，两边对不上就报错。

    扫描口径：``games/epic7/`` 下，**不含** ``_`` 开头的文件、不含 ``modes.py``
    （那是路线准入的表，不是公共流程）、不含各路线模块、也不含**两族的 Runner 基类**
    （``runner_base.py`` / ``transactional_runner_base.py``）—— 那些由 ``runner_base``
    与 ``modes`` 的契约管，不在本模块的职责内。

    ⚠️ **用 AST 解析，不用字符串匹配** —— 这个决定是实测逼出来的：
    本模块自己的 docstring 里就写着 ``runtime.click(``，
    字符串匹配会把它当成"带动作的模块"（一写出来就误报）。
    AST 只认**真正的调用节点**，注释与文档字符串天然被排除。
    """

    routes = route_module_names()
    # ⚠️ 两个 Runner 基类都在 skip 里：它们是**路线 Runner 的骨架**，不是公共流程。
    # 它们的动作验收口径由 ``modes.TRANSITION_EXEMPT`` / ``CONCLUSION_GATE_DECLARATION``
    # 与 ``finish_home`` 三张路线级表管（2026-09-26 新增 ``transactional_runner_base.py``
    # 时漏了这一格，``test_every_action_bearing_module_is_declared`` 当场变红）。
    skip = {
        "modes.py",
        "runner_base.py",
        "transactional_runner_base.py",
        "__init__.py",
        Path(__file__).name,
    }
    action_calls = {"click", "back", "swipe"}

    found: set[str] = set()
    for path in sorted(package_dir.glob("*.py")):
        name = path.name
        if name.startswith("_") or name in skip or name in routes:
            continue
        if _calls_runtime_action(path, action_calls):
            found.add(name)

    missing = found - set(ACTION_BEARING_MODULES)
    extra = set(ACTION_BEARING_MODULES) - found
    if missing:
        raise RuntimeError(
            f"这些模块带了模拟器动作，但没登记进 ACTION_BEARING_MODULES："
            f"{sorted(missing)}。登记后还要在 PUBLIC_FLOW_VERIFICATION 里表态"
            "（写清用什么机制验收，或为什么不需要）。"
        )
    if extra:
        raise RuntimeError(
            f"ACTION_BEARING_MODULES 里这些模块扫不到动作：{sorted(extra)}。"
            "要么动作被移走了（那就从清单和表态表里划掉），要么扫描口径要跟着更新。"
        )


def _calls_runtime_action(path: Path, action_calls: set[str]) -> bool:
    """这个文件里有没有真正的 ``X.click(...)`` / ``X.back(...)`` / ``X.swipe(...)`` 调用。

    ⚠️ **用 AST 而不是字符串匹配**：字符串匹配会把 docstring / 注释里提到的
    ``runtime.click(`` 也算上（本模块自己就中过这个招）。AST 只认调用节点。

    只要求「属性名是这三个之一」而不要求接收者一定叫 ``runtime``：
    实际代码里有 ``self.runtime.click`` / ``runtime.click`` 两种写法，
    钉死接收者名字会漏掉真调用 —— 而这里的目标恰恰是**宁滥勿缺**（漏了护栏就失效）。
    """

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # 语法错的文件交给编译检查去报，这里不重复报
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in action_calls:
            return True
    return False
