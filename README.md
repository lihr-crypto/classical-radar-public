# Classical Radar

日本古典音乐公演发现与开票追踪。当前交付是 **P0 数据来源可行性 POC**，尚无正式网站、数据库、提醒或部署。

**初版 v0.1 已可用：快速开始见 [docs/RELEASE_v0.1.md](docs/RELEASE_v0.1.md)；部署到 Cloudflare 见 [docs/DEPLOY_CLOUDFLARE.md](docs/DEPLOY_CLOUDFLARE.md)。** V1.5 原始交接包见 [docs/handoff-v1.5](docs/handoff-v1.5/)（`03_CONTRACTS.md` 为字段/API 权威）；P0.2 结果见 [覆盖报告](docs/reports/P0_2_COVERAGE.md)。最新产品范围见 [V1.5 需求基线](docs/requirements-v1.5.md)。实际结果见 [来源报告](docs/reports/P0_SOURCE_SPIKE.md) 和 [工具选型](docs/reports/TOOL_SELECTION.md)。接手开发请从 [交接文档](docs/HANDOFF.md) 开始。

## 本地运行

需要 Python 3.11+；本次在 macOS / Python 3.14.7 实测，不需要密钥、云账号或浏览器。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m unittest discover -s tests -v
python scripts/check_evidence.py
python scripts/check_p02_evidence.py
python scripts/check_p03_evidence.py
```

解析仓库内的真实事实片段，离线输出 JSON：

```bash
classical-radar detail kajimoto tests/fixtures/kajimoto-mahler-chamber-orchestra-2026-detail.html \
  --url https://www.kajimotomusic.com/concerts/mahler-chamber-orchestra-2026/
classical-radar list japanarts tests/fixtures/japanarts-list.html \
  --url https://www.japanarts.co.jp/concert/
```

本地 SQLite 存储与发现查询（ADR-0001，无云、无外发）：

```bash
classical-radar db-init radar.db
classical-radar ingest radar.db detail kajimoto tests/fixtures/kajimoto-alexandre-kantorow-2026-detail.html \
  --url https://www.kajimotomusic.com/concerts/alexandre-kantorow-2026/   # 候选入库，永远是 needs_review
classical-radar import-url radar.db https://www.kajimotomusic.com/concerts/alexandre-kantorow-2026/  # 联网读 1 个已登记官方页，只暂存
classical-radar import-confirm radar.db <import_id> --category piano_recital --note "已对照官网"     # 人工确认才会 official_confirmed
classical-radar discover radar.db      # 3.5 发现查询；未确认的候选不会出现
classical-radar coverage radar.db      # 每源已存数量，不给覆盖率百分比
export CLASSICAL_RADAR_TOKEN=<至少16字符的随机串>
classical-radar sync radar.db           # 手动限速同步各来源（候选，需在网页“待确认”人工确认）
classical-radar monitor radar.db         # 手动：一轮礼貌的监测（可监测来源，不含都响；同一来源 6 小时内不重复；没有定时器）
classical-radar monitor-report radar.db  # 轮次间隔、每个变化的延迟上界与（有则）官网页面修改时间
classical-radar leads-sync radar.db      # 礼貌（robots 先读、间隔 2 秒、最多 80 个请求）：读 okemin.com 的海外乐团来日页，存为“线索”（第三方整理，未核实，不是官方数据）。每日云端任务也会跑它（ADR-0018）
classical-radar leads-export radar.db    # 写 site-data/leads.json（线上站点用）；每日任务自己导出、检查、合并上线
classical-radar duplicates-dump radar.db   # 把“同一场/不是同一场”的决定写进 site-data/same_concert.json（只合并不缩减；撤销要加 --prune）
classical-radar duplicates-apply radar.db  # 把该文件重放进数据库（数据库重建后用）
classical-radar remind-run radar.db    # 手动：把到点的提醒交给**本地假发送器**（写 data/outbox.jsonl，不外发；没有定时器）
classical-radar serve radar.db         # 本地 HTTP API（127.0.0.1:8000），所有路由需 Bearer 令牌；OpenAPI: /openapi.json
```

一次性重新探测已登记的公开来源入口与 robots（会联网，结果写本地忽略文件）：

```bash
python scripts/probe_sources.py --source nhkso --source kajimoto
```

这只重新核对入口，不遍历月份或采集全站。来源政策未完成复核，不启用定时任务。403/429/401 暂停该来源；不使用登录、代理绕过或验证码规避。

## 产物

| 路径 | 内容 |
|---|---|
| `src/classical_radar/` | 来源登记、受限网络读取、纯函数解析、日期标准化、幂等键与差异示例、CLI |
| `tests/fixtures/` | 来自十个来源的最小事实片段、NHK JSON 和原页哈希/URL/时间 |
| `evidence/probe.json` | 十站真实 HTTP 和 robots 记录 |
| `evidence/extra.json` | NHK 官网脚本及公共 JSON 的发现链、都响使用条件页 |
| `evidence/details.json` | 详情访问记录，含一次 NHK 404 及正确 URL 的后续 200 |
| `evidence/list-candidates.json` | 254 个列表/JSON 候选，含历史记录与未分类项目 |
| `evidence/presenter-samples.json` | 两个主办方及读卖的十个详情场次样本、五个待关联售票声明 |
| `evidence/coverage.json` | 单页/单数据文件提取范围，**全来源覆盖率未知** |
| `evidence/p02/` | 2026-11-04 P0.2：Japan Arts/KAJIMOTO 全部 UPCOMING 详情、读卖年度日历、四站分页、NHK 售票关联及 16/16 交叉核对、跨源疑似重复、`ERRATA.md` |
| `docs/poc/source-audit.csv` | 十源政策/访问/风险登记（`scripts/build_source_audit.py` 生成） |
| `src/classical_radar/contract.py` / `linking.py` | V1.5 契约模型与旧名扫描、POC→契约映射；售票公告→场次关联 |
| `db.py` / `ingest.py` / `discover.py` / `personal.py` / `import_url.py` / `venues.py` | SQLite 表（契约字段名）、幂等入库与改期匹配、发现查询与覆盖读模型、Pickup/场次状态、URL 导入（暂存→人工确认）、场馆→都道府县 |
| `sync.py` / `web/` | 手动同步各来源；无构建的网页 UI（由 `serve` 在 `/ui/` 提供） |
| `api.py` | `/api/v1` 路由（3.4 + import 确认/驳回扩展），单用户令牌，未配置令牌拒绝启动 |
| `docs/adr/0001-p1-first-slice-decisions.md` | P1 第一切片的决定（存储、枚举、东京爱乐移出范围、身份规则） |

完整原始响应只保存在本地忽略目录 `evidence/raw/`；不包含图片、账号或票务凭据。`scripts/build_evidence.py` 是本机从这些原始响应生成证据的工具，需本机原始文件；另一台电脑直接运行上面的离线测试和 CLI 即可。快照片段验证解析可回放，不等于长期采集成功。

解析器内部与 2026-10-31 证据使用 `poc_schema_version=1`（含旧名 `date_precision=minute|day`），**不是 V1.5 契约**；对外输出必须经 `contract.to_contract_bundles` 或 `compact_candidate`，新证据 `evidence/p02/` 只含契约名。代码没有赋予候选 `official_confirmed` 状态，也没有把售票声明自动挂到所有场次。


## 公开快照说明

本仓库只含代码和文档。抓取的演出数据（`site-data/`）、证据文件（`evidence/`）、第三方网页的测试夹具（`tests/fixtures/`）以及 GitHub 工作流（含定时抓取）均**未随仓库发布**，因此依赖这些文件的测试不在其中。
