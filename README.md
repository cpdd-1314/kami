# kami · 网站卡密系统

给网站 / App 加一道卡密门槛：访客看到的是模糊遮罩弹窗，**卡密正确弹窗消失并显示内容，卡密错误弹窗保持不动**。支持自己指定卡密、天/小时/分钟级有效期、设备绑定、续期和多网站接入。

## 核心功能

- **弹窗模糊解锁**：内容默认毛玻璃遮住，验证通过才展示
- **自定义卡密**：想填什么就填什么，如 `123456`、`1a2a`、`iuahduh`；多个用换行 / 空格 / 逗号分隔；**验证不区分大小写**，重复自动跳过
- **随机批量生成**：`XXXX-XXXX-XXXX-XXXX`（排除 0/O/1/I 易混字符）
- **灵活有效期**：天 / 小时 / 分钟，0 = 永久；到期自动失效，后台可一键续期
- **设备绑定**：默认限 1 台设备，可选 2/3 台或不限
- **多网站接入**：一行 `<script src=".../embed.js">` 即可，自动登记来源网站；也支持 Android / iOS / Flutter / RN / C# / Python 等接入（见后台「接入其他软件」）
- **作者面板**：为每个接入网站生成独立面板链接，网站作者可自助查看、生成自己的卡密
- **管理后台**：数据概览、卡密筛选、批量/自定义生成、续期、删除、CSV 导出、修改密码
- **防刷**：同 IP 每分钟最多 10 次验证尝试
- **数据备份**：`backup.py` 自动备份 SQLite 数据

## 快速开始

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

| 入口 | 地址 |
|---|---|
| 前台页面 | http://localhost:8000/ |
| 管理后台 | http://localhost:8000/admin （默认 `admin` / `admin123`，请立即修改） |
| 嵌入脚本 | http://localhost:8000/embed.js |

## 自定义卡密

后台「✍️ 自定义卡密」面板：填入卡密内容（换行 / 空格 / 逗号分隔，单次最多 500 个），可同时设置有效期、绑定网站、备注、设备限制。

接口方式：

```bash
curl -X POST http://localhost:8000/admin/generate_custom \
  -H "Cookie: kami_session=<登录后的 cookie>" \
  -d "codes=123456,1a2a iuahduh&duration_days=30&duration_min=0&max_devices=1"
```

返回 `{"ok": true, "created": [...], "skipped": [...]}`，`skipped` 为已存在被跳过的卡密。


## 心跳校验与自动锁屏（5 秒）

解锁后，客户端每 **5 秒**向服务端复核一次卡密（`POST /api/check`）。一旦失效（到期 / 后台停用 / 换设备 / 被删除），**立即全屏锁屏并中断功能**，页面上的「重新验证」按钮可让用户重新输入卡密。

**防误锁**：网络异常不会立刻锁屏，连续失败 5 次（约 25 秒）才判定为「无法验证」并锁定；页面切回前台时会立刻补一次校验，防止挂机绕过。

### 宿主页面可配置项

```html
<script>
  window.KAMI_HEARTBEAT_MS = 5000;   // 心跳间隔，默认 5000（最小 1000）
  window.KAMI_LOCK_ACTION = 'screen'; // 'screen' 直接锁屏（默认）｜'function' 只回调，业务自己锁功能
  window.KAMI_ON_LOCK = function (info) {
    // info = { code, reason, message }
    // reason: expired | disabled | invalid | limit | device | net
    myApp.lockFeatures();            // 例如：屏蔽播放器、隐藏数据、跳转付费页
  };
  window.KAMI_ON_UNLOCK = function (info) { myApp.unlockFeatures(); };
</script>
```

也可用 DOM 事件监听（适配任意框架）：

```js
document.addEventListener('kami:lock',   e => lockUI(e.detail));
document.addEventListener('kami:unlock', e => unlockUI(e.detail));
```

### 后台远程“一键锁”

后台卡密列表每行的 **停用** 按钮：点一下，持有该卡密的网站 / App 会在 5 秒内自动锁屏；再点 **启用** 即恢复。适用于退款、盗版、欠费等场景。

### 演示

- 第三方网站接入演示：`/static/demo-embed.html`（含锁屏回调示例）
- 接入代码示例（Android / iOS / Flutter / RN / C# / Python 等）已在后台「接入其他软件」中同步为 5 秒心跳

## 在其他网站使用

```html
<script src="http://你的域名:8000/embed.js"></script>
```

脚本会在页面叠加模糊遮罩 + 卡密弹窗，验证通过后移除；解锁状态记在浏览器本地，有效期到后重新要求输入。

> 仅可用于**您自己拥有管理权限**的网站，不要向他人网站注入代码。

## GitHub Pages 静态版

`docs/` 是纯前端版本，可直接托管在 GitHub Pages（仓库 Settings → Pages → 分支 `main`，目录 `/docs`）。

- 卡密在 `docs/cards.js` 维护：`{ code: "123456", days: 30 }`，`days: 0` 为永久
- 无需后端即可运行，但卡密对查看源码的人可见，适合低价值内容；高价值权益请使用后端版 + `embed.js`

## 部署

仓库内含 `Dockerfile`、`Procfile`、`render.yaml`、`zbpack.json`，可部署到 Docker / Render / Zeabur 等平台；数据库为单文件 SQLite（`kami.db`，已加入 `.gitignore`）。

## 文件结构

```
app.py            FastAPI 主应用（验证 API、后台、embed.js、作者面板）
database.py       SQLite 初始化、卡密生成/自定义/校验/续期/设备绑定
backup.py         数据自动备份
snippets.py       各语言接入代码生成
templates/        index.html 前台、admin.html 后台、panel.html 作者面板
static/           style.css、admin.css、embed.tpl.js
docs/             GitHub Pages 纯静态版
```
