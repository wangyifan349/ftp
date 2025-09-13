#!/usr/bin/env python3
# app.py - corrected full application with share browse page
import os
import sqlite3
import time
import uuid
import shutil
from pathlib import Path
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, render_template_string, session,
    send_file, jsonify, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
# ---- Config (simple, tweak for production) ----
BASE_DIR = Path(__file__).parent.resolve()
USER_FILES_DIR = BASE_DIR / "user_files"
DB_PATH = BASE_DIR / "app.db"
ALLOWED_EXT = None            # e.g. {'.png', '.jpg'}
MAX_FILE_SIZE = 200 * 1024 * 1024
SECRET_KEY = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
os.makedirs(USER_FILES_DIR, exist_ok=True)

# ---- Flask app ----
app = Flask(__name__, static_folder=str(BASE_DIR))
app.secret_key = SECRET_KEY
# ---- Templates (embedded) ----
TPL_LOGIN = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ 'Register' if action=='register' else 'Login' }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root{
      --brand-500: #2f9e44;
      --brand-600: #23863a;
      --bg: #f5fbf6;
    }
    body{ background: var(--bg); font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial; }
    .auth-card{ max-width:520px; margin:6vh auto; background:#fff; border-radius:12px; box-shadow:0 8px 30px rgba(0,0,0,0.06); padding:36px; }
    .brand { color:var(--brand-600); font-weight:700; font-size:1.25rem; display:flex; gap:.6rem; align-items:center; }
    .brand .logo { width:40px; height:40px; background:linear-gradient(135deg,var(--brand-500),var(--brand-600)); border-radius:8px; display:inline-block; }
    .muted { color:#6c757d; }
    .form-control:focus { border-color: var(--brand-500); box-shadow:0 0 0 .15rem rgba(47,158,68,0.12); }
    .btn-primary { background:var(--brand-600); border-color:var(--brand-600); }
  </style>
</head>
<body>
  <div class="auth-card">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <div class="brand">
          <span class="logo" aria-hidden></span>
          <span>MyDrive</span>
        </div>
        <div class="muted small">个人文件存储 · 私密</div>
      </div>
      <div class="text-end">
        <div class="small muted">安全 · 私密</div>
      </div>
    </div>

    <h3 class="mb-2">{{ 'Register' if action=='register' else 'Sign in' }}</h3>
    <p class="muted mb-4">{{ '创建一个新账户' if action=='register' else '使用你的用户名和密码登录' }}</p>

    <form method="post" novalidate>
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input name="username" class="form-control form-control-lg" placeholder="示例: alice" required>
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input name="password" type="password" class="form-control form-control-lg" placeholder="••••••••" required>
      </div>
      <div class="d-flex justify-content-between align-items-center">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="remember" checked disabled>
          <label class="form-check-label muted" for="remember">记住我</label>
        </div>
        <button type="submit" class="btn btn-primary btn-lg">{{ 'Create account' if action=='register' else 'Sign in' }}</button>
      </div>
    </form>

    <hr class="my-4">
    <div class="d-flex justify-content-between" style="font-size:0.95rem;">
      <div>
        {% if action=='register' %}
          已有帐号？ <a href="{{ url_for('login') }}">登录</a>
        {% else %}
          没有帐号？ <a href="{{ url_for('register') }}">注册</a>
        {% endif %}
      </div>
      <div><a href="#" class="muted">帮助</a></div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TPL_INDEX = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>文件管理</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root{
      --brand-500:#2f9e44;
      --brand-600:#23863a;
      --muted:#6c757d;
      --surface:#ffffff;
      --app-bg:#f5fbf6;
    }
    body{ background: var(--app-bg); font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial; padding-bottom:40px; }
    .topbar { background: linear-gradient(90deg, rgba(47,158,68,0.08), rgba(47,158,68,0.02)); padding:12px 20px; border-bottom:1px solid rgba(0,0,0,0.04); }
    .app-card { max-width:1100px; margin:24px auto; background:var(--surface); border-radius:10px; box-shadow:0 8px 30px rgba(18, 38, 12, 0.04); overflow:hidden; }
    .toolbar { padding:16px 20px; display:flex; gap:12px; align-items:center; }
    .path-badge { background: rgba(47,158,68,0.08); color:var(--brand-600); padding:6px 10px; border-radius:6px; font-weight:600; }
    #file-list { padding:8px 20px 28px 20px; min-height:260px; }
    .item { display:flex; align-items:center; justify-content:space-between; padding:10px 12px; border-radius:8px; transition:background .12s, transform .08s; }
    .item:hover { background: #f7fff7; transform:translateY(-2px); }
    .left { display:flex; gap:12px; align-items:center; }
    .name { font-weight:600; color:#123; cursor:pointer; }
    .meta { color:var(--muted); font-size:0.9rem; }
    .drop-target { outline: 2px dashed rgba(47,158,68,0.25); background: #f1fff1; }
    .file-icon { font-size:1.2rem; }
    .controls .btn { margin-left:6px; }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="container d-flex justify-content-between align-items-center">
      <div class="d-flex gap-3 align-items-center">
        <div style="width:44px;height:44px;border-radius:8px;background:linear-gradient(135deg,var(--brand-500),var(--brand-600));"></div>
        <div>
          <div style="font-weight:700;color:var(--brand-600)">MyDrive</div>
          <div style="font-size:0.85rem;color:var(--muted)">私有云 · 个人文件</div>
        </div>
      </div>
      <div class="text-end">
        <div class="small" style="color:var(--muted)">用户: <strong>{{ session.get('username') }}</strong></div>
        <div style="margin-top:6px;">
          <a href="{{ url_for('shares') }}" class="btn btn-sm btn-outline-success">分享管理</a>
          <a href="{{ url_for('logout') }}" class="btn btn-sm btn-outline-secondary mt-1">登出</a>
        </div>
      </div>
    </div>
  </div>
  <div class="app-card">
    <div class="toolbar">
      <button class="btn btn-sm btn-outline-secondary" onclick="goUp()">上一级</button>
      <div class="ms-2">当前: <span id="cur-path" class="path-badge">/</span></div>

      <div class="ms-auto d-flex align-items-center gap-2">
        <input id="new-folder-name" class="form-control form-control-sm" placeholder="新建文件夹名" style="width:200px;">
        <button class="btn btn-sm" style="background:var(--brand-500);color:#fff" onclick="mkdir()">创建文件夹</button>
        <input type="file" id="files" multiple class="form-control form-control-sm" style="width:220px;">
        <button class="btn btn-sm btn-secondary" onclick="uploadFiles()">上传</button>
      </div>
    </div>

    <div id="file-list">
      <!-- items will be injected by JS -->
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    let curPath = "";
    function formatBytes(bytes){
      if (!bytes && bytes !== 0) return '';
      const units = ['B','KB','MB','GB','TB'];
      let i = 0;
      while(bytes >= 1024 && i < units.length-1){ bytes /= 1024; i++; }
      return Math.round(bytes*10)/10 + ' ' + units[i];
    }
    async function listDir(){
      const res = await fetch('/api/list?path=' + encodeURIComponent(curPath));
      const j = await res.json();
      if (j.error){ alert(j.error); return; }
      document.getElementById('cur-path').innerText = '/' + (curPath || '');
      const cont = document.getElementById('file-list');
      cont.innerHTML = '';
      if (!j.items) return;
      for (const it of j.items){
        const div = document.createElement('div');
        div.className = 'item d-flex align-items-center justify-content-between mb-2';
        div.dataset.name = it.name;
        div.dataset.isdir = it.is_dir ? '1' : '0';
        div.draggable = true;
        const left = document.createElement('div'); left.className='left';
        const icon = document.createElement('span'); icon.className='file-icon';
        icon.textContent = it.is_dir ? '📁' : '📄';
        const nameWrap = document.createElement('div');
        const name = document.createElement('div'); name.textContent = it.name; name.className='name';
        const meta = document.createElement('div'); meta.className='meta';
        meta.textContent = it.is_dir ? '文件夹' : (formatBytes(it.size) + (it.mime ? (' · ' + it.mime) : ''));
        nameWrap.appendChild(name); nameWrap.appendChild(meta);
        left.appendChild(icon); left.appendChild(nameWrap);

        const dd = document.createElement('div'); dd.className = 'dropdown';
        const btn = document.createElement('button');
        btn.className = 'btn btn-sm btn-light dropdown-toggle';
        btn.type = 'button';
        btn.setAttribute('data-bs-toggle', 'dropdown');
        btn.innerText = '操作';
        const menu = document.createElement('ul'); menu.className = 'dropdown-menu dropdown-menu-end';

        function addMenuItem(label, onclickStr){
          const li = document.createElement('li');
          const a = document.createElement('a');
          a.className = 'dropdown-item';
          a.href = '#';
          a.innerText = label;
          a.onclick = function(e){ e.preventDefault(); eval(onclickStr); };
          li.appendChild(a);
          menu.appendChild(li);
        }

        if (!it.is_dir){
          addMenuItem('下载', "downloadItem('" + escapeJs(it.name) + "')");
        }
        addMenuItem('移动到...', "promptMove('" + escapeJs(it.name) + "')");
        addMenuItem('重命名', "renameItem('" + escapeJs(it.name) + "', " + (it.is_dir ? "1" : "0") + ")");
        addMenuItem('删除', "deleteItem('" + escapeJs(it.name) + "', " + (it.is_dir ? "1" : "0") + ")");
        if (it.is_dir){
          addMenuItem('分享目录', "shareDir('" + escapeJs(it.name) + "')");
          addMenuItem('取消分享', "unshareDir('" + escapeJs(it.name) + "')");
        }

        dd.appendChild(btn); dd.appendChild(menu);

        div.appendChild(left);
        div.appendChild(dd);

        name.onclick = ()=> { if (it.is_dir) { openDir(it.name) } else { downloadItem(it.name) } }

        div.addEventListener('dragstart', (e)=> {
          e.dataTransfer.setData('text/plain', (curPath ? curPath + '/' : '') + it.name);
          div.classList.add('dragging');
        });
        div.addEventListener('dragend', ()=> div.classList.remove('dragging'));

        if (it.is_dir){
          div.addEventListener('dragover', (e)=> { e.preventDefault(); div.classList.add('drop-target'); });
          div.addEventListener('dragleave', ()=> div.classList.remove('drop-target'));
          div.addEventListener('drop', async (e)=> {
            e.preventDefault(); div.classList.remove('drop-target');
            const src = e.dataTransfer.getData('text/plain');
            const dest = (curPath ? curPath + '/' : '') + it.name;
            await moveItem(src, dest);
            listDir();
          });
        }

        cont.appendChild(div);
      }
    }

    function escapeJs(s){
      return String(s).replace(/\\\\/g, '\\\\\\\\').replace(/'/g, "\\\\'").replace(/"/g, '\\"');
    }

    function openDir(name){
      curPath = curPath ? (curPath + '/' + name) : name;
      listDir();
    }
    function goUp(){
      if (!curPath) return;
      const parts = curPath.split('/');
      parts.pop();
      curPath = parts.join('/');
      listDir();
    }

    async function mkdir(){
      const name = document.getElementById('new-folder-name').value.trim();
      if (!name) return alert('请输入文件夹名');
      const res = await fetch('/api/mkdir', {
        method:'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ path: curPath, name })
      });
      const j = await res.json();
      if (j.ok) { document.getElementById('new-folder-name').value=''; listDir(); }
      else alert(j.error||'错误');
    }

    async function uploadFiles(){
      const input = document.getElementById('files');
      if (!input.files.length) return alert('请选择文件');
      const form = new FormData();
      for (const f of input.files) form.append('files', f);
      form.append('path', curPath);
      const res = await fetch('/api/upload', { method:'POST', body: form });
      const j = await res.json();
      if (j.saved && j.saved.length) { input.value=''; listDir(); }
      else alert(j.error||'上传错误');
    }

    function downloadItem(name){
      const path = curPath ? (curPath + '/' + name) : name;
      window.location = '/api/download?path=' + encodeURIComponent(path);
    }

    async function deleteItem(name, isDir){
      if (!confirm('删除 ' + name + '?')) return;
      const path = curPath ? (curPath + '/' + name) : name;
      const res = await fetch('/api/delete', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ path, permanent: true })
      });
      const j = await res.json();
      if (j.ok) listDir(); else alert(j.error||'错误');
    }

    async function promptMove(name){
      const target = prompt('输入目标目录（相对于根，例如 a/b 或 留空为根），或目标全路径 a/b/newname');
      if (target === null) return;
      const src = curPath ? (curPath + '/' + name) : name;
      const dest = target;
      await moveItem(src, dest);
      listDir();
    }

    async function moveItem(src, dest){
      const res = await fetch('/api/move', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ src, dest })
      });
      const j = await res.json();
      if (!j.ok) alert(j.error || '移动失败');
    }

    async function renameItem(name, isDir){
      const newname = prompt('输入新名称', name);
      if (!newname || newname === name) return;
      const src = curPath ? (curPath + '/' + name) : name;
      const dest = curPath ? (curPath + '/' + newname) : newname;
      await moveItem(src, dest);
      listDir();
    }

    // ---- Sharing helpers: auto-copy link to clipboard when token returned ----
    async function shareDir(name){
      const path = curPath ? (curPath + '/' + name) : name;
      const res = await fetch('/api/share', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ path })
      });
      const j = await res.json();
      if (j.ok) {
        if (j.token) {
          const link = window.location.origin + '/s/' + j.token;
          try {
            await navigator.clipboard.writeText(link);
            alert('已分享并复制到剪贴板： ' + link);
          } catch (e) {
            // fallback to prompt if clipboard API not available
            prompt('分享链接（已生成，请手动复制）：', link);
          }
        } else {
          alert('已分享');
        }
      } else alert(j.error || '分享失败');
    }

    async function unshareDir(name){
      const path = curPath ? (curPath + '/' + name) : name;
      const res = await fetch('/api/unshare', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ path })
      });
      const j = await res.json();
      if (j.ok) alert('已取消分享'); else alert(j.error || '取消分享失败');
    }

    listDir();
  </script>
</body>
</html>
"""

TPL_SHARES = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>分享管理</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{ background:#f5fbf6; font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial; padding:24px; }
    .card{ max-width:900px; margin:0 auto; background:#fff; border-radius:10px; padding:20px; box-shadow:0 8px 30px rgba(0,0,0,0.06); }
    .muted{ color:#6c757d; }
    .share-row{ display:flex; align-items:center; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f0f0f0; }
    .path{ font-weight:600; color:#123; }
    .controls button{ margin-left:8px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <div style="font-weight:700;color:#2f9e44">分享管理</div>
        <div class="muted">管理你创建的公开分享链接（只读）</div>
      </div>
      <div>
        <a href="{{ url_for('index') }}" class="btn btn-sm btn-outline-secondary">返回文件</a>
        <a href="{{ url_for('logout') }}" class="btn btn-sm btn-outline-secondary">登出</a>
      </div>
    </div>

    <div id="shares-list">
      {% if shares %}
        {% for s in shares %}
          <div class="share-row" data-token="{{ s.token }}">
            <div>
              <div class="path">{{ (s.path + '/' + s.display_name).lstrip('/') }}</div>
              <div class="muted" style="font-size:0.9rem;">创建于 {{ s.created_at_human }}</div>
            </div>
            <div class="controls">
              <button class="btn btn-sm btn-outline-primary" onclick="copyLink('{{ s.token }}')">复制链接</button>
              <button class="btn btn-sm btn-danger" onclick="unshare('{{ (s.path + '/' + s.display_name).lstrip('/') }}')">取消分享</button>
            </div>
          </div>
        {% endfor %}
      {% else %}
        <div class="muted">你还没有创建任何分享链接。</div>
      {% endif %}
    </div>
  </div>

<script>
  function copyLink(token){
    const link = window.location.origin + '/s/' + token;
    navigator.clipboard?.writeText(link).then(()=> alert('已复制：' + link)).catch(()=> prompt('分享链接：', link));
  }

  async function unshare(path){
    if (!confirm('取消分享 ' + path + ' ?')) return;
    const res = await fetch('/api/unshare', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path })
    });
    const j = await res.json();
    if (j.ok){
      alert('已取消分享');
      location.reload();
    } else {
      alert(j.error || '取消失败');
    }
  }
</script>
</body>
</html>
"""

# Public share browse template (read-only)
TPL_SHARE_BROWSE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shared: {{ shared_path }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  body{ background:#f5fbf6; font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial; padding:20px; }
  .card{ max-width:900px; margin:0 auto; background:#fff; border-radius:10px; padding:20px; box-shadow:0 8px 30px rgba(0,0,0,0.06); }
  .item{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f0f0f0; align-items:center; }
  .name{ font-weight:600; }
  .muted{ color:#6c757d; }
</style>
</head>
<body>
  <div class="card">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <div style="font-weight:700;color:#2f9e44">公开分享</div>
        <div class="muted">{{ shared_path or '/' }}</div>
      </div>
      <div>
        <a href="/" class="btn btn-sm btn-outline-secondary">返回</a>
      </div>
    </div>

    {% if items %}
      {% for it in items %}
        <div class="item">
          <div>
            <div class="name">
              {% if it.is_dir %}
                📁 <a href="{{ url_for('share_serve', token=token) }}?sub={{ it.name|urlencode }}">{{ it.name }}</a>
              {% else %}
                📄 {{ it.name }}
              {% endif %}
            </div>
            <div class="muted" style="font-size:0.9rem;">{{ it.size }} {{ it.mime or '' }}</div>
          </div>
          <div>
            {% if not it.is_dir %}
              <a class="btn btn-sm btn-primary" href="{{ url_for('share_download', token=token) }}?path={{ (shared_path + '/' + it.name).lstrip('/')|urlencode }}">下载</a>
            {% endif %}
          </div>
        </div>
      {% endfor %}
    {% else %}
      <div class="muted">此目录为空或不可访问。</div>
    {% endif %}
  </div>
</body>
</html>
"""
# ---- Database init & helpers ----
def init_db():
    """Create DB and tables if not exist."""
    if DB_PATH.exists():
        return
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        # Create users table: store user credentials and creation time.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )""")
        # Create files table: store metadata for both files and directories.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stored_name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            path TEXT NOT NULL,
            size INTEGER NOT NULL,
            mime TEXT,
            is_dir INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            modified_at INTEGER NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0
        )""")
        # Create shares table: map directory (by path+display_name) to a token.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            display_name TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL
        )""")
        conn.commit()
def get_db():
    """Return a sqlite3 connection with row factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
# ---- Utilities ----
def login_required(f):
    """Decorator: redirect to login if not authenticated."""
    @wraps(f)
    def deco(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return deco
def current_user_dir():
    """Return Path to current user's file storage directory (create if missing)."""
    uid = session.get("user_id")
    if not uid:
        return None
    d = USER_FILES_DIR / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d
def safe_path_join(base: Path, rel_path: str) -> Path:
    """
    Safely join base and rel_path, preventing path traversal.
    Raises ValueError on invalid path.
    """
    rel = Path(rel_path) if rel_path else Path('.')
    joined = (base / rel).resolve()
    if not str(joined).startswith(str(base.resolve())):
        raise ValueError("Path traversal")
    return joined
def normalize_rel_path(p: str) -> str:
    """Normalize a relative path: strip whitespace, collapse separators, remove '.' and '..' parts.
    Returns '' for root. Raises ValueError for absolute paths or traversal attempts."""
    if p is None:
        return ""
    p = str(p).strip()
    if p == "":
        return ""
    # Reject absolute paths
    if p.startswith("/") or p.startswith("\\"):
        raise ValueError("absolute paths not allowed")
    parts = []
    for part in Path(p).parts:
        if part in ('.', ''):
            continue
        if part == '..':
            # prevent upward traversal escaping root
            if not parts:
                raise ValueError("path traversal")
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)
# ---- Routes: auth & UI ----
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template_string(TPL_LOGIN, action="register")
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not username or not password:
        return "用户名或密码为空", 400
    pw_hash = generate_password_hash(password)
    now = int(time.time())
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)", (username, pw_hash, now))
            conn.commit()
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        return "用户名已存在", 400
    (USER_FILES_DIR / str(uid)).mkdir(parents=True, exist_ok=True)
    session["user_id"] = uid
    session["username"] = username
    return redirect(url_for("index"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(TPL_LOGIN, action="login")
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username=?", (username,))
        row = cur.fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return "用户名或密码错误", 400
    session["user_id"] = row["id"]
    session["username"] = username
    return redirect(url_for("index"))
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
@app.route("/")
@login_required
def index():
    return render_template_string(TPL_INDEX)
# ---- Shares management UI route ----
@app.route("/shares")
@login_required
def shares():
    uid = session["user_id"]
    with get_db() as conn:
        cur = conn.cursor()
        # Select shares for current user; return token, path, display_name, created_at.
        cur.execute("SELECT id, path, display_name, token, created_at FROM shares WHERE user_id=?", (uid,))
        rows = cur.fetchall()
    shares = []
    for r in rows:
        shares.append({
            "id": r["id"],
            "path": r["path"],
            "display_name": r["display_name"],
            "token": r["token"],
            "created_at": r["created_at"],
            "created_at_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"]))
        })
    return render_template_string(TPL_SHARES, shares=shares)
# ---- API Endpoints ----
@app.route("/api/list", methods=["GET"])
@login_required
def api_list():
    """
    List items at given relative path.
    Only non-deleted items are returned.
    Query param: path (relative)
    """
    try:
        rel = normalize_rel_path(request.args.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    uid = session["user_id"]
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT display_name, path, size, mime, is_dir FROM files WHERE user_id=? AND path=? AND deleted=0 ORDER BY is_dir DESC, display_name COLLATE NOCASE", (uid, rel))
        rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({"name": r["display_name"], "is_dir": bool(r["is_dir"]), "size": r["size"], "mime": r["mime"]})
    return jsonify({"path": rel, "items": items})

@app.route("/api/mkdir", methods=["POST"])
@login_required
def api_mkdir():
    """
    Create a directory.
    JSON: { path: "parent/dir", name: "newname" }
    """
    data = request.get_json() or {}
    try:
        rel = normalize_rel_path(data.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "no name"}), 400
    name_safe = secure_filename(name) or name
    uid = session["user_id"]
    user_dir = current_user_dir()
    try:
        parent_fs = safe_path_join(user_dir, rel) if rel else user_dir
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    target_fs = parent_fs / name_safe
    if target_fs.exists():
        return jsonify({"error": "exists"}), 400
    target_fs.mkdir(parents=False, exist_ok=False)
    now = int(time.time())
    with get_db() as conn:
        cur = conn.cursor()
        # Insert a new directory record into files table.
        cur.execute(
            "INSERT INTO files (user_id, stored_name, display_name, path, size, mime, is_dir, created_at, modified_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (uid, "", name_safe, rel, 0, "dir", now, now)
        )
        conn.commit()
    return jsonify({"ok": True})
@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    """
    Upload files into given relative path.
    Form fields:
      - path: destination path (relative)
      - files: file inputs (multiple)
    """
    try:
        rel = normalize_rel_path(request.form.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    uid = session["user_id"]
    user_dir = current_user_dir()
    try:
        target_dir_fs = safe_path_join(user_dir, rel) if rel else user_dir
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not target_dir_fs.exists():
        return jsonify({"error": "target not found"}), 404
    files = request.files.getlist("files")
    saved = []
    errors = []
    now = int(time.time())
    with get_db() as conn:
        cur = conn.cursor()
        for f in files:
            if not f or not getattr(f, "filename", None):
                errors.append({"filename": None, "error": "no file"})
                continue
            filename = secure_filename(f.filename) or f.filename
            ext = Path(filename).suffix.lower()
            if ALLOWED_EXT and ext not in ALLOWED_EXT:
                errors.append({"filename": filename, "error": "ext not allowed"})
                continue
            try:
                f.stream.seek(0, os.SEEK_END)
                size = f.stream.tell()
                f.stream.seek(0)
            except Exception:
                data = f.read()
                size = len(data)
            if MAX_FILE_SIZE and size > MAX_FILE_SIZE:
                errors.append({"filename": filename, "error": "too large"})
                continue
            stored = str(uuid.uuid4().hex) + ext
            dest = target_dir_fs / stored
            try:
                f.save(str(dest))
            except Exception as e:
                errors.append({"filename": filename, "error": f"save failed: {e}"})
                continue
            mime = None
            try:
                import magic
                mime = magic.from_file(str(dest), mime=True)
            except Exception:
                mime = None
            # Insert file metadata into files table.
            cur.execute(
                "INSERT INTO files (user_id, stored_name, display_name, path, size, mime, is_dir, created_at, modified_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (uid, stored, filename, rel, size, mime, now, now)
            )
            saved.append(filename)
        conn.commit()
    return jsonify({"saved": saved, "errors": errors})
@app.route("/api/download", methods=["GET"])
@login_required
def api_download():
    """
    Download a file.
    Query param: path (relative to user root, e.g. "dir/file.txt" or "file.txt")
    """
    try:
        relpath = normalize_rel_path(request.args.get("path", ""))
    except ValueError:
        return "invalid path", 400
    if relpath == "":
        return "not found", 404
    uid = session["user_id"]
    parent = str(Path(relpath).parent) if "/" in relpath else ""
    name = Path(relpath).name
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT stored_name, display_name, is_dir FROM files WHERE user_id=? AND path=? AND display_name=? AND deleted=0", (uid, parent, name))
        row = cur.fetchone()
    if not row: return "not found", 404
    if row["is_dir"]: return "is a directory", 400
    stored = row["stored_name"]
    user_dir = current_user_dir()
    file_fs = user_dir / parent / stored
    if not file_fs.exists(): return "file missing", 500
    return send_file(str(file_fs), as_attachment=True, download_name=row["display_name"])
@app.route("/api/delete", methods=["POST"])
@login_required
def api_delete():
    """
    Permanently delete a file or directory.
    JSON: { path: "relative/path", permanent: true }
    Since recycle bin is removed, deletion is permanent.
    """
    data = request.get_json() or {}
    try:
        rel = normalize_rel_path(data.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not rel: return jsonify({"error": "no path"}), 400
    uid = session["user_id"]
    parent = str(Path(rel).parent) if "/" in rel else ""
    name = Path(rel).name
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, stored_name, is_dir, path, display_name FROM files WHERE user_id=? AND path=? AND display_name=?", (uid, parent, name))
        row = cur.fetchone()
        if not row: return jsonify({"error": "not found"}), 404
        fid = row["id"]; is_dir = bool(row["is_dir"]); stored = row["stored_name"]
        if is_dir:
            prefix = (row["path"] + "/" + row["display_name"]).lstrip('/')
            # Select all descendants (dirs and files) under the directory to delete.
            cur.execute("SELECT id, stored_name, is_dir, path, display_name FROM files WHERE user_id=? AND (path=? OR path LIKE ?)", (uid, prefix, prefix + '/%'))
            rows = cur.fetchall()
            user_dir = current_user_dir()
            for r in rows:
                if r["is_dir"]:
                    dir_fs = user_dir / r["path"] / r["display_name"]
                    if dir_fs.exists(): shutil.rmtree(dir_fs, ignore_errors=True)
                else:
                    ffs = user_dir / r["path"] / r["stored_name"]
                    if ffs.exists():
                        try: ffs.unlink()
                        except: pass
            # Delete DB records for directory and descendants.
            cur.execute("DELETE FROM files WHERE user_id=? AND (path=? OR path LIKE ?)", (uid, prefix, prefix + '/%'))
        else:
            user_dir = current_user_dir()
            ffs = user_dir / row["path"] / stored
            if ffs.exists():
                try: ffs.unlink()
                except: pass
            # Delete file DB record.
            cur.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        return jsonify({"ok": True})
@app.route("/api/move", methods=["POST"])
@login_required
def api_move():
    """
    Move or rename a file or folder.
    JSON: { src: "a/b", dest: "x/y" }.
    dest can be an existing directory (move into) or a new path (rename/move).
    """
    data = request.get_json() or {}
    try:
        src = normalize_rel_path(data.get("src", ""))
        dest = normalize_rel_path(data.get("dest", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not src: return jsonify({"error": "no src"}), 400
    uid = session["user_id"]
    src_parent = str(Path(src).parent) if "/" in src else ""
    src_name = Path(src).name
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, is_dir, stored_name, path, display_name FROM files WHERE user_id=? AND path=? AND display_name=?", (uid, src_parent, src_name))
        row = cur.fetchone()
        if not row: return jsonify({"error": "src not found"}), 404
        final_parent = None; final_name = None
        user_dir = current_user_dir()
        if dest == "":
            final_parent = ""
            final_name = src_name
        else:
            dest_parent = str(Path(dest).parent) if "/" in dest else ""
            dest_name = Path(dest).name
            try:
                dest_fs = safe_path_join(user_dir, dest)
            except ValueError:
                return jsonify({"error": "invalid dest"}), 400
            if dest_fs.exists() and dest_fs.is_dir():
                final_parent = normalize_rel_path(dest)
                final_name = src_name
            else:
                parent_of_dest = str(Path(dest).parent) if "/" in dest else ""
                try:
                    parent_fs = safe_path_join(user_dir, parent_of_dest) if parent_of_dest else user_dir
                except ValueError:
                    return jsonify({"error": "invalid dest"}), 400
                if not parent_fs.exists():
                    return jsonify({"error": "dest parent not found"}), 400
                final_parent = parent_of_dest
                final_name = secure_filename(dest_name) or dest_name

        if row["is_dir"]:
            src_full_fs = current_user_dir() / row["path"] / row["display_name"]
            target_fs = current_user_dir() / final_parent / final_name
            try:
                if str(target_fs.resolve()).startswith(str(src_full_fs.resolve())):
                    return jsonify({"error": "cannot move directory into its own descendant"}), 400
            except Exception:
                pass
        # Check for conflicts in DB
        cur.execute("SELECT id FROM files WHERE user_id=? AND path=? AND display_name=? AND deleted=0", (uid, final_parent, final_name))
        if cur.fetchone():
            return jsonify({"error": "target exists"}), 400
        if row["is_dir"]:
            src_fs = user_dir / row["path"] / row["display_name"]
            dest_fs_parent = user_dir / final_parent
            dest_fs_parent.mkdir(parents=True, exist_ok=True)
            dest_fs = dest_fs_parent / final_name
            try:
                src_fs.rename(dest_fs)
            except Exception:
                try:
                    shutil.move(str(src_fs), str(dest_fs))
                except Exception:
                    return jsonify({"error": "fs move failed"}), 500
            old_prefix = (row["path"] + "/" + row["display_name"]).lstrip('/')
            new_prefix = (final_parent + "/" + final_name).lstrip('/')
            # Update the directory record itself
            cur.execute("UPDATE files SET path=?, display_name=?, modified_at=? WHERE id=?", (final_parent, final_name, int(time.time()), row["id"]))
            # Select descendants to update their path prefixes
            cur.execute("SELECT id, path FROM files WHERE user_id=? AND (path=? OR path LIKE ?)", (uid, old_prefix, old_prefix + '/%'))
            descendants = cur.fetchall()
            for d in descendants:
                old_path = d["path"]
                if old_path == old_prefix:
                    updated = new_prefix
                else:
                    updated = old_path.replace(old_prefix, new_prefix, 1)
                cur.execute("UPDATE files SET path=? WHERE id=?", (updated, d["id"]))
            conn.commit()
            return jsonify({"ok": True})
        else:
            stored = row["stored_name"]
            src_fs = current_user_dir() / row["path"] / stored
            dest_fs_parent = current_user_dir() / final_parent
            dest_fs_parent.mkdir(parents=True, exist_ok=True)
            new_stored = stored
            dest_fs = dest_fs_parent / new_stored
            try:
                src_fs.rename(dest_fs)
            except Exception:
                try:
                    shutil.move(str(src_fs), str(dest_fs))
                except Exception:
                    return jsonify({"error": "fs move failed"}), 500
            # Update file DB record
            cur.execute("UPDATE files SET path=?, display_name=?, modified_at=? WHERE id=?", (final_parent, final_name, int(time.time()), row["id"]))
            conn.commit()
            return jsonify({"ok": True})
@app.route("/api/meta", methods=["GET"])
@login_required
def api_meta():
    """
    Return metadata for a single item.
    Query param: path (relative)
    """
    try:
        rel = normalize_rel_path(request.args.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not rel: return jsonify({"error": "no path"}), 400
    uid = session["user_id"]
    parent = str(Path(rel).parent) if "/" in rel else ""
    name = Path(rel).name
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, display_name, path, size, mime, is_dir, created_at, modified_at, deleted FROM files WHERE user_id=? AND path=? AND display_name=?", (uid, parent, name))
        r = cur.fetchone()
    if not r: return jsonify({"error": "not found"}), 404
    return jsonify(dict(r))
# ---- Sharing endpoints ----
@app.route("/api/share", methods=["POST"])
@login_required
def api_share():
    """
    Create or return a share token for a directory.
    JSON: { path: "relative/path/to/dir_or_name" }
    Returns: { ok: True, token: "..." }
    """
    data = request.get_json() or {}
    try:
        rel = normalize_rel_path(data.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if rel == "":
        # Prevent accidental sharing of whole user root (change if you want to allow)
        return jsonify({"error": "cannot share root"}), 400
    uid = session["user_id"]
    parent = str(Path(rel).parent) if "/" in rel else ""
    name = Path(rel).name
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, is_dir FROM files WHERE user_id=? AND path=? AND display_name=? AND deleted=0", (uid, parent, name))
        r = cur.fetchone()
        if not r:
            return jsonify({"error": "not found"}), 404
        if not r["is_dir"]:
            return jsonify({"error": "not a directory"}), 400
        # Check if share exists
        cur.execute("SELECT token FROM shares WHERE user_id=? AND path=? AND display_name=?", (uid, parent, name))
        s = cur.fetchone()
        if s:
            return jsonify({"ok": True, "token": s["token"]})
        token = uuid.uuid4().hex
        now = int(time.time())
        # Insert share record mapping directory to token.
        cur.execute("INSERT INTO shares (user_id, path, display_name, token, created_at) VALUES (?, ?, ?, ?, ?)", (uid, parent, name, token, now))
        conn.commit()
        return jsonify({"ok": True, "token": token})
@app.route("/api/unshare", methods=["POST"])
@login_required
def api_unshare():
    """
    Delete a share record.
    JSON: { path: "relative/path/to/dir_or_name" }
    """
    data = request.get_json() or {}
    try:
        rel = normalize_rel_path(data.get("path", ""))
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not rel:
        return jsonify({"error": "no path"}), 400
    uid = session["user_id"]
    parent = str(Path(rel).parent) if "/" in rel else ""
    name = Path(rel).name
    with get_db() as conn:
        cur = conn.cursor()
        # Delete share record for this user's path+display_name
        cur.execute("DELETE FROM shares WHERE user_id=? AND path=? AND display_name=?", (uid, parent, name))
        conn.commit()
    return jsonify({"ok": True})
@app.route("/s/<token>", methods=["GET"])
def share_serve(token):
    """
    Publicly list contents of a shared directory (read-only).
    Renders an HTML page that lists direct children of the shared directory.
    Optional query param: sub=child_dir_name to view a child directory (one level).
    """
    if not token:
        return "invalid", 400
    sub = request.args.get("sub")
    # 'sub' is the child directory name to browse into; normalize but do not allow traversal
    if sub:
        try:
            sub = normalize_rel_path(sub)
        except ValueError:
            return "invalid sub", 400
        # only allow single-name sub (no slashes) since UI only links single child directories
        if "/" in sub:
            return "invalid sub", 400
    with get_db() as conn:
        cur = conn.cursor()
        # Lookup share by token
        cur.execute("SELECT user_id, path, display_name FROM shares WHERE token=?", (token,))
        s = cur.fetchone()
        if not s:
            return "not found", 404
        uid = s["user_id"]
        base_prefix = (s["path"] + "/" + s["display_name"]).lstrip('/')
        # Determine which path to query: either base_prefix (direct children) or base_prefix + '/' + sub
        if sub:
            prefix = (base_prefix + "/" + sub).lstrip('/')
        else:
            prefix = base_prefix
        # Query only direct children whose path equals prefix
        cur.execute("SELECT display_name, path, size, mime, is_dir FROM files WHERE user_id=? AND path=? AND deleted=0 ORDER BY is_dir DESC, display_name COLLATE NOCASE", (uid, prefix))
        rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({"name": r["display_name"], "is_dir": bool(r["is_dir"]), "size": r["size"], "mime": r["mime"]})
    return render_template_string(TPL_SHARE_BROWSE, items=items, shared_path=prefix, token=token)
@app.route("/s/<token>/download", methods=["GET"])
def share_download(token):
    """
    Allow downloading a file inside a shared directory (read-only).
    Query param: path=relative_path_from_user_root e.g. 'dir/file.txt' or 'dir/sub/file.txt'
    Only files where their path lies directly under the shared prefix are allowed.
    """
    if not token:
        return "invalid", 400
    qpath = request.args.get("path", "")
    try:
        relpath = normalize_rel_path(qpath)
    except ValueError:
        return "invalid path", 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, path, display_name FROM shares WHERE token=?", (token,))
        s = cur.fetchone()
        if not s:
            return "not found", 404
        uid = s["user_id"]
        prefix = (s["path"] + "/" + s["display_name"]).lstrip('/')
        # Ensure the requested file is under prefix (either directly or deeper)
        if not relpath.startswith(prefix):
            return "forbidden", 403
        # Compute parent/name relative to user's root
        parent = str(Path(relpath).parent) if "/" in relpath else ""
        name = Path(relpath).name
        cur.execute("SELECT stored_name, display_name, is_dir FROM files WHERE user_id=? AND path=? AND display_name=? AND deleted=0", (uid, parent, name))
        row = cur.fetchone()
        if not row:
            return "not found", 404
        if row["is_dir"]:
            return "is a directory", 400
        stored = row["stored_name"]
        user_dir = USER_FILES_DIR / str(uid)
        file_fs = user_dir / parent / stored
        if not file_fs.exists():
            return "file missing", 500
        return send_file(str(file_fs), as_attachment=True, download_name=row["display_name"])
# ---- App entrypoint ----
if __name__ == "__main__":
    init_db()
    print("Starting app on http://127.0.0.1:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)
