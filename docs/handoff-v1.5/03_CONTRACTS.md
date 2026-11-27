# 03. 唯一权威：领域模型、字段与 API 契约

**本文件字段和 API 为规范性定义。** README / PRD / Roadmap 不另起等价别名。若 Agent 需要变更：先更新此文件、两份 JSON fixture、迁移和测试，再改其他文档。

## 3.1 关系与主键

```text
organization(id, source_id, name_ja, official_url)
artist(id, name_ja, verified_aliases)
concert(id, category, title_ja, official_announcement_date?, first_verified_at, last_material_change_at?, verification_status)
  ├── program_item(id, concert_id, position, raw_text, composer_display?, composer_key?, work_display?, work_key?)
  ├── concert_artist(id, concert_id, artist_id?, name_display, role)
  └── performance(id, concert_id, starts_at?, local_date?, date_precision, country_code, prefecture_code, venue_name, confirmation_status, status)
         └── ticket_phase(id, performance_id, phase_type, channel, eligibility?, starts_at?, ends_at?, result_at?, payment_due_at?, start_precision, end_precision, current_status, source_document_id)
source_document(id, source_id, url, kind, published_on?, first_seen_at, last_verified_at, content_hash?, policy_status)
source_claim(id, source_document_id, entity_type, entity_id, field_path, raw_value, normalized_value, verified_at, verification_status)
change_event(id, entity_type, entity_id, field_path, before_json, after_json, source_claim_id, detected_at)
tour_announcement(id, official_source_document_id, organizer_or_artist_name, declared_range?, linked_concert_id?)
unverified_lead(id, source_url, text_summary, observed_at, review_status)
user_pickup(user_id, concert_id, priority, notes, created_at)  -- unique(user_id,concert_id)
user_plan(user_id, concert_id, created_at)  -- unique(user_id,concert_id); an extension of the contract (ADR-0012): "I plan to attend this concert"
user_performance_state(user_id, performance_id, status, notes, updated_at)  -- unique(user_id,performance_id)
reminder_subscription(id, user_id, ticket_phase_id, milestone, offset_minutes, enabled)
notification_delivery(id, reminder_subscription_id, scheduled_for, dedupe_key, status, sent_at?, provider_id?, last_error?)
ingestion_run(id, source_id, started_at, ended_at?, status, counts_json, error_summary?)
```

同一节目中多场次：`concert`聚合，`performance`逐场保存。一个售票公告覆盖多场次时，可由**同一 source_document 分别生成有证据关联的多条 ticket_phase**；不能无证据把公告应用到所有场次。

## 3.2 唯一字段名、枚举和语义

| 字段 | 含义 |
|---|---|
| `concert.category` | `domestic_orchestra` / `overseas_orchestra_visit` / `piano_recital` / `other`；其中 `piano_recital` 不包含协奏曲钢琴独奏嘉宾 |
| `concert.verification_status` | `official_confirmed` / `needs_review`；只有 confirmed 可进入发现主列表 |
| `performance.confirmation_status` | `official_confirmed` / `needs_review`；**未定日期的来日官宣只在 tour_announcement，不能造 performance** |
| `concert.official_announcement_date` | `DATE NULL`；可核实的官方首次公布该日本演出/场次的日期；不是网页修改/抓取/售票时间 |
| `concert.first_verified_at` | `TIMESTAMPTZ NOT NULL`；首次从官方证据核实并收入系统的时间，冷启动降级排序依据 |
| `concert.last_material_change_at` | `TIMESTAMPTZ NULL`；重要字段最近实际变化，**不改变首次公布排序** |
| `source_document.first_seen_at` | 系统首次发现此 URL，与`concert.first_verified_at`含义不同，不用作前台正式公演的“公布日期” |
| `performance.date_precision` | `exact_time` / `date_only` / `month_only` / `unknown`；`exact_time` 时须有明确本地时间或可信时区 |
| `ticket_phase.start_precision/end_precision` | 同上；缺日期保留 null / unknown |
| `performance.status` | `scheduled` / `postponed` / `cancelled` / `completed` / `needs_review` |
| `ticket_phase.current_status` | `not_announced` / `announced` / `open` / `closed` / `unknown`；`open` 不代表实时有余票 |
| `concert_artist.role` | `conductor` / `recital_headliner` / `concerto_soloist` / `other`；同名但不同人不得自动合并 |
| `user_performance_state.status` | `interested` / `planning` / `applied` / `won` / `purchased` / `skipped` / `attended` |
| `user_pickup.priority` | `normal` / `high` |

时间默认 `Asia/Tokyo`，完整时刻数据库统一 `timestamptz`；只有日期时使用 `local_date`，不自动填 00:00 / 10:00。网页仅公布“発売中”可写 `current_status=open` 且 `starts_at=null`。

## 3.3 官宣 / 第三方线索展示隔离

- **正式公演**：有官方来源证据证明日本日级场次日期和场馆，`official_confirmed`，进入正常查询和售票提醒资格判定。
- **官宣待定**：官网明确说将来日本，但日期/场馆不全，写 `tour_announcement`，进入独立板块，不生成日期或提醒。
- **待核实线索**：第三方汇总或未确认描述，仅写 `unverified_lead`，默认折叠的“待核实（非官方确认）”区域可供私用用户浏览；不进正式查询、不能开启售票提醒。

## 3.4 发现查询唯一 API

```http
GET /api/v1/discover?category=all&months=12&region_mode=kanto_first&sort=announcement_desc&page=1&limit=20
GET /api/v1/discover/facets?category=all&months=12
GET /api/v1/discover/announcements
GET /api/v1/discover/leads                   # 仅私有用户，显著标待核实
GET /api/v1/discover/coverage
GET /api/v1/concerts/{concert_id}
PUT /api/v1/me/pickups/{concert_id}
DELETE /api/v1/me/pickups/{concert_id}
PUT /api/v1/me/performances/{performance_id}/state
PUT /api/v1/me/reminders/{ticket_phase_id}   # body: milestone, offset_minutes, enabled
POST /api/v1/import-url                      # 限制可信来源，需人工确认发布
```

`GET /concerts/{id}` 的 `performances[].ticket_phases[].reminder`（增量字段，2026-11-09）：当前用户在该阶段的 `sale_start` 订阅 `{milestone, offset_minutes, enabled}`；没有订阅为 `null`。`PUT /me/reminders/{id}` 另在渠道不是 `official` / `official_presenter`、或里程碑时刻已过去超过 10 分钟时返回 422（关闭订阅永远允许）。投递由本地 `classical-radar remind-run` 经假发送器处理，见 [ADR-0002](../adr/0002-reminder-scheduling-fake-sender.md)。

扩展路由（2026-11-09，不属于 3.4）：`PUT /review/duplicates`（body: `concert_id`, `other_concert_id`, `decision` = `duplicate_of | different`）与 `DELETE /review/duplicates/{concert_id}/{other_concert_id}`；`GET /review/candidates` 的每个 item 增加 `possible_duplicates`，响应增加 `marked_duplicates`。见 [ADR-0003](../adr/0003-cross-source-duplicate-review.md)。

已确认重复卡（2026-11-11，[ADR-0006](../adr/0006-merged-cards-for-confirmed-duplicates.md)，增量字段）：`GET /discover` 的 `items[].other_sources`（数组，可空；元素 `{concert_id, source_id, source_url, title_ja}`：人工判为同一场、在本次结果里由这张卡代表的其他来源的卡）；`GET /concerts/{id}` 增加 `other_sources`（同上）与 `merged_into`（同形状或 null）；`GET /review/candidates` 增加 `confirmed_duplicates`（元素 `{a, b, local_date, reasons, shared_artists, strength, suggested_keeper_id, can_hide}`），`marked_duplicates[]` 增加 `verification_status`。`PUT /review/duplicates` 的 `duplicate_of` 现在也接受两张都已确认的卡（被收起的卡每一场未来演出都须在主卡上，否则 422）。`GET /calendar` 的 `performances` 按同一规则不重复列出。

日历乐团筛选（2026-11-11，增量字段）：`GET /calendar` 的 `performances[]` 与 `sales[]` 每行增加 `orchestras`（数组，可空；元素 `{key, display, origin}`，与 `GET /discover` 的 `items[].orchestras` 同形）。筛选在页面端做：选了乐团时只显示至少有一个所选乐团的行（多选为“任一”），没有已识别乐团的行在筛选开启时不显示。

海外乐团来日线索（2026-11-12，扩展，[ADR-0007](../adr/0007-tour-leads-from-okemin.md)）：`GET /leads` → `{items, source, as_of, notice}`；`GET /leads/{lead_id}` → 单条。`items[]`：`{lead_id, orchestra{key,display,origin,names}|null, orchestra_name, period_raw, date_from, date_to, month_hint, cities[], more_cities, conductor, soloists, article_url, performances[{local_date,local_time,venue,city,program[]}], last_seen_at, last_changed_at, covered_by}`。来自第三方整理站，**不是官方确认数据**：不出现在 `/discover`、日历、搜索，`lead_id` 永远不会解析为 `concert_id`。

**不再使用** `/discover/japan-performances`、`/me/watch`、`event_confirmation_status`、`announced_at`、`official_announcement_at`、`date_precision=minute` 等旧写法。

`GET /api/v1/discover` 默认参数以 `00_DECISIONS.md` 为准；不同过滤维度 AND、同维多个值 OR，`view=concerts|entities` 可选；`entities` 仅由**已匹配的日本场次**聚合而成。分页首版 page + limit + 稳定排序（最后一个 `concert_id` 兜底），不做 cursor；在单次请求内筛选/排序后分页，数据更新导致跨请求轻微漂移属可记录限制。

`items[].organization_id`（可空字符串，增量字段，2026-11-05）：该节目的来源/主办方 id，与 `GET /concerts/{id}` 里 `concert.organization_id` 同值；为 null 表示来源未知。`GET /calendar` 的 `performances[]`/`sales[]` 和 `GET /me/pickups` 的 `items[]` 同样带这个字段；`sales[]` 另带 `category`（`performances[]` 本来就有）。界面只用它给卡片署名和决定封面类型，不据此推断任何事实。

`items[].pieces`（数组，增量字段，2026-11-16，[ADR-0010](../adr/0010-browse-by-people-and-works.md)）：该节目**全部**曲目行，按曲目顺序，每项 `{composer, composer_key|null, work, work_key|null}`（`work` = 作品显示名，缺失时用原文行；键只在别名表认识时才有）。给“按指挥/演奏家/作曲家/曲目浏览”页在浏览器里分组用；`items[].composers`（最多 6 个、给卡片用）不变。指挥和独奏名单继续用已有的 `conductors`（role=conductor）和 `soloists`（recital_headliner + concerto_soloist）。

浏览页怎样把写法不同的名字并成一项（2026-11-19，[ADR-0019](../adr/0019-merge-same-names-status-menu-and-search-button.md)；不改任何接口字段）：只在浏览器里做，规则写在 `app.js` 的 `<browse-rules>` 里——人工审核过的作曲家别名表、作曲家栏里的编曲者备注、同一曲目缺少或多出作品号 / 目录号 / 调号的写法、译名行（作品号或曲号和体裁都对得上才算同一首）。**不是按相似度合并**：看到两个不同的作品号 / 目录号 / 调号，或标题太泛（只剩体裁词），就不合并；`concert_artist` 的“同名但不同人不得自动合并”不变。

## 3.5 发现查询算法（规范性规则）

1. 服务端获取一次 `as_of_utc`；计算 JST 本地开始时刻和加 12（或24）个**日历月**的边界，不以固定天数代替。`exact_time` 从当前时刻之后开始；`date_only` 当天仍算未来/今天有效。两个分支用统一 `performance` 集合合并。
2. 仅 `concert.verification_status=official_confirmed` 且 `performance.confirmation_status=official_confirmed`、`country_code=JP`、未取消、在窗口内的有效场次。
3. 应用类别、日期、作品、作曲家、指挥家、演奏者、场馆、票务等细筛。作曲家/作品先用原文结构化抽取 + 可信别名，全文兜底，不建立世界曲库。
4. 以 `concert_id` 分组并保留每条匹配的 `performance`；任一场次在东京13/神奈川14/埼玉11/千叶12 则位于首都圈桶；非首都圈仍显示。
5. 各桶排序：`announcement_sort_date = COALESCE(concert.official_announcement_date, JST_DATE(first_verified_at))` 降序，其次`first_verified_at DESC`、最近场次时间 ASC、`concert_id ASC`。这是一条**排序约定**而非“缺失即官方最新”的事实判断。没有官方日期的行标“首次收录”；如果大量初次导入导致日期相同，平局用场次最近排序，并在 UI 提示“本批次为首次导入”。
6. `region_mode=nationwide` 时不分桶，统一按上述排序。未定官宣和待核实线索永远不混入主结果。
7. 在 DB 应用条件与分页；首版普通 OFFSET/LIMIT 即可。返回总数和来源覆盖告知，不把未收录解释成无公演。

## 3.6 个人状态与提醒的唯一所有权

- 点击“加入我的 Pickup”仅建一条 `user_pickup(user_id, concert_id)`；默认不订阅提醒。
- 用户可以进一步编辑具体场次状态 `user_performance_state`；不影响其他同节目场次。
- 只有用户明确开启某个`ticket_phase`下的里程碑，且对应时间精度是 `exact_time`、有可信官方来源，才可创建分钟级定时提醒；只有日期时可以选择全天日历标记，**不可隐式创建某时刻提醒**。
- 节点更改、官方取消、用户取消订阅时取消旧投递并重新计划；`notification_delivery.dedupe_key` 唯一，防重复入队。邮件第三方发生超时无法保证绝对 exactly-once，需记发送状态和可恢复失败，不能声称永不重复。
- 收费邮箱服务/正式外发需要用户明确许可；POC 使用本地假发送器验证。

## 3.7 简化架构

```
官方源 → Python httpx/HTML adapter（可选 Crawlee）→ Pydantic 校验
     → 证据归档/场次去重/差异识别 → PostgreSQL
     → 单一后端 API → Vue3 + TypeScript + FullCalendar Vue
     → 本地/定时 worker → 通知适配器（可选 Apprise）
```

私人网站仍需认证；是否采用 Supabase、RLS、changedetection.io、Crawl4AI、云容器由 POC 后 ADR 决策。禁止把 LLM 的抽取当作无证据事实：必须保存原文/出处，复杂日期需人工复核。
