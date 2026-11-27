# V1.5 契约核对（原件已取得）

核对日期：2026-11-04，Asia/Tokyo。**V1.5 原件 `classical-radar-agent-handoff-v1.5.zip` 已取得**（SHA-256 `bc6d67eac84c9641521f9150f295b50413052599ac777f851fb97fc16f112e1c`）。
全部 Markdown 与三份虚构 JSON 样例原样放入 [`docs/handoff-v1.5/`](../handoff-v1.5/)。参考截图 `references/user-screenshots/` 按其 README 的版权说明**未入库**（私有研究参考，不得作为产品素材或公开上传）。

此前仓库的 `poc_schema_version=1` 是在没有原件时的独立实验格式。自今日起：**`docs/handoff-v1.5/03_CONTRACTS.md` 是唯一字段/API 权威**；POC v1 只是解析器的内部中间格式，不得作为输出契约。

## 已落实

| 项 | 实现 |
|---|---|
| 实体与枚举（3.1/3.2） | `src/classical_radar/contract.py`：Pydantic 模型，`extra="forbid"`，未知枚举、多余字段直接失败 |
| 日期精度规则 | `exact_time` 必须有时区时刻且 JST 日期与 `local_date` 一致；`date_only/month_only/unknown` 禁止携带 `starts_at`（不补 00:00/10:00）；`TicketPhase` 同规则 |
| 官方确认门槛（3.3） | `official_confirmed` 的 performance 必须有日级日期、场馆和 `prefecture_code` |
| 旧名禁令（3.4） | `find_legacy_keys` 扫描 `announced_at / official_announcement_at / event_confirmation_status / date_precision=minute\|day / 旧接口路径`；单测对三份样例与全部 `evidence/p02/*.json` 执行，`scripts/check_p02_evidence.py` 在 CI 中强制 |
| 发布排序（3.5-5） | `announcement_sort`：`COALESCE(official_announcement_date, JST_DATE(first_verified_at))` 并返回 `official` / `first_verified_fallback` 标签 |
| 个人状态三粒度（3.6） | `UserPickup / UserPerformanceState / ReminderSubscription` 模型；样例断言 Pickup 本身不开启提醒 |
| POC v1 → 契约 | `to_contract_bundles`：**永不产生 `official_confirmed`**；`date_precision` minute→`exact_time`、day→`date_only`；无日级日期或被排除乐团提示的候选不生成 performance，单独返回 |

对已提交的 254 个 2026-10-31 候选实际映射：219 个 concert、250 个 performance 全部通过校验，4 个无日级日期的候选被拒绝（不造 performance）。228 个 `exact_time`、22 个 `date_only`；250 个均缺 `prefecture_code`，所以没有任何一个能升级为 `official_confirmed`。

## POC v1 与契约的差异（保留，不静默改写）

| POC v1 | 契约 | 处理 |
|---|---|---|
| `date_precision = minute / day` | `exact_time / date_only / month_only / unknown` | 映射层转换；2026-10-31 的 `evidence/*.json` 作为历史快照保持原样，新证据 `evidence/p02/` 只用契约名 |
| `official_announcement_at`（恒为 null） | `concert.official_announcement_date`（DATE） | 解析器没有任何来源提供可核实的首次公布日期，一律 null |
| `verification_status = candidate` | `needs_review / official_confirmed` | 映射为 `needs_review` |
| `concert_id/performance_id` 内容哈希 | 不可变 ID | 仍是 POC 哈希：日期或场馆变化 ID 就变，**未解决改期身份匹配**（见下） |
| `first_seen_at` | `source_document.first_seen_at` 与 `concert.first_verified_at`（语义不同） | 映射层把观察时间同时写入两者，仅为满足 NOT NULL；**对 `needs_review` 候选它不是“已核实时间”，P1 必须在人工确认时才写 `first_verified_at`** |
| 售票声明 `ticket_claims` | `ticket_phase`（必须属于某个 performance） | 只有证据关联成功的才产生 phase（见 P0.2 报告），其余仍是未关联声明 |

## 契约缺口：2026-11-04 的处理（[ADR-0001](../adr/0001-p1-first-slice-decisions.md)）

用户授权由开发者判断，以下为已采用的解释；**原件 `docs/handoff-v1.5/` 未改动**，若要写回契约需另行更新 `03_CONTRACTS.md`、样例与迁移。

1. **枚举**：`phase_type` = `member_presale / general_sale / lottery / additional_sale / other`；`channel` = `official / official_presenter / other`；`source_document.kind` = `list / detail / announcement / calendar / import`（迁移的 CHECK 约束生效）。
2. **`concert.organization_id`**：保留为可选文本（等于 `source_id`）。
3. **`prefecture_code`**：`venues.py` 映射表（只收确定项）+ 来源自带前缀（`東京／`）。对已有证据里 614 次场馆出现，607 次可映射；其余 7 次（6 个不同标签，如どりーむホール、アクシスかつらぎ）不猜测，确认时需显式指定。
4. **改期身份**：UUID 不可变身份 + “同一 concert 下唯一未匹配旧/新配对”规则，写 `change_event`；歧义情形不合并（见 `tests/test_ingest.py`）。
5. **`unverified_lead / tour_announcement`**：表已建，没有采集来源，未实现逻辑。

## 可复现

```bash
python -m unittest tests.test_contract tests.test_ingest tests.test_discover -v
python scripts/check_p02_evidence.py
```
