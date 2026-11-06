# 热门美股 180 日定投成本静态站

这个项目会更新一批纳斯达克 100 和标普 500 热门股票的收盘价，并计算最近 180 个交易日的固定金额定投成本、180 日均线、价格偏离和窗口回撤。

## 本地更新

```bash
python scripts/update_qqq.py
```

只更新指定代码：

```bash
python scripts/update_qqq.py --symbols QQQ,NVDA,AAPL
```

启动本地静态服务器：

```bash
cd public
python -m http.server 8080
```

浏览器打开：

```text
http://127.0.0.1:8080/
```

## 自动更新

`.github/workflows/update-data.yml` 每周二至周六北京时间 06:17 自动运行，07:47 再进行一次补充检查。
任务由 GitHub 云端执行，本机不需要开机。美股休市时保留最近交易日的数据，GitHub 调度偶尔可能延迟。

1. 只拉取 QQQ、SPY 的 Yahoo Finance 日线数据，失败时重试并切换查询节点
2. 只更新这两个 ETF 的行情缓存
3. 重新计算它们的 180 日定投成本，保留其他股票的已有数据
4. 生成网页使用的 `public/data/market_dca.json` 和 `public/data/market_dca.js`
   同时生成优先加载的 `market_priority.json`、摘要和按股票拆分的历史数据。
5. 校验两个指数的数据、历史图表和加载逻辑；任一指数失败时不发布
6. 提交数据更新，部署到现有 Cloudflare Pages 项目，并核对线上数据

仓库加密 Secrets 需要 `CLOUDFLARE_API_TOKEN`（仅有对应账号的 Cloudflare Pages 编辑权限）
和 `CLOUDFLARE_ACCOUNT_ID`。授权码、密钥不应写进代码或提交到仓库。

只更新两个指数也可手动运行：

```bash
python3 scripts/update_qqq.py --symbols QQQ,SPY
python3 scripts/verify_site.py
```

## 页面加载

首页默认显示 QQQ，QQQ 和 SPY 排在最前，首屏仅加载这两个指数 ETF 最近 270 个交易日的图表。
其他股票摘要随后加载；其他股票历史以及三年、五年图表按需加载。
QQQ 和 SPY 另提供十年、二十年及全部历史，全部历史从 2000 年首个交易日开始。
为计算 2000 年初的 180 日定投成本，行情缓存保留了 1999 年的计算缓冲数据。
带内容指纹的摘要和历史文件可长期缓存，原有完整 JSON 下载仍然保留。

验证加载行为和数据输出：

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
node --test scripts/test-loading.mjs
```

## Cloudflare Pages 部署

当前 Cloudflare Pages 项目名：

```text
qqq-dca-site
```

线上地址：

```text
https://qqq-dca-site.pages.dev/
```

手动重新部署：

```bash
npx wrangler pages deploy public --project-name qqq-dca-site --branch main --commit-dirty=true
```

## 计算公式

固定金额定投成本：

```text
180 / sum(1 / close_i)
```

其中 `close_i` 是最近 180 个交易日的收盘价。180 日均线是同一窗口的算术平均价。
