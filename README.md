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

`.github/workflows/update-data.yml` 会在美股收盘后自动运行：

1. 拉取 Yahoo Finance 日线数据
2. 更新 `data/prices/*.csv`
3. 计算 `data/*_180d_dca.csv`
4. 生成网页使用的 `public/data/market_dca.json` 和 `public/data/market_dca.js`
5. 提交更新并部署到 GitHub Pages

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
