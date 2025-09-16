# app.py
import os
from pathlib import Path
import sqlite3
from datetime import datetime
from functools import wraps
from typing import Optional, Dict, Any
from flask import (
    Flask, g, request, session, redirect, url_for,
    render_template_string, send_from_directory, jsonify, abort, flash
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from urllib.parse import urljoin
# ---------------------------
# Configuration
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "uploads"
DATABASE_PATH = BASE_DIR / "file_manager.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB total per request (adjust as needed)
ALLOWED_EXTENSIONS = None  # set to set([...]) to restrict types
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SEND_FILE_MAX_AGE_DEFAULT=0,
)
# ---------------------------
# Database helpers
# ---------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        g._database = conn
    return g._database

def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            parent_id INTEGER,
            name TEXT NOT NULL,
            is_directory INTEGER NOT NULL DEFAULT 1,
            stored_path TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(parent_id) REFERENCES nodes(id)
        );
        CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            FOREIGN KEY(node_id) REFERENCES nodes(id),
            FOREIGN KEY(owner_id) REFERENCES users(id)
        );
        """
    )
    db.commit()

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ---------------------------
# Auth helpers
# ---------------------------
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view

def get_current_user() -> Optional[sqlite3.Row]:
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

# ---------------------------
# Node / storage helpers
# ---------------------------
def create_user_root_if_missing(user_id: int) -> int:
    db = get_db()
    root = db.execute("SELECT id FROM nodes WHERE user_id = ? AND parent_id IS NULL", (user_id,)).fetchone()
    if root:
        return root["id"]
    now = datetime.utcnow().isoformat()
    cur = db.execute(
        "INSERT INTO nodes (user_id, parent_id, name, is_directory, created_at) VALUES (?, NULL, ?, 1, ?)",
        (user_id, "/", now),
    )
    db.commit()
    return cur.lastrowid

def list_children(user_id: int, parent_id: int):
    db = get_db()
    return db.execute(
        "SELECT * FROM nodes WHERE user_id = ? AND parent_id = ? ORDER BY is_directory DESC, name COLLATE NOCASE ASC",
        (user_id, parent_id),
    ).fetchall()

def build_user_storage_path(user_id: int, stored_path: str) -> Path:
    user_dir = UPLOAD_ROOT / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    full_path = user_dir / stored_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    return full_path

def safe_name(filename: str) -> str:
    return secure_filename(filename)

def is_allowed_file(filename: str) -> bool:
    if ALLOWED_EXTENSIONS is None:
        return True
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
def get_ancestors(user_id: int, node_id: int):
    db = get_db()
    ancestors = []
    current = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user_id)).fetchone()
    if not current:
        return ancestors
    ancestors.insert(0, dict(current))
    while current and current["parent_id"] is not None:
        current = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (current["parent_id"], user_id)).fetchone()
        if current:
            ancestors.insert(0, dict(current))
    return ancestors
# ---------------------------
# Share helpers
# ---------------------------
def generate_share_token(length=32):
    return secrets.token_urlsafe(length)
def get_share_by_node(user_id: int, node_id: int):
    db = get_db()
    return db.execute("SELECT * FROM shares WHERE node_id = ? AND owner_id = ?", (node_id, user_id)).fetchone()
def get_share_by_token(token: str):
    db = get_db()
    return db.execute("SELECT * FROM shares WHERE token = ?", (token,)).fetchone()
def build_share_url(token: str):
    base = request.host_url if request else ""
    return urljoin(base, f"s/{token}")
# ---------------------------
# Templates (inline, enhanced Bootstrap UI)
# ---------------------------
BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>File Manager</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
    <style>
      body { background: #f7f9fc; }
      .card-file { transition: box-shadow .12s ease; }
      .card-file:hover { box-shadow: 0 4px 18px rgba(13,110,253,0.08); }
      .file-icon { font-size: 1.25rem; }
      .drop-target { border: 2px dashed transparent; border-radius: 6px; transition: background .12s ease, border-color .12s ease; padding: .5rem; }
      .drop-target.over { background: #eef6ff; border-color: #0d6efd; }
      .breadcrumb a { text-decoration: none; }
      .multi-upload-list { max-height: 160px; overflow:auto; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
      <div class="container">
        <a class="navbar-brand d-flex align-items-center" href="{{ url_for('index') }}">
          <i class="bi bi-folder2-open me-2"></i> File Manager
        </a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav ms-auto">
            {% if user %}
              <li class="nav-item"><a class="nav-link" href="#"> <i class="bi bi-person-circle"></i> {{ user['username'] }}</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('shares') }}">My Shares</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}"> <i class="bi bi-box-arrow-right"></i> Logout</a></li>
            {% else %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
            {% endif %}
          </ul>
        </div>
      </div>
    </nav>

    <div class="container mb-5">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="alert alert-info">{{ messages[0] }}</div>
        {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

INDEX_HTML = """
{% extends base %}
{% block content %}
<div class="row">
  <div class="col-lg-4">
    <div class="card mb-3">
      <div class="card-body">
        <h5 class="card-title"><i class="bi bi-cloud-arrow-up-fill me-2"></i> Upload Files</h5>
        <form id="uploadForm" method="post" action="{{ url_for('upload', parent_id=current_node['id']) }}" enctype="multipart/form-data">
          <div class="mb-3">
            <input class="form-control" type="file" name="files" id="fileInput" multiple>
          </div>
          <div class="mb-2">
            <button class="btn btn-primary me-2"><i class="bi bi-upload"></i> Upload</button>
            <button type="button" class="btn btn-outline-secondary" onclick="document.getElementById('fileInput').value=null"><i class="bi bi-x-circle"></i> Clear</button>
          </div>
          <div class="multi-upload-list list-group mt-2" id="fileList"></div>
        </form>

        <hr>

        <h6 class="mt-3"><i class="bi bi-folder-plus me-2"></i> New Folder</h6>
        <form id="mkdirForm" method="post" action="{{ url_for('mkdir', parent_id=current_node['id']) }}">
          <div class="input-group">
            <input class="form-control" name="name" placeholder="Folder name" required>
            <button class="btn btn-outline-primary">Create</button>
          </div>
        </form>

        <hr>

        <div class="mt-3 small text-muted">
          Tips: Drag items from the file list and drop onto a folder target to move them. You can upload multiple files at once.
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-body">
        <h6 class="card-title"><i class="bi bi-info-circle-fill me-2"></i> Summary</h6>
        <p class="mb-1">Current folder: <strong>{{ current_node['name'] }}</strong></p>
        <p class="mb-0">Items: <strong>{{ children|length }}</strong></p>
      </div>
    </div>
  </div>

  <div class="col-lg-8">
    <div class="card mb-3">
      <div class="card-body">
        <nav aria-label="breadcrumb">
          <ol class="breadcrumb mb-3">
            {% for anc in ancestors %}
              <li class="breadcrumb-item"><a href="{{ url_for('index', node_id=anc['id']) }}">{{ anc['name'] }}</a></li>
            {% endfor %}
            <li class="breadcrumb-item active" aria-current="page">{{ current_node['name'] }}</li>
          </ol>
        </nav>

        <div class="row g-3" id="itemsGrid">
          {% for item in children %}
            <div class="col-12">
              <div class="card card-file d-flex align-items-center p-2" draggable="true"
                   data-id="{{ item['id'] }}" data-is-dir="{{ 1 if item['is_directory'] else 0 }}">
                <div class="d-flex w-100 align-items-center">
                  <div class="me-3 file-icon">
                    {% if item['is_directory'] %}
                      <i class="bi bi-folder2-fill text-warning fs-3"></i>
                    {% else %}
                      <i class="bi bi-file-earmark-fill text-secondary fs-3"></i>
                    {% endif %}
                  </div>
                  <div class="flex-grow-1">
                    <div class="d-flex justify-content-between">
                      <div>
                        {% if item['is_directory'] %}
                          <a class="h6 mb-0" href="{{ url_for('index', node_id=item['id']) }}">{{ item['name'] }}</a>
                        {% else %}
                          <a class="h6 mb-0" href="{{ url_for('download', node_id=item['id']) }}">{{ item['name'] }}</a>
                        {% endif %}
                        <div class="small text-muted">Created: {{ item['created_at'] }}</div>
                      </div>
                      <div class="btn-group">
                        <button class="btn btn-sm btn-outline-secondary" onclick="renameItem({{ item['id'] }})"><i class="bi bi-pencil"></i></button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteItem({{ item['id'] }})"><i class="bi bi-trash"></i></button>
                        {% if item['is_directory'] %}
                          <button class="btn btn-sm btn-outline-success" id="share-btn-{{ item['id'] }}" onclick="toggleShare({{ item['id'] }})"><i class="bi bi-share"></i></button>
                        {% endif %}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          {% else %}
            <div class="col-12">
              <div class="p-4 text-center text-muted">This folder is empty.</div>
            </div>
          {% endfor %}
        </div>

        <hr>

        <h6>Move Targets</h6>
        <div class="row g-2" id="dropTargets">
          {% for item in children if item['is_directory'] %}
            <div class="col-6">
              <div class="drop-target bg-white" data-target-id="{{ item['id'] }}">
                <i class="bi bi-folder-fill text-warning me-2"></i> {{ item['name'] }}
              </div>
            </div>
          {% endfor %}
          <div class="col-6">
            <div class="drop-target bg-white" data-target-id="{{ current_node['id'] }}">
              <i class="bi bi-folder2-open me-2"></i> Current: {{ current_node['name'] }}
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</div>

<script>
// Multiple file list preview
const fileInput = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');
fileInput?.addEventListener('change', () => {
  fileList.innerHTML = '';
  for (const f of fileInput.files) {
    const el = document.createElement('div');
    el.className = 'list-group-item d-flex justify-content-between align-items-center';
    el.textContent = `${f.name} (${Math.round(f.size/1024)} KB)`;
    fileList.appendChild(el);
  }
});

// Drag & Drop logic
let draggingId = null;
let draggingIsDir = 0;

document.querySelectorAll('[draggable="true"]').forEach(el=>{
  el.addEventListener('dragstart', e=>{
    draggingId = el.dataset.id;
    draggingIsDir = el.dataset.isDir;
    e.dataTransfer.setData('text/plain', draggingId);
    e.dataTransfer.effectAllowed = 'move';
  });
});

function setOverClass(el, yes) {
  if (yes) el.classList.add('over'); else el.classList.remove('over');
}

document.querySelectorAll('.drop-target').forEach(target=>{
  target.addEventListener('dragover', e=>{ e.preventDefault(); setOverClass(target, true); });
  target.addEventListener('dragleave', e=>{ setOverClass(target, false); });
  target.addEventListener('drop', async e=>{
    e.preventDefault(); setOverClass(target, false);
    const targetId = parseInt(target.dataset.targetId);
    if (!draggingId) return;
    const res = await fetch('{{ url_for("move_node_api") }}', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ node_id: parseInt(draggingId), new_parent: targetId })
    });
    const j = await res.json();
    if (j.success) location.reload(); else alert('Move failed: ' + (j.error || 'Unknown'));
  });
});

// Delete & Rename functions
async function deleteItem(id) {
  if (!confirm('Confirm delete? This action cannot be undone.')) return;
  const res = await fetch('{{ url_for("delete_node_api") }}', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ node_id: id })
  });
  const j = await res.json();
  if (j.success) location.reload(); else alert('Delete failed: ' + (j.error || ''));
}

async function renameItem(id) {
  const newName = prompt('Enter new name:');
  if (!newName) return;
  const res = await fetch('{{ url_for("rename_node_api") }}', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ node_id: id, new_name: newName })
  });
  const j = await res.json();
  if (j.success) location.reload(); else alert('Rename failed: ' + (j.error || ''));
}

// Share toggle: attempt to create share; response includes token if created or existing
async function toggleShare(id) {
  const res = await fetch('{{ url_for("share_node", node_id=0) }}'.replace('/0','/'+id), { method: 'POST' });
  const j = await res.json();
  if (!j.success) {
    alert('Share failed: ' + (j.error || 'Unknown'));
    return;
  }
  if (j.token) {
    const openNow = confirm('Share created. Open share URL?\\n' + j.url + '\\n\\nPress Cancel to manage (you can cancel share).');
    if (openNow) {
      window.open(j.url, '_blank');
      return;
    }
    if (confirm('Cancel this share?')) {
      const r2 = await fetch('{{ url_for("unshare_node", node_id=0) }}'.replace('/0','/'+id), { method: 'POST' });
      const j2 = await r2.json();
      if (j2.success) location.reload(); else alert('Unshare failed: ' + (j2.error||''));
    }
  } else {
    alert('Share created');
  }
}
</script>
{% endblock %}
"""

AUTH_HTML = """
{% extends base %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="mb-3">{{ title }}</h4>
        <form method="post" class="mb-0">
          <div class="mb-3">
            <label class="form-label">Username</label>
            <input class="form-control" name="username" required>
          </div>
          <div class="mb-3">
            <label class="form-label">Password</label>
            <input class="form-control" name="password" type="password" required>
          </div>
          <button class="btn btn-primary">{{ button_text }}</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

# ---------------------------
# Routes
# ---------------------------
@app.route("/")
@login_required
def index():
    db = get_db()
    user = get_current_user()
    node_id = request.args.get("node_id", type=int)
    if node_id is None:
        node_id = create_user_root_if_missing(user["id"])
    # validate node ownership
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user["id"])).fetchone()
    if not node:
        abort(404, "Node not found or no permission")
    children = list_children(user["id"], node_id)
    ancestors = get_ancestors(user["id"], node_id)
    return render_template_string(INDEX_HTML, base=BASE_HTML, user=user, current_node=node, children=children, ancestors=ancestors)

@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Missing username or password")
            return render_template_string(AUTH_HTML, base=BASE_HTML, title="Register", button_text="Register")
        password_hash = generate_password_hash(password, method="pbkdf2:sha512:260000")
        now = datetime.utcnow().isoformat()
        try:
            cur = db.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, now),
            )
            db.commit()
            user_id = cur.lastrowid
            create_user_root_if_missing(user_id)
            session["user_id"] = user_id
            return redirect(url_for("index"))
        except sqlite3.IntegrityError:
            flash("Username already exists")
    return render_template_string(AUTH_HTML, base=BASE_HTML, title="Register", button_text="Register")

@app.route("/login", methods=["GET", "POST"])
def login():
    db = get_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            flash("Invalid username or password")
            return render_template_string(AUTH_HTML, base=BASE_HTML, title="Login", button_text="Login")
        session["user_id"] = row["id"]
        return redirect(url_for("index"))
    return render_template_string(AUTH_HTML, base=BASE_HTML, title="Login", button_text="Login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/upload/<int:parent_id>", methods=["POST"])
@login_required
def upload(parent_id: int):
    user = get_current_user()
    db = get_db()
    parent = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (parent_id, user["id"])).fetchone()
    if not parent:
        abort(404)
    files = request.files.getlist("files")
    if not files:
        flash("No files selected")
        return redirect(url_for("index", node_id=parent_id))
    for uploaded in files:
        if uploaded and uploaded.filename:
            filename = safe_name(uploaded.filename)
            if not is_allowed_file(filename):
                flash(f"File type not allowed: {filename}")
                continue
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            stored_name = f"{parent_id}_{timestamp}_{filename}"
            disk_path = build_user_storage_path(user["id"], stored_name)
            uploaded.save(str(disk_path))
            db.execute(
                "INSERT INTO nodes (user_id, parent_id, name, is_directory, stored_path, created_at) VALUES (?, ?, ?, 0, ?, ?)",
                (user["id"], parent_id, filename, stored_name, datetime.utcnow().isoformat())
            )
    db.commit()
    return redirect(url_for("index", node_id=parent_id))

@app.route("/mkdir/<int:parent_id>", methods=["POST"])
@login_required
def mkdir(parent_id: int):
    user = get_current_user()
    db = get_db()
    parent = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (parent_id, user["id"])).fetchone()
    if not parent:
        abort(404)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Folder name required")
        return redirect(url_for("index", node_id=parent_id))
    name = safe_name(name)
    db.execute(
        "INSERT INTO nodes (user_id, parent_id, name, is_directory, created_at) VALUES (?, ?, ?, 1, ?)",
        (user["id"], parent_id, name, datetime.utcnow().isoformat())
    )
    db.commit()
    return redirect(url_for("index", node_id=parent_id))

@app.route("/download/<int:node_id>")
@login_required
def download(node_id: int):
    user = get_current_user()
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user["id"])).fetchone()
    if not node or node["is_directory"]:
        abort(404)
    stored = node["stored_path"]
    file_path = build_user_storage_path(user["id"], stored)
    if not file_path.exists():
        abort(404, "File not found")
    # send_from_directory with download_name for proper filename
    return send_from_directory(directory=str(file_path.parent), path=file_path.name, as_attachment=True, download_name=node["name"])
# API: move node
@app.route("/api/move", methods=["POST"])
@login_required
def move_node_api():
    user = get_current_user()
    data: Dict[str, Any] = request.get_json() or {}
    node_id = data.get("node_id")
    new_parent = data.get("new_parent")
    if node_id is None or new_parent is None:
        return jsonify({"success": False, "error": "Missing parameters"})
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user["id"])).fetchone()
    target = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (new_parent, user["id"])).fetchone()
    if not node or not target:
        return jsonify({"success": False, "error": "Node not found or no permission"})
    if not target["is_directory"]:
        return jsonify({"success": False, "error": "Target must be a directory"})
    # prevent moving a directory into its descendant
    if node["is_directory"]:
        cur = target
        while cur:
            if cur["id"] == node["id"]:
                return jsonify({"success": False, "error": "Cannot move directory into its descendant"})
            cur = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (cur["parent_id"], user["id"])).fetchone() if cur["parent_id"] else None
    db.execute("UPDATE nodes SET parent_id = ? WHERE id = ? AND user_id = ?", (new_parent, node_id, user["id"]))
    db.commit()
    return jsonify({"success": True})
# API: delete node (recursive)
@app.route("/api/delete", methods=["POST"])
@login_required
def delete_node_api():
    user = get_current_user()
    data = request.get_json() or {}
    node_id = data.get("node_id")
    if node_id is None:
        return jsonify({"success": False, "error": "Missing node_id"})
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user["id"])).fetchone()
    if not node:
        return jsonify({"success": False, "error": "Node not found"})
    def _delete_recursive(nid: int):
        children = db.execute("SELECT * FROM nodes WHERE parent_id = ? AND user_id = ?", (nid, user["id"])).fetchall()
        for c in children:
            _delete_recursive(c["id"])
        row = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (nid, user["id"])).fetchone()
        if row and not row["is_directory"] and row["stored_path"]:
            p = build_user_storage_path(user["id"], row["stored_path"])
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        db.execute("DELETE FROM nodes WHERE id = ? AND user_id = ?", (nid, user["id"]))
    _delete_recursive(node_id)
    db.commit()
    return jsonify({"success": True})
# API: rename node
@app.route("/api/rename", methods=["POST"])
@login_required
def rename_node_api():
    user = get_current_user()
    data = request.get_json() or {}
    node_id = data.get("node_id")
    new_name = (data.get("new_name") or "").strip()
    if node_id is None or not new_name:
        return jsonify({"success": False, "error": "Missing parameters"})
    new_name = safe_name(new_name)
    db = get_db()
    db.execute("UPDATE nodes SET name = ? WHERE id = ? AND user_id = ?", (new_name, node_id, user["id"]))
    db.commit()
    return jsonify({"success": True})
# ---------------------------
# Share routes
# ---------------------------
@app.route("/share/<int:node_id>", methods=["POST"])
@login_required
def share_node(node_id: int):
    user = get_current_user()
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, user["id"])).fetchone()
    if not node:
        return jsonify({"success": False, "error": "Node not found"}), 404
    if not node["is_directory"]:
        return jsonify({"success": False, "error": "Only directories can be shared"}), 400
    existing = get_share_by_node(user["id"], node_id)
    if existing:
        return jsonify({"success": True, "token": existing["token"], "url": build_share_url(existing["token"])})
    token = generate_share_token()
    now = datetime.utcnow().isoformat()
    db.execute("INSERT INTO shares (node_id, owner_id, token, created_at) VALUES (?, ?, ?, ?)",
               (node_id, user["id"], token, now))
    db.commit()
    return jsonify({"success": True, "token": token, "url": build_share_url(token)})
@app.route("/unshare/<int:node_id>", methods=["POST"])
@login_required
def unshare_node(node_id: int):
    user = get_current_user()
    db = get_db()
    existing = get_share_by_node(user["id"], node_id)
    if not existing:
        return jsonify({"success": False, "error": "Not shared"}), 404
    db.execute("DELETE FROM shares WHERE id = ? AND owner_id = ?", (existing["id"], user["id"]))
    db.commit()
    return jsonify({"success": True})
@app.route("/shares")
@login_required
def list_shares():
    user = get_current_user()
    db = get_db()
    shares = db.execute(
        "SELECT s.*, n.name AS node_name FROM shares s JOIN nodes n ON s.node_id = n.id WHERE s.owner_id = ? ORDER BY s.created_at DESC",
        (user["id"],)
    ).fetchall()
    # Simple management page
    html = """
    {% extends base %}
    {% block content %}
    <div class="row">
      <div class="col-md-8 offset-md-2">
        <div class="card">
          <div class="card-body">
            <h5>My Shares</h5>
            {% if shares %}
              <ul class="list-group">
                {% for s in shares %}
                  <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                      <div><strong>{{ s['node_name'] }}</strong> (id: {{ s['node_id'] }})</div>
                      <div class="small text-muted">Created: {{ s['created_at'] }}</div>
                      <div><a href="{{ url_for('shared_view', token=s['token']) }}" target="_blank">{{ request.host_url }}s/{{ s['token'] }}</a></div>
                    </div>
                    <div>
                      <button class="btn btn-sm btn-outline-danger" onclick="unshare({{ s['node_id'] }})">Unshare</button>
                    </div>
                  </li>
                {% endfor %}
              </ul>
            {% else %}
              <div class="text-muted">You have not shared any directories.</div>
            {% endif %}
          </div>
        </div>
      </div>
    </div>

    <script>
    async function unshare(nodeId) {
      if (!confirm('Cancel share?')) return;
      const res = await fetch('{{ url_for("unshare_node", node_id=0) }}'.replace('/0','/'+nodeId), { method: 'POST' });
      const j = await res.json();
      if (j.success) location.reload(); else alert('Failed: '+(j.error||''));
    }
    </script>
    {% endblock %}
    """
    return render_template_string(html, base=BASE_HTML, shares=shares)
@app.route("/s/<token>")
def shared_view(token):
    db = get_db()
    share = get_share_by_token(token)
    if not share:
        abort(404)
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (share["node_id"], share["owner_id"])).fetchone()
    if not node:
        abort(404)
    children = db.execute(
        "SELECT * FROM nodes WHERE parent_id = ? AND user_id = ? ORDER BY is_directory DESC, name COLLATE NOCASE ASC",
        (node["id"], share["owner_id"])
    ).fetchall()
    html = """
    {% extends base %}
    {% block content %}
    <div class="row">
      <div class="col-12">
        <div class="card mb-3">
          <div class="card-body">
            <h5>Shared: {{ node['name'] }}</h5>
            <div class="small text-muted">Shared by user id {{ share['owner_id'] }}</div>
            <div class="row g-3 mt-3">
              {% for item in children %}
                <div class="col-12">
                  <div class="card p-2">
                    <div class="d-flex justify-content-between">
                      <div>
                        {% if item['is_directory'] %}
                          <i class="bi bi-folder2-fill text-warning me-2"></i>
                          <span>{{ item['name'] }}</span>
                        {% else %}
                          <i class="bi bi-file-earmark-fill text-secondary me-2"></i>
                          <a href="{{ url_for('shared_download', token=share['token'], node_id=item['id']) }}">{{ item['name'] }}</a>
                        {% endif %}
                        <div class="small text-muted">Created: {{ item['created_at'] }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              {% else %}
                <div class="col-12 text-muted">This folder is empty.</div>
              {% endfor %}
            </div>
          </div>
        </div>
      </div>
    </div>
    {% endblock %}
    """
    return render_template_string(html, base=BASE_HTML, node=node, children=children, share=share)
@app.route("/s/<token>/download/<int:node_id>")
def shared_download(token, node_id: int):
    db = get_db()
    share = get_share_by_token(token)
    if not share:
        abort(404)
    node = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (node_id, share["owner_id"])).fetchone()
    if not node or node["is_directory"]:
        abort(404)
    # ensure node is descendant of share.node_id or equal
    cur = node
    is_descendant = False
    while cur:
        if cur["id"] == share["node_id"]:
            is_descendant = True
            break
        if not cur["parent_id"]:
            break
        cur = db.execute("SELECT * FROM nodes WHERE id = ? AND user_id = ?", (cur["parent_id"], share["owner_id"])).fetchone()
    if not is_descendant:
        abort(404)
    stored = node["stored_path"]
    file_path = build_user_storage_path(share["owner_id"], stored)
    if not file_path.exists():
        abort(404)
    return send_from_directory(directory=str(file_path.parent), path=file_path.name, as_attachment=True, download_name=node["name"])
@app.route("/status")
def status():
    return "OK"
# ---------------------------
# Initialize and run
# ---------------------------
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=False, host="0.0.0.0", port=5000)
