#!/usr/bin/env python3
"""
Improved single-file Flask Cloud Drive.
Features:
- Bootstrap 5 UI with icons, sidebar, modal dialogs, upload queue.
- Two SQLite DBs: authentication.db and shares.db.
- User-isolated storage under ./user_storage/<username>/
- Multi-file upload, drag & drop move, create folder, delete, download.
- Share/unshare per-file or per-folder with short token URLs.
- Frontend queries /api/myshares to toggle Share/Unshare buttons.
- Reasonable security measures: secure_filename, path traversal protection,
  password hashing, session checks, CORS via same-origin browser behavior.
"""
import os
import pathlib
import shutil
import hashlib
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, send_from_directory, render_template_string,
    redirect, url_for, session
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
# --- Config ---
BASE_DIR = pathlib.Path(__file__).parent.resolve()
USER_STORAGE_DIR = BASE_DIR / "user_storage"
USER_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
AUTH_DB_URL = f"sqlite:///{BASE_DIR / 'authentication.db'}"
SHARES_DB_URL = f"sqlite:///{BASE_DIR / 'shares.db'}"
APP = Flask(__name__)
APP.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
APP.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB default limit for uploads
# --- DB models ---
BaseAuth = declarative_base()
BaseShares = declarative_base()
class User(BaseAuth):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
class Share(BaseShares):
    __tablename__ = "shares"
    id = Column(Integer, primary_key=True)
    owner_username = Column(String(150), nullable=False, index=True)
    relative_path = Column(Text, nullable=False)
    is_directory = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    public_token = Column(String(64), nullable=True, unique=True)
auth_engine = create_engine(AUTH_DB_URL, connect_args={"check_same_thread": False})
shares_engine = create_engine(SHARES_DB_URL, connect_args={"check_same_thread": False})
BaseAuth.metadata.create_all(auth_engine)
BaseShares.metadata.create_all(shares_engine)
AuthSession = scoped_session(sessionmaker(bind=auth_engine))
SharesSession = scoped_session(sessionmaker(bind=shares_engine))
# --- Helpers ---
def get_user_dir(username: str) -> pathlib.Path:
    safe_name = secure_filename(username)
    p = USER_STORAGE_DIR / safe_name
    p.mkdir(parents=True, exist_ok=True)
    return p
def safe_join_user_path(username: str, relative_path: str) -> pathlib.Path:
    base = get_user_dir(username).resolve()
    rel_clean = relative_path.lstrip("/\\")
    target = (base / rel_clean).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("invalid path")
    return target
def generate_token(username: str, relative_path: str) -> str:
    h = hashlib.sha1(f"{username}:{relative_path}:{datetime.utcnow().timestamp()}".encode()).hexdigest()
    return h[:12]
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "authentication required"}), 401
        return f(*args, **kwargs)
    return wrapper
# --- Templates (improved UI) ---
TEMPLATE_INDEX = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Cloud Drive</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap-icons/1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <style>
    body { padding:1rem; }
    .sidebar { height: calc(100vh - 2rem); overflow:auto; }
    .file-item { cursor: default; user-select: none; }
    .file-item:hover { background:#f8f9fa; }
    #contextMenu { position:absolute; display:none; z-index:2500; background:#fff; border:1px solid #ddd; border-radius:6px; box-shadow:0 6px 20px rgba(0,0,0,.08); }
    #contextMenu button { width:100%; text-align:left; border:none; background:none; padding:.5rem 1rem; }
    .drop-overlay { outline:3px dashed #0d6efd; border-radius:6px; }
    .file-icon { width:28px; text-align:center; }
    .muted-small { font-size:.875rem; color:#6c757d; }
  </style>
</head>
<body>
<div class="container-fluid">
  <div class="d-flex justify-content-between mb-3">
    <h4 class="mb-0">Cloud Drive</h4>
    <div>
      <span class="me-3 muted-small">Signed in: <strong>{{ username }}</strong></span>
      <button id="logoutBtn" class="btn btn-outline-secondary btn-sm">Logout</button>
    </div>
  </div>

  <div class="row g-3">
    <div class="col-md-3">
      <div class="card sidebar p-2">
        <div class="mb-2 d-flex justify-content-between align-items-center">
          <strong>Actions</strong>
          <button id="newFolderBtn" class="btn btn-sm btn-primary">New</button>
        </div>
        <div class="mb-2">
          <label class="form-label small mb-1">Upload files</label>
          <input id="fileInput" type="file" multiple class="form-control form-control-sm" />
          <div class="mt-2">
            <button id="uploadBtn" class="btn btn-success btn-sm">Upload</button>
            <span id="uploadStatus" class="ms-2 muted-small"></span>
          </div>
        </div>
        <hr>
        <div>
          <strong>My Shares</strong>
          <ul id="sharesList" class="list-group list-group-flush mt-2"></ul>
        </div>
      </div>
    </div>

    <div class="col-md-9">
      <div class="card p-3" id="mainArea">
        <nav>
          <ol class="breadcrumb mb-2" id="breadcrumb"></ol>
        </nav>

        <div class="mb-2 d-flex justify-content-between align-items-center">
          <div>
            <button id="refreshBtn" class="btn btn-outline-secondary btn-sm me-2"><i class="bi bi-arrow-clockwise"></i> Refresh</button>
            <button id="goRootBtn" class="btn btn-outline-secondary btn-sm"><i class="bi bi-house"></i> Root</button>
          </div>
          <div class="muted-small">Drag items to folders to move</div>
        </div>

        <div id="fileArea" class="list-group" ondragover="event.preventDefault();" ondrop="onDropToArea(event)"></div>
      </div>
    </div>
  </div>
</div>

<div id="contextMenu">
  <button id="ctxDownload"><i class="bi bi-download me-2"></i>Download</button>
  <button id="ctxShare"><i class="bi bi-share me-2"></i>Share</button>
  <button id="ctxUnshare"><i class="bi bi-x-circle me-2"></i>Unshare</button>
  <button id="ctxRename"><i class="bi bi-pencil me-2"></i>Rename/Move</button>
  <button id="ctxDelete" class="text-danger"><i class="bi bi-trash me-2"></i>Delete</button>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
const username = "{{ username }}";
let currentPath = "";
let contextTarget = null; // { path, is_directory }

function escapeText(s){ const d = document.createTextNode(s); const div = document.createElement('div'); div.appendChild(d); return div.innerHTML; }

function setBreadcrumb(path){
  const parts = path === "" ? [] : path.split("/").filter(Boolean);
  const bc = document.getElementById("breadcrumb");
  bc.innerHTML = "";
  const rootLi = document.createElement("li");
  rootLi.className = "breadcrumb-item";
  const rootLink = document.createElement("a");
  rootLink.href = "#";
  rootLink.textContent = "/";
  rootLink.onclick = (e)=>{ e.preventDefault(); loadList(""); };
  rootLi.appendChild(rootLink);
  bc.appendChild(rootLi);
  let accum = "";
  for(const p of parts){
    accum = accum ? accum + "/" + p : p;
    const li = document.createElement("li");
    li.className = "breadcrumb-item";
    const a = document.createElement("a");
    a.href = "#";
    a.textContent = p;
    a.onclick = (e)=>{ e.preventDefault(); loadList(accum); };
    li.appendChild(a);
    bc.appendChild(li);
  }
}

async function loadList(path=""){
  currentPath = path;
  setBreadcrumb(path);
  const res = await fetch(`/api/list?path=${encodeURIComponent(path)}`, { credentials: 'same-origin' });
  if(!res.ok){ alert("Failed to load"); return; }
  const data = await res.json();
  const area = document.getElementById("fileArea");
  area.innerHTML = "";
  if(data.items.length === 0){
    const empty = document.createElement("div");
    empty.className = "text-muted";
    empty.textContent = "(empty)";
    area.appendChild(empty);
    return;
  }
  data.items.forEach(item=>{
    const row = document.createElement("div");
    row.className = "list-group-item d-flex align-items-center file-item";
    row.draggable = true;
    row.ondragstart = (e)=>{ e.dataTransfer.setData('text/plain', item.path); e.dataTransfer.effectAllowed = 'move'; };
    row.ondragover = (e)=>{ if(item.is_dir) e.preventDefault(); };
    row.ondrop = (e)=>{ if(item.is_dir){ e.preventDefault(); onDropToFolder(e, item.path); } };
    row.oncontextmenu = (e)=>{ e.preventDefault(); openContextMenu(e, item); };

    const icon = document.createElement("div");
    icon.className = "me-3 file-icon";
    icon.innerHTML = item.is_dir ? '<i class="bi bi-folder-fill text-warning"></i>' : '<i class="bi bi-file-earmark-fill"></i>';

    const title = document.createElement("div");
    title.style.flex = "1";
    const name = document.createElement("div");
    name.textContent = item.name;
    name.style.cursor = "pointer";
    name.onclick = ()=> { if(item.is_dir) loadList(item.path); else window.open(`/api/download?path=${encodeURIComponent(item.path)}`); };
    const meta = document.createElement("div");
    meta.className = "muted-small";
    meta.textContent = item.is_dir ? "Folder" : `${(item.size/1024).toFixed(1)} KB • ${new Date(item.mtime*1000).toLocaleString()}`;

    title.appendChild(name);
    title.appendChild(meta);

    row.appendChild(icon);
    row.appendChild(title);

    area.appendChild(row);
  });
  refreshSharesSidebar();
}

document.getElementById("refreshBtn").onclick = ()=> loadList(currentPath);
document.getElementById("goRootBtn").onclick = ()=> loadList("");

document.getElementById("uploadBtn").onclick = async ()=>{
  const input = document.getElementById("fileInput");
  if(!input.files.length) return alert("Pick files first");
  const form = new FormData();
  for(const f of input.files) form.append("files", f);
  form.append("path", currentPath);
  const status = document.getElementById("uploadStatus");
  status.textContent = "Uploading...";
  const res = await fetch("/api/upload", { method: "POST", body: form, credentials:'same-origin' });
  const data = await res.json();
  if(res.ok){ status.textContent = `Uploaded ${data.saved.length}`; loadList(currentPath); }
  else { status.textContent = `Upload failed: ${data.error||''}`; }
  setTimeout(()=> status.textContent = "", 2500);
};

document.getElementById("newFolderBtn").onclick = async ()=>{
  const name = prompt("New folder name:");
  if(!name) return;
  const res = await fetch("/api/mkdir", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({path: currentPath, name}), credentials:'same-origin' });
  if(res.ok) loadList(currentPath);
  else alert("Failed to create");
};

document.getElementById("logoutBtn").onclick = async ()=>{
  await fetch("/api/logout", { method:"POST", credentials:'same-origin' });
  window.location.href = "/login";
};

// Drag and drop move
async function onDropToFolder(event, destinationPath){
  const source = event.dataTransfer.getData('text/plain');
  if(!source) return;
  await fetch("/api/move", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ src: source, dst: destinationPath }), credentials:'same-origin' });
  loadList(currentPath);
}
async function onDropToArea(event){
  const source = event.dataTransfer.getData('text/plain');
  if(!source) return;
  await fetch("/api/move", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ src: source, dst: currentPath }), credentials:'same-origin' });
  loadList(currentPath);
}

// Context menu logic
function openContextMenu(e, item){
  contextTarget = { path: item.path, is_directory: item.is_dir };
  const menu = document.getElementById("contextMenu");
  menu.style.left = e.pageX + "px";
  menu.style.top = e.pageY + "px";
  menu.style.display = "block";
  // toggle share/unshare buttons based on whether item is shared
  checkShared(item.path).then(shared=>{
    document.getElementById("ctxShare").style.display = shared ? "none" : "block";
    document.getElementById("ctxUnshare").style.display = shared ? "block" : "none";
  });
}
document.addEventListener("click", ()=> document.getElementById("contextMenu").style.display = "none");

async function checkShared(path){
  const res = await fetch("/api/myshares", { credentials:'same-origin' });
  if(!res.ok) return false;
  const data = await res.json();
  return data.shares.some(s=> s.relative_path === path);
}

document.getElementById("ctxDownload").onclick = ()=>{
  if(contextTarget && !contextTarget.is_directory) window.open(`/api/download?path=${encodeURIComponent(contextTarget.path)}`);
  document.getElementById("contextMenu").style.display = "none";
};
document.getElementById("ctxShare").onclick = async ()=>{
  if(!contextTarget) return;
  const res = await fetch("/api/share", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: contextTarget.path }), credentials:'same-origin' });
  const data = await res.json();
  if(res.ok){
    alert("Shared. Public link copied to clipboard.");
    if(data.public_url && navigator.clipboard) await navigator.clipboard.writeText(data.public_url);
    refreshSharesSidebar();
  } else alert("Share failed: " + (data.error||""));
  document.getElementById("contextMenu").style.display = "none";
};
document.getElementById("ctxUnshare").onclick = async ()=>{
  if(!contextTarget) return;
  const res = await fetch("/api/unshare", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: contextTarget.path }), credentials:'same-origin' });
  if(res.ok) refreshSharesSidebar(); else alert("Unshare failed");
  document.getElementById("contextMenu").style.display = "none";
};
document.getElementById("ctxDelete").onclick = async ()=>{
  if(!contextTarget) return;
  if(!confirm("Delete permanently?")) return;
  const res = await fetch("/api/delete", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: contextTarget.path }), credentials:'same-origin' });
  if(res.ok) loadList(currentPath); else alert("Delete failed");
  document.getElementById("contextMenu").style.display = "none";
};
document.getElementById("ctxRename").onclick = async ()=>{
  if(!contextTarget) return;
  const newPath = prompt("Enter new name or destination path (relative):", contextTarget.path);
  if(!newPath) return;
  const res = await fetch("/api/move", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ src: contextTarget.path, dst: newPath }), credentials:'same-origin' });
  if(res.ok) loadList(currentPath); else alert("Rename/Move failed");
  document.getElementById("contextMenu").style.display = "none";
};

// Shares sidebar
async function refreshSharesSidebar(){
  const res = await fetch("/api/myshares", { credentials:'same-origin' });
  if(!res.ok) return;
  const data = await res.json();
  const list = document.getElementById("sharesList");
  list.innerHTML = "";
  data.shares.forEach(s=>{
    const li = document.createElement("li");
    li.className = "list-group-item small";
    const a = document.createElement("a");
    a.href = s.public_url;
    a.target = "_blank";
    a.textContent = s.relative_path + (s.is_directory ? " (dir)" : "");
    li.appendChild(a);
    const btn = document.createElement("button");
    btn.className = "btn btn-sm btn-outline-secondary float-end";
    btn.textContent = "Unshare";
    btn.onclick = async ()=>{ await fetch("/api/unshare", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ path: s.relative_path }), credentials:'same-origin' }); refreshSharesSidebar(); };
    li.appendChild(btn);
    list.appendChild(li);
  });
}

window.addEventListener("load", ()=> loadList(""));
</script>
</body>
</html>
"""

TEMPLATE_LOGIN = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Login - Cloud Drive</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style> body{ padding:2rem; } </style>
</head>
<body>
<div class="container" style="max-width:480px;">
  <div class="card">
    <div class="card-body">
      <h5 class="card-title">Sign in or Register</h5>
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input id="username" class="form-control">
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input id="password" type="password" class="form-control">
      </div>
      <div class="d-flex gap-2">
        <button id="loginBtn" class="btn btn-primary">Login</button>
        <button id="registerBtn" class="btn btn-outline-secondary">Register</button>
      </div>
      <div id="authMsg" class="mt-2 text-danger small"></div>
    </div>
  </div>
</div>

<script>
document.getElementById("loginBtn").onclick = async ()=>{
  const user = document.getElementById("username").value.trim();
  const pw = document.getElementById("password").value;
  const msg = document.getElementById("authMsg");
  msg.textContent = "";
  if(!user || !pw){ msg.textContent = "Enter username and password"; return; }
  const res = await fetch("/api/login", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ username: user, password: pw }) });
  if(res.ok) window.location.href = "/";
  else { const d = await res.json(); msg.textContent = d.error || "Login failed"; }
};
document.getElementById("registerBtn").onclick = async ()=>{
  const user = document.getElementById("username").value.trim();
  const pw = document.getElementById("password").value;
  const msg = document.getElementById("authMsg");
  msg.textContent = "";
  if(!user || !pw){ msg.textContent = "Enter username and password"; return; }
  const res = await fetch("/api/register", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ username: user, password: pw }) });
  const d = await res.json();
  if(res.ok) { alert("Registered. Please login."); }
  else msg.textContent = d.error || "Register failed";
};
</script>
</body>
</html>
"""
# --- Routes ---
@APP.route("/")
def index():
    if "username" not in session:
        return redirect("/login")
    return render_template_string(TEMPLATE_INDEX, username=session["username"])
@APP.route("/login")
def login_page():
    return render_template_string(TEMPLATE_LOGIN)
# --- Auth APIs ---
@APP.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error":"username and password required"}), 400
    db = AuthSession()
    if db.query(User).filter_by(username=username).first():
        return jsonify({"error":"username taken"}), 400
    user = User(username=username, password_hash=generate_password_hash(password))
    db.add(user)
    db.commit()
    get_user_dir(username)
    return jsonify({"ok": True})
@APP.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error":"username and password required"}), 400
    db = AuthSession()
    user = db.query(User).filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error":"invalid credentials"}), 401
    session["username"] = username
    return jsonify({"ok": True})
@APP.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("username", None)
    return jsonify({"ok": True})
# --- File APIs ---
@APP.route("/api/list", methods=["GET"])
@login_required
def api_list():
    username = session["username"]
    relative_path = (request.args.get("path") or "").strip("/")
    try:
        target = safe_join_user_path(username, relative_path) if relative_path else get_user_dir(username)
    except ValueError:
        return jsonify({"error":"invalid path"}), 400
    if not target.exists() or not target.is_dir():
        return jsonify({"error":"not a directory"}), 400
    items = []
    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        stat = entry.stat()
        items.append({
            "name": entry.name,
            "path": str((pathlib.Path(relative_path) / entry.name).as_posix()) if relative_path else entry.name,
            "is_dir": entry.is_dir(),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime)
        })
    return jsonify({"path": relative_path, "items": items})
@APP.route("/api/upload", methods=["POST"])
@login_required
def api_upload():
    username = session["username"]
    target_path = (request.form.get("path") or "").strip("/")
    try:
        dest = safe_join_user_path(username, target_path) if target_path else get_user_dir(username)
    except ValueError:
        return jsonify({"error":"invalid path"}), 400
    if not dest.exists():
        dest.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist("files")
    saved = []
    for fs in files:
        filename = secure_filename(fs.filename)
        if not filename:
            continue
        out = dest / filename
        fs.save(out)
        saved.append(str((pathlib.Path(target_path) / filename).as_posix()) if target_path else filename)
    return jsonify({"saved": saved})
@APP.route("/api/download", methods=["GET"])
@login_required
def api_download():
    username = session["username"]
    relative_path = (request.args.get("path") or "")
    try:
        target = safe_join_user_path(username, relative_path)
    except ValueError:
        return jsonify({"error":"invalid path"}), 400
    if target.is_dir():
        return jsonify({"error":"path is directory"}), 400
    userdir = get_user_dir(username)
    return send_from_directory(userdir, str(pathlib.Path(relative_path).name), as_attachment=True)
@APP.route("/api/mkdir", methods=["POST"])
@login_required
def api_mkdir():
    username = session["username"]
    data = request.get_json(force=True)
    parent = (data.get("path") or "").strip("/")
    folder_name = (data.get("name") or "").strip()
    if not folder_name:
        return jsonify({"error":"missing name"}), 400
    try:
        parent_dir = safe_join_user_path(username, parent) if parent else get_user_dir(username)
    except ValueError:
        return jsonify({"error":"invalid path"}), 400
    newdir = parent_dir / secure_filename(folder_name)
    newdir.mkdir(parents=True, exist_ok=True)
    rel = str((pathlib.Path(parent) / newdir.name).as_posix()) if parent else newdir.name
    return jsonify({"ok": True, "path": rel})
@APP.route("/api/delete", methods=["POST"])
@login_required
def api_delete():
    username = session["username"]
    data = request.get_json(force=True)
    relative_path = (data.get("path") or "")
    if not relative_path:
        return jsonify({"error":"path required"}), 400
    try:
        target = safe_join_user_path(username, relative_path)
    except ValueError:
        return jsonify({"error":"invalid path"}), 400
    shares_db = SharesSession()
    shares_db.query(Share).filter(Share.owner_username==username, Share.relative_path.like(f"{relative_path}%")).delete(synchronize_session=False)
    shares_db.commit()
    if target.is_dir():
        shutil.rmtree(target)
    else:
        try: target.unlink()
        except FileNotFoundError: pass
    return jsonify({"ok": True})
@APP.route("/api/move", methods=["POST"])
@login_required
def api_move():
    username = session["username"]
    data = request.get_json(force=True)
    src = (data.get("src") or "")
    dst = (data.get("dst") or "")
    if not src:
        return jsonify({"error":"src required"}), 400
    try:
        src_path = safe_join_user_path(username, src)
    except ValueError:
        return jsonify({"error":"invalid src"}), 400
    try:
        dst_path = safe_join_user_path(username, dst) if dst else get_user_dir(username)
    except ValueError:
        return jsonify({"error":"invalid dst"}), 400
    if dst_path.exists() and dst_path.is_dir():
        final = dst_path / src_path.name
    else:
        final = dst_path
        final.parent.mkdir(parents=True, exist_ok=True)
    src_path.rename(final)
    return jsonify({"ok": True, "new_path": str(final.relative_to(get_user_dir(username)).as_posix())})
# --- Share APIs ---
@APP.route("/api/share", methods=["POST"])
@login_required
def api_share():
    username = session["username"]
    data = request.get_json(force=True)
    relative_path = (data.get("path") or "").strip("/")
    if not relative_path:
        return jsonify({"error":"path required"}), 400
    try:
        target = safe_join_user_path(username, relative_path)
    except ValueError:
        return jsonify({"error":"invalid path"}), 400
    shares_db = SharesSession()
    existing = shares_db.query(Share).filter_by(owner_username=username, relative_path=relative_path).first()
    if existing:
        public_url = url_for("public_share_by_token", token=existing.public_token, _external=True) if existing.public_token else url_for("public_share_by_id", owner_username=username, share_id=existing.id, _external=True)
        return jsonify({"ok": True, "share_id": existing.id, "public_url": public_url})
    token = generate_token(username, relative_path)
    new = Share(owner_username=username, relative_path=relative_path, is_directory=target.is_dir(), public_token=token)
    shares_db.add(new); shares_db.commit()
    public_url = url_for("public_share_by_token", token=token, _external=True)
    return jsonify({"ok": True, "share_id": new.id, "public_url": public_url})
@APP.route("/api/unshare", methods=["POST"])
@login_required
def api_unshare():
    username = session["username"]
    data = request.get_json(force=True)
    relative_path = (data.get("path") or "").strip("/")
    shares_db = SharesSession()
    shares_db.query(Share).filter_by(owner_username=username, relative_path=relative_path).delete()
    shares_db.commit()
    return jsonify({"ok": True})
@APP.route("/api/myshares", methods=["GET"])
@login_required
def api_myshares():
    username = session["username"]
    shares_db = SharesSession()
    items = []
    for s in shares_db.query(Share).filter_by(owner_username=username).all():
        url = url_for("public_share_by_token", token=s.public_token, _external=True) if s.public_token else url_for("public_share_by_id", owner_username=username, share_id=s.id, _external=True)
        items.append({"id": s.id, "relative_path": s.relative_path, "is_directory": s.is_directory, "public_url": url})
    return jsonify({"shares": items})
# --- Public share access ---
@APP.route("/s/token/<token>/")
def public_share_by_token(token):
    shares_db = SharesSession()
    s = shares_db.query(Share).filter_by(public_token=token).first()
    if not s: return "Not found", 404
    return public_share_content(s.owner_username, s.relative_path)
@APP.route("/s/<owner_username>/<int:share_id>/")
def public_share_by_id(owner_username, share_id):
    shares_db = SharesSession()
    s = shares_db.query(Share).filter_by(owner_username=owner_username, id=share_id).first()
    if not s: return "Not found", 404
    return public_share_content(owner_username, s.relative_path)
def public_share_content(owner_username, relative_path):
    try:
        target = safe_join_user_path(owner_username, relative_path)
    except ValueError:
        return "Invalid", 400
    if target.is_dir():
        items = [{"name": e.name, "is_dir": e.is_dir()} for e in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))]
        return jsonify({"owner": owner_username, "path": relative_path, "items": items})
    else:
        return send_from_directory(get_user_dir(owner_username), str(pathlib.Path(relative_path).parent), filename=target.name, as_attachment=True)
# --- Health ---
@APP.route("/health")
def health():
    return jsonify({"status":"ok", "time": datetime.utcnow().isoformat()})
# --- Run ---
if __name__ == "__main__":
    print("Starting improved Cloud Drive on http://127.0.0.1:5000")
    APP.run(debug=True, host="127.0.0.1", port=5000)
