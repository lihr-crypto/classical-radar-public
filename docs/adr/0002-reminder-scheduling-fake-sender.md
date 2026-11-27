# ADR-0002 — 提醒调度与本地假发送器

日期：2026-11-09。状态：采纳（HANDOFF「下一轮任务」第 5 项；动手前经评审，评审意见已并入下表）。范围严格限定在 `03_CONTRACTS.md` 3.6：只做**调度**和**本地假发送器**，不外发邮件、不推送、不装定时任务、不花钱。

## 做了什么

| 议题 | 决定 | 理由 / 后果 |
|---|---|---|
| 模型 | **对账（reconcile）**：`reminders.reconcile(conn, subscription_id, now)` 根据订阅与票务阶段的当前状态算出“应不应该有一条投递”，再让 `notification_delivery` 与之一致。开关、改期、取消、过期都走同一个函数 | 重放、重试、重复点击都不会产生第二条投递；改时间/改提前量自然让旧投递作废（T13） |
| `dedupe_key` | `rem:` + sha256(`订阅id｜里程碑｜目标时刻(UTC)｜提前分钟`)[:32]；`INSERT OR IGNORE` + 表上已有的 UNIQUE | 同一个 (订阅, 目标时刻, 提前量) 永远只有一行；A→B→A 时旧行从 `cancelled` 复活，不撞唯一约束 |
| 何时应有投递 | 订阅已开启，**且**对应里程碑是 `exact_time`，**且**公演与节目都是 `official_confirmed`，**且**票务阶段 `channel` 为 `official` / `official_presenter`，**且**公演状态为 `scheduled`，**且**里程碑时刻没有过去超过 10 分钟 | `postponed` / `cancelled` / `needs_review`（来源里消失）都不再提醒。**channel 门槛是比契约字面更严的决定**：契约说“可信官方来源”，这里理解为官方售票渠道；`other` 渠道的阶段不能开启 |
| 不再需要的行 | 该订阅下**其余所有 `pending` 与 `failed`** 的行一律改为 `cancelled` 并写原因；`sent` 行是历史，永不改动，也永不删除 | 评审指出的坑：只取消 `pending` 会让“失败待重试”的旧行在用户改了提前量或退订后仍被发出 |
| 过期 | 目标时刻 + 10 分钟（`GRACE`）之后不再发；提前量为 0 的提醒在开售那一刻仍能发出。过期行被取消并写 `missed: …`，之后不会因为对账又“复活” | 过期本身就是“应有投递”的一个条件，所以不会来回抖动；不发过时提醒 |
| 开启时的拦截 | 开启已经过期的里程碑返回 422（“nothing left to remind”）；关闭永远允许 | 否则界面显示“已设置”但永远不会响，是静默失败 |
| 发送器 | `Sender` 协议 `send(delivery) -> provider_id`，失败抛异常；`FakeSender` 只把一行 JSON 追加到本地 outbox 文件，不碰网络 | 契约 3.6：真实发送需要用户明确许可，POC 用本地假发送器 |
| 运行 | `run_due(conn, now, sender)`：先对账，再发送所有 `scheduled_for <= now` 的 `pending`（和默认的 `failed` 重试）；逐行提交。CLI：`classical-radar remind-run DB [--now ISO] [--outbox PATH] [--no-retry]` | **手动运行，没有安装任何调度器**。失败会一直重试，直到里程碑过期被取消；没有次数上限 |
| 送达语义 | **至少一次**。发送成功与“记为已发送”之间崩溃会重发；单机单进程运行，没有 `sending` 中间态 | 契约原话：第三方可能超时，不能保证恰好一次，只记录状态与可恢复失败，不宣称不会重复 |
| 对账触发点 | `put_reminder`（用户开关）、`ingest_ticket_phases`（时间变更）、`sync_source` 结束时（公演被取消/改期）、`run_due` 开头（兜底） | 任何路径漏掉都会在下一次 `remind-run` 前被兜底纠正 |
| 读侧 | `GET /concerts/{id}` 每个票务阶段新增 `reminder`：`{milestone, offset_minutes, enabled}` 或 `null`（只看当前用户的 `sale_start` 订阅）。界面代码不用改（`app.js` 本来就读 `t.reminder`） | 这是对 3.4 响应的**增量字段**；修复了“真实后端刷新后提醒按钮回到未设置”的老毛病（之前只有 demo 模式能保存） |
| 库表 | `UNIQUE(user_id, ticket_phase_id, milestone)` 索引；`notification_delivery(status, scheduled_for)` 索引；新库的 `status` 有 CHECK（`pending/sent/failed/cancelled`） | 老库补不了 CHECK（SQLite 限制），Python 层用同一个集合约束。`db.init` 建唯一索引前会先合并历史重复订阅（保留启用的那条，投递改挂到它名下） |

## 没做（以及为什么）

- **真实发送、定时调度**：需要用户明确授权；`remind-run` 必须手动跑。
- **`sale_end` 提醒**：入库一律把 `end_precision` 写成 `unknown`，所以现在开不了；代码路径已支持，等解析出结束时刻再开。
- **Cloudflare Pages 上的个人状态**（`functions/api/me/[[path]].js`）：它把状态存在 KV，没有票务阶段查询，也没有精确时刻/渠道门槛，**线上站点的“提醒我”不会产生任何投递**。这是已知缺口，不要把 T13 理解成线上端到端可用。
- `result` / `payment_due` 里程碑、多用户、跨源重复复核（第 4 项）、持续监测（第 6 项）。
