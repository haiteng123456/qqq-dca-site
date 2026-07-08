# QQQ 180日定投成本静态站

这个项目会每天更新 QQQ 收盘价，并计算“当天之前 180 个交易日”的固定金额定投成本。

## 本地更新

```powershell
cd D:\AliWorkbenchData\qqq-dca-site
python .\scripts\update_qqq.py --seed ..\qqq_prices_inception_to_2026-06-10.csv
```

然后启动一个本地静态服务器：

```powershell
cd D:\AliWorkbenchData\qqq-dca-site\public
python -m http.server 8080
```

浏览器打开：

```text
http://127.0.0.1:8080/
```

## 自动更新

`.github/workflows/update-data.yml` 会在美股收盘后自动运行：

1. 拉取 Yahoo Finance 的 QQQ 日线数据
2. 更新 `data/qqq_prices.csv`
3. 重新计算 `data/qqq_180d_dca.csv`
4. 生成网页使用的 `public/data/qqq_180d_dca.json` 和 `public/data/qqq_180d_dca.js`
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

```powershell
cd D:\AliWorkbenchData\qqq-dca-site
npx wrangler pages deploy public --project-name qqq-dca-site --branch main --commit-dirty=true
```

## 计算公式

固定金额定投成本：

```text
180 / sum(1 / close_i)
```

其中 `close_i` 是目标日期之前 180 个交易日的 QQQ 收盘价。
