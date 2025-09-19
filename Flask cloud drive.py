# app.py — Flask cloud drive with auth, SQLite, multi-upload, share/unshare (single file)
import os
import sqlite3
import secrets
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, g, render_template_string, request, redirect, url_for,
    flash, session, send_from_directory, jsonify, abort
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import functools
# --- Config ---
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "cloud.db"
ALLOWED_EXT = None  # None = allow all, or set to {"png","jpg","pdf"} etc.
MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GB per request
SECRET_KEY = os.environ.get("CLOUD_SECRET") or "dev-secret-change-me"
UPLOAD_FOLDER.mkdir(exist_ok=True, parents=True)
app = Flask(__name__)
app.config.update(
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    DATABASE=str(DB_PATH),
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SECRET_KEY=SECRET_KEY,
)
# --- DB helpers ---
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        need_init = not Path(app.config["DATABASE"]).exists()
        db = g._database = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        if need_init:
            _init_db_conn(db)
    return db
def _init_db_conn(db_conn):
    schema = """
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password TEXT NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS files (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      filename TEXT NOT NULL,
      stored_name TEXT NOT NULL,
      uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      shared_token TEXT DEFAULT NULL,
      is_public INTEGER DEFAULT 0,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id);
    CREATE INDEX IF NOT EXISTS idx_files_token ON files(shared_token);
    """
    db_conn.executescript(schema)
    db_conn.commit()
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()
def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv
def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid
# --- Auth / helpers ---
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view
def allowed(filename):
    if ALLOWED_EXT is None:
        return True
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT
def generate_token():
    return secrets.token_urlsafe(24)
# --- Templates as strings ---
layout_t = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{{ title or "Cloud Drive" }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <style>
    .dropzone { border: 2px dashed #6c757d; border-radius:8px; padding:18px; text-align:center; transition:background 0.15s;}
    .dropzone.dragover { background:#e9f5ff; }
    .small-code { font-family: monospace; font-size:0.9rem; background:#f8f9fa; padding:4px 8px; border-radius:4px; }
  </style>
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-light bg-white border-bottom">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">CloudDrive</a>
    <div>
      {% if session.get('username') %}
        <span class="me-2">Signed in as <strong>{{ session.username }}</strong></span>
        <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('logout') }}">Logout</a>
      {% else %}
        <a class="btn btn-outline-primary btn-sm me-2" href="{{ url_for('login') }}">Login</a>
        <a class="btn btn-primary btn-sm" href="{{ url_for('register') }}">Register</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container py-4">
  {% with messages = get_flashed_messages() %}
  {% if messages %}
    <div class="mb-3">
      {% for msg in messages %}
        <div class="alert alert-info">{{ msg }}</div>
      {% endfor %}
    </div>
  {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
</body>
</html>
"""
register_t = """
{% extends "layout" %}
{% block content %}
<h2>Register</h2>
<form method="post" class="w-50">
  <div class="mb-3">
    <label class="form-label">Username</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="mb-3">
    <label class="form-label">Password</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  <button class="btn btn-primary" type="submit">Register</button>
</form>
{% endblock %}
"""

login_t = """
{% extends "layout" %}
{% block content %}
<h2>Login</h2>
<form method="post" class="w-50">
  <div class="mb-3">
    <label class="form-label">Username</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="mb-3">
    <label class="form-label">Password</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  <button class="btn btn-primary" type="submit">Login</button>
</form>
{% endblock %}
"""

index_t = """
{% extends "layout" %}
{% block content %}
<h2>Your Files</h2>

<div class="mb-3">
  <form id="uploadForm" method="post" action="{{ url_for('upload') }}" enctype="multipart/form-data">
    <div id="dropzone" class="dropzone mb-2">
      <p class="mb-2">Drag & drop files here or click to select</p>
      <input id="fileInput" name="files[]" type="file" multiple style="display:none;">
      <button type="button" class="btn btn-outline-primary" id="pickBtn">Choose files</button>
    </div>
    <div class="d-flex gap-2">
      <button class="btn btn-primary" type="submit">Upload</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Refresh</a>
    </div>
  </form>
</div>

<div class="card mb-3">
  <div class="card-header">Files ({{ files|length }})</div>
  <ul class="list-group list-group-flush" id="fileList">
    {% for f in files %}
    <li class="list-group-item d-flex justify-content-between align-items-center">
      <div class="w-50">
        <div class="text-truncate">{{ f.filename }}</div>
        <small class="text-muted">Uploaded: {{ f.uploaded_at }}</small>
      </div>
      <div class="btn-group">
        <a class="btn btn-sm btn-outline-success" href="{{ url_for('download', file_id=f.id) }}">Download</a>
        {% if f.is_public %}
          <button class="btn btn-sm btn-outline-warning btn-unshare" data-id="{{ f.id }}">Unshare</button>
          <button class="btn btn-sm btn-outline-info btn-copy" data-url="{{ request.url_root.rstrip('/') + url_for('shared_download', token=f.shared_token) }}">Copy Link</button>
        {% else %}
          <button class="btn btn-sm btn-outline-primary btn-share" data-id="{{ f.id }}">Share</button>
        {% endif %}
        <button class="btn btn-sm btn-outline-danger btn-delete" data-id="{{ f.id }}" data-name="{{ f.filename }}">Delete</button>
      </div>
    </li>
    {% else %}
    <li class="list-group-item">No files</li>
    {% endfor %}
  </ul>
</div>

{% if shared_files %}
<div class="card">
  <div class="card-header">Your Shared Files</div>
  <ul class="list-group list-group-flush">
    {% for sf in shared_files %}
    <li class="list-group-item d-flex justify-content-between align-items-center">
      <div>
        <div>{{ sf.filename }}</div>
        <div class="small-code mt-1">{{ request.url_root.rstrip('/') + url_for('shared_download', token=sf.shared_token) }}</div>
      </div>
      <div>
        <button class="btn btn-sm btn-outline-warning btn-unshare" data-id="{{ sf.id }}">Unshare</button>
      </div>
    </li>
    {% endfor %}
  </ul>
</div>
{% endif %}

<script>
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const pickBtn = document.getElementById('pickBtn');

pickBtn.addEventListener('click', ()=> fileInput.click());
dropzone.addEventListener('click', ()=> fileInput.click());

['dragenter','dragover'].forEach(ev=>{
  dropzone.addEventListener(ev, e=> { e.preventDefault(); e.stopPropagation(); dropzone.classList.add('dragover'); });
});
['dragleave','drop'].forEach(ev=>{
  dropzone.addEventListener(ev, e=> { e.preventDefault(); e.stopPropagation(); dropzone.classList.remove('dragover'); });
});

dropzone.addEventListener('drop', e=>{
  const dt = e.dataTransfer;
  if (dt && dt.files && dt.files.length) {
    fileInput.files = dt.files;
  }
});

document.querySelectorAll('.btn-delete').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    const id = btn.dataset.id;
    const name = btn.dataset.name;
    if (!confirm('Delete ' + name + '?')) return;
    const resp = await fetch('/delete/' + encodeURIComponent(id), { method: 'POST' });
    if (resp.ok) location.reload();
    else alert('Delete failed');
  });
});

document.querySelectorAll('.btn-share').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    const id = btn.dataset.id;
    const resp = await fetch('/share/' + encodeURIComponent(id), { method: 'POST' });
    const data = await resp.json();
    if (resp.ok) {
      alert('Shared. Link:\\n' + data.url);
      location.reload();
    } else alert('Share failed: ' + (data.err || resp.status));
  });
});

document.querySelectorAll('.btn-unshare').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    const id = btn.dataset.id;
    if (!confirm('Unshare this file?')) return;
    const resp = await fetch('/unshare/' + encodeURIComponent(id), { method: 'POST' });
    if (resp.ok) location.reload();
    else alert('Unshare failed');
  });
});

document.querySelectorAll('.btn-copy').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    const url = btn.dataset.url;
    try {
      await navigator.clipboard.writeText(url);
      alert('Link copied to clipboard');
    } catch (e) {
      prompt('Copy this link:', url);
    }
  });
});
</script>
{% endblock %}
"""
shared_download_t = """
{% extends "layout" %}
{% block content %}
<h2>Download Shared File</h2>
<div class="card">
  <div class="card-body">
    <h5 class="card-title">{{ filename }}</h5>
    <p class="card-text">Uploaded: {{ uploaded_at }}</p>
    <a class="btn btn-primary" href="{{ url_for('shared_download', token=token) }}">Download</a>
  </div>
</div>
{% endblock %}
"""
# Register templates in memory
app.jinja_loader.mapping = {
    "layout": layout_t,
    "register.html": register_t,
    "login.html": login_t,
    "index.html": index_t,
    "shared_download.html": shared_download_t,
}
# --- Routes: auth ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Username and password required")
            return redirect(url_for("register"))
        existing = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
        if existing:
            flash("Username already taken")
            return redirect(url_for("register"))
        pw_hash = generate_password_hash(password)
        execute_db("INSERT INTO users (username, password) VALUES (?, ?)", (username, pw_hash))
        flash("Registered — please log in")
        return redirect(url_for("login"))
    return render_template_string(register_t)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        if user is None or not check_password_hash(user["password"], password):
            flash("Invalid credentials")
            return redirect(url_for("login"))
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        next_url = request.args.get("next") or url_for("index")
        return redirect(next_url)
    return render_template_string(login_t)
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out")
    return redirect(url_for("login"))
# --- File routes ---
@app.route("/")
@login_required
def index():
    files = query_db(
        "SELECT id, filename, stored_name, uploaded_at, shared_token, is_public FROM files WHERE user_id = ? ORDER BY uploaded_at DESC",
        (session["user_id"],)
    )
    shared_files = [f for f in files if f["is_public"]]
    return render_template_string(index_t, files=files, shared_files=shared_files)
@app.route("/upload", methods=["POST"])
@login_required
def upload():
    if "files[]" not in request.files:
        flash("No files part")
        return redirect(url_for("index"))
    files = request.files.getlist("files[]")
    saved = []
    for f in files:
        if f and allowed(f.filename):
            orig = secure_filename(f.filename)
            if not orig:
                continue
            # ensure unique stored filename
            base, ext = os.path.splitext(orig)
            counter = 0
            while True:
                candidate = f"{base}{f'({counter})' if counter else ''}{ext}"
                stored = secure_filename(candidate)
                dest = Path(app.config["UPLOAD_FOLDER"]) / stored
                if not dest.exists():
                    break
                counter += 1
            f.save(str(dest))
            execute_db(
                "INSERT INTO files (user_id, filename, stored_name) VALUES (?, ?, ?)",
                (session["user_id"], orig, stored)
            )
            saved.append(orig)
    if saved:
        flash(f"Uploaded: {', '.join(saved)}")
    return redirect(url_for("index"))
@app.route("/download/<int:file_id>")
@login_required
def download(file_id):
    row = query_db("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, session["user_id"]), one=True)
    if not row:
        abort(404)
    try:
        return send_from_directory(app.config["UPLOAD_FOLDER"], row["stored_name"], as_attachment=True, download_name=row["filename"])
    except TypeError:
        return send_from_directory(app.config["UPLOAD_FOLDER"], row["stored_name"], as_attachment=True, attachment_filename=row["filename"])
@app.route("/delete/<int:file_id>", methods=["POST"])
@login_required
def delete(file_id):
    row = query_db("SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, session["user_id"]), one=True)
    if not row:
        return jsonify({"status": "not_found"}), 404
    p = Path(app.config["UPLOAD_FOLDER"]) / row["stored_name"]
    if p.exists():
        p.unlink()
    execute_db("DELETE FROM files WHERE id = ?", (file_id,))
    return jsonify({"status": "ok", "file": row["filename"]})
# --- Share / Unshare ---
@app.route("/share/<int:file_id>", methods=["POST"])
@login_required
def share(file_id):
    row = query_db("SELECT id, filename, stored_name, is_public FROM files WHERE id = ? AND user_id = ?", (file_id, session["user_id"]), one=True)
    if not row:
        return jsonify({"err": "not_found"}), 404
    if row["is_public"]:
        # already shared, return existing link
        existing = query_db("SELECT shared_token FROM files WHERE id = ?", (file_id,), one=True)
        token = existing["shared_token"]
    else:
        token = generate_token()
        execute_db("UPDATE files SET shared_token = ?, is_public = 1 WHERE id = ?", (token, file_id))
    share_url = request.url_root.rstrip('/') + url_for("shared_download", token=token)
    return jsonify({"url": share_url})
@app.route("/unshare/<int:file_id>", methods=["POST"])
@login_required
def unshare(file_id):
    row = query_db("SELECT id FROM files WHERE id = ? AND user_id = ?", (file_id, session["user_id"]), one=True)
    if not row:
        return jsonify({"err": "not_found"}), 404
    execute_db("UPDATE files SET shared_token = NULL, is_public = 0 WHERE id = ?", (file_id,))
    return jsonify({"ok": True})
# Public shared download by token (no login required)
@app.route("/s/<token>")
def shared_download(token):
    row = query_db("SELECT * FROM files WHERE shared_token = ? AND is_public = 1", (token,), one=True)
    if not row:
        abort(404)
    # show a simple page with download button (or direct download)
    if request.args.get("dl") == "1":
        try:
            return send_from_directory(app.config["UPLOAD_FOLDER"], row["stored_name"], as_attachment=True, download_name=row["filename"])
        except TypeError:
            return send_from_directory(app.config["UPLOAD_FOLDER"], row["stored_name"], as_attachment=True, attachment_filename=row["filename"])
    return render_template_string(shared_download_t, filename=row["filename"], uploaded_at=row["uploaded_at"], token=token)
# Optional: initialize DB route — remove or protect in production
@app.route("/init-db")
def initdb_route():
    with app.app_context():
        get_db()
    return "Initialized DB (if it was missing)."
if __name__ == "__main__":
    # ensure DB exists
    with app.app_context():
        get_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
