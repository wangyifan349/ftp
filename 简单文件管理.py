# app.py
import os
import shutil
import sqlite3
import hashlib
import hmac
import secrets
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, request, jsonify, send_file, render_template_string, g, abort, session, redirect, url_for
)
from werkzeug.utils import secure_filename
# ---------- CONFIG ----------
APP_SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
DATABASE = os.environ.get("FILEMGR_DB") or "filemgr.db"
ROOT_STORAGE = os.path.abspath(os.environ.get("FILEMGR_ROOT") or "storage_root")
os.makedirs(ROOT_STORAGE, exist_ok=True)
MAX_UPLOAD = 500 * 1024 * 1024  # 500 MB
# Password hashing params
PWD_SALT_BYTES = 16
# ---------- FLASK APP ----------
app = Flask(__name__)
app.secret_key = APP_SECRET
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD

# ---------- HTML (embedded, Bootstrap) ----------
INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>文件管理器（带用户与分享）</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 20px; }
    #file-tree { max-height: 55vh; overflow: auto; border: 1px solid #e5e7eb; border-radius: .25rem; padding: .75rem; background: #fff; }
    .item-row { display:flex; justify-content:space-between; align-items:center; padding: .25rem .5rem; border-radius:.25rem; }
    .item-row:hover { background: #f8fafc; cursor: default; }
    .folder-name { font-weight: 600; }
    .drop-target { background: #eef7ff !important; border: 1px dashed #93c5fd; }
    .small-muted { font-size: .9rem; color: #6b7280; }
    .topbar { display:flex; gap:10px; align-items:center; margin-bottom:12px;}
  </style>
</head>
<body class="bg-light">
  <div class="container">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h3>文件管理器</h3>
      <div>
        {% if user %}
          <span class="me-2">已登录: <strong>{{ user }}</strong></span>
          <a href="/logout" class="btn btn-sm btn-outline-secondary">登出</a>
        {% else %}
          <a href="/login" class="btn btn-sm btn-primary">登录</a>
          <a href="/register" class="btn btn-sm btn-outline-primary">注册</a>
        {% endif %}
      </div>
    </div>

    <div class="card p-3 mb-3">
      <div class="topbar">
        <div>当前路径：<strong id="current-path">/</strong></div>
        <button id="up-btn" class="btn btn-sm btn-outline-secondary">上一级</button>
        <input id="mkdir-name" class="form-control form-control-sm w-auto" placeholder="新建目录名">
        <button id="mkdir-btn" class="btn btn-sm btn-primary">新建目录</button>

        <div class="ms-auto">
          <input id="upload-input" type="file" multiple style="display:none">
          <button id="choose-btn" class="btn btn-sm btn-success">选择文件</button>
          <button id="upload-btn" class="btn btn-sm btn-success">上传</button>
          <button id="myshares-btn" class="btn btn-sm btn-outline-info">我的分享</button>
        </div>
      </div>

      <div class="mb-2 small-muted">提示：拖拽条目到目录上以移动；可多选上传；删除目录会递归（有确认）。</div>

      <div id="file-tree" class="bg-white"></div>
      <div id="log" class="mt-3"></div>
    </div>

    <div id="share-panel" class="card p-3 mb-3" style="display:none;">
      <h5>分享链接</h5>
      <div id="share-list"></div>
    </div>

    <div class="card p-3">
      <h6>公开分享访问</h6>
      <div class="mb-2">通过分享链接可匿名访问被分享的目录（只读）。</div>
      <div>
        <input id="public-token" class="form-control form-control-sm w-50 d-inline" placeholder="在此粘贴分享 token">
        <button id="open-share-btn" class="btn btn-sm btn-outline-primary">打开分享</button>
      </div>
      <div id="public-share-area" class="mt-3"></div>
    </div>
  </div>

<script>
const api = {
  list: p => fetch(`/api/list?path=${encodeURIComponent(p||"")}`).then(r=>r.json()),
  mkdir: (path,name) => fetch('/api/mkdir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,name})}).then(r=>r.json()),
  upload: (path, files) => { const fd=new FormData(); fd.append('path', path); for (const f of files) fd.append('file', f); return fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json()) },
  download: path => { window.location = `/api/download?path=${encodeURIComponent(path)}`; },
  delete: (path, recursive=false) => fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path, recursive})}).then(r=>r.json()),
  move: (src,dest_dir) => fetch('/api/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({src,dest_dir})}).then(r=>r.json()),
  share_create: (path, name) => fetch('/api/share/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,name})}).then(r=>r.json()),
  share_list: () => fetch('/api/share/list').then(r=>r.json()),
  share_delete: (token) => fetch('/api/share/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})}).then(r=>r.json()),
  public_list: (token, path) => fetch(`/api/share/public/list?token=${encodeURIComponent(token)}&path=${encodeURIComponent(path||"")}`).then(r=>r.json()),
  public_download: (token, path) => { window.location = `/api/share/public/download?token=${encodeURIComponent(token)}&path=${encodeURIComponent(path)}`; }
};

let currentPath = "";
let currentUser = {{ 'null' if not user else ('"'+user+'"' ) }};

function log(msg, type='info'){
  const el = document.getElementById('log');
  const div = document.createElement('div');
  div.className = type==='error' ? 'text-danger' : 'text-muted';
  div.textContent = msg;
  el.prepend(div);
  setTimeout(()=>{ if (el.children.length>10) el.removeChild(el.lastChild); }, 5000);
}

function setCurrentPath(p){
  currentPath = p||"";
  document.getElementById('current-path').textContent = "/" + currentPath;
  load();
}

async function load(){
  const res = await api.list(currentPath);
  if (res.error){ alert(res.error); return; }
  renderList(res.items);
}

function renderList(items){
  const container = document.getElementById('file-tree');
  container.innerHTML = '';

  const controlsRow = document.createElement('div');
  controlsRow.className = 'item-row';
  controlsRow.innerHTML = `<div class="small-muted">操作：右侧按钮 | 拖拽移动到目录 | 选中后可分享</div>`;
  container.appendChild(controlsRow);

  // 上一级
  const upRow = document.createElement('div');
  upRow.className = 'item-row';
  upRow.innerHTML = `<div class="text-muted">.. (上一级)</div>`;
  upRow.onclick = ()=> {
    const parts = currentPath.split('/').filter(Boolean);
    parts.pop();
    setCurrentPath(parts.join('/'));
  };
  container.appendChild(upRow);

  items.forEach(it=>{
    const row = document.createElement('div');
    row.className = 'item-row';
    row.draggable = true;
    row.dataset.path = it.path;

    const left = document.createElement('div');
    left.style.display = 'flex';
    left.style.gap = '12px';
    left.style.alignItems = 'center';
    const icon = document.createElement('div');
    icon.innerHTML = it.is_dir ? '📁' : '📄';
    const name = document.createElement('div');
    name.textContent = it.name + (it.is_dir ? '/' : '');
    if (it.is_dir) name.className = 'folder-name';
    left.appendChild(icon);
    left.appendChild(name);

    const right = document.createElement('div');

    if (!it.is_dir){
      const dl = document.createElement('button'); dl.className='btn btn-sm btn-outline-primary me-1'; dl.textContent='下载';
      dl.onclick = (e)=>{ e.stopPropagation(); api.download(it.path); };
      right.appendChild(dl);
    }

    const shareBtn = document.createElement('button'); shareBtn.className='btn btn-sm btn-outline-info me-1'; shareBtn.textContent='分享';
    shareBtn.onclick = async (e)=>{ e.stopPropagation(); const name = prompt('分享名称（可选）'); const r = await api.share_create(it.path, name||''); if (r.error) alert(r.error); else { log('创建分享: ' + r.token); showShares(); } };
    right.appendChild(shareBtn);

    const del = document.createElement('button'); del.className='btn btn-sm btn-outline-danger me-1'; del.textContent='删除';
    del.onclick = async (e) => {
      e.stopPropagation();
      const confirmMsg = it.is_dir ? `确定要递归删除目录 ${it.path} 吗？` : `确定要删除文件 ${it.path} 吗？`;
      if (!confirm(confirmMsg)) return;
      const r = await api.delete(it.path, it.is_dir);
      if (r.error) { log(r.error, 'error'); } else { log('删除成功: ' + it.path); load(); }
    };
    right.appendChild(del);

    const moveBtn = document.createElement('button'); moveBtn.className='btn btn-sm btn-outline-secondary'; moveBtn.textContent='选中并移动';
    moveBtn.onclick = async (e) => {
      e.stopPropagation();
      const dest = prompt("输入目标目录（相对路径，留空为根）:");
      if (dest===null) return;
      const r = await api.move(it.path, dest.trim());
      if (r.error) { alert(r.error); } else { log('移动到 ' + r.moved_to); load(); }
    };
    right.appendChild(moveBtn);

    row.appendChild(left);
    row.appendChild(right);

    row.onclick = () => {
      if (it.is_dir) setCurrentPath(it.path);
      else api.download(it.path);
    };

    row.addEventListener('dragstart', (ev)=>{
      ev.dataTransfer.setData('text/plain', it.path);
    });

    if (it.is_dir){
      row.addEventListener('dragover', (ev)=>{ ev.preventDefault(); row.classList.add('drop-target'); });
      row.addEventListener('dragleave', ()=> row.classList.remove('drop-target'));
      row.addEventListener('drop', async (ev)=>{
        ev.preventDefault();
        row.classList.remove('drop-target');
        const src = ev.dataTransfer.getData('text/plain');
        if (!src) return;
        if (src === it.path || src.startsWith(it.path + '/')) { alert('不能移动到自身或子目录'); return; }
        const res = await api.move(src, it.path);
        if (res.error) alert(res.error); else { log('移动成功: ' + src + ' → ' + res.moved_to); load(); }
      });
    }

    container.appendChild(row);
  });
}

document.getElementById('up-btn').onclick = ()=> {
  const parts = currentPath.split('/').filter(Boolean);
  parts.pop();
  setCurrentPath(parts.join('/'));
};

document.getElementById('mkdir-btn').onclick = async ()=>{
  const name = document.getElementById('mkdir-name').value.trim();
  if (!name) return alert('请输入目录名');
  const res = await api.mkdir(currentPath, name);
  if (res.error) alert(res.error); else { document.getElementById('mkdir-name').value=''; load(); }
};

document.getElementById('choose-btn').onclick = ()=> document.getElementById('upload-input').click();

document.getElementById('upload-btn').onclick = async ()=>{
  const input = document.getElementById('upload-input');
  if (input.files.length === 0) return alert('请选择文件');
  const res = await api.upload(currentPath, input.files);
  if (res.error) alert(res.error); else { log('上传成功: ' + (res.saved||[]).join(', ')); input.value=''; load(); }
};

document.getElementById('myshares-btn').onclick = ()=> showShares();

async function showShares(){
  const panel = document.getElementById('share-panel');
  panel.style.display = 'block';
  const res = await api.share_list();
  const list = document.getElementById('share-list');
  list.innerHTML = '';
  if (res.error) { list.textContent = res.error; return; }
  if (!res.shares.length) { list.textContent = '无分享'; return; }
  res.shares.forEach(s=>{
    const d = document.createElement('div');
    d.className = 'd-flex align-items-center justify-content-between mb-1';
    d.innerHTML = `<div><strong>${s.name||s.token}</strong> — ${s.path} <div class="small text-muted">创建: ${s.created}</div></div>
      <div>
        <button class="btn btn-sm btn-outline-primary me-1" onclick="navigator.clipboard.writeText(window.location.origin + '/s/' + '${s.token}')" >复制链接</button>
        <button class="btn btn-sm btn-outline-danger" onclick="delShare('${s.token}')">取消分享</button>
      </div>`;
    list.appendChild(d);
  });
}

async function delShare(token){
  if (!confirm('确认取消分享？')) return;
  const r = await api.share_delete(token);
  if (r.error) alert(r.error); else { log('取消分享: ' + token); showShares(); }
}

document.getElementById('open-share-btn').onclick = async ()=>{
  const token = document.getElementById('public-token').value.trim();
  if (!token) return alert('请输入分享 token');
  const res = await api.public_list(token, '');
  const area = document.getElementById('public-share-area');
  if (res.error) { area.textContent = res.error; return; }
  area.innerHTML = `<h6>分享：${token}</h6>`;
  const ul = document.createElement('div');
  ul.className = 'bg-white p-2';
  if (!res.items.length) ul.textContent = '分享为空或不可访问';
  res.items.forEach(it=>{
    const row = document.createElement('div');
    row.className = 'd-flex justify-content-between align-items-center p-1';
    row.innerHTML = `<div>${it.is_dir? '📁':'📄'} ${it.name + (it.is_dir?'/':'')}</div>
      <div>
        ${it.is_dir ? `<button class="btn btn-sm btn-outline-secondary" onclick="openPublic('${token}','${it.path}')">打开</button>` : `<button class="btn btn-sm btn-outline-primary" onclick="downloadPublic('${token}','${it.path}')">下载</button>`}
      </div>`;
    ul.appendChild(row);
  });
  area.appendChild(ul);
};

function openPublic(token, path){
  api.public_list(token, path).then(res=>{
    const area = document.getElementById('public-share-area');
    if (res.error) { area.textContent = res.error; return; }
    area.innerHTML = `<h6>分享：${token} — /${path}</h6>`;
    const ul = document.createElement('div'); ul.className = 'bg-white p-2';
    const up = document.createElement('div'); up.className='mb-2'; up.innerHTML=`<button class="btn btn-sm btn-outline-secondary" onclick="document.getElementById('public-token').value='${token}'; openPublic('${token}','')">返回根</button>`;
    ul.appendChild(up);
    res.items.forEach(it=>{
      const row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-center p-1';
      row.innerHTML = `<div>${it.is_dir? '📁':'📄'} ${it.name + (it.is_dir?'/':'')}</div>
        <div>${it.is_dir ? `<button class="btn btn-sm btn-outline-secondary" onclick="openPublic('${token}','${it.path}')">打开</button>` : `<button class="btn btn-sm btn-outline-primary" onclick="downloadPublic('${token}','${it.path}')">下载</button>`}</div>`;
      ul.appendChild(row);
    });
    area.appendChild(ul);
  });
}

function downloadPublic(token, path){ api.public_download(token, path); }

// 初始化
setCurrentPath("");
</script>
</body>
</html>
"""
# ---------- DB Helpers ----------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db
def init_db():
    db = get_db()
    cur = db.cursor()
    # users: id, username(unique), password_hash (salt$hash), created_at
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        user_id INTEGER,
        path TEXT NOT NULL,
        name TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    db.commit()
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()
# ---------- Auth Helpers ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(PWD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200000)
    return salt.hex() + "$" + digest.hex()
def verify_password(stored: str, password: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db()
    cur = db.execute("SELECT id, username FROM users WHERE id = ?", (uid,))
    r = cur.fetchone()
    return r["username"] if r else None
def require_login():
    if not session.get("user_id"):
        abort(401)
# ---------- File helpers ----------
def safe_join(root: str, *paths: str) -> str:
    root_p = Path(root).resolve()
    target = root_p.joinpath(*paths).resolve()
    try:
        target.relative_to(root_p)
    except Exception:
        raise ValueError("Attempt to access outside storage root")
    return str(target)
def list_directory(rel_path=""):
    target = safe_join(ROOT_STORAGE, rel_path) if rel_path else str(Path(ROOT_STORAGE))
    if not os.path.exists(target):
        raise FileNotFoundError
    if not os.path.isdir(target):
        raise NotADirectoryError
    items = []
    with os.scandir(target) as it:
        for entry in it:
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "path": os.path.join(rel_path, entry.name).replace("\\", "/") if rel_path else entry.name.replace("\\", "/"),
                "size": entry.stat().st_size if entry.is_file() else None
            })
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return items
# ---------- ROUTES: AUTH ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template_string("""
        <!doctype html><html><head><meta charset="utf-8"><title>注册</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
        </head><body class="p-3"><div class="container">
        <h4>注册</h4>
        <form method="post">
        <div class="mb-2"><input name="username" class="form-control" placeholder="用户名"></div>
        <div class="mb-2"><input name="password" type="password" class="form-control" placeholder="密码"></div>
        <button class="btn btn-primary">注册</button> <a href="/">返回</a>
        </form></div></body></html>
        """)
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not username or not password:
        return "用户名与密码必填", 400
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, hash_password(password), datetime.utcnow().isoformat()))
        db.commit()
    except sqlite3.IntegrityError:
        return "用户名已存在", 400
    return redirect(url_for("login"))
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string("""
        <!doctype html><html><head><meta charset="utf-8"><title>登录</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
        </head><body class="p-3"><div class="container">
        <h4>登录</h4>
        <form method="post">
        <div class="mb-2"><input name="username" class="form-control" placeholder="用户名"></div>
        <div class="mb-2"><input name="password" type="password" class="form-control" placeholder="密码"></div>
        <button class="btn btn-primary">登录</button> <a href="/">返回</a>
        </form></div></body></html>
        """)
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    db = get_db()
    cur = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    r = cur.fetchone()
    if not r or not verify_password(r["password_hash"], password):
        return "用户名或密码错误", 400
    session.clear()
    session["user_id"] = r["id"]
    return redirect(url_for("index"))
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
# ---------- ROUTES: UI ----------
@app.route("/")
def index():
    user = current_user()
    return render_template_string(INDEX_HTML, user=user)
# ---------- ROUTES: API (file ops) ----------
@app.route("/api/list")
def api_list():
    rel = request.args.get("path", "").strip().strip("/")
    try:
        items = list_directory(rel)
    except FileNotFoundError:
        return jsonify({"error": "目录不存在"}), 404
    except NotADirectoryError:
        return jsonify({"error": "不是目录"}), 400
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    return jsonify({"path": rel, "items": items})
@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    require_login()
    data = request.get_json() or {}
    rel = (data.get("path") or "").strip().strip("/")
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name 必须提供"}), 400
    name = secure_filename(name)
    try:
        target = safe_join(ROOT_STORAGE, rel, name) if rel else safe_join(ROOT_STORAGE, name)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    try:
        os.makedirs(target, exist_ok=False)
    except FileExistsError:
        return jsonify({"error": "目录已存在"}), 400
    return jsonify({"ok": True, "path": os.path.join(rel, name).replace("\\", "/")})
@app.route("/api/upload", methods=["POST"])
def api_upload():
    require_login()
    rel = (request.form.get("path") or "").strip().strip("/")
    try:
        dest = safe_join(ROOT_STORAGE, rel) if rel else safe_join(ROOT_STORAGE)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.isdir(dest):
        return jsonify({"error": "目标目录不存在"}), 404
    if 'file' not in request.files:
        return jsonify({"error": "没有文件上传（字段名为 file）"}), 400
    files = request.files.getlist("file")
    saved = []
    for f in files:
        filename = secure_filename(f.filename)
        if not filename:
            continue
        out = os.path.join(dest, filename)
        # 若文件存在则添加 suffix 避免覆盖
        if os.path.exists(out):
            base, ext = os.path.splitext(filename)
            i = 1
            while os.path.exists(os.path.join(dest, f"{base}({i}){ext}")):
                i += 1
            filename = f"{base}({i}){ext}"
            out = os.path.join(dest, filename)
        f.save(out)
        saved.append(os.path.join(rel, filename).replace("\\", "/") if rel else filename.replace("\\", "/"))
    return jsonify({"ok": True, "saved": saved})
@app.route("/api/download")
def api_download():
    rel = (request.args.get("path") or "").lstrip("/")
    if not rel:
        return jsonify({"error": "path 必须提供"}), 400
    try:
        target = safe_join(ROOT_STORAGE, rel)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(target, as_attachment=True)
@app.route("/api/delete", methods=["POST"])
def api_delete():
    require_login()
    data = request.get_json() or {}
    rel = (data.get("path") or "").lstrip("/")
    if not rel:
        return jsonify({"error": "path 必须提供"}), 400
    try:
        target = safe_join(ROOT_STORAGE, rel)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(target):
        return jsonify({"error": "目标不存在"}), 404
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500
    return jsonify({"ok": True})
@app.route("/api/move", methods=["POST"])
def api_move():
    require_login()
    data = request.get_json() or {}
    src = (data.get("src") or "").lstrip("/")
    dest_dir = (data.get("dest_dir") or "").strip().strip("/")
    if not src:
        return jsonify({"error": "src 必须提供"}), 400
    try:
        abs_src = safe_join(ROOT_STORAGE, src)
        abs_dest_dir = safe_join(ROOT_STORAGE, dest_dir) if dest_dir else safe_join(ROOT_STORAGE)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(abs_src):
        return jsonify({"error": "源不存在"}), 404
    if not os.path.isdir(abs_dest_dir):
        return jsonify({"error": "目标目录不存在"}), 404
    name = os.path.basename(abs_src)
    abs_dest = os.path.join(abs_dest_dir, name)
    if os.path.exists(abs_dest):
        return jsonify({"error": "目标已存在"}), 400
    try:
        shutil.move(abs_src, abs_dest)
    except Exception as e:
        return jsonify({"error": f"移动失败: {str(e)}"}), 500
    rel_dest = os.path.join(dest_dir, name).replace("\\", "/") if dest_dir else name.replace("\\", "/")
    return jsonify({"ok": True, "moved_to": rel_dest})
# ---------- ROUTES: SHARE (uses sqlite shares table) ----------
@app.route("/api/share/create", methods=["POST"])
def api_share_create():
    require_login()
    data = request.get_json() or {}
    path = (data.get("path") or "").lstrip("/")
    name = (data.get("name") or "").strip()
    if not path:
        return jsonify({"error": "path 必须提供"}), 400
    # path must exist
    try:
        p_abs = safe_join(ROOT_STORAGE, path)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(p_abs):
        return jsonify({"error": "路径不存在"}), 404
    token = secrets.token_urlsafe(16)
    uid = session.get("user_id")
    db = get_db()
    db.execute("INSERT INTO shares (token, user_id, path, name, created_at) VALUES (?, ?, ?, ?, ?)",
               (token, uid, path, name, datetime.utcnow().isoformat()))
    db.commit()
    return jsonify({"ok": True, "token": token})
@app.route("/api/share/list")
def api_share_list():
    require_login()
    uid = session.get("user_id")
    db = get_db()
    cur = db.execute("SELECT token, path, name, created_at FROM shares WHERE user_id = ? ORDER BY created_at DESC", (uid,))
    rows = cur.fetchall()
    shares = [{"token": r["token"], "path": r["path"], "name": r["name"], "created": r["created_at"]} for r in rows]
    return jsonify({"shares": shares})
@app.route("/api/share/delete", methods=["POST"])
def api_share_delete():
    require_login()
    data = request.get_json() or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "token 必须提供"}), 400
    uid = session.get("user_id")
    db = get_db()
    cur = db.execute("SELECT id FROM shares WHERE token = ? AND user_id = ?", (token, uid))
    r = cur.fetchone()
    if not r:
        return jsonify({"error": "未找到该分享或无权限"}), 404
    db.execute("DELETE FROM shares WHERE id = ?", (r["id"],))
    db.commit()
    return jsonify({"ok": True})
# Public share listing & download
@app.route("/api/share/public/list")
def api_share_public_list():
    token = (request.args.get("token") or "").strip()
    rel = (request.args.get("path") or "").strip().strip("/")
    if not token:
        return jsonify({"error": "token 必须提供"}), 400
    db = get_db()
    cur = db.execute("SELECT path FROM shares WHERE token = ?", (token,))
    r = cur.fetchone()
    if not r:
        return jsonify({"error": "分享不存在"}), 404
    base = r["path"]
    # compute effective path
    full_rel = (base + ("/" + rel if rel else "")).strip("/")
    try:
        items = list_directory(full_rel)
    except FileNotFoundError:
        return jsonify({"error": "目录不存在"}), 404
    except NotADirectoryError:
        return jsonify({"error": "不是目录"}), 400
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    return jsonify({"items": items})
@app.route("/api/share/public/download")
def api_share_public_download():
    token = (request.args.get("token") or "").strip()
    rel = (request.args.get("path") or "").lstrip("/")
    if not token or not rel:
        return jsonify({"error": "token 和 path 必须提供"}), 400
    db = get_db()
    cur = db.execute("SELECT path FROM shares WHERE token = ?", (token,))
    r = cur.fetchone()
    if not r:
        return jsonify({"error": "分享不存在"}), 404
    base = r["path"]
    full_rel = (base + "/" + rel).strip("/")
    try:
        target = safe_join(ROOT_STORAGE, full_rel)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(target, as_attachment=True)
# Friendly public route for sharing links
@app.route("/s/<token>")
def public_share_page(token):
    # simple redirect to main page with token filled
    return redirect("/?share=" + token)
# ---------- BOOTSTRAP: ensure DB init ----------
with app.app_context():
    init_db()
# ---------- RUN ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
