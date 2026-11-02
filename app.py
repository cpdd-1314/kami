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
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/verify")
async def verify(request: Request, code: str = Form("")):
    ip = client_ip(request)
    if not check_rate(ip):
        return JSONResponse({"ok": False, "message": "尝试过于频繁，请稍后再试"}, status_code=429)
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    domain = None
    if origin:
        from urllib.parse import urlparse
        domain = urlparse(origin).netloc or None
    ok, message, expire_at = db.verify_card(code, user=ip, domain=domain)
    return {"ok": ok, "message": message, "expire_at": expire_at}


# ---------------- embed.js ----------------

EMBED_JS = """(function () {
  var KEY = 'kami_unlocked_until';
  var now = Date.now();
  var until = parseInt(localStorage.getItem(KEY) || '0', 10);
  function unlocked() { return until > now && (until === 1 || until > Date.now()); }
  function unlock() {
    var el = document.getElementById('kami-overlay');
    if (el) el.remove();
  }
  if (unlocked()) { window.addEventListener('DOMContentLoaded', unlock); return; }
  function build() {
    if (document.getElementById('kami-overlay')) return;
    var overlay = document.createElement('div');
    overlay.id = 'kami-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.15);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);';
    var box = document.createElement('div');
    box.style.cssText = 'width:min(92vw,400px);background:#fff;border-radius:16px;padding:32px 28px;box-shadow:0 20px 60px rgba(80,60,180,.35);font-family:system-ui,-apple-system,sans-serif;text-align:center;';
    box.innerHTML = ''
      + '<div style="font-size:40px;">\\u{1F511}</div>'
      + '<h2 style="margin:10px 0 6px;color:#1f2340;font-size:22px;">\\u8bf7\\u8f93\\u5165\\u5361\\u5bc6</h2>'
      + '<p style="margin:0 0 18px;color:#8a8fa8;font-size:13px;">\\u9a8c\\u8bc1\\u901a\\u8fc7\\u540e\\u5373\\u53ef\\u67e5\\u770b\\u672c\\u9875\\u5185\\u5bb9</p>'
      + '<input id="kami-code" placeholder="XXXX-XXXX-XXXX-XXXX" style="width:100%;box-sizing:border-box;padding:12px 14px;border:1.5px solid #dcdff0;border-radius:10px;font-size:16px;letter-spacing:2px;text-align:center;outline:none;transition:border-color .2s;" />'
      + '<button id="kami-btn" style="margin-top:14px;width:100%;padding:12px;border:none;border-radius:10px;background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;font-size:16px;cursor:pointer;">\\u9a8c \\u8bc1</button>'
      + '<p id="kami-msg" style="min-height:18px;margin:12px 0 0;color:#ef4444;font-size:13px;"></p>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    var input = box.querySelector('#kami-code'), msg = box.querySelector('#kami-msg'), btn = box.querySelector('#kami-btn');
    input.focus();
    function shake() { input.style.borderColor = '#ef4444'; box.style.transition = 'transform .1s'; var n = 0; var t = setInterval(function () { n++; box.style.transform = 'translateX(' + (n % 2 ? -6 : 6) + 'px)'; if (n > 5) { clearInterval(t); box.style.transform = ''; } }, 60); }
    function submit() {
      var code = input.value.trim();
      if (!code) { msg.textContent = '\\u8bf7\\u8f93\\u5165\\u5361\\u5bc6'; shake(); return; }
      btn.disabled = true; btn.textContent = '\\u9a8c\\u8bc1\\u4e2d...';
      fetch('%BASE%/api/verify', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'code=' + encodeURIComponent(code) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.ok) {
            var exp = d.expire_at ? new Date(d.expire_at).getTime() : 1;
            localStorage.setItem(KEY, String(exp));
            unlock();
          } else { msg.textContent = d.message || '\\u9a8c\\u8bc1\\u5931\\u8d25'; shake(); }
        })
        .catch(function () { msg.textContent = '\\u7f51\\u7edc\\u9519\\u8bef\\uff0c\\u8bf7\\u91cd\\u8bd5'; })
        .finally(function () { btn.disabled = false; btn.textContent = '\\u9a8c \\u8bc1'; });
    }
    btn.onclick = submit;
    input.onkeydown = function (e) { if (e.key === 'Enter') submit(); };
    input.oninput = function () { input.style.borderColor = '#dcdff0'; msg.textContent = ''; };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();"""


@app.get("/embed.js")
async def embed_js(request: Request):
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(EMBED_JS.replace("%BASE%", base), media_type="application/javascript")


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
