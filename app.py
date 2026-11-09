"""网站卡密系统 - FastAPI 主应用"""
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database as db
import snippets
import backup


def fix_enc(s: str) -> str:
    """修复表单中文被按 latin-1 解码的双重编码问题"""
    if not s:
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def base_url(request: Request) -> str:
    """对外可访问的基础地址。

    Render 等平台部署在反向代理后面，request.base_url 可能是容器内部地址
    （如 http://0.0.0.0:10000），必须优先使用代理转发的 X-Forwarded-* 头。
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = (request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or request.url.netloc)
    return f"{proto}://{host}".rstrip("/")

BASE_DIR = Path(__file__).parent
app = FastAPI(title="卡密系统")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 数据库持久化：Render 免费实例重启会丢文件，用 GitHub 私有仓库自动备份/恢复
# 注意：必须先恢复再 init_db，否则空库会阻止恢复
try:
    backup.restore_if_missing()
except Exception as e:
    print("[backup] 恢复失败:", e)

db.init_db()
backup.start()

# 简易内存 session 与防刷
SESSIONS: dict[str, str] = {}
RATE: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()


def check_rate(ip: str) -> bool:
    import time

    now = time.time()
    stamps = [t for t in RATE.get(ip, []) if now - t < 60]
    if len(stamps) >= 10:
        RATE[ip] = stamps
        return False
    stamps.append(now)
    RATE[ip] = stamps
    return True


def fmt_time(s: str | None) -> str:
    """2026-11-09T17:37:31 → 2026-11-09 17:37"""
    if not s:
        return ""
    try:
        return datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return s


def card_view(r: dict) -> dict:
    if r.get("is_disabled"):
        st = "已停用"
    elif r["is_expired"]:
        st = "已过期"
    elif r["status"] == "used":
        st = "已使用"
    else:
        st = "未使用"
    expire_at = r["expire_at"]
    remain = ""
    if r["status"] == "used" and expire_at:
        if r["is_expired"]:
            remain = "已过期"
        else:
            try:
                total_min = int((datetime.fromisoformat(expire_at) - datetime.now()).total_seconds() // 60)
                d, rest = divmod(max(total_min, 0), 1440)
                h, m = divmod(rest, 60)
                remain = "剩 " + (f"{d} 天 " if d else "") + (f"{h} 小时 " if h else "") + (f"{m} 分" if m or (not d and not h) else "")
                remain = remain.strip()
            except ValueError:
                remain = ""
    elif r["status"] == "unused":
        remain = "未激活"
    else:
        remain = "永久"
    return {
        **r,
        "status_text": st,
        "duration_text": db.duration_text(r["duration_days"], r.get("duration_min", 0)),
        "expire_text": fmt_time(expire_at),
        "used_text": fmt_time(r["used_at"]),
        "remain_text": remain,
    }


# ---------------- 用户端 ----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    lang = (request.query_params.get("lang") or "").strip().lower()[:2]
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "site": "", "mode": db.DEFAULT_MODE, "site_lang": lang},
    )


@app.get("/admin/version")
async def admin_version(kami_session: str | None = Cookie(None)):
    """后台轮询数据版本号，变了前端自动刷新 → 卡密激活/接入秒显示"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False}, status_code=401)
    return {"ok": True, "v": db.data_version()}


@app.get("/panel/{token}", response_class=HTMLResponse)
async def panel_page(token: str, request: Request):
    """网站作者控制面板：作者凭专属链接进入，管理自己网站的卡密"""
    domain = db.site_by_token(token)
    if not domain:
        return PlainTextResponse("面板链接无效或已失效", status_code=404)
    return templates.TemplateResponse("panel.html", {"request": request, "token": token, "domain": domain})


def _panel_domain(token: str) -> str | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT domain FROM sites WHERE token=? OR IFNULL(panel_slug,'')=?",
            ((token or "").strip(), (token or "").strip()),
        ).fetchone()
        return row["domain"] if row else None
    finally:
        conn.close()


@app.post("/panel/api/data")
async def panel_data(request: Request, token: str = Form("")):
    domain = _panel_domain(token)
    if not domain:
        return JSONResponse({"ok": False, "message": "面板链接无效"}, status_code=404)
    st = db.site_settings(domain)
    cards = db.list_cards(domain=domain)
    return {
        "ok": True,
        "domain": domain,
        "stats": db.site_stats(domain),
        "unlock_mode": st["unlock_mode"],
        "lang": st["lang"],
        "cards": [
            {
                "code": c["code"], "status": c["status"],
                "days": db.duration_text(c["duration_days"], c.get("duration_min", 0)),
                "expire": c["expire_at"], "expired": c["is_expired"],
                "by": c["used_by"], "note": c["note"],
            }
            for c in cards[:500]
        ],
    }


@app.post("/panel/api/generate")
async def panel_generate(request: Request, token: str = Form(""), count: int = Form(1),
                         days: int = Form(30), hours: int = Form(0), minutes: int = Form(0),
                         note: str = Form("")):
    domain = _panel_domain(token)
    if not domain:
        return JSONResponse({"ok": False, "message": "面板链接无效"}, status_code=404)
    count = min(max(count, 1), 100)
    days = min(max(days, 0), 3650)
    hours = min(max(hours, 0), 23)
    minutes = min(max(minutes, 0), 59)
    codes = db.create_cards(count, days, note=fix_enc(note)[:50], site_domain=domain,
                            duration_min=hours * 60 + minutes)
    return {"ok": True, "codes": codes}


@app.post("/api/verify")
async def verify(request: Request, code: str = Form(""), site: str = Form(""), device: str = Form("")):
    ip = client_ip(request)
    if not check_rate(ip):
        return JSONResponse({"ok": False, "message": "尝试过于频繁，请稍后再试", "key": "rate"}, status_code=429)
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = site.strip() or None
    if not domain and origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at, key = db.verify_card(code, user=ip, domain=domain, device=device)
    return {"ok": ok, "message": message, "expire_at": expire_at, "key": key}


@app.post("/api/check")
async def check(request: Request, code: str = Form(""), site: str = Form(""), device: str = Form("")):
    """回访校验：不激活卡密，仅检查有效性（过期则要求重新输入）"""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = site.strip() or None
    if not domain and origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at, key = db.check_card(code, domain=domain, device=device)
    return {"ok": ok, "message": message, "expire_at": expire_at, "key": key}


# ---------------- App / 客户端接入（JSON API）----------------

@app.options("/api/app/verify")
async def app_verify_preflight():
    return PlainTextResponse("")


@app.post("/api/app/verify")
async def app_verify(request: Request):
    """App 首次激活：等同 /api/verify，但纯 JSON、支持 Header 传卡密

    请求（任选一种）：
      POST /api/app/verify
      Header: X-Kami-Code: XXXX-XXXX-XXXX-XXXX
      Header: X-Kami-App:  myapp
    或表单/JSON: {"code": "...", "app": "..."}
    """
    ip = client_ip(request)
    if not check_rate(ip):
        return JSONResponse({"ok": False, "key": "rate", "message": "尝试过于频繁，请稍后再试"}, status_code=429)
    code, app_id, dev = await _app_args(request)
    if not app_id:
        return JSONResponse({"ok": False, "key": "invalid", "message": "缺少 app 参数"}, status_code=400)
    ok, message, expire_at, key = db.verify_card(code, user=ip, domain=app_id, device=dev)
    return _app_resp(ok, key, expire_at, message)


@app.options("/api/app/check")
async def app_check_preflight():
    return PlainTextResponse("")


@app.post("/api/app/check")
async def app_check(request: Request):
    """App 每次启动校验：不激活、不扣时长，过期则返回 ok=false"""
    code, app_id, dev = await _app_args(request)
    if not app_id:
        return JSONResponse({"ok": False, "key": "invalid", "message": "缺少 app 参数"}, status_code=400)
    ok, message, expire_at, key = db.check_card(code, domain=app_id, device=dev)
    return _app_resp(ok, key, expire_at, message)


async def _app_args(request: Request) -> tuple[str, str, str]:
    """从 Header / JSON / 表单中取出卡密、App 标识与设备标识"""
    code = request.headers.get("x-kami-code") or ""
    app_id = request.headers.get("x-kami-app") or ""
    dev = request.headers.get("x-kami-device") or ""
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            code = code or str(body.get("code") or "")
            app_id = app_id or str(body.get("app") or body.get("site") or "")
            dev = dev or str(body.get("device") or "")
    else:
        try:
            form = await request.form()
            code = code or str(form.get("code") or "")
            app_id = app_id or str(form.get("app") or form.get("site") or "")
            dev = dev or str(form.get("device") or "")
        except Exception:
            pass
    return (code or "").strip().upper(), db.normalize_domain(app_id), (dev or "").strip()


def _app_resp(ok: bool, key: str, expire_at, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "ok": ok,
            "key": key,
            "message": message,
            "expire_at": expire_at,
            "expire_text": (
                "永久有效" if (ok and not expire_at)
                else (str(expire_at).replace("T", " ")[:16] if expire_at else "")
            ),
            "days_left": _days_left(expire_at),
        }
    )


def _days_left(expire_at):
    if not expire_at:
        return None
    try:
        delta = datetime.fromisoformat(str(expire_at)) - datetime.now()
        return max(0, delta.days)
    except ValueError:
        return None


@app.get("/api/site")
async def api_site(request: Request):
    """供嵌入脚本 / 指定链接页读取站点配置（解锁方式、首选语言）"""
    site = (request.query_params.get("site") or "").strip()
    st = db.site_settings(site or None)
    return {"site": site, "mode": st["unlock_mode"], "lang": st["lang"]}


# ---------------- embed.js ----------------

EMBED_TPL = BASE_DIR / "static" / "embed.tpl.js"
_TPL_CACHE: dict = {"mtime": 0.0, "text": ""}


def embed_template() -> str:
    """读取嵌入脚本模板（按 mtime 缓存，改了文件自动生效）"""
    try:
        mt = EMBED_TPL.stat().st_mtime
        if _TPL_CACHE["mtime"] != mt or not _TPL_CACHE["text"]:
            _TPL_CACHE["text"] = EMBED_TPL.read_text(encoding="utf-8")
            _TPL_CACHE["mtime"] = mt
    except OSError:
        return ""
    return _TPL_CACHE["text"]


@app.get("/embed.js")
async def embed_js(request: Request):
    import json
    base = base_url(request)
    site = request.query_params.get("site") or ""
    st = db.site_settings(site or None)
    t = dict(db.THEME_DEFAULT)  # 弹窗样式系统统一，文案由 embed.tpl.js 按语言翻译
    js = (
        embed_template()
        .replace("__BASE__", base)
        .replace("__SITE__", site)
        .replace("__MODE__", st["unlock_mode"])
        .replace("__LANG__", st["lang"] or "")
        .replace("__TITLE__", json.dumps("", ensure_ascii=False))
        .replace("__SUB__", json.dumps("", ensure_ascii=False))
        .replace("__BTN__", json.dumps("", ensure_ascii=False))
        .replace("__COLOR__", json.dumps(t["color"], ensure_ascii=False))
    )
    return PlainTextResponse(
        js,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Access-Control-Allow-Origin": "*"},
    )


# ---------------- 管理后台 ----------------

@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
async def admin_login(request: Request, username: str = Form(""), password: str = Form("")):
    ip = client_ip(request)
    if not check_rate(ip):
        return JSONResponse({"ok": False, "message": "尝试过于频繁"}, status_code=429)
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row or not db.check_password(password, row["password_hash"]):
        return JSONResponse({"ok": False, "message": "用户名或密码错误"}, status_code=401)
    token = secrets.token_hex(32)
    SESSIONS[token] = username
    resp = JSONResponse({"ok": True})
    resp.set_cookie("kami_session", token, httponly=True, samesite="lax")
    return resp


def require_auth(kami_session: str | None = Cookie(None)):
    return kami_session in SESSIONS


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, kami_session: str | None = Cookie(None)):
    if not require_auth(kami_session):
        return RedirectResponse("/admin")
    status = request.query_params.get("status") or None
    q = request.query_params.get("q") or None
    domain = request.query_params.get("domain") or None
    cards = [card_view(r) for r in db.list_cards(status, q, domain)]
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "cards": cards,
            "stats": db.stats(),
            "sites": db.list_sites(),
            "status": status or "",
            "q": q or "",
            "domain": domain or "",
            "base": base_url(request),
        },
    )


@app.post("/admin/generate")
async def generate(
    kami_session: str | None = Cookie(None),
    count: int = Form(10),
    duration_days: int = Form(0),
    duration_min: int = Form(0),
    note: str = Form(""),
    site_domain: str = Form(""),
    max_devices: int = Form(1),
):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    site_domain = db.normalize_domain(site_domain)
    if site_domain and not db.site_exists(site_domain):
        return JSONResponse(
            {"ok": False, "message": f"网站「{site_domain}」尚未接入，请先在「添加网站」中登记"},
            status_code=400,
        )
    duration_days = min(max(duration_days, 0), 3650)
    duration_min = min(max(duration_min, 0), 3650 * 1440)
    if duration_days == 0 and duration_min == 0:
        pass  # 永久卡
    codes = db.create_cards(
        count, duration_days, fix_enc(note), site_domain or None,
        max_devices=min(max(int(max_devices), 0), 10), duration_min=duration_min,
    )
    return {"ok": True, "codes": codes}


@app.post("/admin/generate_custom")
async def generate_custom(
    kami_session: str | None = Cookie(None),
    codes: str = Form(""),
    duration_days: int = Form(0),
    duration_min: int = Form(0),
    note: str = Form(""),
    site_domain: str = Form(""),
    max_devices: int = Form(1),
):
    """自定义卡密：任意内容（123456 / 1a2a / iuahduh），换行、空格或逗号分隔"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    import re

    raw = [c for c in re.split(r"[\s,，;；]+", codes or "") if c.strip()]
    if not raw:
        return {"ok": False, "message": "请填写至少一个卡密"}
    if len(raw) > 500:
        return {"ok": False, "message": "单次最多 500 个"}
    site_domain = db.normalize_domain(site_domain)
    if site_domain and not db.site_exists(site_domain):
        return {"ok": False, "message": f"网站「{site_domain}」尚未接入，请先登记"}
    duration_days = min(max(duration_days, 0), 3650)
    duration_min = min(max(duration_min, 0), 3650 * 1440)
    created, skipped = db.create_custom_cards(
        raw, duration_days, fix_enc(note), site_domain or None,
        max_devices=min(max(int(max_devices), 0), 10), duration_min=duration_min,
    )
    return {"ok": True, "created": created, "skipped": skipped}


@app.post("/admin/extend/{card_id}")
async def extend(card_id: int, kami_session: str | None = Cookie(None),
                 days: int = Form(0), hours: int = Form(0), minutes: int = Form(0)):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    ok, msg = db.extend_card(card_id, days, hours, minutes)
    return {"ok": ok, "message": msg}


@app.post("/admin/toggle/{card_id}")
async def toggle_card(card_id: int, kami_session: str | None = Cookie(None), disabled: int = Form(1)):
    """停用 / 启用卡密：客户端下次心跳（默认 5 秒）即锁屏"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    ok, msg = db.set_disabled(card_id, bool(disabled))
    return {"ok": ok, "message": msg}


@app.post("/admin/delete/{card_id}")
async def delete(card_id: int, kami_session: str | None = Cookie(None)):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    db.delete_card(card_id)
    return {"ok": True}


@app.post("/admin/change-password")
async def change_password(
    request: Request,
    kami_session: str | None = Cookie(None),
    old_password: str = Form(""),
    new_password: str = Form(""),
):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    username = SESSIONS.get(kami_session, "admin")
    ok, msg = db.change_password(username, old_password, new_password)
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    # 密码修改成功后使所有会话失效，强制重新登录
    SESSIONS.clear()
    resp = JSONResponse({"ok": True, "message": msg})
    resp.delete_cookie("kami_session")
    return resp


@app.get("/admin/logout")
async def logout(kami_session: str | None = Cookie(None)):
    if kami_session:
        SESSIONS.pop(kami_session, None)
    resp = RedirectResponse("/admin")
    resp.delete_cookie("kami_session")
    return resp


@app.post("/admin/site/panel/{site_id}")
async def admin_site_panel(site_id: int, request: Request, kami_session: str | None = Cookie(None),
                           slug: str = Form("")):
    """设置作者面板链接。slug 为空 → 使用/生成随机地址；自定义后缀仅限字母数字-_"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    r = db.site_token(site_id)
    if not r:
        return JSONResponse({"ok": False, "message": "网站不存在"}, status_code=404)
    domain, tok = r
    base = base_url(request)
    slug = (slug or "").strip()
    if slug:
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9_-]{3,40}", slug):
            return JSONResponse({"ok": False, "message": "后缀只能用 3~40 位字母、数字、- 或 _"}, status_code=400)
        ok, msg = db.set_panel_slug(site_id, slug)
        if not ok:
            return JSONResponse({"ok": False, "message": msg}, status_code=400)
    return {"ok": True, "domain": domain, "panel": f"{base}/panel/{slug or tok}"}


@app.post("/admin/site/delete/{site_id}")
async def delete_site(site_id: int, kami_session: str | None = Cookie(None)):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    db.delete_site(site_id)
    return {"ok": True}


@app.post("/admin/site/add")
async def admin_site_add(
    request: Request,
    kami_session: str | None = Cookie(None),
    domain: str = Form(""),
    note: str = Form(""),
    unlock_mode: str = Form(""),
    lang: str = Form(""),
):
    """手动新增一个接入网站（也可以等它自己上报，这里用于提前登记）"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    ok, msg, row = db.add_site(fix_enc(domain), fix_enc(note), unlock_mode or None, lang)
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    base = base_url(request)
    slug = (row.get("panel_slug") or "").strip()
    panel = f"{base}/panel/{slug or row.get('token', '')}"
    return {
        "ok": True,
        "id": row["id"],
        "domain": row["domain"],
        "embed": f'<script src="{base}/embed.js?site={row["domain"]}"></script>',
        "is_app": "." not in row["domain"],
        "api": f"{base}/api/app/verify",
        "panel": panel,
    }


@app.post("/admin/site/code/{site_id}")
async def admin_site_code(site_id: int, request: Request, kami_session: str | None = Cookie(None)):
    """返回该网站/App 的全部接入代码（按技术栈分组）"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    conn = db.get_conn()
    row = conn.execute("SELECT domain, note FROM sites WHERE id=?", (site_id,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse({"ok": False, "message": "网站不存在"}, status_code=404)
    base = base_url(request)
    domain = row["domain"]
    is_app = "." not in domain
    return {
        "ok": True,
        "domain": domain,
        "is_app": is_app,
        "base": base,
        "embed": f'<script src="{base}/embed.js?site={domain}"></script>',
        "snippets": snippets.build_snippets(base, domain),
    }


@app.post("/admin/site/mode/{site_id}")
async def admin_site_mode(site_id: int, mode: str = Form(""), kami_session: str | None = Cookie(None)):
    """设置该网站的解锁方式：blur 模糊 / dim 变暗 / lock 锁屏"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    if not db.set_site_unlock_mode(site_id, mode):
        return JSONResponse({"ok": False, "message": "解锁方式无效"}, status_code=400)
    return {"ok": True, "mode": mode}


@app.post("/admin/site/lang/{site_id}")
async def admin_site_lang(site_id: int, lang: str = Form(""), kami_session: str | None = Cookie(None)):
    """设置该网站的语言；留空 = 按访客浏览器语言自动检测"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    db.set_site_lang(site_id, lang)
    return {"ok": True, "lang": lang}


@app.get("/admin/export")
async def export(kami_session: str | None = Cookie(None)):
    if not require_auth(kami_session):
        return RedirectResponse("/admin")
    import csv, io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["卡密", "状态", "有效天数", "创建时间", "使用时间", "到期时间", "使用者", "绑定网站", "备注"])
    for r in db.list_cards():
        w.writerow([r["code"], card_view(r)["status_text"], card_view(r)["duration_text"], r["created_at"],
                    r["used_at"] or "", r["expire_at"] or "", r["used_by"] or "", r["site_domain"] or "全网通用", r["note"] or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cards.csv"},
    )
