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

BASE_DIR = Path(__file__).parent
app = FastAPI(title="卡密系统")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

db.init_db()

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


def card_view(r: dict) -> dict:
    st = "已过期" if r["is_expired"] else ("已使用" if r["status"] == "used" else "未使用")
    return {**r, "status_text": st}


# ---------------- 用户端 ----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    lang = (request.query_params.get("lang") or "").strip().lower()[:2]
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "site": "", "mode": db.DEFAULT_MODE, "site_lang": lang},
    )


@app.get("/s/{token}", response_class=HTMLResponse)
async def site_page(token: str, request: Request):
    """网站指定链接：验证页绑定到该网站，只能用该网站（或通用）的卡密"""
    domain = db.site_by_token(token)
    if not domain:
        return PlainTextResponse("链接无效或已失效", status_code=404)
    st = db.site_settings(domain)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "site": domain, "mode": st["unlock_mode"], "site_lang": st["lang"]},
    )


@app.post("/api/verify")
async def verify(request: Request, code: str = Form(""), site: str = Form("")):
    ip = client_ip(request)
    if not check_rate(ip):
        return JSONResponse({"ok": False, "message": "尝试过于频繁，请稍后再试", "key": "rate"}, status_code=429)
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = site.strip() or None
    if not domain and origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at, key = db.verify_card(code, user=ip, domain=domain)
    return {"ok": ok, "message": message, "expire_at": expire_at, "key": key}


@app.post("/api/check")
async def check(request: Request, code: str = Form(""), site: str = Form("")):
    """回访校验：不激活卡密，仅检查有效性（过期则要求重新输入）"""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = site.strip() or None
    if not domain and origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at, key = db.check_card(code, domain=domain)
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
    code, app_id = await _app_args(request)
    if not app_id:
        return JSONResponse({"ok": False, "key": "invalid", "message": "缺少 app 参数"}, status_code=400)
    ok, message, expire_at, key = db.verify_card(code, user=ip, domain=app_id)
    return _app_resp(ok, key, expire_at, message)


@app.options("/api/app/check")
async def app_check_preflight():
    return PlainTextResponse("")


@app.post("/api/app/check")
async def app_check(request: Request):
    """App 每次启动校验：不激活、不扣时长，过期则返回 ok=false"""
    code, app_id = await _app_args(request)
    if not app_id:
        return JSONResponse({"ok": False, "key": "invalid", "message": "缺少 app 参数"}, status_code=400)
    ok, message, expire_at, key = db.check_card(code, domain=app_id)
    return _app_resp(ok, key, expire_at, message)


async def _app_args(request: Request) -> tuple[str, str]:
    """从 Header / JSON / 表单中取出卡密与 App 标识"""
    code = request.headers.get("x-kami-code") or ""
    app_id = request.headers.get("x-kami-app") or ""
    ctype = (request.headers.get("content-type") or "").lower()
    if "json" in ctype:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            code = code or str(body.get("code") or "")
            app_id = app_id or str(body.get("app") or body.get("site") or "")
    else:
        try:
            form = await request.form()
            code = code or str(form.get("code") or "")
            app_id = app_id or str(form.get("app") or form.get("site") or "")
        except Exception:
            pass
    return (code or "").strip().upper(), db.normalize_domain(app_id)


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
    base = str(request.base_url).rstrip("/")
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
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, max-age=60", "Access-Control-Allow-Origin": "*"},
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
    cards = [card_view(r) for r in db.list_cards(status, q)]
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "cards": cards,
            "stats": db.stats(),
            "sites": db.list_sites(),
            "status": status or "",
            "q": q or "",
            "base": str(request.base_url).rstrip("/"),
        },
    )


@app.post("/admin/generate")
async def generate(
    kami_session: str | None = Cookie(None),
    count: int = Form(10),
    duration_days: int = Form(0),
    note: str = Form(""),
    site_domain: str = Form(""),
):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    site_domain = db.normalize_domain(site_domain)
    if site_domain and not db.site_exists(site_domain):
        return JSONResponse(
            {"ok": False, "message": f"网站「{site_domain}」尚未接入，请先在「添加网站」中登记"},
            status_code=400,
        )
    codes = db.create_cards(count, duration_days, note, site_domain or None)
    return {"ok": True, "codes": codes}


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


@app.post("/admin/site/link/{site_id}")
async def admin_site_link(site_id: int, request: Request, kami_session: str | None = Cookie(None)):
    """为指定网站生成「指定链接」（admin 自选是否生成；重复调用会轮换 token）"""
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    r = db.site_token(site_id)
    if not r:
        return JSONResponse({"ok": False, "message": "网站不存在"}, status_code=404)
    domain, tok = r
    base = str(request.base_url).rstrip("/")
    return {"ok": True, "domain": domain, "url": f"{base}/s/{tok}"}


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
    ok, msg, row = db.add_site(domain, note, unlock_mode or None, lang)
    if not ok:
        return JSONResponse({"ok": False, "message": msg}, status_code=400)
    base = str(request.base_url).rstrip("/")
    r = db.site_token(row["id"])
    link = f"{base}/s/{r[1]}" if r else ""
    return {
        "ok": True,
        "id": row["id"],
        "domain": row["domain"],
        "embed": f'<script src="{base}/embed.js?site={row["domain"]}"></script>',
        "link": link,
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
        w.writerow([r["code"], card_view(r)["status_text"], r["duration_days"], r["created_at"],
                    r["used_at"] or "", r["expire_at"] or "", r["used_by"] or "", r["site_domain"] or "全网通用", r["note"] or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cards.csv"},
    )
