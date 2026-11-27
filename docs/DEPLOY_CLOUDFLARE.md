# 部署到 Cloudflare Pages（一次性设置）

目标：`https://classical-radar.pages.dev` 只有你能登录；手机和电脑共用收藏、场次状态和提醒设置。代码和数据都通过 PR 更新：合并到 `main` 自动部署正式站，PR 自动生成预览站。全部在 Cloudflare 免费额度内（Pages、Functions、KV、Access 50 人以内免费）。

## 结构

| 部分 | 放在哪里 |
|---|---|
| 网页（发现、详情、日历、我的、来源） | Cloudflare Pages 静态文件，由 `scripts/build_site.py` 生成到 `site/` |
| 公演数据 | `site-data/concerts.json`（只有事实字段），在 PR 里审阅后合并 |
| 个人状态 | Pages Function `functions/api/me/[[path]].js` → KV 命名空间 `CR_STATE`，按登录邮箱分开 |
| 登录 | Cloudflare Access（邮箱一次性验证码）。函数会校验 Access 签发的令牌；没配置好时拒绝一切请求 |
| 初始化 | `scripts/cf_bootstrap.py`：部署前自动确保 Pages 项目、KV、Access 应用与允许策略存在，并写入 `wrangler.toml` |
| 免登录的图标 | 同一个脚本再建一个只覆盖 `classical-radar.pages.dev/icons/*` 的 Access 应用（策略：对所有人放行）。原因：iPhone“添加到主屏幕”下载图标和 manifest 时不带登录状态，在登录保护后面会拿到登录页，只好画一个字母。该文件夹里只有图标和 manifest（测试守住），其余路径仍需邮箱登录；Access 取最具体的路径规则 |
| 采集与审核 | 仍在本机（或 Claude 会话）用 `classical-radar sync` + 本地网页的“待确认”完成，然后导出数据开 PR |

## 第一次设置（约 5 分钟，全在浏览器里）

Pages 项目、KV 存储、Access 登录保护和 `wrangler.toml` 的配置，都由 GitHub Actions 里的 `scripts/cf_bootstrap.py` 在部署前自动创建（已存在就不动）。你只需要做下面几步：

1. **开通 Zero Trust（一次）**：dash.cloudflare.com → 左侧 *Zero Trust* → 按提示起一个团队名，选 *Free* 计划。（Access 登录依赖它，API 无法替你开通；如果提示填写付款方式，免费计划不会扣费。）
2. **建 API 令牌**：右上角头像 → *My Profile* → *API Tokens* → *Create Token* → *Create Custom Token*，加入这 4 项权限（都选 *Account*，账户选你的）：
   - Cloudflare Pages · Edit
   - Workers KV Storage · Edit
   - Access: Apps and Policies · Edit
   - Access: Organizations, Identity Providers, and Groups · Read
3. **在 GitHub 仓库里填写**（Settings → Secrets and variables → Actions）：
   - *Secrets* 页：`CLOUDFLARE_API_TOKEN` = 上一步的令牌；`CLOUDFLARE_ACCOUNT_ID` = Cloudflare 首页右侧栏的 Account ID。
   - *Variables* 页：`ACCESS_EMAILS` = 允许登录的邮箱（你的邮箱；多个用逗号分隔）。
   令牌只放在这里，不要发到聊天里。
4. **运行部署**：仓库 *Actions* → *Deploy to Cloudflare Pages* → *Run workflow*（或直接合并 PR）。运行摘要里会显示网址。
5. 打开 `https://classical-radar.pages.dev`，输入邮箱收到的验证码登录。手机上用浏览器的“添加到主屏幕”，以后像 App 一样打开。

失败时，工作流会原样显示 Cloudflare 的报错（例如令牌缺权限、Zero Trust 未开通），改好后重新运行即可，不会重复创建资源。

## 日常更新数据（PR 流程）

```bash
classical-radar sync data/radar.db                 # 手动、限速；东京爱乐不采集
classical-radar serve data/radar.db                # 在本地网页“待确认”里核对、确认
python scripts/export_site.py data/radar.db        # 写出 site-data/concerts.json（一行一个节目，diff 好读）
git switch -c data/2026-11-xx && git commit -am "data: sync 2026-11-xx" && git push   # 开 PR，预览站上检查后合并
```

数据 PR 的 diff 就是审阅记录：新增、改期、换指挥都在里面。合并即发布。

## 注意

- 公开快照不含抓取的数据和页面副本：数据来自各官网页面的解析，来源许可均未确认。部署自己的实例时，数据由你自己抓取，并自行确认各来源的使用条件。网站由 Access 保护、`noindex`，不对外公开。
- 本地数据库 `data/radar.db` 不入库。它保存改期匹配所需的历史；换电脑时把它一起拷过去。
- 提醒目前只记录设置，不发送。
