"""数据库自动备份 / 恢复（用 GitHub 私有仓库当免费持久盘）

原理：
- Render 免费实例没有持久磁盘，每次部署/重启容器后 kami.db 丢失。
- 启动时：本地无 db → 从 GitHub 私有仓库拉回最近一次备份。
- 运行中：数据有变更（mark_dirty）后由后台线程每 60 秒上传一次备份。
- 未配置 GITHUB_TOKEN / KAMI_BACKUP_REPO 时静默跳过，不影响正常使用。

需要的环境变量：
- GITHUB_TOKEN       GitHub 访问令牌（需要 repo 权限）
- KAMI_BACKUP_REPO   备份仓库，如 cpdd-1314/kami-db（不存在会自动创建为私有仓库）
"""
import base64
import json
import os
import threading
import time
from pathlib import Path

import database

REPO = os.environ.get("KAMI_BACKUP_REPO", "").strip()
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
FILE = "kami.db"
API = "https://api.github.com"

_dirty = threading.Event()
_lock = threading.Lock()
_file_sha: str | None = None
_cloud_cache: bytes | None = None
_last_push = 0.0

enabled = bool(REPO and TOKEN)


def _headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "kami-backup",
    }


def _req(method: str, url: str, payload: dict | None = None, timeout: int = 30):
    import urllib.request
    import urllib.error

    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception:
        return 0, {}


def _ensure_repo():
    """备份仓库不存在时自动创建为私有仓库"""
    status, _ = _req("GET", f"{API}/repos/{REPO}")
    if status == 200:
        return True
    if status == 404:
        name = REPO.split("/", 1)[1]
        status, _ = _req(
            "POST",
            f"{API}/user/repos",
            {"name": name, "private": True, "auto_init": False},
        )
        return status in (201, 422)  # 422 = 已存在
    return False


def _db_counts() -> tuple[int, int]:
    """返回 (sites 数, cards 数)，出错返回 (0, 0)"""
    try:
        import sqlite3
        conn = sqlite3.connect(database.DB_PATH)
        s = conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
        c = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        conn.close()
        return s, c
    except Exception:
        return 0, 0


def _cloud_counts() -> tuple[int, int] | None:
    """下载云端备份数据并返回 (sites, cards)；无备份返回 None"""
    status, body = _req("GET", f"{API}/repos/{REPO}/contents/{FILE}")
    if status != 200 or "content" not in body:
        return None
    try:
        data = base64.b64decode(body["content"])
        global _cloud_cache, _file_sha
        _cloud_cache = data
        _file_sha = body.get("sha")
        import sqlite3
        import tempfile
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            "CREATE TABLE sites (id INTEGER PRIMARY KEY, domain TEXT);"
            "CREATE TABLE cards (id INTEGER PRIMARY KEY, code TEXT);"
        )
        conn.close()
        fd, tmp = tempfile.mkstemp(suffix=".db")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            conn = sqlite3.connect(tmp)
            s = conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
            c = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            conn.close()
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return s, c
    except Exception:
        return None


def restore_if_missing() -> bool:
    """本地无数据库、或本地是空库时，从 GitHub 恢复云端有数据的备份。"""
    if not enabled:
        return False
    db_path = Path(database.DB_PATH)
    local_exists = db_path.exists() and db_path.stat().st_size > 0
    if local_exists:
        s, c = _db_counts()
        if s > 0 or c > 0:
            return False  # 本地有真实数据，不覆盖
    if not _ensure_repo():
        print("[backup] 备份仓库不可用，跳过恢复")
        return False
    cc = _cloud_counts()
    if cc is None:
        print("[backup] 云端暂无备份，跳过恢复")
        return False
    if cc == (0, 0):
        print("[backup] 云端备份也是空的，跳过恢复")
        return False
    data = _cloud_cache
    if not local_exists:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(data)
    print(f"[backup] 已从云端恢复数据库（{len(data)} 字节，{cc[0]} 个站点 / {cc[1]} 张卡密）")
    return True


def _push_once() -> bool:
    global _file_sha, _last_push
    db_path = Path(database.DB_PATH)
    if not db_path.exists() or db_path.stat().st_size == 0:
        return False
    # 防覆盖：本地没有任何站点和卡密时，云端若有数据备份则绝不用空库覆盖
    ls, lc = _db_counts()
    if ls == 0 and lc == 0:
        if not _ensure_repo():
            return False
        cc = _cloud_counts()
        if cc is not None and cc != (0, 0):
            print("[backup] 本地为空库而云端有数据，跳过上传以保护云端备份")
            return False
    # WAL 模式下先落盘，保证备份包含最新数据
    try:
        import sqlite3
        conn = sqlite3.connect(database.DB_PATH)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception:
        pass
    # 若本地没有记录 sha，先取一次（避免覆盖冲突）
    if _file_sha is None:
        status, body = _req("GET", f"{API}/repos/{REPO}/contents/{FILE}")
        _file_sha = body.get("sha") if status == 200 else None
    content = base64.b64encode(db_path.read_bytes()).decode()
    payload: dict = {
        "message": f"kami.db auto backup {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content,
    }
    if _file_sha:
        payload["sha"] = _file_sha
    status, body = _req("PUT", f"{API}/repos/{REPO}/contents/{FILE}", payload)
    if status in (200, 201):
        _file_sha = body.get("content", {}).get("sha")
        _last_push = time.time()
        return True
    if status == 409:  # sha 过期，重取再试一次
        st2, body2 = _req("GET", f"{API}/repos/{REPO}/contents/{FILE}")
        if st2 == 200:
            _file_sha = body2.get("sha")
            payload["sha"] = _file_sha
            status, body = _req("PUT", f"{API}/repos/{REPO}/contents/{FILE}", payload)
            if status in (200, 201):
                _file_sha = body.get("content", {}).get("sha")
                _last_push = time.time()
                return True
    return False


def mark_dirty():
    """数据发生变更时调用（非阻塞）"""
    if enabled:
        _dirty.set()


def _worker():
    global _file_sha
    # 启动时先确保仓库可用
    for _ in range(3):
        if _ensure_repo():
            break
        time.sleep(5)
    while True:
        _dirty.wait()
        time.sleep(3)          # 合并短时间内的多次变更
        _dirty.clear()
        with _lock:
            ok = False
            for _ in range(3):  # 失败重试
                if _push_once():
                    ok = True
                    break
                time.sleep(5)
            if not ok:
                print("[backup] 备份上传失败，稍后重试")
                _dirty.set()


def start():
    """启动备份线程（未配置环境变量时不启动）"""
    if not enabled:
        print("[backup] 未配置 GITHUB_TOKEN / KAMI_BACKUP_REPO，自动备份未启用")
        return
    threading.Thread(target=_worker, daemon=True).start()
    print(f"[backup] 自动备份已启用 → {REPO}")
