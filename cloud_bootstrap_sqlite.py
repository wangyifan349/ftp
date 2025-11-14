# cloud_bootstrap_sqlite.py
# Single-file Flask app (upper half)
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from urllib.parse import unquote
from functools import wraps
from flask import Flask, g, render_template_string, request, redirect, url_for, flash, send_from_directory, session
from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt
BASE_DIR = Path(__file__).parent.resolve()
DB_FILE = BASE_DIR / "users.sqlite"
STORAGE_ROOT = BASE_DIR / "storage"
MAX_CONTENT_LENGTH = 200 * 1024 * 1024
os.makedirs(STORAGE_ROOT, exist_ok=True)
app = Flask(__name__)
app.config['SECRET_KEY'] = "dev-secret-change-me"
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
bcrypt = Bcrypt(app)
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = sqlite3.connect(str(DB_FILE))
        db.row_factory = sqlite3.Row
        g._db = db
    return db
def init_db():
    db = get_db()
    db.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );
    """)
    db.commit()
@app.teardown_appcontext
def close_db(exception=None):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()
def allowed_file(filename):
    if not filename:
        return False
    return True
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
def get_user_by_id(user_id):
    db = get_db()
    cur = db.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
    return cur.fetchone()
def get_user_by_username(username):
    db = get_db()
    cur = db.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
    return cur.fetchone()
def user_base_path(username):
    p = STORAGE_ROOT / secure_filename(username)
    p.mkdir(parents=True, exist_ok=True)
    return p
def resolve_user_path(username, rel_path):
    base = user_base_path(username)
    rp = unquote(rel_path or "")
    candidate = (base / rp).resolve()
    try:
        candidate.relative_to(base.resolve())
    except Exception:
        return None, None
    norm_rel = rp.strip("/")
    return candidate, norm_rel
def list_directory(username, rel_path):
    target, norm = resolve_user_path(username, rel_path)
    if target is None or not target.exists():
        return []
    items = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        stat = p.stat()
        items.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": stat.st_size if p.is_file() else None,
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "rel": (f"{norm}/{p.name}" if norm else p.name)
        })
    return items
BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Mini Cloud</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-light">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">MiniCloud</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
        {% if user %}
          <li class="nav-item"><span class="nav-link">Hello, {{ user['username'] }}</span></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container my-4">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-warning">{{ messages[0] }}</div>
    {% endif %}
  {% endwith %}
  {{ body }}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

LOGIN_HTML = """
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>Login</h3>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      <button class="btn btn-primary">Login</button>
    </form>
  </div>
</div>
"""

REGISTER_HTML = """
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>Register</h3>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      <button class="btn btn-success">Register</button>
    </form>
  </div>
</div>
"""

DASHBOARD_HTML = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h3>File Manager</h3>
    <div class="text-muted small">User root: {{ user_dir }}</div>
  </div>
  <div>
    <nav aria-label="breadcrumb">
      <ol class="breadcrumb mb-0">
        <li class="breadcrumb-item"><a href="{{ url_for('index') }}">/</a></li>
        {% if cur_parts %}
          {% for i in range(cur_parts|length) %}
            {% set p = cur_parts[:i+1]|join('/') %}
            <li class="breadcrumb-item"><a href="{{ url_for('index', path=p) }}">{{ cur_parts[i] }}</a></li>
          {% endfor %}
        {% endif %}
      </ol>
    </nav>
  </div>
</div>

<div class="card mb-3">
  <div class="card-body">
    <form class="row g-2" action="{{ url_for('upload') }}" method="post" enctype="multipart/form-data">
      <div class="col-auto">
        <input type="file" name="file" class="form-control">
      </div>
      <input type="hidden" name="path" value="{{ cur_path }}">
      <div class="col-auto">
        <button class="btn btn-primary">Upload (max {{ max_mb }} MB)</button>
      </div>
      <div class="col-auto">
        <a class="btn btn-secondary" href="{{ url_for('mkdir') }}?path={{ cur_path }}">New Folder</a>
      </div>
    </form>
  </div>
</div>

<table class="table table-sm table-hover">
  <thead>
    <tr>
      <th>Name</th><th>Type</th><th>Size</th><th>Modified</th><th>Actions</th>
    </tr>
  </thead>
  <tbody>
    {% for item in files %}
      <tr>
        <td>
          {% if item.is_dir %}
            <a href="{{ url_for('index', path=item.rel) }}">📁 {{ item.name }}</a>
          {% else %}
            {{ item.name }}
          {% endif %}
        </td>
        <td>{{ 'Folder' if item.is_dir else 'File' }}</td>
        <td>{{ (item.size/1024)|round(2) if item.size else '' }}</td>
        <td>{{ item.mtime }}</td>
        <td>
          {% if not item.is_dir %}
            <a class="btn btn-sm btn-outline-primary" href="{{ url_for('download') }}?path={{ item.rel }}">Download</a>
          {% endif %}
          <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete') }}?path={{ item.rel }}" onclick="return confirm('Delete {{ item.name }}?')">Delete</a>
          <button class="btn btn-sm btn-outline-secondary" onclick="showMoveModal('{{ item.rel }}')">Move</button>
        </td>
      </tr>
    {% endfor %}
  </tbody>
</table>

<div class="modal fade" id="moveModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form id="moveForm" method="post" action="{{ url_for('move') }}" class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Move</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body">
        <input type="hidden" name="src" id="move_src">
        <div class="mb-3">
          <label class="form-label">Destination directory (relative to your root, empty = root)</label>
          <input name="dst" id="move_dst" class="form-control" placeholder="folder/subfolder">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" type="button" data-bs-dismiss="modal">Cancel</button>
        <button class="btn btn-primary" type="submit">Confirm Move</button>
      </div>
    </form>
  </div>
</div>

<script>
function showMoveModal(src) {
  var modal = new bootstrap.Modal(document.getElementById('moveModal'));
  document.getElementById('move_src').value = src;
  document.getElementById('move_dst').value = '';
  modal.show();
}
</script>
"""
@app.before_first_request
def startup():
    init_db()

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Username and password required")
            return redirect(url_for('register'))
        if get_user_by_username(username):
            flash("Username already exists")
            return redirect(url_for('register'))
        pw_hash = bcrypt.generate_password_hash(password).decode()
        db = get_db()
        try:
            db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Username already exists")
            return redirect(url_for('register'))
        user_base_path(username)
        flash("Registered. Please login.")
        return redirect(url_for('login'))
    user = get_user_by_id(session.get("user_id")) if session.get("user_id") else None
    return render_template_string(BASE_HTML.replace("{{ body }}", REGISTER_HTML), user=user)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_user_by_username(username)
        if not row or not bcrypt.check_password_hash(row["password_hash"], password):
            flash("Invalid username or password")
            return redirect(url_for('login'))
        session.clear()
        session["user_id"] = row["id"]
        flash("Logged in")
        return redirect(url_for('index'))
    user = get_user_by_id(session.get("user_id")) if session.get("user_id") else None
    return render_template_string(BASE_HTML.replace("{{ body }}", LOGIN_HTML), user=user)
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out")
    return redirect(url_for('login'))
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
@login_required
def index(path):
    user = get_user_by_id(session.get("user_id"))
    cur_path = path or ""
    parts = [p for p in cur_path.split("/") if p] if cur_path else []
    files = list_directory(user["username"], cur_path)
    return render_template_string(BASE_HTML.replace("{{ body }}", DASHBOARD_HTML),
                                  user=user,
                                  files=files,
                                  cur_path=cur_path,
                                  cur_parts=parts,
                                  max_mb=app.config['MAX_CONTENT_LENGTH'] // (1024*1024),
                                  user_dir=str(user_base_path(user["username"])))
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    user = get_user_by_id(session.get("user_id"))
    path = request.form.get("path", "") or ""
    target, norm = resolve_user_path(user["username"], path)
    if target is None:
        flash("Invalid path")
        return redirect(url_for('index'))
    if 'file' not in request.files:
        flash("No file selected")
        return redirect(url_for('index', path=path))
    file = request.files['file']
    if not file or file.filename == "":
        flash("No file selected")
        return redirect(url_for('index', path=path))
    filename = secure_filename(file.filename)
    save_path = target / filename
    if save_path.exists():
        base, ext = os.path.splitext(filename)
        filename = f"{base}_{int(datetime.utcnow().timestamp())}{ext}"
        save_path = target / filename
    try:
        file.save(save_path)
        flash("Uploaded")
    except Exception as e:
        flash(f"Upload failed: {e}")
    return redirect(url_for('index', path=path))
@app.route("/mkdir", methods=["GET", "POST"])
@login_required
def mkdir():
    user = get_user_by_id(session.get("user_id"))
    if request.method == "GET":
        path = request.args.get("path", "") or ""
        body = f'''
        <h3>New Folder</h3>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">Folder name</label>
            <input name="dirname" class="form-control" required>
            <input type="hidden" name="path" value="{path}">
          </div>
          <button class="btn btn-primary">Create</button>
        </form>
        '''
        return render_template_string(BASE_HTML.replace("{{ body }}", body), user=user)
    dirname = (request.form.get("dirname") or "").strip()
    path = request.form.get("path", "") or ""
    if not dirname:
        flash("Folder name required")
        return redirect(url_for('index', path=path))
    target, norm = resolve_user_path(user["username"], path)
    if target is None:
        flash("Invalid path")
        return redirect(url_for('index'))
    new_dir = target / secure_filename(dirname)
    try:
        new_dir.mkdir(parents=False, exist_ok=False)
        flash("Folder created")
    except FileExistsError:
        flash("Folder or file already exists with that name")
    except Exception as e:
        flash(f"Create failed: {e}")
    return redirect(url_for('index', path=path))
@app.route("/download")
@login_required
def download():
    user = get_user_by_id(session.get("user_id"))
    path = request.args.get("path", "") or ""
    target, norm = resolve_user_path(user["username"], path)
    if target is None or not target.exists() or target.is_dir():
        flash("File not found or not downloadable")
        parent = os.path.dirname(norm) if norm else ""
        return redirect(url_for('index', path=parent))
    return send_from_directory(str(target.parent), target.name, as_attachment=True)
@app.route("/delete")
@login_required
def delete():
    user = get_user_by_id(session.get("user_id"))
    path = request.args.get("path", "") or ""
    target, norm = resolve_user_path(user["username"], path)
    parent = os.path.dirname(norm) if norm else ""
    if target is None or not target.exists():
        flash("Target does not exist")
        return redirect(url_for('index', path=parent))
    try:
        if target.is_dir():
            if any(target.iterdir()):
                flash("Directory not empty, cannot delete")
            else:
                target.rmdir()
                flash("Directory deleted")
        else:
            target.unlink()
            flash("File deleted")
    except Exception as e:
        flash(f"Delete failed: {e}")
    return redirect(url_for('index', path=parent))
@app.route("/move", methods=["POST"])
@login_required
def move():
    user = get_user_by_id(session.get("user_id"))
    src = request.form.get("src", "") or ""
    dst = request.form.get("dst", "") or ""
    src_target, src_norm = resolve_user_path(user["username"], src)
    if src_target is None or not src_target.exists():
        flash("Source not found")
        return redirect(url_for('index'))
    dst_target, dst_norm = resolve_user_path(user["username"], dst)
    if dst_target is None:
        flash("Invalid destination")
        return redirect(url_for('index'))
    try:
        dst_target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        flash(f"Cannot prepare destination: {e}")
        return redirect(url_for('index'))
    new_name = src_target.name
    dest_path = dst_target / new_name
    if dest_path.exists():
        base, ext = os.path.splitext(new_name)
        new_name = f"{base}_{int(datetime.utcnow().timestamp())}{ext}"
        dest_path = dst_target / new_name
    try:
        src_target.replace(dest_path)
        flash("Moved successfully")
    except Exception as e:
        flash(f"Move failed: {e}")
    return redirect(url_for('index', path=dst_norm))
if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
