---
status: accepted
date: 2026-11-08
deciders: 用户（提出质疑）
supersedes:
superseded_by:
---

# 0005. 进行中的交接单放在 `docs/wip/`，合并即删

## 背景

[0004](0004-four-channels-for-docs.md) 定下「交接说明不进仓库」。**那一条切得太宽了。**

用户当天追问：新增一条路线做到一半、因为超时或被叫停停下来了，让 agent 写交接文档，
它该写在哪？而且打开 `docs/STATUS.md` 只能看到「已经合入代码的事实」，**半成品完全隐形**。

这是真问题，不是形式问题。agent 被中断是常态（超时、用户叫停、上下文用尽），
后果很具体：

- 下一个人只能去读**未提交的 diff** 猜意图，不知道哪些改动是刻意的、哪些是半路状态；
- 已经试过、失败的做法没有被记下来，会原地重试一遍；
- `STATUS.md` 看起来一切正常，实际有活干了一半 —— 这比报错更危险。

## 决定

新增第五个通道：**在制品交接单**，位置 `docs/wip/`。

- 文件名 `YYYY-MM-DD-<英文短名>.md`，模板 [`docs/wip/_TEMPLATE.md`](../../docs/wip/_TEMPLATE.md)。
- 必填元数据：`route` / `status`（`in-progress` | `blocked` | `abandoned`）/ `owner` /
  `started` / `next_step`。**没有 `done`** —— 做完了就直接删，不要留一份「已完成」的交接单。
- **自动出现在 `docs/STATUS.md` 的「在制品」一节**（生成器扫目录，按文件名排序），
  带状态、开始日期、下一步。这一节有条目就说明有活没干完。
- **不登记到 `docs/README.md` 索引**：它是临时凭证，开户/收尾都要改索引太吵。
  由门禁单独校验元数据。
- **合并进 main 之后删掉**：结论进提交信息、`CHANGELOG.md`、`docs/decisions/` 或
  `docs/maintenance/<路线>.md`。

## 后果

- 换个会话、换个人、换个 agent，打开 `STATUS.md` 就知道从哪接。
- 代价是 wip 会堆。**这是有意接受的**：`STATUS.md` 里带 `started` 日期，
  堆着不清理一眼就能看出来（一排两周前的日期）。真要做成硬约束，
  可以加「`started` 超过 N 天且 `status=in-progress` 就警告」，暂未加 —— 那属于催办，不属于正确性。
- 交接单的元数据由 `tests/test_docs_index.py` 校验，缺字段或文件名不合规会红。

## 考虑过但被否掉的方案

| 方案 | 为什么没选 |
|---|---|
| 写进 `.workbuddy/memory/` | 那是 agent 私人记忆，按天流水、不结构化，交接给「另一个 agent」时没人知道去哪找，也进不了 `STATUS.md` |
| 写进 GitHub Issue / PR 草稿 | 单机开发不常开 issue；而且 agent 未必有网络与权限，交接必须离线可读 |
| 干脆不写，让它把 diff 留在工作区 | 试过。代价是下一个人重做一遍，且分不清「刻意改的」和「改到一半」 |
| 标 `status: done` 保留在 wip 里 | 会让 wip 变成第二个「过期文档坟场」。做完就删，历史在提交信息里 |
