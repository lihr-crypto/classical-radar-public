# 02. 采集来源、合规核查与验证路线

## 国内 7 家（固定范围）

**唯一名单及 URL 见 `00_DECISIONS.md`。** 以下只规定每站采集需要特别测试的差异，不再复制其他来源名单，避免漂移。

| source_id | 关键风险 | 首轮验证重点 |
|---|---|---|
| `nhkso` | 售票时间在季度/年度公告而非每场详情 | 对应关系、会员/一般发售、同节目多日期 |
| `tmso` | 列表可能包括室内乐和特色节目 | 类型、人员角色和实际场次归类 |
| `tso` | 详情页、专题售票页可能分离 | 售票时刻覆盖和缺失率 |
| `jpo` | “発売中”可能无初始开售时间 | `current_status` 与 `starts_at` 分离 |
| `njp` | 分批销售、追加销售 | 公告/列表/详情三方关联，变化发现 |
| `yomikyo` | 年度日历、新闻、票务渠道分离 | 官方日历 https://yomikyo.or.jp/cal.php ；票务链接与公告关联 |
| `tpo` | 一页多节目/长日期范围、歌剧/芭蕾协演 | https://www.tpo.or.jp/concert/ 的列表与场次拆分；公演类型过滤，不能把所有页面当交响定期 |

## 海外名团、钢琴独奏会（与七团并行 P0）

- Japan Arts：https://www.japanarts.co.jp/concert/ （官方主办方；需核验法律与实际可采集范围）
- KAJIMOTO：https://www.kajimotomusic.com/concerts/ （官方主办方；巡演多城市、独奏与协奏角色）
- 第三类互补来源：选择**一个**国内音乐厅或正式主办方，优先能补足钢琴独奏会，如神奈川艺术协会 https://kanagawa-geikyo.com/ （来源待验证）。
- 汇总信息源如 オケミン！、ぶらあぼ、Bachtrack、日本交响乐团联盟，可用于**发现线索/人工覆盖对照**，并非默认授权的官方正文抓取源；入库时回到场馆/主办方/乐团官方核实。

## 分阶段验证内容（每个 source 单独记录）

1. 检查 `robots.txt`、服务条款、版权和接口许可；**可访问≠可自动抓取≠可再发布**。状态记录 `permitted/restricted/unknown/blocked` 与证据链接、核查时间；不确定时暂停自动轮询。
2. 优先 RSS、iCal、JSON-LD、公开授权接口；再静态 HTML；确需 JS 且许可允许时使用浏览器自动化。不绕过登录、验证码、反机器人屏障、限流；403/429 停止并按政策处理。
3. 对列表、详情、新闻、售票页分别做小规模人工清单、HTTP/解析 fixture；查公告发布日期。`sitemap lastmod` 仅作重新抓取线索，**绝非官方首次公告时间证据**。
4. 比对七团与海外的真实公演、人员、节目、场次和售票；无公布时刻的节点保留 null，不得推测 10:00。
5. 检测重复抓取幂等、跨来源去重、场次级新增和重要字段更新；初次导入日期不可伪装成“最近公布”。
6. 允许缓存的证据片段和元数据可保存为本地 fixture；不得把有版权的整页正文、海报或受限截图放入公开 repo。

## P0 的官方 URL 手动导入

`用户粘贴 https URL → 域名/地址安全校验（防 SSRF、DNS/IP 重定向）→ 获取许可允许的网页 → 解析出候选字段 → 人工核对关键日期/场馆/对象 → 入库并记录源证据`。

该通道对难采来源是**备用输入**，绝不能代替持续自动发现。对禁止采集的站点只能使用用户有权取得的内容进行手动录入，不能借手动入口绕过访问限制。

## 核查报告（每站均要）

`policy_status, tested_at, legal_basis_urls, acquisition_mode, list_total_observed, parsed_count, missing_fields, critical_field_errors, duplicate_count, date_precision_distribution, announcement_date_coverage, ticket_event_coverage, known_blind_spots, last_success_at, decision(go/conditional/no_go), fallback`。

**禁止声称“全日本覆盖”**；覆盖率的分母仅限明确写出的官方页面/期间和口径。来源不具备技术或政策可行性则明确 No-Go 并报告替代流程。
