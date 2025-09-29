# app.py
import os
import sqlite3
import uuid
import datetime
import hashlib
from pathlib import Path
from flask import (
    Flask, g, request, jsonify, send_file, abort, url_for,
    render_template_string, redirect, session
)
# ---------------- Config ----------------
APP_DIR = Path(__file__).parent
STORAGE_ROOT = APP_DIR / "storage"
FILES_DB = APP_DIR / "files.db"
USER_DB = APP_DIR / "user.db"
SECRET_KEY = os.environ.get("MINICLOUD_SECRET") or "change_this_secret_for_prod"
os.makedirs(STORAGE_ROOT, exist_ok=True)
app = Flask(__name__)
app.secret_key = SECRET_KEY
# ---------------- Helpers ----------------
def now_iso():
    return datetime.datetime.utcnow().isoformat()
def hash_password(password, salt=None):
    if salt is None:
        salt = uuid.uuid4().hex
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${h}"
def verify_password(stored, password):
    try:
        salt, h = stored.split("$",1)
    except ValueError:
        return False
    return hash_password(password, salt) == stored
# ---------------- DB Utilities ----------------
USER_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

FILES_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER,
    owner_id INTEGER,
    is_dir INTEGER NOT NULL DEFAULT 0,
    size INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(parent_id, name, owner_id),
    FOREIGN KEY(parent_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    node_id INTEGER NOT NULL,
    owner_id INTEGER,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE SET NULL
);
"""
def get_user_db():
    db = getattr(g, "_user_db", None)
    if db is None:
        db = sqlite3.connect(str(USER_DB), detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
        g._user_db = db
    return db

def get_files_db():
    db = getattr(g, "_files_db", None)
    if db is None:
        db = sqlite3.connect(str(FILES_DB), detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
        g._files_db = db
    return db
@app.before_first_request
def init_dbs():
    # init user db
    udb = get_user_db()
    udb.executescript(USER_SCHEMA)
    udb.commit()
    # init files db
    fdb = get_files_db()
    fdb.executescript(FILES_SCHEMA)
    fdb.commit()
    # ensure root nodes per user is not created here; we'll treat root as parent_id NULL and owner_id set for uploaded nodes
@app.teardown_appcontext
def close_dbs(exc):
    udb = getattr(g, "_user_db", None)
    if udb is not None:
        udb.close()
    fdb = getattr(g, "_files_db", None)
    if fdb is not None:
        fdb.close()
# ---------------- Storage helpers ----------------
def node_path_on_disk(node_id):
    return STORAGE_ROOT / str(node_id)
def get_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_user_db()
    cur = db.execute("SELECT id, username FROM users WHERE id = ?", (uid,))
    return cur.fetchone()
# ---------------- Node operations ----------------
def resolve_path_to_node_for_user(path, owner_id):
    """
    path: "a/b/c" or "" for root (represented as None). Owner-aware: searches nodes with owner_id or owner_id IS NULL (shared root).
    For simplicity, treat root as parent_id IS NULL and name = '' and owner_id = owner_id.
    We'll create a virtual root per user if needed by ensuring a root node with parent_id IS NULL and owner_id = <owner_id>.
    """
    path = path.strip("/")
    fdb = get_files_db()
    # ensure user's root node exists
    cur = fdb.execute("SELECT id FROM nodes WHERE parent_id IS NULL AND owner_id = ?", (owner_id,))
    row = cur.fetchone()
    if not row:
        # create root node for user with empty name
        now = now_iso()
        cur = fdb.execute(
            "INSERT INTO nodes (name, parent_id, owner_id, is_dir, size, created_at) VALUES (?, ?, ?, 1, 0, ?)",
            ("", None, owner_id, now)
        )
        fdb.commit()
        root_id = cur.lastrowid
    else:
        root_id = row["id"]
    if not path:
        return get_node(root_id)
    current = root_id
    for part in [p for p in path.split("/") if p]:
        cur = fdb.execute(
            "SELECT * FROM nodes WHERE parent_id = ? AND name = ? AND owner_id = ?",
            (current, part, owner_id)
        )
        r = cur.fetchone()
        if not r:
            return None
        current = r["id"]
    return get_node(current)
def get_node(node_id):
    fdb = get_files_db()
    cur = fdb.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
    return cur.fetchone()
def list_children(node_id, owner_id):
    fdb = get_files_db()
    cur = fdb.execute(
        "SELECT * FROM nodes WHERE parent_id = ? AND owner_id = ? ORDER BY is_dir DESC, name ASC",
        (node_id, owner_id)
    )
    return cur.fetchall()
def create_dir(parent_id, owner_id, name):
    fdb = get_files_db()
    now = now_iso()
    try:
        cur = fdb.execute(
            "INSERT INTO nodes (name, parent_id, owner_id, is_dir, size, created_at) VALUES (?, ?, ?, 1, 0, ?)",
            (name, parent_id, owner_id, now)
        )
        fdb.commit()
        return get_node(cur.lastrowid)
    except sqlite3.IntegrityError:
        abort(400, "already exists")
def create_file(parent_id, owner_id, name, file_stream):
    fdb = get_files_db()
    now = now_iso()
    cur = fdb.cursor()
    try:
        cur.execute(
            "INSERT INTO nodes (name, parent_id, owner_id, is_dir, size, created_at) VALUES (?, ?, ?, 0, 0, ?)",
            (name, parent_id, owner_id, now)
        )
        nid = cur.lastrowid
        path = node_path_on_disk(nid)
        with open(path, "wb") as fd:
            data = file_stream.read()
            fd.write(data)
            size = len(data)
        cur.execute("UPDATE nodes SET size = ? WHERE id = ?", (size, nid))
        fdb.commit()
        return get_node(nid)
    except sqlite3.IntegrityError:
        abort(409, "already exists")
def delete_node_recursive(node_id):
    fdb = get_files_db()
    node = get_node(node_id)
    if not node:
        abort(404, "not found")
    if node["is_dir"] == 0:
        p = node_path_on_disk(node_id)
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    else:
        cur = fdb.execute("SELECT id FROM nodes WHERE parent_id = ?", (node_id,))
        rows = cur.fetchall()
        for r in rows:
            delete_node_recursive(r["id"])
    fdb.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    fdb.commit()
def create_share(node_id, owner_id, expires_in_seconds=None):
    fdb = get_files_db()
    token = uuid.uuid4().hex[:12]
    now = now_iso()
    expires_at = None
    if expires_in_seconds:
        expires_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in_seconds)).isoformat()
    fdb.execute(
        "INSERT INTO shares (token, node_id, owner_id, expires_at, created_at, active) VALUES (?, ?, ?, ?, ?, 1)",
        (token, node_id, owner_id, expires_at, now)
    )
    fdb.commit()
    return token, expires_at
def get_share(token):
    fdb = get_files_db()
    cur = fdb.execute("SELECT * FROM shares WHERE token = ? AND active = 1", (token,))
    row = cur.fetchone()
    if not row:
        return None
    if row["expires_at"]:
        if datetime.datetime.fromisoformat(row["expires_at"]) < datetime.datetime.utcnow():
            return None
    return row
def revoke_share(token, owner_id):
    fdb = get_files_db()
    cur = fdb.execute("SELECT * FROM shares WHERE token = ? AND owner_id = ?", (token, owner_id))
    row = cur.fetchone()
    if not row:
        abort(404, "share not found")
    fdb.execute("UPDATE shares SET active = 0 WHERE id = ?", (row["id"],))
    fdb.commit()
    return True
# ---------------- Auth endpoints ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template_string(REGISTER_HTML)
    data = request.form
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")
    if not username or not password:
        return "username and password required", 400
    udb = get_user_db()
    try:
        udb.execute(
            "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), now_iso())
        )
        udb.commit()
    except sqlite3.IntegrityError:
        return "username exists", 400
    return redirect(url_for("login"))
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(LOGIN_HTML)
    data = request.form
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "")
    udb = get_user_db()
    cur = udb.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    if not row or not verify_password(row["password"], password):
        return "invalid credentials", 400
    session["user_id"] = row["id"]
    session["username"] = row["username"]
    return redirect(url_for("index"))
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
# ---------------- Frontend HTML (Bootstrap 淡绿色主题) ----------------
BASE_CSS = """
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
:root{
  --bs-body-bg: #f6fffa;
  --bs-body-color: #0b3b2e;
  --accent: #7be3a8;
  --accent-dark: #49c077;
}
body{ background: var(--bs-body-bg); color: var(--bs-body-color); padding:20px; }
.navbar{ background: linear-gradient(90deg, #e9fbe9, #e0fff0); border-radius:8px; padding:12px; }
.btn-accent{ background: var(--accent); border-color: var(--accent-dark); color: #0b3b2e; }
.folder{ font-weight:600; color: var(--accent-dark); }
.item-row{ padding:8px 0; border-bottom:1px solid rgba(0,0,0,0.04); }
.small-muted{ color: rgba(0,0,0,0.45); font-size:0.9em; }
</style>
"""

INDEX_HTML = BASE_CSS + """
<div class="container">
  <div class="d-flex justify-content-between align-items-center navbar mb-3">
    <div><h4>Mini Cloud</h4></div>
    <div>
      {% if user %}
        <span class="me-2">Hi, <strong>{{user.username}}</strong></span>
        <a href="{{ url_for('logout') }}" class="btn btn-sm btn-outline-secondary">Logout</a>
      {% else %}
        <a href="{{ url_for('login') }}" class="btn btn-sm btn-outline-primary">Login</a>
        <a href="{{ url_for('register') }}" class="btn btn-sm btn-outline-success">Register</a>
      {% endif %}
    </div>
  </div>

  <div class="mb-2 d-flex gap-2">
    <div class="me-auto">
      <span id="cwd">/</span>
      <button class="btn btn-sm btn-outline-secondary" onclick="goUp()">Up</button>
    </div>
    <div>
      <input id="newfolder" class="form-control form-control-sm d-inline-block" style="width:200px" placeholder="New folder">
      <button class="btn btn-sm btn-accent" onclick="mkdir()">Create</button>
    </div>
  </div>

  <div class="mb-3">
    <input id="fileinput" type="file" multiple>
    <button class="btn btn-sm btn-accent" onclick="upload()">Upload</button>
  </div>

  <div id="list" class="card p-3"></div>

  <div class="mt-3 small-muted">Features: multi-file upload, download, delete, share & revoke. Shares can expire.</div>
</div>

<script>
let cwd = "";
function fmtPath(p){ return p?("/"+p):"/"; }
function api(path){
  return fetch(path).then(r=>{
    if(!r.ok) return r.json().then(e=>Promise.reject(e));
    return r.json();
  });
}
function load(path=""){
  fetch("/api/list?path="+encodeURIComponent(path)).then(r=>r.json()).then(data=>{
    cwd = data.path;
    document.getElementById("cwd").innerText = fmtPath(cwd);
    const list = document.getElementById("list");
    list.innerHTML = "";
    if(!data.items || data.items.length===0){ list.innerHTML="<i>empty</i>"; return; }
    data.items.forEach(it=>{
      const div = document.createElement("div");
      div.className="d-flex align-items-center item-row";
      const left = document.createElement("div");
      left.style.flex="1";
      const name = document.createElement("span");
      name.innerText = it.name;
      if(it.is_dir) name.className="folder";
      left.appendChild(name);
      const meta = document.createElement("div");
      meta.className="small-muted";
      meta.innerText = (it.is_dir? "Folder":"File") + (it.size? (" • " + it.size + " bytes") : "");
      left.appendChild(document.createElement("br"));
      left.appendChild(meta);
      div.appendChild(left);

      const btns = document.createElement("div");
      btns.className="d-flex gap-1";
      const openBtn = document.createElement("button");
      openBtn.className="btn btn-sm btn-outline-primary";
      openBtn.innerText = it.is_dir? "Open":"Download";
      openBtn.onclick = ()=>{ if(it.is_dir) openDir(it.name); else download(it.name); };
      btns.appendChild(openBtn);

      const delBtn = document.createElement("button");
      delBtn.className="btn btn-sm btn-outline-danger";
      delBtn.innerText="Delete";
      delBtn.onclick = ()=>{ if(confirm("Delete?")) deleteItem(it.name); };
      btns.appendChild(delBtn);

      const shareBtn = document.createElement("button");
      shareBtn.className="btn btn-sm btn-outline-success";
      shareBtn.innerText="Share";
      shareBtn.onclick = ()=> shareItem(it.name);
      btns.appendChild(shareBtn);

      const revokeBtn = document.createElement("button");
      revokeBtn.className="btn btn-sm btn-outline-secondary";
      revokeBtn.innerText="Revoke";
      revokeBtn.onclick = ()=> revokePrompt(it.name);
      btns.appendChild(revokeBtn);

      div.appendChild(btns);
      list.appendChild(div);
    });
  });
}
function openDir(name){
  const p = cwd? (cwd+"/"+name) : name;
  load(p);
}
function goUp(){
  if(!cwd) return;
  const parts = cwd.split("/");
  parts.pop();
  const np = parts.join("/");
  load(np);
}
function mkdir(){
  const name = document.getElementById("newfolder").value.trim();
  if(!name) return alert("name required");
  fetch("/api/mkdir", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({path:cwd, name})
  }).then(r=>r.json()).then(()=>{ document.getElementById("newfolder").value=""; load(cwd); }).catch(e=>alert(e.error||JSON.stringify(e)));
}
function upload(){
  const files = document.getElementById("fileinput").files;
  if(!files.length) return alert("select files");
  const form = new FormData();
  form.append("path", cwd);
  for(let f of files) form.append("files", f);
  fetch("/api/upload", {method:"POST", body: form}).then(r=>r.json()).then(()=>{ document.getElementById("fileinput").value=""; load(cwd); }).catch(e=>alert(e.error||JSON.stringify(e)));
}
function download(name){
  const p = cwd? (cwd+"/"+name) : name;
  window.location = "/api/download?path="+encodeURIComponent(p);
}
function deleteItem(name){
  const p = cwd? (cwd+"/"+name) : name;
  fetch("/api/delete", {
    method:"POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({path: p})
  }).then(r=>r.json()).then(()=> load(cwd));
}
function shareItem(name){
  const p = cwd? (cwd+"/"+name) : name;
  const exp = prompt("Share expires in seconds (empty = never):");
  let body = {path: p};
  if(exp) body.expires = parseInt(exp,10);
  fetch("/api/share/create", {
    method:"POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body)
  }).then(r=>r.json()).then(data=>{
    if(data.link) prompt("Share link:", data.link);
    else alert("error");
  });
}
function revokePrompt(name){
  const token = prompt("Enter share token to revoke (you can get token from share action):");
  if(!token) return;
  fetch("/api/share/revoke", {
    method:"POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({token: token})
  }).then(r=>r.json()).then(data=>{ alert("revoked"); }).catch(e=>alert("error"));
}
window.onload = ()=> load("");
</script>
"""

LOGIN_HTML = BASE_CSS + """
<div class="container">
  <div class="card p-3" style="max-width:480px; margin:30px auto;">
    <h4>Login</h4>
    <form method="post">
      <div class="mb-2">
        <label class="form-label">Username</label>
        <input name="username" class="form-control">
      </div>
      <div class="mb-2">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control">
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-accent">Login</button>
        <a href="{{ url_for('register') }}" class="btn btn-outline-secondary">Register</a>
      </div>
    </form>
  </div>
</div>
"""

REGISTER_HTML = BASE_CSS + """
<div class="container">
  <div class="card p-3" style="max-width:480px; margin:30px auto;">
    <h4>Register</h4>
    <form method="post">
      <div class="mb-2">
        <label class="form-label">Username</label>
        <input name="username" class="form-control">
      </div>
      <div class="mb-2">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control">
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-accent">Register</button>
        <a href="{{ url_for('login') }}" class="btn btn-outline-secondary">Login</a>
      </div>
    </form>
  </div>
</div>
"""

# ---------------- Routes: Main UI ----------------
@app.route("/")
def index():
    user = get_user()
    return render_template_string(INDEX_HTML, user=user)
# ---------------- API: file operations ----------------
@app.route("/api/list")
def api_list():
    user = get_user()
    if not user:
        return jsonify({"error":"login required"}), 401
    path = request.args.get("path", "").strip("/")
    node = resolve_path_to_node_for_user(path, user["id"])
    if node is None:
        return jsonify({"error":"not found"}), 404
    children = list_children(node["id"], user["id"])
    items = []
    for c in children:
        items.append({
            "id": c["id"],
            "name": c["name"],
            "is_dir": bool(c["is_dir"]),
            "size": c["size"],
            "created_at": c["created_at"]
        })
    return jsonify({"path": path, "items": items})
@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    user = get_user()
    if not user:
        return jsonify({"error":"login required"}), 401
    data = request.get_json() or {}
    path = (data.get("path") or "").strip("/")
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400
    parent = resolve_path_to_node_for_user(path, user["id"])
    if parent is None:
        return jsonify({"error":"parent not found"}), 404
    if parent["is_dir"] == 0:
        return jsonify({"error":"parent is not directory"}), 400
    nd = create_dir(parent["id"], user["id"], name)
    return jsonify({"ok": True, "id": nd["id"], "path": (path+"/"+name).strip("/")})
@app.route("/api/upload", methods=["POST"])
def api_upload():
    user = get_user()
    if not user:
        return jsonify({"error":"login required"}), 401
    path = request.form.get("path", "").strip("/")
    parent = resolve_path_to_node_for_user(path, user["id"])
    if parent is None:
        return jsonify({"error":"parent not found"}), 404
    if parent["is_dir"] == 0:
        return jsonify({"error":"parent is not directory"}), 400
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error":"no files"}), 400
    saved = []
    for f in files:
        name = f.filename or "unnamed"
        nd = create_file(parent["id"], user["id"], name, f.stream)
        saved.append({"id": nd["id"], "name": name})
    return jsonify({"ok": True, "saved": saved})
@app.route("/api/download")
def api_download():
    user = get_user()
    if not user:
        return "login required", 401
    path = request.args.get("path", "").strip("/")
    node = resolve_path_to_node_for_user(path, user["id"])
    if node is None:
        return jsonify({"error":"not found"}), 404
    if node["is_dir"]:
        return jsonify({"error":"is a directory"}), 400
    p = node_path_on_disk(node["id"])
    if not p.exists():
        return jsonify({"error":"file missing on disk"}), 500
    return send_file(str(p), as_attachment=True, download_name=node["name"])
@app.route("/api/delete", methods=["POST"])
def api_delete():
    user = get_user()
    if not user:
        return jsonify({"error":"login required"}), 401
    data = request.get_json() or {}
    path = (data.get("path") or "").strip("/")
    node = resolve_path_to_node_for_user(path, user["id"])
    if node is None:
        return jsonify({"error":"not found"}), 404
    delete_node_recursive(node["id"])
    return jsonify({"ok": True})
# ---------------- API: share create / revoke ----------------
@app.route("/api/share/create", methods=["POST"])
def api_share_create():
    user = get_user()
    if not user:
        return jsonify({"error":"login required"}), 401
    data = request.get_json() or {}
    path = (data.get("path") or "").strip("/")
    expires = data.get("expires")
    node = resolve_path_to_node_for_user(path, user["id"])
    if node is None:
        return jsonify({"error":"not found"}), 404
    token, expires_at = create_share(node["id"], user["id"], expires)
    link = url_for("share_access", token=token, _external=True)
    return jsonify({"ok": True, "token": token, "expires_at": expires_at, "link": link})
@app.route("/api/share/revoke", methods=["POST"])
def api_share_revoke():
    user = get_user()
    if not user:
        return jsonify({"error":"login required"}), 401
    data = request.get_json() or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"error":"token required"}), 400
    try:
        revoke_share(token, user["id"])
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})
@app.route("/s/<token>")
def share_access(token):
    sh = get_share(token)
    if not sh:
        abort(404, "share not found or expired")
    node = get_node(sh["node_id"])
    if not node:
        abort(404, "target missing")
    if node["is_dir"]:
        fdb = get_files_db()
        cur = fdb.execute("SELECT id, name, is_dir, size FROM nodes WHERE parent_id = ?", (node["id"],))
        rows = cur.fetchall()
        items = [{"id":r["id"], "name":r["name"], "is_dir":bool(r["is_dir"]), "size":r["size"]} for r in rows]
        return jsonify({"shared": True, "path": node["name"], "items": items})
    else:
        p = node_path_on_disk(node["id"])
        if not p.exists():
            abort(500, "file missing")
        return send_file(str(p), as_attachment=True, download_name=node["name"])
# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
