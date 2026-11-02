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
    return templates.TemplateResponse("index.html", {"request": request, "site": ""})


@app.get("/s/{token}", response_class=HTMLResponse)
async def site_page(token: str, request: Request):
    """网站指定链接：验证页绑定到该网站，只能用该网站（或通用）的卡密"""
    domain = db.site_by_token(token)
    if not domain:
        return PlainTextResponse("链接无效或已失效", status_code=404)
    return templates.TemplateResponse("index.html", {"request": request, "site": domain})


@app.post("/api/verify")
async def verify(request: Request, code: str = Form(""), site: str = Form("")):
    ip = client_ip(request)
    if not check_rate(ip):
        return JSONResponse({"ok": False, "message": "尝试过于频繁，请稍后再试"}, status_code=429)
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = site.strip() or None
    if not domain and origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at = db.verify_card(code, user=ip, domain=domain)
    return {"ok": ok, "message": message, "expire_at": expire_at}


@app.post("/api/check")
async def check(request: Request, code: str = Form(""), site: str = Form("")):
    """回访校验：不激活卡密，仅检查有效性（过期则要求重新输入）"""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = site.strip() or None
    if not domain and origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at = db.check_card(code, domain=domain)
    return {"ok": ok, "message": message, "expire_at": expire_at}


# ---------------- embed.js ----------------

EMBED_JS = """(function () {
  var KC = 'kami_code';
  var SITE = '%SITE%';
  var T_TITLE = %TITLE%;
  var T_SUB = %SUB%;
  var T_BTN = %BTN%;
  var T_COLOR = %COLOR%;
  function fmtExp(e) { return e ? '有效期至 ' + e.replace('T', ' ').slice(0, 16) : '永久有效'; }
  function toast(txt) {
    var t = document.createElement('div');
    t.style.cssText = 'position:fixed;left:50%;top:24px;transform:translateX(-50%);z-index:2147483647;background:#16a34a;color:#fff;padding:12px 22px;border-radius:10px;font-size:15px;font-family:system-ui,-apple-system,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.25);';
    t.textContent = txt;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 3000);
  }
  function post(url, code, cb) {
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'code=' + encodeURIComponent(code) + '&site=' + encodeURIComponent(SITE) })
      .then(function (r) { return r.json(); }).then(cb)
      .catch(function () { cb({ ok: false, message: '网络错误，请重试' }); });
  }
  function unlock() {
    var el = document.getElementById('kami-overlay');
    if (el) el.remove();
  }
  function build(prefill, tip) {
    if (document.getElementById('kami-overlay')) return;
    var overlay = document.createElement('div');
    overlay.id = 'kami-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.15);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);';
    var box = document.createElement('div');
    box.style.cssText = 'width:min(92vw,400px);background:#fff;border-radius:16px;padding:32px 28px;box-shadow:0 20px 60px rgba(80,60,180,.35);font-family:system-ui,-apple-system,sans-serif;text-align:center;';
    box.innerHTML = ''
      + '<div style="width:74px;height:74px;margin:0 auto;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:34px;background:linear-gradient(135deg,' + T_COLOR + '22,' + T_COLOR + '11);box-shadow:0 10px 24px ' + T_COLOR + '33;">\\u{1F511}</div>'
      + '<h2 style="margin:14px 0 6px;color:#1f2340;font-size:21px;">' + T_TITLE + '</h2>'
      + '<p style="margin:0 0 20px;color:#8a8fa8;font-size:13px;">' + (tip || T_SUB) + '</p>'
      + '<input id="kami-code" placeholder="XXXX-XXXX-XXXX-XXXX" style="width:100%;box-sizing:border-box;padding:13px 14px;border:1.5px solid #dcdff0;border-radius:12px;font-size:16px;letter-spacing:2px;text-align:center;outline:none;transition:border-color .2s,box-shadow .2s;background:#fafbff;" />'
      + '<button id="kami-btn" style="margin-top:14px;width:100%;padding:13px;border:none;border-radius:12px;background:linear-gradient(135deg,' + T_COLOR + ',' + T_COLOR + 'cc);color:#fff;font-size:16px;font-weight:600;letter-spacing:6px;cursor:pointer;box-shadow:0 8px 20px ' + T_COLOR + '55;">' + T_BTN + '</button>'
      + '<p id="kami-msg" style="min-height:18px;margin:12px 0 0;color:#ef4444;font-size:13px;"></p>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    var input = box.querySelector('#kami-code'), msg = box.querySelector('#kami-msg'), btn = box.querySelector('#kami-btn');
    if (prefill) input.value = prefill;
    input.focus();
    function shake() { input.style.borderColor = '#ef4444'; box.style.transition = 'transform .1s'; var n = 0; var t = setInterval(function () { n++; box.style.transform = 'translateX(' + (n % 2 ? -6 : 6) + 'px)'; if (n > 5) { clearInterval(t); box.style.transform = ''; } }, 60); }
    function submit() {
      var code = input.value.trim();
      if (!code) { msg.textContent = '\\u8bf7\\u8f93\\u5165\\u5361\\u5bc6'; shake(); return; }
      btn.disabled = true; btn.textContent = T_BTN + '...';
      post('%BASE%/api/verify', code, function (d) {
        if (d.ok) {
          localStorage.setItem(KC, code);
          unlock();
          toast('✓ 卡密有效，' + fmtExp(d.expire_at));
        } else { msg.textContent = d.message || '卡密无效'; shake(); }
        btn.disabled = false; btn.textContent = T_BTN;
      });
    }
    btn.onclick = submit;
    input.onkeydown = function (e) { if (e.key === 'Enter') submit(); };
    input.oninput = function () { input.style.borderColor = '#dcdff0'; msg.textContent = ''; };
  }
  // 每次进入都用服务器校验一次已保存的卡密（过期/失效立即弹窗）
  var saved = null;
  try { saved = localStorage.getItem(KC); } catch (e) {}
  if (saved) {
    post('%BASE%/api/check', saved, function (d) {
      if (d.ok) {
        var go = function () { unlock(); toast('✓ 卡密有效，' + fmtExp(d.expire_at)); };
        if (document.readyState === 'loading') window.addEventListener('DOMContentLoaded', go); else go();
      }
      else build(saved, d.message);
    });
  } else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { build(); });
  else build();
})();"""


@app.get("/embed.js")
async def embed_js(request: Request):
    import json
    base = str(request.base_url).rstrip("/")
    site = request.query_params.get("site") or ""
    t = db.site_theme(site or None)
    js = (
        EMBED_JS.replace("%BASE%", base)
        .replace("%SITE%", site)
        .replace("%TITLE%", json.dumps(t["title"], ensure_ascii=False))
        .replace("%SUB%", json.dumps(t["sub"], ensure_ascii=False))
        .replace("%BTN%", json.dumps(t["btn"], ensure_ascii=False))
        .replace("%COLOR%", json.dumps(t["color"], ensure_ascii=False))
    )
    return PlainTextResponse(js, media_type="application/javascript")


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
        {"request": request, "cards": cards, "stats": db.stats(), "sites": db.list_sites(), "status": status or "", "q": q or ""},
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


@app.post("/admin/site/theme/{site_id}")
async def admin_site_theme(
    site_id: int,
    kami_session: str | None = Cookie(None),
    title: str = Form(""),
    sub: str = Form(""),
    btn: str = Form(""),
    color: str = Form(""),
):
    if not require_auth(kami_session):
        return JSONResponse({"ok": False, "message": "未登录"}, status_code=401)
    if color and not color.startswith("#"):
        return JSONResponse({"ok": False, "message": "颜色需为 #RRGGBB 格式"}, status_code=400)
    db.set_site_theme(site_id, title, sub, btn, color)
    return {"ok": True}


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
