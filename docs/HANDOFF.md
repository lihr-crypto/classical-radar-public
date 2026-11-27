# Classical Radar 交接

更新日期：2026-11-04，Asia/Tokyo。面向任意第三方开发智能体，无须读取 Codex 记忆或其他对话即可开始本轮后续工作。

## 当前交付（2026-11-04 更新）

- 仓库：[lihr-crypto/classical-radar-public](https://github.com/lihr-crypto/classical-radar-public)。P0.2 工作在分支 `claude/upbeat-goldberg-wukmxe`，**未合并、未开 PR、无部署、无定时任务**。
- **V1.5 原件已取得**并入库：[`docs/handoff-v1.5/`](handoff-v1.5/)（SHA-256 见 [契约核对](reports/CONTRACT_RECONCILIATION.md)；参考截图按版权说明未入库）。`03_CONTRACTS.md` 是字段/API 唯一权威；`poc_schema_version=1` 降为解析器内部格式。
- 新增：契约层 `contract.py`（模型 + 旧名扫描 + POC→契约映射，永不赋予 `official_confirmed`）、售票关联 `linking.py`、读卖年度日历 adapter、四站分页遍历、Japan Arts/KAJIMOTO 全部 UPCOMING 详情基准、NHK 公告→场次关联（16/16 交叉核对一致）、跨源疑似重复提示、排除乐团与钢琴独奏提示、`docs/poc/source-audit.csv`。
- 修复：Japan Arts 把相关公演卡片算成本页场次（[勘误](../evidence/p02/ERRATA.md)）、读卖 `2026 11. 7` 日期解析、传输错误处理。
- 数字、n/N、盲区与 Gate 判断见 [P0.2 覆盖报告](reports/P0_2_COVERAGE.md) 与 [P0.3 报告](reports/P0_3_ANNOUNCEMENT_AND_JAPANARTS.md)（首次公布日期、Japan Arts 核对）。离线测试（见下节 P1 切片后为 77 项）、`check_evidence.py`、`check_p02_evidence.py` 通过。

## 阅读顺序

1. 根目录 [README](../README.md)：安装、离线测试、CLI。
2. [`handoff-v1.5/00_DECISIONS.md`](handoff-v1.5/00_DECISIONS.md)（范围）→ [`03_CONTRACTS.md`](handoff-v1.5/03_CONTRACTS.md)（字段/API）→ [`05_ACCEPTANCE.md`](handoff-v1.5/05_ACCEPTANCE.md)。
3. [契约核对](reports/CONTRACT_RECONCILIATION.md)：已落实项、POC 差异、契约缺口。
4. [P0.2 覆盖报告](reports/P0_2_COVERAGE.md) 与 [P0 首轮报告](reports/P0_SOURCE_SPIKE.md)（注意勘误）。
5. [`poc/source-audit.csv`](poc/source-audit.csv)、`evidence/p02/*.json`、`src/classical_radar/`。

## 已验证与未验证

| 层级 | 已有证据 | 不代表 |
|---|---|---|
| 真实网络 | Japan Arts 42/42、KAJIMOTO 15/15 详情；读卖年度日历 83/83 + 33 详情（日历与详情 0 不一致）；东响/日本爱乐/新日本爱乐/神奈川艺术协会分页全遍历；NHK JSON + 公告 + 16 个详情页 | 全年/全站普查、字段准确率、长期稳定、使用许可 |
| 关联 | NHK 未来定期公演 32/32 关联，含“12 月 A 程序在 11 月举行”例外，16/16 与各场自述一致；KAJIMOTO 单场页 13 项关联、2 个多场页拒绝关联 | 通知可发送（全部 `reminder_eligible=false`） |
| 契约 | 三份官方样例与全部 p02 证据无旧名；254 个旧候选映射为 219 concert/250 performance（均 `needs_review`） | 数据库/API/OpenAPI 已实现 |
| 监测 | 两次快照相隔约 85 小时，观察到 KAJIMOTO 一条改期 | 任何时效 SLA；官方改动时间未知 |
| 缺口 | 东京爱乐已由用户移出当前范围（取得时本环境 TLS 重置不可达）；都响受使用条件限制未扩大；首次公布日期可得率未测；35 个 Japan Arts 详情未逐页人工核对 | — |

本机原始响应在忽略目录 `evidence/raw/`，clone 中没有；重跑联网脚本会重新生成。`scripts/p02_link_tickets.py` 的 KAJIMOTO 部分与 `p02_verify_nhk_sale.py` 依赖这些本地原始文件/联网。离线检查（`unittest`、`check_*`）不需要。

## v0.1 初版（2026-11-04）

可用的最小版本已完成：`sync`（手动同步）→ 待确认队列（批量人工确认）→ 网页 UI（发现/详情/日历/我的/待确认/来源）。快速开始、数据来源、已知限制见 [RELEASE_v0.1](RELEASE_v0.1.md)。新增的非 3.4 路由（`/review/candidates`、`/review/confirm`、`/calendar`、`GET /me/pickups`）为扩展，由测试强制路径集合。

## P1 第一切片（2026-11-04，已完成）与下一轮任务

用户指示“东京爱乐不用管，其他由智能体判断”。四项决定与契约缺口的处理见 [ADR-0001](adr/0001-p1-first-slice-decisions.md)：东京爱乐移出当前范围、都响不遍历、本地 SQLite、枚举冻结、场馆映射表、不可变身份与改期匹配规则。

已落地（均有离线测试，138 项通过）：
- `db.py`：契约全部实体的 SQLite 表（枚举 CHECK），外加 `import_candidate` 暂存表。
- `ingest.py`：幂等入库；concert 以 `(source, 规范化 URL)` 匹配，performance 先精确匹配再做“唯一未匹配配对”改期；歧义不合并；已过日期标 `completed`；单源失败回滚且写 `ingestion_run`（T11）；售票阶段入库并记录变更；**流水线永不写 `official_confirmed`**。
- `discover.py` / `personal.py`：3.5 发现查询（日历月窗口、JST 今日、首都圈分桶、公布日期降级为“首次收录”、同日平局稳定排序、分页、同节目一张卡）与覆盖读模型；Pickup / 场次状态三粒度（T12）。
- `import_url.py` + CLI：只接受已登记的 https 源且拒绝解析到非公网地址的主机；暂存 → 人工确认 → 入库；失败/驳回不产生公演。真实页面 `kajimoto/alexandre-kantorow-2026` 端到端验证过（导入、确认、discover 出现一张卡）。
- `api.py`（HTTP 层，FastAPI）：3.4 全部路由 + import 确认/驳回扩展；单用户 Bearer 令牌，未配置则拒绝启动；契约测试强制路径集合、枚举、旧名禁令与官方样例字段一致，并有“每个路由未带令牌都 401”的逐路由测试（已用变异验证能抓到漏守卫）。`classical-radar serve DB` 本地启动，真实冒烟通过。
- `venues.py`：场馆→都道府县（证据中 614 次出现里 607 次可映射）。

验收项状态（`05_ACCEPTANCE.md`）：T01、T03、T04、T05、T06、T08（售票未知不补时刻）、T09（NHK）、T11（入库层）、T12、T16（未确认/导入不入发现）、T17（URL 导入防 SSRF，已知 TOCTOU 限制）有对应测试；**T02/T07 仅部分**（分类提示，未人工确认入库）；**T10 部分**（改期/标题/售票变更有事件，换指挥/追加销售未覆盖）；**T15（API/OpenAPI 一致）已覆盖到路径/枚举/旧名/样例字段；T14（多维筛选：跨维 AND、同维 OR、仅已确认日本公演）已覆盖；T13 只做了订阅规则（精度门槛、不重复订阅），投递调度与 `dedupe_key` 未做；T18（UI）有浏览器实测，无自动化 UI 测试**。

下一轮任务（按价值排序，仍不涉及外发/付费/部署）：
1. ~~HTTP API 层~~ 已完成（见上）。后续可补：把 OpenAPI 导出为仓库内快照文件并在 CI 比对漂移。
2. ~~详情级解析~~ 已完成：东响/日本爱乐/新日本爱乐/神奈川艺术协会的曲目与出演者，新日本爱乐与神奈川的明确开售时刻，KAJIMOTO/Japan Arts/读卖/NHK 的曲目与出演者（见 ADR 补充）。后续：Japan Arts 已结束场次标 `completed`（入库层已处理，解析层尚未标）；~~东响/日本爱乐售票时刻页面本身不给年份/时刻，无法解析~~（2026-11-09 实测**部分更正**：东响有的页面确实只写“12/16(火)”这样的日期，但抽样 4/8 页写了带年份和时刻的会员先行开售（**现已补解析**，[ADR-0005](adr/0005-sale-time-parsing.md)）；日本爱乐 8/8 页只有泛泛说明，确实没有日期；见 [开售时刻覆盖报告](reports/P0_3_SALE_TIME_COVERAGE.md)）。
3. ~~作品/作曲家等结构化筛选（T14）~~ 已完成（`composer/work/conductor/performer/venue`，facets，UI 筛选面板）。后续：`view=entities`、更大的作曲家别名表、俗称（“第九”）到作品键的人工别名。
4. ~~跨源重复复核~~ 已接进确认流程（2026-11-09，[ADR-0003](adr/0003-cross-source-duplicate-review.md)）：待确认队列显示“可能重复”提示，人工可标“同一场（隐藏这条）/不是同一场”，可撤销，不合并。**没做**：已经都确认的两张卡，发现页仍会出两张（需要先决定主卡与展示方式）。
5. ~~提醒调度（假发送器）~~ 已完成（2026-11-09，[ADR-0002](adr/0002-reminder-scheduling-fake-sender.md)）：对账式调度、`dedupe_key` 唯一、本地假发送器、`classical-radar remind-run`、详情接口返回 `reminder`。**仍然没有**：真实发送（需用户许可）、定时器（`remind-run` 手动跑）、线上 Pages 站点的投递（KV 函数无门槛无调度）、`sale_end`（入库不写结束时刻）。
6. ~~持续监测~~ 机制已做（2026-11-09，[ADR-0004](adr/0004-monitoring-and-p03-measurements.md)）：`classical-radar monitor`（手动一轮、最小间隔 6 小时、都响硬排除）与 `monitor-report`（延迟上界；有页面修改时间的 5 个来源才有 `official_change_known_at`）。**没有跑过任何真实长期数据，也没有定时器，不提供 cron 配方**（来源政策未定）。要积累数据请在你的机器上手动跑。
7. **补强：部分完成**（2026-11-09，[P0.3 报告](reports/P0_3_ANNOUNCEMENT_AND_JAPANARTS.md)）。已做：首次公布日期可得率（Japan Arts 42/42、东京交响乐团 8/8、神奈川艺术协会 8/8 有页面发布时间，其余没有；**页面发布时间不等于首次公布**，要不要写进 `official_announcement_date` 待你决定）；Japan Arts 42 页程序比对一致。**后来补做**：Japan Arts 售票时刻已补解析（[ADR-0005](adr/0005-sale-time-parsing.md)；神奈川艺术协会、东响的漏读也一并补上；多场演出页读出了但仍不挂到场次，要不要放开待你决定）。**没做**：Japan Arts 余下 35 页的**人工**字段核对（只做了程序比对，不是人工）、KAJIMOTO 15 页核对。

## 在本机继续（2026-11-04）

云端会话碰不到本机文件，按下面在 Mac 上接手（路径可换成你放 Claude 项目的文件夹）：

```bash
mkdir -p ~/Documents/Claude && cd ~/Documents/Claude
git clone https://github.com/lihr-crypto/classical-radar-public.git && cd classical-radar
git switch claude/upbeat-goldberg-wukmxe          # PR #1 的分支；合并后改用 main
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e .
python -m unittest discover -s tests                # 应全部通过
claude plugin marketplace add cloudflare/skills && claude plugin install cloudflare@cloudflare
claude                                              # 在这个文件夹里启动 Claude Code，然后 /reload-plugins
```

在本机会话里可以完成云端做不了的事：Cloudflare MCP / `npx wrangler login` 的浏览器授权、`classical-radar images` 拉取维基共享资源照片（云端被 Wikimedia 拒绝）、`classical-radar sync` 后把 `data/radar.db` 留在本机。接着按 `docs/DEPLOY_CLOUDFLARE.md` 上线，并用 PR 推进后续开发。

给本机 Claude 的第一句话可以是：

> 读 docs/HANDOFF.md 和 docs/DEPLOY_CLOUDFLARE.md。Pages 项目、KV、Access 由 `scripts/cf_bootstrap.py` 在部署作业里自动创建（不必手动用 MCP 建）；告诉我还需要我在 GitHub 里填哪些密钥/变量，然后让 PR #1 的预览站跑起来。

注意：仓库里的 `wrangler.toml` **刻意保留占位符**（KV id 全 0、`ACCESS_AUD = ""`，`tests/test_site.py` 会检查）；真实值只由 CI 写入，不要提交。

## 必须保留的边界

- 国内目标只有 NHK、都响、东响、日本爱乐、新日本爱乐、读卖、东京爱乐。**神奈川艺术协会**作为主办方与被排除的**神奈川爱乐**不是同一机构。
- 自动发现是核心，URL 人工确认导入是备用；不能把项目缩成让用户自己搜链接的工具。
- 公告时间未知留空；首次收录不是官方公布。节目、场次、售票阶段及三种个人状态粒度保持分离。
- `concert_id`、`performance_id` 当前是内容推导的 POC 哈希：重复回放稳定，日期或场馆改变时 ID 会变。**不是已经解决改期身份匹配的永久数据库 ID**；P1 须建立不可变身份与有依据的改期关联。
- 目前 `material_hash/changes` 证明的是离线差异，尚无数据库 upsert、取消/改期关联或通知幂等实现。
- 来源政策目前 unknown；都响使用条件的复用限制须优先处理。未获适当使用依据不扩大为定时全站采集/公开转载，不提交完整网页或图片。
- 网络层仅允许登记 HTTPS 主机及 www 别名；401/403/429 停源；传输错误不暂停来源但也不绕过（东京爱乐连接被重置时没有换路径、代理或 UA）。
- 对外输出一律使用契约名；`poc_schema_version=1` 的 `date_precision=minute|day`、`official_announcement_at` 只允许留在 2026-10-31 历史快照里。
- 不引入费用、账户、第三方凭据、云部署或外部发送来完成 P0。后续需要时再依据用户对具体动作的授权推进。

## 可直接交给下一位智能体

> 请克隆 `lihr-crypto/classical-radar-public` 的分支 `claude/upbeat-goldberg-wukmxe`（或其合并后的 `main`），先读 `docs/HANDOFF.md`、`docs/adr/0001-p1-first-slice-decisions.md`、`docs/handoff-v1.5/00_DECISIONS.md`、`03_CONTRACTS.md`、`docs/reports/P0_2_COVERAGE.md`。跑 `python -m unittest discover -s tests` 与两个 `check_*` 脚本后，从“下一轮任务”第 2 项（详情级解析）开始；先通读 `docs/RELEASE_v0.1.md` 的已知限制。东京爱乐不在当前范围；都响不遍历；保持七团（六源）与海外/钢琴同优先级，缺数据如实记 unknown/No-Go，不自行合并、公开或部署，不外发邮件、不花钱。
