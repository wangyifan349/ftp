import os
import re
import sqlite3
from pathlib import Path
from flask import Flask, request, g, redirect, url_for, render_template_string, flash, send_from_directory, abort, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# ---------- Configuration ----------
BASE_DIRECTORY = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIRECTORY / "static" / "uploads"
DATABASE_PATH = BASE_DIRECTORY / "users.db"
ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".webm", ".ogg", ".mov", ".avi"}
SECRET_KEY_VALUE = "replace-with-a-secure-random-key"  # replace in production
USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MAX_SEARCH_RESULTS = 200
CANDIDATE_FETCH_LIMIT = 1000
os.makedirs(UPLOAD_ROOT, exist_ok=True)
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY_VALUE
# ---------- Database helpers (native SQL) ----------
def get_database_connection():
    database_connection = getattr(g, "_database_connection", None)
    if database_connection is None:
        database_connection = g._database_connection = sqlite3.connect(str(DATABASE_PATH), timeout=30, check_same_thread=False)
        database_connection.row_factory = sqlite3.Row
    return database_connection
def initialize_database():
    conn = sqlite3.connect(str(DATABASE_PATH))
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        """)
        conn.commit()
    finally:
        conn.close()
@app.teardown_appcontext
def close_database_connection(exception):
    database_connection = getattr(g, "_database_connection", None)
    if database_connection is not None:
        database_connection.close()
# ---------- Utility functions ----------
def filename_allowed(filename):
    extension = Path(filename).suffix.lower()
    return extension in ALLOWED_EXTENSIONS
def user_directory_from_username(username_string):
    safe_username = secure_filename(username_string)
    return UPLOAD_ROOT / safe_username
def create_user_directory(username_string):
    folder_path = user_directory_from_username(username_string)
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path
def sanitize_username_for_lookup(raw_username):
    return secure_filename(raw_username)
def longest_common_subsequence_length(string_first, string_second):
    length_first = len(string_first)
    length_second = len(string_second)
    previous_row = [0] * (length_second + 1)
    for i in range(1, length_first + 1):
        current_row = [0] * (length_second + 1)
        c1 = string_first[i - 1]
        for j in range(1, length_second + 1):
            if c1 == string_second[j - 1]:
                current_row[j] = previous_row[j - 1] + 1
            else:
                if previous_row[j] >= current_row[j - 1]:
                    current_row[j] = previous_row[j]
                else:
                    current_row[j] = current_row[j - 1]
        previous_row = current_row
    return previous_row[length_second]
def compute_similarity_percentage(query_string, target_string):
    if not query_string and not target_string:
        return 100.0
    if not query_string or not target_string:
        return 0.0
    lcs_length_value = longest_common_subsequence_length(query_string, target_string)
    similarity_ratio = (2.0 * lcs_length_value) / (len(query_string) + len(target_string))
    return similarity_ratio * 100.0
# ---------- Templates (inline, green theme using Bootstrap 5 CDN) ----------
TEMPLATE_BASE_HEADER = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Video Share</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #f6fff6; }
    .navbar-brand { font-weight: 700; color: #fff !important; }
    .card { border-radius: 10px; }
    .video-card video { max-height: 320px; object-fit: cover; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg" style="background: linear-gradient(90deg,#0f5132,#198754);">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">VideoShare</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
        <li class="nav-item"><a class="nav-link text-white" href="{{ url_for('upload_video') }}">Upload</a></li>
        <li class="nav-item"><a class="nav-link text-white" href="{{ url_for('register_user') }}">Register</a></li>
        {% if session.username %}
          <li class="nav-item"><a class="nav-link text-white" href="{{ url_for('logout_user') }}">Logout ({{ session.username }})</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link text-white" href="{{ url_for('login_user') }}">Login</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container my-4">
"""

TEMPLATE_BASE_FOOTER = """
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TEMPLATE_INDEX = TEMPLATE_BASE_HEADER + """
<div class="row mb-3">
  <div class="col-md-8">
    <form class="d-flex" action="{{ url_for('search_user') }}" method="get">
      <input class="form-control me-2" name="q" placeholder="Search username" value="{{ query|default('') }}">
      <button class="btn btn-success" type="submit">Search</button>
    </form>
  </div>
</div>

{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <div class="row">
      <div class="col-md-8">
        {% for category, message in messages %}
          <div class="alert alert-{{ 'success' if category=='success' else 'info' if category=='info' else 'warning' }}">{{ message }}</div>
        {% endfor %}
      </div>
    </div>
  {% endif %}
{% endwith %}

{% if users is defined %}
  <div class="row mb-3">
    <div class="col-md-10">
      <h4>Search Results for "{{ query }}"</h4>
      {% if users %}
        <table class="table table-striped table-hover">
          <thead class="table-success">
            <tr>
              <th scope="col">Username</th>
              <th scope="col">Similarity</th>
              <th scope="col">View</th>
            </tr>
          </thead>
          <tbody>
            {% for item in users %}
              <tr>
                <td>{{ item.username }}</td>
                <td>{{ "{:.2f}%".format(item.similarity) }}</td>
                <td><a class="btn btn-sm btn-outline-success" href="{{ url_for('view_user_videos', username_string=item.username) }}">View Videos</a></td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      {% else %}
        <div class="alert alert-warning">No users found</div>
      {% endif %}
    </div>
  </div>
{% endif %}
""" + TEMPLATE_BASE_FOOTER

TEMPLATE_REGISTER = TEMPLATE_BASE_HEADER + """
<div class="row">
  <div class="col-md-6">
    <h3>Register</h3>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input class="form-control" name="username" required>
        <div class="form-text">3-32 chars: letters, numbers, underscore, dot, hyphen</div>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input class="form-control" type="password" name="password" required>
      </div>
      <button class="btn btn-success" type="submit">Register</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Cancel</a>
    </form>
  </div>
</div>
""" + TEMPLATE_BASE_FOOTER

TEMPLATE_LOGIN = TEMPLATE_BASE_HEADER + """
<div class="row">
  <div class="col-md-6">
    <h3>Login</h3>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input class="form-control" type="password" name="password" required>
      </div>
      <button class="btn btn-success" type="submit">Login</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Cancel</a>
    </form>
  </div>
</div>
""" + TEMPLATE_BASE_FOOTER

TEMPLATE_UPLOAD = TEMPLATE_BASE_HEADER + """
<div class="row">
  <div class="col-md-8">
    <h3>Upload Video to Specified User</h3>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label class="form-label">Target Username</label>
        <input class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Video File</label>
        <input class="form-control" type="file" name="file" required>
      </div>
      <button class="btn btn-success" type="submit">Upload</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Home</a>
    </form>
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="mt-3">
          {% for category, message in messages %}
            <div class="alert alert-{{ 'success' if category=='success' else 'info' if category=='info' else 'warning' }}">{{ message }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
  </div>
</div>
""" + TEMPLATE_BASE_FOOTER

TEMPLATE_USER_VIDEOS = TEMPLATE_BASE_HEADER + """
<div class="row">
  <div class="col-md-10">
    <h3>{{ username }}'s Videos</h3>
    <a class="btn btn-secondary mb-3" href="{{ url_for('index') }}">Back</a>
    {% if videos %}
      <div class="row row-cols-1 row-cols-md-2 g-4">
        {% for video in videos %}
          <div class="col">
            <div class="card video-card">
              <video class="card-img-top" controls>
                <source src="{{ url_for('serve_uploaded_file', username_string=username, filename_string=video) }}">
                Your browser does not support the video tag.
              </video>
              <div class="card-body">
                <h5 class="card-title">{{ video }}</h5>
                <a class="btn btn-sm btn-success" href="{{ url_for('serve_uploaded_file', username_string=username, filename_string=video) }}" target="_blank">Open</a>
              </div>
            </div>
          </div>
        {% endfor %}
      </div>
    {% else %}
      <div class="alert alert-warning">No videos</div>
    {% endif %}
  </div>
</div>
""" + TEMPLATE_BASE_FOOTER
# ---------- Routes ---------
@app.route("/")
def index():
    return render_template_string(TEMPLATE_INDEX)
@app.route("/register", methods=["GET", "POST"])
def register_user():
    if request.method == "POST":
        username_form = request.form.get("username", "").strip()
        password_form = request.form.get("password", "")
        if not username_form or not password_form:
            flash("Username and password are required", "error")
            return redirect(url_for("register_user"))
        if not USERNAME_REGEX.match(username_form):
            flash("Username must be 3-32 characters and only letters, numbers, underscore, dot, or hyphen", "error")
            return redirect(url_for("register_user"))
        db = get_database_connection()
        try:
            db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username_form, generate_password_hash(password_form)))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Username already exists", "error")
            return redirect(url_for("register_user"))
        create_user_directory(username_form)
        flash("Registration successful. You can now login.", "success")
        return redirect(url_for("login_user"))
    return render_template_string(TEMPLATE_REGISTER)
@app.route("/login", methods=["GET", "POST"])
def login_user():
    if request.method == "POST":
        username_form = request.form.get("username", "").strip()
        password_form = request.form.get("password", "")
        db = get_database_connection()
        row = db.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username_form,)).fetchone()
        if row and check_password_hash(row["password_hash"], password_form):
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            flash("Login successful", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password", "error")
            return redirect(url_for("login_user"))
    return render_template_string(TEMPLATE_LOGIN)
@app.route("/logout")
def logout_user():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("index"))
@app.route("/upload", methods=["GET", "POST"])
def upload_video():
    if request.method == "POST":
        target_username_form = request.form.get("username", "").strip()
        if not target_username_form:
            flash("Target username is required", "error")
            return redirect(url_for("upload_video"))
        db = get_database_connection()
        row = db.execute("SELECT id FROM users WHERE username = ?", (target_username_form,)).fetchone()
        if not row:
            flash("Target user does not exist", "error")
            return redirect(url_for("upload_video"))
        if "file" not in request.files:
            flash("No file part in request", "error")
            return redirect(url_for("upload_video"))
        upload_file = request.files["file"]
        if upload_file.filename == "":
            flash("No selected file", "error")
            return redirect(url_for("upload_video"))
        if not filename_allowed(upload_file.filename):
            flash("File extension not allowed", "error")
            return redirect(url_for("upload_video"))
        secure_filename_value = secure_filename(upload_file.filename)
        target_folder_path = create_user_directory(target_username_form)
        destination_path = target_folder_path / secure_filename_value
        base_stem = Path(secure_filename_value).stem
        base_suffix = Path(secure_filename_value).suffix
        counter_index = 1
        while destination_path.exists():
            destination_path = target_folder_path / f"{base_stem}_{counter_index}{base_suffix}"
            counter_index += 1
        upload_file.save(str(destination_path))
        flash("Upload successful", "success")
        return redirect(url_for("view_user_videos", username_string=target_username_form))
    return render_template_string(TEMPLATE_UPLOAD)
@app.route("/user/<username_string>")
def view_user_videos(username_string):
    safe_username_value = sanitize_username_for_lookup(username_string)
    db = get_database_connection()
    row = db.execute("SELECT id FROM users WHERE username = ?", (safe_username_value,)).fetchone()
    if not row:
        abort(404)
    folder_path = user_directory_from_username(safe_username_value)
    videos_list = []
    if folder_path.exists():
        for path_object in sorted(folder_path.iterdir()):
            if path_object.is_file() and path_object.suffix.lower() in ALLOWED_EXTENSIONS:
                videos_list.append(path_object.name)
    return render_template_string(TEMPLATE_USER_VIDEOS, username=safe_username_value, videos=videos_list)
@app.route("/uploads/<username_string>/<filename_string>")
def serve_uploaded_file(username_string, filename_string):
    safe_username_value = secure_filename(username_string)
    safe_filename_value = secure_filename(filename_string)
    folder_path = user_directory_from_username(safe_username_value)
    full_path = (folder_path / safe_filename_value).resolve()
    if not str(full_path).startswith(str(folder_path.resolve())):
        abort(403)
    if not full_path.exists():
        abort(404)
    return send_from_directory(str(folder_path), safe_filename_value)
@app.route("/search")
def search_user():
    query_string = (request.args.get("q") or "").strip()
    db = get_database_connection()
    users_result_list = []
    if query_string == "":
        users_result_list = []
    else:
        like_pattern = f"%{query_string}%"
        try:
            rows = db.execute("SELECT username FROM users WHERE LOWER(username) LIKE LOWER(?) ORDER BY username LIMIT ?", (like_pattern, MAX_SEARCH_RESULTS)).fetchall()
        except sqlite3.DatabaseError:
            rows = []
        candidate_usernames = [r["username"] for r in rows]
        if not candidate_usernames:
            rows_all = db.execute("SELECT username FROM users ORDER BY username LIMIT ?", (min(CANDIDATE_FETCH_LIMIT, MAX_SEARCH_RESULTS),)).fetchall()
            candidate_usernames = [r["username"] for r in rows_all]
        query_lower = query_string.lower()
        results_with_similarity = []
        for candidate in candidate_usernames:
            candidate_lower = candidate.lower()
            similarity = compute_similarity_percentage(query_lower, candidate_lower)
            results_with_similarity.append({"username": candidate, "similarity": similarity})
        results_with_similarity.sort(key=lambda e: (-e["similarity"], e["username"]))
        users_result_list = results_with_similarity[:MAX_SEARCH_RESULTS]
    return render_template_string(TEMPLATE_INDEX, users=users_result_list, query=query_string)
# ---------- Main ----------
if __name__ == "__main__":
    initialize_database()
    app.run(debug=False)
