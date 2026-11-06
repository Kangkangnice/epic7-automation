"""模板路径解析：把「平台差异」收敛到**图片**这一个维度。

背景
----
PC 客户端与雷电模拟器跑的是**同一套业务代码**：同一个状态机、同一片搜索区域、
同一组点击坐标（两边都先进入 1982x1132 兼容画布）。真正不一样的是**同一块 UI
在两个客户端上的渲染**——字体、抗锯齿、亮度不同，导致同一张模板在另一个客户端上
「长得像但不像到过阈」。

所以正确的做法不是把平台差异写进业务代码（历史包袱：7 个证据模块各有一张
`PC_THRESHOLD_OVERRIDES`，竞技场 / 导航 / 英雄合成里还有就地写死的
`0.85 if backend == "pc" else 0.90`），而是**只换图片**。

本模块就是那个唯一的入口。约定：

    templates/<路线>/xxx.png        ← 模拟器用（也是 PC 的默认）
    templates/<路线>/pc/xxx.png     ← 存在则在 PC 上优先用它

通则是「**当前目录 / pc / 同一段相对路径**」。刷书签 / 幸存者的锚点路径自带前缀
（`shop_refresh/xxx.png`，模板根就是 `templates`），所以它们的 PC 图落在
`templates/pc/shop_refresh/xxx.png` —— 规则一致，只是拼的地方不同。

**没有 `pc/` 里的同名图就自动回落共享图**，所以：
- 绝大多数锚点两边通用，不需要复制；
- 模拟器模板以后改了，PC 不会「忘记同步」——因为它压根没有副本；
- 以后要开发 PC 路线，唯一动作就是往 `pc/` 丢一张同名图，**代码一行都不用动**。

为什么要一个包装类而不是纯函数
------------------------------
全仓有 132 处 `load_template(str(template_dir / "x.png"))`，而 `template_dir`
是各工厂的**局部变量**。有了 `TemplateDir`，工厂入口只要重绑一行，
底下那 132 处一行都不用改。

⚠️ 三个必须保留的语义（踩过的坑）：
- `.name` / `.parent` 必须还原到**原目录**而不是 `pc/` 子目录 ——
  `pre_battle.py` 靠 `template_dir.name in {"story", "fodder", "expedition"}`
  判断路线，一旦 `.name` 变成 `"pc"` 业务就错了。
- `/` 的结果如果是目录，要继续返回 `TemplateDir`，否则
  `hero = template_root / "hero"` 之后再 `/ "x.png"` 会丢掉覆盖能力。
- **目录本身不做覆盖跳转**，只有叶子图片才查 `pc/`。否则
  `root/pc/hero/` 存在时，`root / "hero" / "x.png"` 的回落目标会变成
  `root/pc/hero/x.png`（而共享图在 `root/hero/x.png`），「没放 PC 图就用共享图」
  这条约定会被悄悄破坏 —— 2026-09-28 写离线用例时实测到的。
"""

from __future__ import annotations

from pathlib import Path

# PC 专属图的子目录名。放在共享目录**内部**而不是另开一个镜像根，
# 就是为了「没放图 = 自动跟随共享图」，不产生第二份需要维护的副本。
PC_SUBDIR = "pc"


class TemplateDir:
    """一个模板目录的包装：``dir / "x.png"`` 在 PC 后端下优先取 ``dir/pc/x.png``。

    除了 ``/`` 之外的所有属性（``.name``、``.parent``、``.is_dir()``、``str()``…）
    一律还原到**原目录**，保证它对所有既有代码表现得像一个普通 ``Path``。
    """

    __slots__ = ("_base", "_backend")

    def __init__(self, base, backend: str = "emulator") -> None:
        # 防止 base 已经是 TemplateDir 时 ``Path(base)`` 触发未初始化的 __getattr__。
        source = base.base if isinstance(base, TemplateDir) else base
        self._base = Path(source)
        self._backend = backend

    @property
    def base(self) -> Path:
        """被包装的原始目录（不含 ``pc/`` 覆盖）。"""
        return self._base

    @property
    def backend(self) -> str:
        return self._backend

    def __truediv__(self, name):
        # ⚠️ 目录**不切换**，只有叶子（图片文件）才走覆盖。
        # 早期版本会把 ``root / "hero"`` 解析成 ``root/pc/hero``（当那个目录存在时），
        # 结果再往下取 ``rating_sss.png`` 时，回落目标变成了
        # ``root/pc/hero/rating_sss.png`` —— 图只存在于 ``root/hero/`` 下，
        # 于是「没放 PC 图就用共享图」这条最基本的约定被悄悄破坏。
        # 正确做法是**始终记住共享路径**，每一步都在共享路径上找 ``pc/`` 同名图。
        target = self._base / name
        if self._backend == "pc":
            candidate = self._base / PC_SUBDIR / name
            if candidate.is_file():
                return candidate
        if target.is_dir():
            return TemplateDir(target, self._backend)
        return target

    def __getattr__(self, item: str):
        # 私有属性不代理：否则 ``_base`` 尚未赋值时会无限递归。
        if item.startswith("_"):
            raise AttributeError(item)
        value = getattr(self._base, item)
        # ``.parent`` 必须继续带覆盖能力：狗粮 / 世界首领战 / 战前页都会
        # ``template_dir.parent`` 之后再往下拼子目录，退回纯 Path 就把覆盖断掉了。
        if item == "parent":
            return TemplateDir(value, self._backend)
        return value

    def __fspath__(self) -> str:
        return str(self._base)

    def __str__(self) -> str:
        return str(self._base)

    def __repr__(self) -> str:
        return f"TemplateDir({self._base!s}, backend={self._backend!r})"

    def __eq__(self, other) -> bool:
        if isinstance(other, TemplateDir):
            return self._base == other._base and self._backend == other._backend
        try:
            return self._base == Path(other)
        except TypeError:
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self._base)


def is_template_root(value) -> bool:
    """``True`` = 这是**模板目录**（要现场 build 模板），不是已经 build 好的模板对象。

    ⚠️ 四个状态机（远征 / 世界首领战 / 骑士团捐赠 / 迷宫强化石）的构造函数同时接受
    「目录」和「已建好的模板对象」，靠 ``isinstance(templates, Path)`` 区分。
    ``TemplateDir`` **不是** ``Path`` 子类 —— 刻意不继承：``Path`` 的实例一律由
    ``_from_parts`` 经 ``object.__new__`` 造出来，子类很难安全地带上自己的状态。
    ⇒ 这里显式认两种，业务代码不用知道 ``pc/`` 的存在。

    实测（2026-09-28）：不改这四处的话，实跑时传进去的是 ``TemplateDir``，
    ``isinstance`` 判 False ⇒ 把**目录当成已建好的模板对象**直接赋给
    ``self.templates``，随后读 ``.evidence`` 才炸 —— 属于「类型看着对、语义错了」。
    """
    return isinstance(value, (Path, TemplateDir))


def is_pc(template_dir) -> bool:
    """模板目录是不是 PC 后端。普通 ``Path`` 一律按模拟器处理。

    PC 移植新增的判据 / 状态分支只在这一项为真时启用；模拟器传进来的
    要么是 ``TemplateDir(..., "emulator")``、要么是普通 ``Path``，都会走原路径。
    """
    return getattr(template_dir, "backend", "emulator") == "pc"


def resolve_template_dir(base, backend: str = "emulator") -> TemplateDir:
    """把一个模板目录包成「会按平台挑图」的目录。

    工厂入口用法（一行）：
        ``template_dir = resolve_template_dir(template_dir, backend)``
    之后函数体里所有 ``template_dir / "x.png"`` 自动生效，不用再改。
    """
    return TemplateDir(base, backend)


def resolve_template(base, relative_path: str, backend: str = "emulator") -> Path:
    """解析单张模板：``base/pc/<相对路径>`` 存在就用它，否则用 ``base/<相对路径>``。

    给「手上只有目录 + 相对路径」的场合用（例如 ``AtomEvidence.template_path``
    的拼接点），不需要包装对象。
    """
    shared = Path(base) / relative_path
    if backend != "pc":
        return shared
    override = Path(base) / PC_SUBDIR / relative_path
    return override if override.is_file() else shared
