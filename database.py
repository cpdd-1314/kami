"""SQLite 数据库初始化与操作"""
import sqlite3
import secrets
import hashlib
import os
from datetime import datetime, timedelta

# 数据库文件路径：可通过环境变量 KAMI_DB_PATH 指定（便于 Zeabur 等平台挂载持久卷，如 /data/kami.db）
DB_PATH = os.environ.get("KAMI_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "kami.db"
)
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

SAFE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 排除 0 O 1 I


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'unused',   -- unused / used
            duration_days INTEGER NOT NULL DEFAULT 0, -- 0 = 永久
            created_at TEXT NOT NULL,
            used_at TEXT,
            expire_at TEXT,
            used_by TEXT,
            site_domain TEXT,                          -- 绑定网站域名，NULL = 全网通用
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    # 默认管理员 admin / admin123
    if not conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("admin", hash_password("admin123")),
        )
    conn.commit()
    conn.close()


def hash_password(pwd: str) -> str:
    salt = secrets.token_hex(16)
    return salt + "$" + hashlib.sha256((salt + pwd).encode()).hexdigest()


def check_password(pwd: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hashlib.sha256((salt + pwd).encode()).hexdigest() == _


def generate_code() -> str:
    conn = get_conn()
    while True:
        parts = [
            "".join(secrets.choice(SAFE_CHARS) for _ in range(4)) for _ in range(4)
        ]
        code = "-".join(parts)
        if not conn.execute("SELECT 1 FROM cards WHERE code=?", (code,)).fetchone():
            conn.close()
            return code


def create_cards(count: int, duration_days: int, note: str = "", site_domain: str | None = None) -> list[str]:
    conn = get_conn()
    codes = []
    now = datetime.now().isoformat(timespec="seconds")
    for _ in range(min(max(count, 1), 500)):
        code = generate_code()
        conn.execute(
            "INSERT INTO cards (code, status, duration_days, created_at, site_domain, note) VALUES (?,?,?,?,?,?)",
            (code, "unused", duration_days, now, site_domain, note),
        )
        codes.append(code)
    conn.commit()
    conn.close()
    return codes


def check_card(code: str, domain: str | None = None):
    """回访校验（不激活、不扣次数）。返回 (ok, message, expire_at, key)"""
    code = (code or "").strip().upper()
    conn = get_conn()
    row = conn.execute("SELECT * FROM cards WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return False, "卡密无效", None, "invalid"
    if row["site_domain"] and domain and row["site_domain"] != domain:
        return False, f"该卡密仅限 {row['site_domain']} 使用", None, "limit"
    if row["status"] == "used":
        exp = row["expire_at"]
        if not exp:
            return True, "永久有效", None, "ok"
        try:
            if datetime.fromisoformat(exp) > datetime.now():
                return True, "卡密有效", exp, "ok"
        except ValueError:
            pass
        return False, "卡密已过期", None, "expired"
    return False, "卡密未激活", None, "notyet"


def verify_card(code: str, user: str = "", domain: str | None = None):
    code = (code or "").strip().upper()
    conn = get_conn()
    row = conn.execute("SELECT * FROM cards WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        return False, "卡密无效", None, "invalid"
    # 站点绑定检查
    if row["site_domain"] and domain and row["site_domain"] != domain:
        conn.close()
        return False, f"该卡密仅限 {row['site_domain']} 使用", None, "limit"
    now = datetime.now()
    if row["status"] == "used":
        exp = row["expire_at"]
        if exp:
            try:
                if datetime.fromisoformat(exp) > now:
                    conn.close()
                    return True, "卡密有效", exp, "ok"  # 已激活未到期，视为有效
            except ValueError:
                pass
        conn.close()
        return False, "卡密已过期", None, "expired"
    # 激活
    expire_at = (
        (now + timedelta(days=row["duration_days"])).isoformat(timespec="seconds")
        if row["duration_days"] > 0
        else None
    )
    conn.execute(
        "UPDATE cards SET status='used', used_at=?, expire_at=?, used_by=?, site_domain=COALESCE(?, site_domain) WHERE id=?",
        (now.isoformat(timespec="seconds"), expire_at, user, domain, row["id"]),
    )
    # 登记接入网站
    if domain:
        conn.execute(
            "INSERT OR IGNORE INTO sites (domain, created_at) VALUES (?, ?)",
            (domain, now.isoformat(timespec="seconds")),
        )
    conn.commit()
    conn.close()
    return True, "验证成功", expire_at, "ok"


def list_cards(status: str | None = None, q: str | None = None):
    conn = get_conn()
    sql = "SELECT * FROM cards WHERE 1=1"
    params: list = []
    if status in ("unused", "used"):
        sql += " AND status=?"
        params.append(status)
    if q:
        sql += " AND (code LIKE ? OR IFNULL(note,'') LIKE ? OR IFNULL(used_by,'') LIKE ?)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY id DESC LIMIT 1000"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    # 动态过期
    now = datetime.now()
    for r in rows:
        r["is_expired"] = bool(
            r["expire_at"] and r["status"] == "used"
            and _expired(r["expire_at"], now)
        )
    return rows


def _expired(exp: str, now) -> bool:
    try:
        return datetime.fromisoformat(exp) <= now
    except ValueError:
        return False


def stats():
    rows = list_cards()
    total = len(rows)
    unused = sum(1 for r in rows if r["status"] == "unused")
    used = sum(1 for r in rows if r["status"] == "used" and not r["is_expired"])
    expired = sum(1 for r in rows if r["status"] == "used" and r["is_expired"])
    return {"total": total, "unused": unused, "used": used, "expired": expired}


def delete_card(card_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
    conn.commit()
    conn.close()


def change_password(username: str, old_pwd: str, new_pwd: str) -> tuple[bool, str]:
    """修改管理员密码。返回 (是否成功, 提示信息)"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    if not row or not check_password(old_pwd, row["password_hash"]):
        conn.close()
        return False, "原密码错误"
    if len(new_pwd) < 6:
        conn.close()
        return False, "新密码至少 6 位"
    conn.execute(
        "UPDATE admins SET password_hash=? WHERE username=?",
        (hash_password(new_pwd), username),
    )
    conn.commit()
    conn.close()
    return True, "密码修改成功，请重新登录"


THEME_DEFAULT = {"title": "请输入卡密", "sub": "验证通过后即可查看本页内容", "btn": "验 证", "color": "#6366f1"}

# 解锁方式：blur 模糊 / dim 变暗 / lock 锁屏
UNLOCK_MODES = {"blur": "锁屏模糊", "dim": "深色变暗", "lock": "完全隐藏"}
DEFAULT_MODE = "blur"


def _ensure_site_columns(conn):
    """站点扩展列（解锁方式、接入语言、指定链接 token）"""
    for col, typ in (
        ("unlock_mode", "TEXT"),
        ("lang", "TEXT"),
        ("token", "TEXT"),
    ):
        try:
            conn.execute(f"ALTER TABLE sites ADD COLUMN {col} {typ}")
        except Exception:
            pass  # 列已存在


def site_settings(domain: str | None) -> dict:
    """读取网站设置：解锁方式 + 语言（未设置为空=自动检测）"""
    s = {"unlock_mode": DEFAULT_MODE, "lang": ""}
    if not domain:
        return s
    conn = get_conn()
    _ensure_site_columns(conn)
    row = conn.execute("SELECT unlock_mode, lang FROM sites WHERE domain=?", (domain,)).fetchone()
    conn.close()
    if row:
        if row["unlock_mode"] in UNLOCK_MODES:
            s["unlock_mode"] = row["unlock_mode"]
        if row["lang"]:
            s["lang"] = row["lang"]
    return s


def set_site_unlock_mode(site_id: int, mode: str):
    if mode not in UNLOCK_MODES:
        return False
    conn = get_conn()
    _ensure_site_columns(conn)
    conn.execute("UPDATE sites SET unlock_mode=? WHERE id=?", (mode, site_id))
    conn.commit()
    conn.close()
    return True


def set_site_lang(site_id: int, lang: str):
    """lang 为空字符串表示自动检测"""
    conn = get_conn()
    _ensure_site_columns(conn)
    conn.execute("UPDATE sites SET lang=? WHERE id=?", ((lang or "").strip() or None, site_id))
    conn.commit()
    conn.close()
    return True


def _ensure_token_column(conn):
    _ensure_site_columns(conn)


def site_token(site_id: int) -> tuple[str, str] | None:
    """获取（必要时生成）网站指定链接 token。返回 (domain, token)"""
    conn = get_conn()
    _ensure_token_column(conn)
    row = conn.execute("SELECT domain, token FROM sites WHERE id=?", (site_id,)).fetchone()
    if not row:
        conn.close()
        return None
    tok = row["token"] or secrets.token_urlsafe(16)
    if not row["token"]:
        conn.execute("UPDATE sites SET token=? WHERE id=?", (tok, site_id))
        conn.commit()
    conn.close()
    return row["domain"], tok


def site_by_token(token: str):
    conn = get_conn()
    _ensure_token_column(conn)
    row = conn.execute("SELECT domain FROM sites WHERE token=?", (token,)).fetchone()
    conn.close()
    return row["domain"] if row else None


def list_sites():
    conn = get_conn()
    _ensure_site_columns(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM sites ORDER BY id DESC").fetchall()]
    conn.close()
    for s in rows:
        if s.get("unlock_mode") not in UNLOCK_MODES:
            s["unlock_mode"] = DEFAULT_MODE
        s["lang"] = s.get("lang") or ""
    # 每个网站的卡密统计（含全网通用卡密在其上的激活数）
    now = datetime.now()
    for s in rows:
        conn = get_conn()
        s["bound_total"] = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE site_domain=?", (s["domain"],)
        ).fetchone()[0]
        s["bound_unused"] = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE site_domain=? AND status='unused'", (s["domain"],)
        ).fetchone()[0]
        s["activated"] = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE status='used' AND (site_domain=? OR site_domain IS NULL) AND used_by IS NOT NULL",
            (s["domain"],),
        ).fetchone()[0]
        last = conn.execute(
            "SELECT MAX(used_at) FROM cards WHERE status='used' AND (site_domain=? OR site_domain IS NULL)",
            (s["domain"],),
        ).fetchone()[0]
        s["last_active"] = last
        s["is_expired_active"] = bool(
            last and any(
                r["expire_at"] and datetime.fromisoformat(r["expire_at"]) <= now
                for r in conn.execute(
                    "SELECT expire_at FROM cards WHERE status='used' AND site_domain=?", (s["domain"],)
                ).fetchall()
            )
        ) if s["domain"] else False
        conn.close()
    return rows


def delete_site(site_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM sites WHERE id=?", (site_id,))
    conn.commit()
    conn.close()
