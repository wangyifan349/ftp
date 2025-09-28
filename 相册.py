from flask import Flask, request, session, redirect, url_for, render_template_string, send_from_directory, flash, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql
import os
import re
import shutil
import uuid
from pathlib import Path
from datetime import timedelta

APP_ROOT = Path(__file__).parent.resolve()
UPLOAD_ROOT = APP_ROOT / "uploads"
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "photoapp")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_CONTENT_LENGTH = 64 * 1024 * 1024

UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

def get_conn():
    return pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=True)

def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id INT AUTO_INCREMENT PRIMARY KEY,
              username VARCHAR(100) NOT NULL UNIQUE,
              password_hash VARCHAR(255) NOT NULL,
              display_name VARCHAR(200),
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS albums (
              id INT AUTO_INCREMENT PRIMARY KEY,
              user_id INT NOT NULL,
              title VARCHAR(255) NOT NULL,
              slug VARCHAR(255) NOT NULL,
              description TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              UNIQUE KEY user_slug_unique (user_id, slug),
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS photos (
              id INT AUTO_INCREMENT PRIMARY KEY,
              album_id INT NOT NULL,
              filename VARCHAR(500) NOT NULL,
              filepath VARCHAR(1000) NOT NULL,
              uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
    finally:
        conn.close()

init_db()

def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in ALLOWED_EXT

def slugify(text):
    s = re.sub(r'[^\w\s-]', '', text).strip().lower()
    s = re.sub(r'[-\s]+', '-', s)
    return s or str(uuid.uuid4())[:8]

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, display_name FROM users WHERE id=%s", (uid,))
            return cur.fetchone()
    finally:
        conn.close()

def ensure_user_dir(username):
    p = UPLOAD_ROOT / username
    p.mkdir(parents=True, exist_ok=True)
    return p

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    safe_path = Path(filename)
    if ".." in safe_path.parts:
        abort(400)
    full = UPLOAD_ROOT / safe_path
    if not full.exists():
        abort(404)
    return send_from_directory(str(full.parent), full.name)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        display_name = (request.form.get("display_name") or "").strip() or username
        if not username or not password:
            flash("用户名和密码必填")
            return redirect(url_for('register'))
        if not re.match(r'^[A-Za-z0-9_.-]{3,30}$', username):
            flash("用户名规则不符合")
            return redirect(url_for('register'))
        pw_hash = generate_password_hash(password)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute("INSERT INTO users (username, password_hash, display_name) VALUES (%s,%s,%s)", (username, pw_hash, display_name))
                except pymysql.err.IntegrityError:
                    flash("用户名已存在")
                    return redirect(url_for('register'))
        finally:
            conn.close()
        ensure_user_dir(username)
        flash("注册成功，请登录")
        return redirect(url_for('login'))
    return render_template_string(REG_TEMPLATE)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, password_hash FROM users WHERE username=%s", (username,))
                user = cur.fetchone()
                if not user or not check_password_hash(user['password_hash'], password):
                    flash("用户名或密码错误")
                    return redirect(url_for('login'))
                session['user_id'] = user['id']
                session.permanent = True
        finally:
            conn.close()
        flash("登录成功")
        return redirect(url_for('index'))
    return render_template_string(LOGIN_TEMPLATE)

@app.route("/logout")
def logout():
    session.clear()
    flash("已登出")
    return redirect(url_for('index'))

@app.route("/")
def index():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT a.id, a.title, a.slug, a.created_at, u.username, u.display_name FROM albums a JOIN users u ON a.user_id=u.id ORDER BY a.created_at DESC LIMIT 12")
            recent = cur.fetchall()
    finally:
        conn.close()
    return render_template_string(INDEX_TEMPLATE, recent=recent, user=current_user())

@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    results = []
    if q:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, display_name FROM users WHERE username LIKE %s OR display_name LIKE %s LIMIT 50", (f"%{q}%", f"%{q}%"))
                results = cur.fetchall()
        finally:
            conn.close()
    return render_template_string(SEARCH_TEMPLATE, q=q, results=results, user=current_user())

@app.route("/u/<username>")
def user_page(username):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, display_name FROM users WHERE username=%s", (username,))
            profile = cur.fetchone()
            if not profile:
                abort(404)
            cur.execute("SELECT id, title, slug, description, created_at FROM albums WHERE user_id=%s ORDER BY created_at DESC", (profile['id'],))
            albums = cur.fetchall()
    finally:
        conn.close()
    return render_template_string(USER_TEMPLATE, profile=profile, albums=albums, user=current_user())

@app.route("/albums/create", methods=["GET", "POST"])
def create_album():
    user = current_user()
    if not user:
        flash("请先登录")
        return redirect(url_for('login'))
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        if not title:
            flash("标题不能为空")
            return redirect(url_for('create_album'))
        slug = slugify(title)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                base = slug
                i = 0
                while True:
                    try:
                        cur.execute("INSERT INTO albums (user_id, title, slug, description) VALUES (%s,%s,%s,%s)", (user['id'], title, slug, description))
                        break
                    except pymysql.err.IntegrityError:
                        i += 1
                        slug = f"{base}-{i}"
                cur.execute("SELECT LAST_INSERT_ID() as id")
                new_id = cur.fetchone()['id']
        finally:
            conn.close()
        ensure_user_dir(user['username'])
        album_dir = UPLOAD_ROOT / user['username'] / slug
        album_dir.mkdir(parents=True, exist_ok=True)
        flash("相册创建成功")
        return redirect(url_for('user_page', username=user['username']))
    return render_template_string(CREATE_ALBUM_TEMPLATE, user=current_user())

@app.route("/albums/<int:album_id>", methods=["GET", "POST"])
def view_album(album_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT a.*, u.username, u.display_name FROM albums a JOIN users u ON a.user_id=u.id WHERE a.id=%s", (album_id,))
            album = cur.fetchone()
            if not album:
                abort(404)
            cur.execute("SELECT id, filename, filepath, uploaded_at FROM photos WHERE album_id=%s ORDER BY uploaded_at DESC", (album_id,))
            photos = cur.fetchall()
    finally:
        conn.close()
    user = current_user()
    if request.method == "POST":
        if not user or user['username'] != album['username']:
            flash("无权限上传")
            return redirect(url_for('view_album', album_id=album_id))
        files = request.files.getlist("photos")
        if not files:
            flash("请选择文件")
            return redirect(url_for('view_album', album_id=album_id))
        saved = 0
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                album_dir = UPLOAD_ROOT / album['username'] / album['slug']
                album_dir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    if f and allowed_file(f.filename):
                        fname = secure_filename(f.filename)
                        dest_name = fname
                        dest_path = album_dir / dest_name
                        k = 0
                        while dest_path.exists():
                            k += 1
                            stem = Path(fname).stem
                            suffix = Path(fname).suffix
                            dest_name = f"{stem}-{k}{suffix}"
                            dest_path = album_dir / dest_name
                        f.save(str(dest_path))
                        relpath = f"{album['username']}/{album['slug']}/{dest_name}"
                        cur.execute("INSERT INTO photos (album_id, filename, filepath) VALUES (%s,%s,%s)", (album_id, dest_name, relpath))
                        saved += 1
        finally:
            conn.close()
        flash(f"上传 {saved} 张图片")
        return redirect(url_for('view_album', album_id=album_id))
    return render_template_string(ALBUM_TEMPLATE, album=album, photos=photos, user=user)

@app.route("/albums/<int:album_id>/delete", methods=["POST"])
def delete_album(album_id):
    user = current_user()
    if not user:
        flash("请先登录")
        return redirect(url_for('login'))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT a.*, u.username FROM albums a JOIN users u ON a.user_id=u.id WHERE a.id=%s", (album_id,))
            album = cur.fetchone()
            if not album:
                flash("相册不存在")
                return redirect(url_for('index'))
            if album['username'] != user['username']:
                flash("无权限删除")
                return redirect(url_for('user_page', username=album['username']))
            cur.execute("DELETE FROM albums WHERE id=%s", (album_id,))
    finally:
        conn.close()
    album_dir = UPLOAD_ROOT / album['username'] / album['slug']
    if album_dir.exists():
        shutil.rmtree(album_dir, ignore_errors=True)
    flash("相册已删除")
    return redirect(url_for('user_page', username=album['username']))

@app.route("/photos/<int:photo_id>/delete", methods=["POST"])
def delete_photo(photo_id):
    user = current_user()
    if not user:
        flash("请先登录")
        return redirect(url_for('login'))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT p.*, a.slug, u.username FROM photos p JOIN albums a ON p.album_id=a.id JOIN users u ON a.user_id=u.id WHERE p.id=%s", (photo_id,))
            photo = cur.fetchone()
            if not photo:
                flash("图片不存在")
                return redirect(url_for('index'))
            if photo['username'] != user['username']:
                flash("无权限删除")
                return redirect(url_for('view_album', album_id=photo['album_id']))
            fp = UPLOAD_ROOT / photo['filepath']
            if fp.exists():
                try:
                    fp.unlink()
                except Exception:
                    pass
            cur.execute("DELETE FROM photos WHERE id=%s", (photo_id,))
    finally:
        conn.close()
    flash("图片已删除")
    return redirect(url_for('view_album', album_id=photo['album_id']))

@app.route("/photos/<int:photo_id>")
def photo_page(photo_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT p.id, p.filename, p.filepath, p.uploaded_at, a.id as album_id, a.slug, a.title, u.username, u.display_name FROM photos p JOIN albums a ON p.album_id=a.id JOIN users u ON a.user_id=u.id WHERE p.id=%s", (photo_id,))
            photo = cur.fetchone()
            if not photo:
                abort(404)
    finally:
        conn.close()
    return render_template_string(PHOTO_TEMPLATE, photo=photo, user=current_user())

REG_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>注册</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<div class="container py-4">
<h3>注册</h3>
<form method="post">
  <div class="mb-3"><label class="form-label">用户名</label><input class="form-control" name="username" required></div>
  <div class="mb-3"><label class="form-label">显示名</label><input class="form-control" name="display_name"></div>
  <div class="mb-3"><label class="form-label">密码</label><input class="form-control" type="password" name="password" required></div>
  <button class="btn btn-primary">注册</button>
  <a class="btn btn-link" href="/login">已有账号？登录</a>
</form>
</div>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>登录</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<div class="container py-4">
<h3>登录</h3>
<form method="post">
  <div class="mb-3"><label class="form-label">用户名</label><input class="form-control" name="username" required></div>
  <div class="mb-3"><label class="form-label">密码</label><input class="form-control" type="password" name="password" required></div>
  <button class="btn btn-primary">登录</button>
  <a class="btn btn-link" href="/register">注册新账号</a>
</form>
</div>
</body>
</html>
"""

INDEX_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>首页</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<nav class="navbar navbar-light bg-light">
  <div class="container">
    <a class="navbar-brand" href="/">PhotoSite</a>
    <form class="d-flex" action="/search"><input class="form-control me-2" name="q" placeholder="搜索用户名或显示名"><button class="btn btn-outline-primary">搜索</button></form>
    <div>
      {% if user %}
        <span class="me-2">你好，{{ user.display_name or user.username }}</span>
        <a class="btn btn-sm btn-success" href="/albums/create">创建相册</a>
        <a class="btn btn-sm btn-danger" href="/logout">登出</a>
      {% else %}
        <a class="btn btn-sm btn-primary" href="/login">登录</a>
        <a class="btn btn-sm btn-secondary" href="/register">注册</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container py-4">
  <h4>最新相册</h4>
  <div class="row">
    {% for a in recent %}
      <div class="col-md-3 mb-3">
        <div class="card">
          <div class="card-body">
            <h5 class="card-title">{{ a.title }}</h5>
            <p class="card-text small">by <a href="/u/{{ a.username }}">{{ a.display_name or a.username }}</a></p>
            <a class="btn btn-sm btn-primary" href="/albums/{{ a.id }}">查看相册</a>
          </div>
        </div>
      </div>
    {% else %}
      <p>暂无相册</p>
    {% endfor %}
  </div>
</div>
</body>
</html>
"""

SEARCH_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>搜索</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body>
<div class="container py-4">
<h4>搜索: "{{ q }}"</h4>
{% if results %}
  <ul class="list-group">
  {% for r in results %}
    <li class="list-group-item d-flex justify-content-between align-items-center">
      <div><a href="/u/{{ r.username }}">{{ r.display_name or r.username }}</a><div class="small text-muted">{{ r.username }}</div></div>
    </li>
  {% endfor %}
  </ul>
{% else %}
  <p>未找到</p>
{% endif %}
<a class="btn btn-link" href="/">返回</a>
</div>
</body>
</html>
"""

USER_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ profile.display_name or profile.username }}</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body>
<div class="container py-4">
<div class="d-flex justify-content-between align-items-center mb-3">
  <div><h3>{{ profile.display_name or profile.username }}</h3><div class="small text-muted">{{ profile.username }}</div></div>
  {% if user and user.username==profile.username %}
    <a class="btn btn-success" href="/albums/create">创建相册</a>
  {% endif %}
</div>
<div class="row">
  {% for a in albums %}
    <div class="col-md-4 mb-3">
      <div class="card">
        <div class="card-body">
          <h5>{{ a.title }}</h5>
          <p class="small text-muted">{{ a.created_at }}</p>
          <a class="btn btn-sm btn-primary" href="/albums/{{ a.id }}">查看</a>
          {% if user and user.username==profile.username %}
            <form method="post" action="/albums/{{ a.id }}/delete" style="display:inline" onsubmit="return confirm('确认删除？')"><button class="btn btn-sm btn-danger">删除</button></form>
          {% endif %}
        </div>
      </div>
    </div>
  {% else %}
    <p>暂无相册</p>
  {% endfor %}
</div>
<a class="btn btn-link" href="/">返回</a>
</div>
</body>
</html>
"""

CREATE_ALBUM_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>创建相册</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body>
<div class="container py-4">
<h4>创建相册</h4>
<form method="post">
  <div class="mb-3"><label class="form-label">标题</label><input class="form-control" name="title" required></div>
  <div class="mb-3"><label class="form-label">描述</label><textarea class="form-control" name="description"></textarea></div>
  <button class="btn btn-primary">创建</button>
  <a class="btn btn-link" href="/">取消</a>
</form>
</div>
</body>
</html>
"""

ALBUM_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ album.title }}</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"><style>.thumb{width:100%;height:200px;object-fit:cover}.modal-img{max-width:100%;height:auto}</style></head>
<body>
<div class="container py-4">
<div class="d-flex justify-content-between align-items-center mb-3">
  <div><h3>{{ album.title }}</h3><div class="small text-muted">by <a href="/u/{{ album.username }}">{{ album.display_name or album.username }}</a></div></div>
  {% if user and user.username==album.username %}
    <form method="post" enctype="multipart/form-data" class="d-flex">
      <input class="form-control form-control-sm me-2" type="file" name="photos" accept="image/*" multiple required>
      <button class="btn btn-sm btn-success">上传</button>
    </form>
  {% endif %}
</div>
<div class="row">
  {% for p in photos %}
    <div class="col-md-3 mb-3">
      <div class="card">
        <a href="/photos/{{ p.id }}"><img src="/uploads/{{ p.filepath }}" class="thumb card-img-top" alt="{{ p.filename }}"></a>
        <div class="card-body">
          <p class="small text-truncate">{{ p.filename }}</p>
          <p class="small text-muted">{{ p.uploaded_at }}</p>
          {% if user and user.username==album.username %}
            <form method="post" action="/photos/{{ p.id }}/delete" onsubmit="return confirm('确认删除？')"><button class="btn btn-sm btn-danger">删除</button></form>
          {% else %}
            <a class="btn btn-sm btn-primary" href="/photos/{{ p.id }}">查看大图</a>
          {% endif %}
        </div>
      </div>
    </div>
  {% else %}
    <p>相册暂无图片</p>
  {% endfor %}
</div>
<a class="btn btn-link" href="/u/{{ album.username }}">返回用户主页</a>
</div>
</body>
</html>
"""

PHOTO_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ photo.filename }}</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"></head>
<body>
<div class="container py-4">
<div class="mb-3">
  <a class="btn btn-link" href="/albums/{{ photo.album_id }}">返回相册</a>
  {% if user and user.username==photo.username %}
    <form method="post" action="/photos/{{ photo.id }}/delete" style="display:inline" onsubmit="return confirm('确认删除？')"><button class="btn btn-danger">删除</button></form>
  {% endif %}
</div>
<div class="text-center">
  <img src="/uploads/{{ photo.filepath }}" class="img-fluid" alt="{{ photo.filename }}">
  <h5 class="mt-3">{{ photo.filename }}</h5>
  <p class="text-muted">{{ photo.uploaded_at }}</p>
</div>
</div>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
