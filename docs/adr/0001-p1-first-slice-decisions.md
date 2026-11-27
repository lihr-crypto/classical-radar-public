# ADR-0001 — P1 第一切片的决定

日期：2026-11-04。状态：采纳（用户授权“东京爱乐不用管，其他由智能体判断”）。以下是原 [HANDOFF 四项待决](../HANDOFF.md) 与契约缺口的处理。**不改动 `docs/handoff-v1.5/` 原件**；本 ADR 只补充选择，若 P1 之后要把它们写回契约，应另行更新 `03_CONTRACTS.md`、样例与迁移。

| 议题 | 决定 | 理由 / 后果 |
|---|---|---|
| 东京爱乐 | **移出当前执行范围**（来源登记保留，标记 `deferred_by_user`）。不再尝试访问，不做多日范围展开 | 用户指示。七团白名单本身不变（`00_DECISIONS.md` 仍是范围权威），覆盖报告里写“东京爱乐未覆盖”，不假称覆盖 |
| 都响 | 不遍历月份页；只允许 URL 导入通道里由人工提供的官方 URL | 使用条件限制内容复用，政策结论由用户保留；导入通道对 tmso 仍需 `policy_status` 为 `restricted` 的显式提示 |
| 存储 | **本地 SQLite**（标准库 `sqlite3`），表和字段名与 `03_CONTRACTS.md` 一致；时间存 UTC ISO8601 文本，规则校验在 Python 层 | 无云账号/费用；结构可原样迁到 Postgres（`timestamptz`）。已知差异：SQLite 无 `timestamptz`/部分唯一约束细节，迁移时再核 |
| 枚举冻结 | `ticket_phase.phase_type`: `member_presale` / `general_sale` / `lottery` / `additional_sale` / `other`；`channel`: `official` / `official_presenter` / `other`；`source_document.kind`: `list` / `detail` / `announcement` / `calendar` / `import` | 取自本轮真实出现的值并留出追加销售/抽选；仅在迁移的 CHECK 约束中生效，值外使用需先改 ADR |
| `concert.organization_id` | **保留为可选**（文本，等于 `source_id`），因为官方样例使用它 | 关系图未定义该字段，样例使用；不构成必填 |
| 场馆 → 都道府县 | 仓库内维护 `venues.py` 映射表（确定的才收录）；来源自带前缀（KAJIMOTO 的 `東京/`、`神奈川/`）优先于表；查不到返回 `None` | 用户未指定维护人，由开发者在导入确认时补充；`official_confirmed` 在映射缺失时拒绝，人工确认可显式指定 |
| 不可变身份 | `concert.id`/`performance.id` 为随机 UUID；concert 以 `(source_id, 规范化来源 URL)` 匹配；performance 先按 `(local_date, local_time, 场馆)` 精确匹配，再允许“同一 concert 下 1 条未匹配旧 + 1 条未匹配新”的唯一配对认定为改期（写 `change_event`），其余歧义**不合并**，旧条标记 `needs_review`、新条新增 | 内容哈希 ID 的改期问题的第一版有依据解法；歧义时保守，宁可多一条待复核也不错误合并 |
| `first_verified_at` | `needs_review` 记录存首次观察时间；**人工确认时重置为确认时间**，重置不记入 `last_material_change_at` | 契约要求 NOT NULL 且仅对 `official_confirmed` 的排序有意义 |
| 自动确认 | 流水线永不写 `official_confirmed`；只有 URL 导入的“人工确认”步骤可以 | 与 `05_ACCEPTANCE.md` 一致 |
| 未实现 | HTTP API 层（FastAPI）、Vue UI、提醒调度、`unverified_lead`/`tour_announcement` 采集 | 本切片先落地数据层与发现查询算法，API 层是下一个独立切片 |

## 补充（HTTP API 切片，2026-11-04）

| 议题 | 决定 |
|---|---|
| 框架 | FastAPI（仅用于路由和 OpenAPI 文档）；`docs_url/redoc_url` 关闭，OpenAPI 在 `/openapi.json` |
| 认证 | 单用户，所有路由要求 `Authorization: Bearer <token>`（`CLASSICAL_RADAR_TOKEN`，至少 16 字符，缺失/过短则**拒绝启动**）；`/me/*` 用户固定为 `me`；`/discover/leads` 同样需要令牌。默认只监听 127.0.0.1 |
| 对 3.4 的扩展 | 为使 `POST /import-url` 停在人工决定，新增 `POST /import-url/{id}/confirm`、`POST /import-url/{id}/reject`；另有 `GET /concerts/{id}` 返回节目/场次/售票阶段/个人状态。除此之外路径与 3.4 完全一致，测试强制 |
| 提醒规则 | `PUT /me/reminders/{ticket_phase_id}` 写 `reminder_subscription`（2026-11-09 起同时排/撤投递，见 ADR-0002；原先只写订阅）。`milestone` 限 `sale_start / sale_end`；启用时对应时刻必须 `exact_time`，否则 422（日期精度的开票永远不会变成 10:00 或 0:00 的分钟级提醒）；只有 `official_confirmed` 的场次可订阅；同一 (用户, 阶段, 里程碑) 更新而非重复创建 |
| 未做 | ~~投递调度与假发送器~~（2026-11-09 已做，见 [ADR-0002](0002-reminder-scheduling-fake-sender.md)）、`result / payment_due` 里程碑、多用户 |

## 补充（v0.1 初版，2026-11-04）

| 议题 | 决定 |
|---|---|
| 人工确认的承载 | 待确认队列（`GET /review/candidates`、`POST /review/confirm`）是对 3.4 的扩展：批量确认已入库的候选，按节目原子化；缺场馆/都道府县的拒绝；确认写 `change_event`（`verification_status needs_review→official_confirmed`）。确认只发布未来场次 |
| 日历/我的 | `GET /calendar?from&to`（≤62 天）、`GET /me/pickups`：为 UI 的读模型，同属扩展 |
| 同步 | `classical-radar sync` 仅手动；都响拒绝、东京爱乐跳过；`NHK_TICKET_NEWS` 为季度手工配置 |
| UI | 无构建原生 JS；文本一律经 `textContent`；CSP `default-src 'self'` 且禁止内联；令牌存 localStorage（本机单用户） |
| 未做 | 候选的“驳回/忽略”持久化（目前未确认的候选会一直在队列里）、多用户、HTTPS |

## 补充（作品/作曲家筛选与详情页解析）

| 议题 | 决定 |
|---|---|
| 筛选维度 | `composer / work / conductor / performer / venue`，API 以重复查询参数传值（每维 ≤10 个值、每值 ≤100 字）；同维度 OR、跨维度 AND；未使用的维度不出现在回显的 `filters` 里。`venue` 是场次级筛选（卡片只列匹配的场次），其余是节目级 |
| 匹配规则 | composer：已知别名按 `composer_key` 相等，否则按显示名子串；work：形如 `composer:kind` 的值按 `work_key` 相等，否则对作品/原文做去空格去标点子串匹配；conductor 仅匹配 `conductor` 角色；performer 匹配任意角色。归一化：NFKC、大小写、去音调符、去空白/点/连字符 |
| 规范键 | 只为别名表内作曲家生成 `composer_key`（约 120 位，`works.py`，不追求完备）；`work_key` 只在“交响曲/协奏曲/奏鸣曲/四重奏/三重奏 + 第N番”这类无歧义形式生成。其余保持 `null`，靠原文兜底（与 `00_DECISIONS` 0.3-2 一致，不建全球曲库） |
| 演奏者 | 以显示名存储，不做相似度合并（`artist_id` 恒空）。`recital_headliner`=恰一位独奏者且无指挥/乐团；`concerto_soloist`=指挥或乐团旁的独奏者（含声乐独奏）；二重奏等不升格，记 `other`。KAJIMOTO 页面不标乐器，仅在“单一艺术家 + 钢琴独奏会提示”时记为独奏会演奏者 |
| 入库 | `program_item / concert_artist` 在页面给出非空且不同的列表时整体替换；空列表表示“页面没说”，从不清空已存数据；替换已有的非空列表写 `change_event`（换指挥/曲目变更，T10）并更新 `last_material_change_at`，首次载入不算变更 |
| 售票 | **（2026-11-09 被 [ADR-0005](0005-sale-time-parsing.md) 修改：没写年份时可由括号里的星期定年份；Japan Arts、东响现在也读开售时刻，神奈川也读套票。下面是当时的决定。）** 仅当页面写明年月日与时刻时才产生声明：新日本爱乐一回券（按受众分档，"いずれも10:00発売"）与追加发售通知、神奈川艺术协会一回券（不取套票）。东响（无年份/时刻）、日本爱乐（仅“发售中”）、读卖（无年份）不解析。关联沿用“页面仅一个场次”规则，渠道记 `official` |

## 补充（按乐团浏览与海外乐团来日）

| 议题 | 决定 |
|---|---|
| 乐团识别 | `orchestras.py` 维护乐团表（七团 / 其他日本乐团 / 海外），最长别名优先匹配；七团官网的节目，乐团即来源本身，只从演出者名单里再识别其他乐团，不从标题识别（避免“ウィーン・フィルの至宝”这类成员介绍被当成乐团）；“…の / 首席 / 団員 / メンバー”紧跟的别名不算 |
| 海外乐团来日 | 候选的类别提示：钢琴独奏会 > 识别到海外乐团 → `overseas_orchestra_visit` > 七团之一 → `domestic_orchestra` > 其他。表外乐团不猜海外。未确认的候选在每次同步时更新提示；已确认的类别不再改 |
| 筛选维度 | 新增 `orchestra`：值为乐团键（如 `nhkso`、`ov-br-so`）、`overseas` / `seven`（整组）或名称子串；facets 增加 `orchestra`（含 origin）与 `orchestra_groups` 计数；卡片给出 `orchestras` |
| 界面 | 发现页首行为乐团选择（全部 / 七团 / 海外乐团 / 钢琴独奏会，选海外乐团后展开具体乐团），作曲家/作品/演奏者等收进“作曲家 / 作品 / 演奏者…”折叠面板；说明性文字压缩到最少 |

## 补充（图片）

| 议题 | 决定 |
|---|---|
| 海报与主办方照片 | **不抓取、不展示。** 著作权属主办方/摄影师；KAJIMOTO 使用条件明确禁止转用图片；交接包硬性禁令“未经许可不得重用海报/人物照片”。详情页保留“官方页面”链接，海报在官网看 |
| 人物与乐团照片 | 只用 Wikidata（P18）→ Wikimedia Commons 上 CC0 / 公有领域 / CC BY / CC BY-SA 的图片，缓存缩略图到 `data/media/`（不入库），每张图旁显示作者、许可与 Commons 来源页 |
| 匹配规则 | 显示名与 Wikidata 标签/别名完全一致（去掉“サー・”等敬称）；人物须为 Q5 且职业/描述为音乐家，乐团须为乐团/合奏团；**恰好一个**候选才采用，同名多人一律不放图 |
| 访问方式 | `classical-radar images DB` 手动运行，3 秒一请求，User-Agent 标明项目；429 退避后仍 429 即停。2026-11-04 云端环境访问 Wikimedia 被 403（机器人策略）拒绝，未绕过——需在本机运行 |
| 无图降级 | 卡片使用按乐团配色的生成式封面（首字 + “海外 / Recital”角标），演出者用首字圆形头像；不使用任何第三方图片 |

## 补充（都响自动采集，2026-11-04 用户决定）

用户指示推进都响自动采集。复核其“このサイトについて”页：为一般性著作权声明（未经许可不得复制、转用、改变、发送、销售网站内容；链接原则自由），未专门禁止访问或自动读取，`robots.txt` 仅禁止 `/contents/`。处理与其他各站一致：

- 只保存事实字段（标题、日期、开演时刻、场馆、出演者与角色、曲目），**不保存**简介/履历、解说文字与图片；测试夹具同样去掉了履历；
- 手动、限速同步（`classical-radar sync`，2 秒/请求，401/403/429 停源），无定时任务；不公开转载，演示页仅私有；
- 列表走 `?tab=1&page=N`；只读取都响自己域名下的详情页，外部主办方的公演保留列表级信息；
- 都响页面的开售日期不带年份和时刻（“一般発売：7/8（水）”），不解析；只有写明年月日与时刻时才产生售票声明。
- `policy_status` 仍记 `unknown`（不是 `permitted`）：用户决定启用不等于取得了对方许可。

## 补充（Cloudflare 部署与 PR 流程，2026-11-04 用户要求）

| 议题 | 决定 |
|---|---|
| 托管 | Cloudflare Pages（免费）。Python 后端不搬上云：发现/筛选在浏览器里对 `site-data/concerts.json` 运行（与本地 API 由 24 项一致性检查保证同结果）；只有个人状态走 Pages Function + KV |
| 访问控制 | 全站放在 Cloudflare Access 后面（用户邮箱一次性验证码）；Function 自行校验 Access JWT（RS256、AUD、iss、exp），未配置即 401；`DEV_USER` 仅在 `ENVIRONMENT=development` 时生效；`X-Robots-Tag: noindex` 与 `robots.txt` 全站禁止收录 |
| 数据发布 | 确认后的数据导出为一行一个节目的 JSON，以 PR 审阅；合并即部署。采集与逐条审核仍在本地（定时云端采集不启用：来源许可未确认） |
| 发布流程 | `main` → 正式站；同仓库 PR → 预览站；缺少 Cloudflare 密钥时只构建和测试 |
