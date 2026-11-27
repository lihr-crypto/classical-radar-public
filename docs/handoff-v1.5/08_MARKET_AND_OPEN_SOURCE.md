# 08. 竞品与开源候选（仅供复用评审）

## 现有产品定位

- **演奏会びより**（https://ensokai.app/）：已有乐团、人物、作品筛选与日历；Classical Radar 不应以“再次实现普通演出列表”作为唯一价值。
- **ぶらあぼ**（https://concert-search.ebravo.jp/）：可参考发售日期检索和日本演出分类。
- **Bachtrack**（https://bachtrack.com/）：国际古典演出发现思路；日本覆盖率需独立校验。
- **オケミン！**（https://okemin.com/）：海外名团来日计划线索，不自动等于可授权转载或官方已确认。
- **Apple Music Concerts**：只参考呈现方式和交互，不当作可直接调用的数据 API。

## 候选工具与何时使用

| 候选 | 借鉴/复用内容 | 是否现在必装 |
|---|---|---|
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 网页公告差异监测、Webhook | 否；先比较内置字段 diff 的成本 |
| [Crawlee Python](https://github.com/apify/crawlee-python) | 多页爬取、重试、动态网页 | 否；复杂数据源 POC 后再选 |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | 不规则页面辅助提取 | 否；不作为售票时刻事实裁判 |
| [FullCalendar Vue](https://github.com/fullcalendar/fullcalendar-vue) | 演出/票务月历、列表 | 候选优先；先验证免费功能和许可 |
| [Apprise](https://github.com/caronc/apprise) | 多通知渠道适配 | 否；首版单一邮件可更轻 |
| [RSSHub](https://github.com/DIYgod/RSSHub) | 已有许可/合法订阅源整合 | 否；不可借其绕开站点限制 |
| [Huginn](https://github.com/huginn/huginn) | 自动化工作流 | 否；个人项目可能太重 |
| [urlwatch](https://github.com/thp/urlwatch) | 轻量网页变化监控 | 备选 changedetection.io |
| [Showbook](https://github.com/ethanasm/showbook) | 购票状态、邮件票务信息组织的结构参考 | 不建议直接 Fork；日本业务不吻合且成熟度待验证 |

**选择标准**：许可证与维护状态、实际 POC 减少多少代码、部署资源与维护成本、数据来源合规。不要同时部署所有工具，也不要为追求高 GitHub Star 重复造轮子或叠加不必要服务。
