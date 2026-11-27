# P0 工具选型

核验日期 2026-10-31。**本轮采用 httpx + BeautifulSoup + Python 标准库；其他候选未部署、未做性能基准。** 根据实际响应，八站列表为静态 HTML，读卖详情为静态 HTML；NHK 的官网 Vue 脚本引用公共 JSON，当前无须浏览器渲染即可验证结构。

| 候选 | 当前结论 | 证据与适用条件 |
|---|---|---|
| [HTTPX](https://www.python-httpx.org/quickstart/) + [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) | 采用，版本写入 lock | 本机十源入口及样本直接 HTTP 实测；网络与纯解析分离；无密钥 |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 暂缓 | Apache-2.0，支持网页变更监测；仍需将变更映射为节目/场次/票务声明。本轮字段 diff 可离线验证；没有实际运行对比，不能声称它一定更省维护 |
| [Crawlee Python](https://github.com/apify/crawlee-python) | 暂缓 | Apache-2.0，适合请求队列、重试、浏览器混合场景。当前低频少量 HTTP 已可取得数据；月份遍历与调度规模确定后再考虑 |
| [RSSHub](https://github.com/DIYgod/RSSHub) | 不作为当前底座 | 当前 LICENSE 为 AGPL-3.0；未验证到本项目十源的可用官方路由。不要把安装成功当来源已覆盖，也不要沿用旧版 MIT 印象 |
| Playwright / Crawl4AI / Scrapy | 暂不引入 | 未发现本次样本必须依赖浏览器执行的证据；NHK JSON 路径先从官网脚本核验。需要时按具体来源验证，不用代理绕过限制 |
| FullCalendar Vue / Apprise | 后续阶段再评估 | 当前无 UI 或通知；选型不是安装清单 |

许可证依据为各项目当日官方 [changedetection LICENSE](https://github.com/dgtlmoon/changedetection.io/blob/master/LICENSE)、[Crawlee LICENSE](https://github.com/apify/crawlee-python/blob/master/LICENSE)、[RSSHub LICENSE](https://github.com/DIYgod/RSSHub/blob/master/LICENSE)。未来引入时应对选定版本再次核验，而非仅引用本报告。

后续工程优先补齐来源覆盖和语义关联，再选持久化/调度。当前没有证据支持引入独立全球目录、向量数据库、复杂微服务或多套监测服务。
