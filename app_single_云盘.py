# app_single.py
import os
import sqlite3
import time
import uuid
import shutil
from pathlib import Path
from flask import (
    Flask, request, redirect, url_for, render_template_string, session,
    send_file, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
# ---- Config ----
BASE_DIR = Path(__file__).parent.resolve()
USER_FILES_DIR = BASE_DIR / "user_files"
DB_PATH = BASE_DIR / "app.db"
ALLOWED_EXT = None
MAX_FILE_SIZE = 200 * 1024 * 1024
SECRET_KEY = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
os.makedirs(USER_FILES_DIR, exist_ok=True)
app = Flask(__name__, static_folder=str(BASE_DIR))
app.secret_key = SECRET_KEY
# ---- Templates (embedded) ----
TPL_LOGIN = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>登录/注册</title></head>
<body>
  <h2>{{ 'Register' if action=='register' else 'Login' }}</h2>
  <form method="post">
    <label>用户名: <input name="username"></label><br>
    <label>密码: <input type="password" name="password"></label><br>
    <button type="submit">{{ 'Register' if action=='register' else 'Login' }}</button>
  </form>
  <p><a href="{{ url_for('login') }}">Login</a> | <a href="{{ url_for('register') }}">Register</a></p>
</body>
</html>
"""

TPL_INDEX = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>文件管理</title>
  <style>
    body{font-family: Arial, Helvetica, sans-serif; margin:20px;}
    .toolbar { margin-bottom:12px; }
    #file-list { border:1px solid #ddd; padding:8px; max-width:900px; min-height:200px; }
    .item { padding:6px; border-bottom:1px solid #f0f0f0; display:flex; justify-content:space-between; align-items:center; }
    .item.dragging { opacity:0.5; }
    .left { display:flex; gap:8px; align-items:center; }
    .dir { font-weight:700; color:#0563aa; cursor:pointer; }
    .file { color:#333; }
    .drop-target { background:#f7fdf7; border-left:4px solid #2d9c3a; }
    .controls button { margin-left:6px; }
  </style>
</head>
<body>
  <div>
    <span>用户: {{ session.get('username') }}</span> |
    <a href="{{ url_for('logout') }}">登出</a>
  </div>

  <div class="toolbar">
    <button onclick="goUp()">上一级</button>
    <span> 当前: <strong id="cur-path">/</strong> </span>
    <button onclick="openRecycle()">回收站</button>
    <input id="new-folder-name" placeholder="新建文件夹名">
    <button onclick="mkdir()">创建文件夹</button>
    <input type="file" id="files" multiple>
    <button onclick="uploadFiles()">上传</button>
  </div>

  <div id="file-list"></div>

  <script>
    let curPath = "";
    let inRecycle = false;

    async function listDir(){
      const res = await fetch('/api/list?path=' + encodeURIComponent(curPath) + '&deleted=' + (inRecycle? '1':'0'));
      const j = await res.json();
      document.getElementById('cur-path').innerText = '/' + (curPath || '');
      const cont = document.getElementById('file-list');
      cont.innerHTML = '';
      if (!j.items) return;
      for (const it of j.items){
        const div = document.createElement('div');
        div.className = 'item';
        div.dataset.name = it.name;
        div.dataset.isdir = it.is_dir ? '1' : '0';
        div.draggable = true;
        const left = document.createElement('div'); left.className='left';
        const icon = document.createElement('span'); icon.textContent = it.is_dir ? '📁' : '📄';
        const name = document.createElement('span'); name.textContent = it.name; name.className = it.is_dir ? 'dir':'file';
        left.appendChild(icon); left.appendChild(name);
        const controls = document.createElement('div'); controls.className='controls';
        if (!it.is_dir && !inRecycle){
          const dl = document.createElement('button'); dl.textContent='下载'; dl.onclick = ()=> download(it.name);
          controls.appendChild(dl);
        }
        if (!inRecycle){
          const mv = document.createElement('button'); mv.textContent='移动'; mv.onclick = ()=> promptMove(it.name);
          controls.appendChild(mv);
        }
        const del = document.createElement('button'); del.textContent = inRecycle ? '永久删除' : '删除';
        del.onclick = ()=> deleteItem(it.name, it.is_dir);
        controls.appendChild(del);
        if (inRecycle){
          const resb = document.createElement('button'); resb.textContent='恢复'; resb.onclick = ()=> restoreItem(it.name);
          controls.appendChild(resb);
        } else {
          const rn = document.createElement('button'); rn.textContent='重命名'; rn.onclick = ()=> renameItem(it.name, it.is_dir);
          controls.appendChild(rn);
        }

        div.appendChild(left); div.appendChild(controls);
        name.onclick = ()=> { if (it.is_dir) { openDir(it.name) } else { download(it.name) } }

        div.addEventListener('dragstart', (e)=> {
          e.dataTransfer.setData('text/plain', (curPath ? curPath + '/' : '') + it.name);
          div.classList.add('dragging');
        });
        div.addEventListener('dragend', ()=> div.classList.remove('dragging'));

        if (it.is_dir && !inRecycle){
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
      if (j.saved) { input.value=''; listDir(); }
      else alert(j.error||'上传错误');
    }

    function download(name){
      const path = curPath ? (curPath + '/' + name) : name;
      window.location = '/api/download?path=' + encodeURIComponent(path);
    }

    async function deleteItem(name, isDir){
      if (!confirm((inRecycle? '永久删除 ':'删除 ') + name + '?')) return;
      const path = curPath ? (curPath + '/' + name) : name;
      const res = await fetch('/api/delete', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ path, permanent: inRecycle })
      });
      const j = await res.json();
      if (j.ok) listDir(); else alert(j.error||'错误');
    }

    async function restoreItem(name){
      const path = curPath ? (curPath + '/' + name) : name;
      const res = await fetch('/api/restore', {
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ path })
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

    function openRecycle(){
      inRecycle = !inRecycle;
      if (inRecycle){
        curPath = "";
      }
      listDir();
    }

    listDir();
  </script>
</body>
</html>
"""
# ---- DB init & helpers ----
def init_db():
    if DB_PATH.exists():
        return
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )""")
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
        conn.commit()
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
# ---- utils ----
def login_required(f):
    @wraps(f)
    def deco(*a, **kw):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return deco
def current_user_dir():
    uid = session.get("user_id")
    if not uid:
        return None
    d = USER_FILES_DIR / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d
def safe_path_join(base: Path, rel_path: str) -> Path:
    rel = Path(rel_path) if rel_path else Path('.')
    joined = (base / rel).resolve()
    if not str(joined).startswith(str(base.resolve())):
        raise ValueError("Path traversal")
    return joined
def normalize_rel_path(p: str) -> str:
    if not p:
        return ""
    parts = [part for part in Path(p).parts if part not in ('.', '')]
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
# ---- API: list, mkdir, upload, download, delete, restore, move, meta ----
@app.route("/api/list", methods=["GET"])
@login_required
def api_list():
    rel = normalize_rel_path(request.args.get("path", ""))
    show_deleted = request.args.get("deleted", "0") == "1"
    uid = session["user_id"]
    with get_db() as conn:
        cur = conn.cursor()
        if show_deleted:
            cur.execute("SELECT display_name, path, size, mime, is_dir FROM files WHERE user_id=? AND path=? ORDER BY is_dir DESC, display_name COLLATE NOCASE", (uid, rel))
        else:
            cur.execute("SELECT display_name, path, size, mime, is_dir FROM files WHERE user_id=? AND path=? AND deleted=0 ORDER BY is_dir DESC, display_name COLLATE NOCASE", (uid, rel))
        rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({"name": r["display_name"], "is_dir": bool(r["is_dir"]), "size": r["size"], "mime": r["mime"]})
    return jsonify({"path": rel, "items": items})
@app.route("/api/mkdir", methods=["POST"])
@login_required
def api_mkdir():
    data = request.get_json() or {}
    rel = normalize_rel_path(data.get("path", ""))
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
        cur.execute("INSERT INTO files (user_id, stored_name, display_name, path, size, mime, is_dir, created_at, modified_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (uid, "", name_safe, rel, 0, "dir", now, now))
        conn.commit()
    return jsonify({"ok": True})
@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    rel = normalize_rel_path(request.form.get("path", ""))
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
    now = int(time.time())
    with get_db() as conn:
        cur = conn.cursor()
        for f in files:
            if not f or not f.filename: continue
            filename = secure_filename(f.filename) or f.filename
            ext = Path(filename).suffix.lower()
            if ALLOWED_EXT and ext not in ALLOWED_EXT: continue
            f.seek(0, os.SEEK_END); size = f.tell(); f.seek(0)
            if MAX_FILE_SIZE and size > MAX_FILE_SIZE: continue
            stored = str(uuid.uuid4().hex) + ext
            dest = target_dir_fs / stored
            f.save(str(dest))
            mime = None
            try:
                import magic
                mime = magic.from_file(str(dest), mime=True)
            except Exception:
                mime = None
            cur.execute("INSERT INTO files (user_id, stored_name, display_name, path, size, mime, is_dir, created_at, modified_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                        (uid, stored, filename, rel, size, mime, now, now))
            saved.append(filename)
        conn.commit()
    return jsonify({"saved": saved})
@app.route("/api/download", methods=["GET"])
@login_required
def api_download():
    relpath = normalize_rel_path(request.args.get("path", ""))
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
    data = request.get_json() or {}
    rel = normalize_rel_path(data.get("path", ""))
    permanent = bool(data.get("permanent", False))
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
        if permanent:
            if is_dir:
                prefix = (row["path"] + "/" + row["display_name"]).lstrip('/')
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
                cur.execute("DELETE FROM files WHERE user_id=? AND (path=? OR path LIKE ?)", (uid, prefix, prefix + '/%'))
            else:
                user_dir = current_user_dir()
                ffs = user_dir / row["path"] / stored
                if ffs.exists():
                    try: ffs.unlink()
                    except: pass
                cur.execute("DELETE FROM files WHERE id=?", (fid,))
            conn.commit()
            return jsonify({"ok": True})
        else:
            if is_dir:
                prefix = (row["path"] + "/" + row["display_name"]).lstrip('/')
                cur.execute("UPDATE files SET deleted=1 WHERE id=?", (fid,))
                cur.execute("UPDATE files SET deleted=1 WHERE user_id=? AND (path=? OR path LIKE ?)", (uid, prefix, prefix + '/%'))
            else:
                cur.execute("UPDATE files SET deleted=1 WHERE id=?", (fid,))
            conn.commit()
            return jsonify({"ok": True})
@app.route("/api/restore", methods=["POST"])
@login_required
def api_restore():
    data = request.get_json() or {}
    rel = normalize_rel_path(data.get("path", ""))
    if not rel: return jsonify({"error": "no path"}), 400
    uid = session["user_id"]
    parent = str(Path(rel).parent) if "/" in rel else ""
    name = Path(rel).name
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, is_dir, path, display_name FROM files WHERE user_id=? AND path=? AND display_name=? AND deleted=1", (uid, parent, name))
        row = cur.fetchone()
        if not row: return jsonify({"error": "not found"}), 404
        fid = row["id"]
        if row["is_dir"]:
            prefix = (row["path"] + "/" + row["display_name"]).lstrip('/')
            cur.execute("UPDATE files SET deleted=0 WHERE user_id=? AND (path=? OR path LIKE ?)", (uid, prefix, prefix + '/%'))
        else:
            cur.execute("UPDATE files SET deleted=0 WHERE id=?", (fid,))
        conn.commit()
    return jsonify({"ok": True})
@app.route("/api/move", methods=["POST"])
@login_required
def api_move():
    data = request.get_json() or {}
    src = normalize_rel_path(data.get("src", ""))
    dest = normalize_rel_path(data.get("dest", ""))
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
        if dest == "":
            final_parent = ""
            final_name = src_name
        else:
            dest_parent = str(Path(dest).parent) if "/" in dest else ""
            dest_name = Path(dest).name
            # check if dest refers to existing dir (by filesystem)
            user_dir = current_user_dir()
            try:
                dest_fs = safe_path_join(user_dir, dest)
            except ValueError:
                return jsonify({"error": "invalid dest"}), 400
            if dest_fs.exists() and dest_fs.is_dir():
                # move into this dir
                final_parent = normalize_rel_path(dest)
                final_name = src_name
            else:
                parent_of_dest = str(Path(dest).parent) if "/" in dest else ""
                parent_fs = safe_path_join(user_dir, parent_of_dest) if parent_of_dest else user_dir
                if not parent_fs.exists():
                    return jsonify({"error": "dest parent not found"}), 400
                final_parent = parent_of_dest
                final_name = secure_filename(dest_name) or dest_name

        # prevent moving dir into its descendant
        if row["is_dir"]:
            src_full_fs = current_user_dir() / row["path"] / row["display_name"]
            target_fs = current_user_dir() / final_parent / final_name
            try:
                if str(target_fs.resolve()).startswith(str(src_full_fs.resolve())):
                    return jsonify({"error": "cannot move directory into its own descendant"}), 400
            except Exception:
                pass

        cur.execute("SELECT id FROM files WHERE user_id=? AND path=? AND display_name=? AND deleted=0", (uid, final_parent, final_name))
        if cur.fetchone():
            return jsonify({"error": "target exists"}), 400

        user_dir = current_user_dir()
        if row["is_dir"]:
            src_fs = user_dir / row["path"] / row["display_name"]
            dest_fs_parent = user_dir / final_parent
            dest_fs_parent.mkdir(parents=True, exist_ok=True)
            dest_fs = dest_fs_parent / final_name
            try:
                src_fs.rename(dest_fs)
            except Exception:
                try: shutil.move(str(src_fs), str(dest_fs))
                except: return jsonify({"error": "fs move failed"}), 500
            old_prefix = (row["path"] + "/" + row["display_name"]).lstrip('/')
            new_prefix = (final_parent + "/" + final_name).lstrip('/')
            cur.execute("UPDATE files SET path=?, display_name=?, modified_at=? WHERE id=?", (final_parent, final_name, int(time.time()), row["id"]))
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
                try: shutil.move(str(src_fs), str(dest_fs))
                except: return jsonify({"error": "fs move failed"}), 500
            cur.execute("UPDATE files SET path=?, display_name=?, modified_at=? WHERE id=?", (final_parent, final_name, int(time.time()), row["id"]))
            conn.commit()
            return jsonify({"ok": True})
@app.route("/api/meta", methods=["GET"])
@login_required
def api_meta():
    rel = normalize_rel_path(request.args.get("path", ""))
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
# ---- Run ----
if __name__ == "__main__":
    init_db()
    print("Starting app on http://127.0.0.1:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
