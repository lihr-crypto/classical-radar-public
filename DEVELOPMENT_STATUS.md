# 开发状态

更新日期：2026-11-11，Asia/Tokyo。

**数据链路 GO；自动定时采集/真实提醒发送 NO-GO（未授权、未安装）。** `main` 已含 v0.1 初版、作品/作曲家等筛选、四家详情级解析、按你的设计稿重做的网页界面（PR #4），以及 2026-11-10 合并并部署的**提醒调度 + 本地假发送器**（[ADR-0002](docs/adr/0002-reminder-scheduling-fake-sender.md)）、**跨源重复复核**（[ADR-0003](docs/adr/0003-cross-source-duplicate-review.md)）、**持续监测机制与 P0.3 测量**（[ADR-0004](docs/adr/0004-monitoring-and-p03-measurements.md)）、**开售时刻解析**（[ADR-0005](docs/adr/0005-sale-time-parsing.md)）（PR #5、#6）。分支 `feat/sale-end-and-merged-cards` 在其上加了**已确认重复卡的主卡显示**（[ADR-0006](docs/adr/0006-merged-cards-for-confirmed-duplicates.md)）。交接清单第 1–6 项已做；第 7 项部分完成（Japan Arts 余下页只做了程序比对；KAJIMOTO 核对未做）。2026-11-11 你定了三件事：重复卡以乐团/主办方官网为主卡；多场演出页的开售时刻继续不挂；定时监测与真实发送先只出方案。

| 项目 | 当前事实 |
|---|---|
| 仓库 | [lihr-crypto/classical-radar-public](https://github.com/lihr-crypto/classical-radar-public)；`main` = b728302（PR #5） |
| 需求/契约依据 | [`docs/handoff-v1.5/`](docs/handoff-v1.5/)；[契约核对](docs/reports/CONTRACT_RECONCILIATION.md) |
| 数据与来源 | 十源登记，六源可同步（东京爱乐移出范围，都响不遍历）；来源政策全部 unknown，都响 restricted；实网证据见 [P0.2 报告](docs/reports/P0_2_COVERAGE.md) |
| 数据库/API | 本地 SQLite；`api.py` 实现 3.4 全部路由（含增量字段）；单用户令牌；OpenAPI 在 `/openapi.json` |
| 界面 | `web/`：无构建原生 JS 单页，严格 CSP；发现/详情/日历/我的/待确认；线上版个人状态存在浏览器/KV |
| 提醒 | 本地：开启 → 排一条 `notification_delivery`（`dedupe_key` 唯一）→ `classical-radar remind-run` 手动交给假发送器（写 outbox 文件）。**不外发、无定时器、线上 Pages 站点不产生投递** |
| 重复复核 | 待确认队列提示“可能重复”，人工标“同一场（隐藏这条）/不是同一场”，可撤销。**已确认的两张卡**（线上数据现有 9 对）：待确认页另列一块，人工选主卡（建议乐团/主办方官网）后，发现页和日历只显示主卡，主卡带“其他来源”；两张卡的详情、收藏、提醒、售票阶段都不动。决定存 `site-data/same_concert.json`，站点构建时套用。**该文件目前是空的：9 对要你逐对确认后才写入** |
| 自动化验证 | Python 离线测试（全套见 CI）+ 2 个 JS 套件 + `check_evidence.py` / `check_p02_evidence.py` / `check_p03_evidence.py`；OpenAPI 快照 `docs/openapi.json` 由测试比对；CI 为离线检查，不联网采集 |
| 监测 | `monitor`（手动、6 小时最小间隔、都响硬排除）+ `monitor-report`（延迟上界；有页面修改时间的 5 个来源才有官网变更时间）。**没有跑过真实长期数据，没有定时器** |
| 首次公布日期 | P0.3 实测：Japan Arts 42/42、东京交响乐团 8/8、神奈川艺术协会 8/8 的页面有发布时间（CMS 页面发布时间，不等于首次公布）；其余只有更新时间或无日期。`official_announcement_date` 仍未写入 |
| 开售时刻 | Japan Arts / 东响 / 神奈川（含套票）已补解析（[ADR-0005](docs/adr/0005-sale-time-parsing.md)）：没写年份时由星期定年份，每条带 `year_basis`；单场演出才挂到场次，同页有同名重复行也不挂。**已做一次真实同步（临时库，186 个请求）**，它暴露了解析的漏读（东响 10/69 场有阶段）；修好后用同一批缓存详情页重放（列表页重新取，另 36 个请求，不是第二次完整抓取）得到：东响 37/69 场演出有开售阶段、神奈川 62/63（原来 57）、Japan Arts 29/55（不变）；去重后的未来开售时刻只有几十个（东响 12、神奈川 9、Japan Arts 5） |
| 海外乐团来日线索 | 2026-11-12 起用 オケミン！（第三方整理站）作为**线索**，不是官方数据（[ADR-0007](docs/adr/0007-tour-leads-from-okemin.md)）：`classical-radar leads-sync` 礼貌地读两个年度页和各乐团文章，存进 `tour_lead` 表（2026-11-17 起由每日云端任务读取并自动上线，闸门和开关见 [ADR-0018](docs/adr/0018-tour-leads-in-the-daily-run.md)；开关 `AUTO_LEADS=false`）；发现页“海外乐团来日”一栏（虚线卡片，每张带“未核实”标记；标题后面的“第三方整理，未核实”副标题 2026-11-20 起去掉）、`#leads`、`#lead/<id>`；官方已有同乐团同日期的演出时，线索让位。一次真实读取：45 个请求、52 条线索、31 条尚未过期、6 条已被官方数据覆盖。线上数据在 `site-data/leads.json`。**不进发现页主列表、日历、搜索、提醒** |
| 尚无 | 真实提醒发送、定时调度、真实长期监测数据、KAJIMOTO 详情页核对、日历上两个来源的开售事件去重。**停售前提醒（`sale_end`）不做**：2026-11-11 离线量了缓存页面，约 42 个 Japan Arts 页里只有 2 个写了带钟点的停售时刻且都已过期，东响与神奈川没有；调度代码早已支持，等来源有数据再开。多场演出页的开售时刻：按你的决定继续不挂 |

源验证事实以 [P0.2 报告](docs/reports/P0_2_COVERAGE.md)、[P0 首轮报告](docs/reports/P0_SOURCE_SPIKE.md)（含勘误）与 `evidence/` 为准；不要以测试通过代替真实跨月覆盖、政策核验或时效验收。
