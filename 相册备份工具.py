#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import time
import uuid
from datetime import timedelta
from io import BytesIO
from flask import (Flask, abort, flash, g, redirect, render_template_string,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
# ---------------- Config ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'db.sqlite3')
UPLOAD_ROOT = os.path.join(BASE_DIR, 'media')
PUBLIC_DIR = os.path.join(UPLOAD_ROOT, 'public')
PRIVATE_DIR = os.path.join(UPLOAD_ROOT, 'private')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
SECRET_KEY = os.environ.get('FLASK_SECRET', 'replace-this-with-a-secure-random-key')
ALLOW_THUMBNAILS = True
THUMB_SIZE = (320, 240)  # thumbnail size
os.makedirs(PUBLIC_DIR, exist_ok=True)
os.makedirs(PRIVATE_DIR, exist_ok=True)
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
# ---------------- Schema (原生 SQL) ----------------
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    thumb_filename TEXT,
    original_name TEXT NOT NULL,
    is_public INTEGER NOT NULL DEFAULT 0,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""
# ---------------- DB helpers (原生 SQL) ----------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db
def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv
def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    lastrowid = cur.lastrowid
    cur.close()
    return lastrowid
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
def init_db():
    db = get_db()
    db.executescript(SCHEMA_SQL)
    db.commit()
# initialize DB file if missing
if not os.path.exists(DATABASE):
    init_db()
# ---------------- Utilities ----------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return query_db('SELECT * FROM users WHERE id = ?', (uid,), one=True)
def make_stored_name(user_id, original_filename):
    ext = original_filename.rsplit('.', 1)[1].lower()
    return f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
def make_thumb(image_stream, ext):
    try:
        img = Image.open(image_stream)
        img.thumbnail(THUMB_SIZE)
        out = BytesIO()
        format = 'JPEG' if ext in ('jpg', 'jpeg') else ext.upper()
        img.save(out, format=format, quality=85)
        out.seek(0)
        return out.read()
    except Exception:
        return None
# ---------------- Templates (Bootstrap 5) ----------------
# All templates embedded as strings for single-file app
BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "云相册" }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body {{ padding-top: 4.5rem; }}
      .thumb {{ max-width: 200px; max-height:150px; object-fit:cover; }}
      .card-img-top {{ height: 160px; object-fit: cover; }}
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-md navbar-dark bg-dark fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('index') }}">云相册</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarsExampleDefault" aria-controls="navbarsExampleDefault" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarsExampleDefault">
          <ul class="navbar-nav me-auto mb-2 mb-md-0">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">公开相册</a></li>
          </ul>
          <ul class="navbar-nav ms-auto">
            {% if user %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('gallery') }}">我的相册</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
            {% else %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
            {% endif %}
          </ul>
        </div>
      </div>
    </nav>

    <main class="container">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="mt-2">
            {% for m in messages %}
              <div class="alert alert-info alert-dismissible fade show" role="alert">{{ m }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
            {% endfor %}
          </div>
        {% endif %}
      {% endwith %}
      {{ body|safe }}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

INDEX_BODY = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4">公开相册</h1>
</div>

{% if public_photos %}
  <div class="row row-cols-1 row-cols-sm-2 row-cols-md-3 g-3">
    {% for p in public_photos %}
      <div class="col">
        <div class="card shadow-sm">
          <a href="{{ url_for('media', scope='public', filename=p.filename) }}" target="_blank">
            {% if p.thumb_filename %}
              <img src="{{ url_for('media', scope='public', filename=p.thumb_filename) }}" class="card-img-top" alt="{{ p.original_name }}">
            {% else %}
              <img src="{{ url_for('media', scope='public', filename=p.filename) }}" class="card-img-top" alt="{{ p.original_name }}">
            {% endif %}
          </a>
          <div class="card-body">
            <p class="card-text text-truncate"><strong>{{ p.original_name }}</strong></p>
            <div class="d-flex justify-content-between align-items-center">
              <small class="text-muted">by {{ p.username }}</small>
              <small class="text-muted">{{ p.uploaded_at.split(' ')[0] }}</small>
            </div>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="alert alert-secondary">暂无公开图片</div>
{% endif %}
"""

REGISTER_BODY = """
<h1 class="h4 mb-3">注册</h1>
<form method="post" class="row g-3">
  <div class="col-md-6">
    <label class="form-label">用户名</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="col-md-6">
    <label class="form-label">密码</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  <div class="col-12">
    <button class="btn btn-primary">注册</button>
    <a class="btn btn-link" href="{{ url_for('login') }}">已有账号？登录</a>
  </div>
</form>
"""

LOGIN_BODY = """
<h1 class="h4 mb-3">登录</h1>
<form method="post" class="row g-3">
  <div class="col-md-6">
    <label class="form-label">用户名</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="col-md-6">
    <label class="form-label">密码</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  <div class="col-12">
    <button class="btn btn-primary">登录</button>
    <a class="btn btn-link" href="{{ url_for('register') }}">没有账号？注册</a>
  </div>
</form>
"""

UPLOAD_BODY = """
<h1 class="h4 mb-3">上传图片</h1>
<form method="post" enctype="multipart/form-data" class="row g-3">
  <div class="col-12">
    <input type="file" name="file" class="form-control" accept="image/*" required>
  </div>
  <div class="col-auto form-check">
    <input class="form-check-input" type="checkbox" name="is_public" id="is_public">
    <label class="form-check-label" for="is_public">公开</label>
  </div>
  <div class="col-12">
    <button class="btn btn-success">上传</button>
    <a class="btn btn-link" href="{{ url_for('gallery') }}">返回我的相册</a>
  </div>
</form>
"""

GALLERY_BODY = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h4">我的相册 — {{ user.username }}</h1>
  <div>
    <a class="btn btn-primary me-2" href="{{ url_for('upload') }}">上传新图片</a>
    <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">查看公开相册</a>
  </div>
</div>

{% if photos %}
  <div class="row row-cols-1 row-cols-sm-2 row-cols-md-3 g-3">
    {% for p in photos %}
      <div class="col">
        <div class="card shadow-sm">
          <a href="{{ url_for('media', scope='public' if p.is_public else 'private', filename=(p.thumb_filename or p.filename)) }}" target="_blank">
            {% if p.thumb_filename %}
              <img src="{{ url_for('media', scope='public' if p.is_public else 'private', filename=p.thumb_filename) }}" class="card-img-top" alt="{{ p.original_name }}">
            {% else %}
              <img src="{{ url_for('media', scope='public' if p.is_public else 'private', filename=p.filename) }}" class="card-img-top" alt="{{ p.original_name }}">
            {% endif %}
          </a>
          <div class="card-body">
            <p class="card-text text-truncate"><strong>{{ p.original_name }}</strong></p>
            <div class="d-flex justify-content-between align-items-center">
              <small class="text-muted">{{ p.uploaded_at.split(' ')[0] }}</small>
              <div>
                <form action="{{ url_for('toggle', photo_id=p.id) }}" method="post" style="display:inline">
                  <button class="btn btn-sm btn-outline-{{ 'warning' if p.is_public else 'success' }}">{{ '设为私密' if p.is_public else '设为公开' }}</button>
                </form>
                <form action="{{ url_for('delete', photo_id=p.id) }}" method="post" style="display:inline" onsubmit="return confirm('确认删除？');">
                  <button class="btn btn-sm btn-outline-danger">删除</button>
                </form>
              </div>
            </div>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="alert alert-secondary">你还没有上传任何图片。</div>
{% endif %}
"""
# ---------------- Views / Routes ----------------
@app.route('/')
def index():
    user = current_user()
    # 所有用户的公开图片，包含上传者用户名
    public_photos = query_db(
        'SELECT p.*, u.username FROM photos p JOIN users u ON p.user_id = u.id WHERE is_public = 1 ORDER BY uploaded_at DESC'
    )
    body = render_template_string(INDEX_BODY, public_photos=public_photos)
    return render_template_string(BASE_HTML, title="公开相册", body=body, user=user)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        existing = query_db('SELECT id FROM users WHERE username = ?', (username,), one=True)
        if existing:
            flash('用户名已存在')
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password)
        execute_db('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    body = render_template_string(REGISTER_BODY)
    return render_template_string(BASE_HTML, title="注册", body=body, user=current_user())
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = query_db('SELECT * FROM users WHERE username = ?', (username,), one=True)
        if not user or not check_password_hash(user['password_hash'], password):
            flash('用户名或密码错误')
            return redirect(url_for('login'))
        session.clear()
        session['user_id'] = user['id']
        session.permanent = True
        return redirect(url_for('index'))
    body = render_template_string(LOGIN_BODY)
    return render_template_string(BASE_HTML, title="登录", body=body, user=current_user())

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        f = request.files.get('file')
        is_public = 1 if request.form.get('is_public') == 'on' else 0
        if not f or f.filename == '':
            flash('请选择文件')
            return redirect(url_for('upload'))
        if not allowed_file(f.filename):
            flash('不支持的文件类型')
            return redirect(url_for('upload'))
        orig_name = secure_filename(f.filename)
        stored_name = make_stored_name(user['id'], orig_name)
        ext = orig_name.rsplit('.', 1)[1].lower()
        target_dir = PUBLIC_DIR if is_public else PRIVATE_DIR
        save_path = os.path.join(target_dir, stored_name)
        # 保存原图
        f.stream.seek(0)
        f.save(save_path)
        thumb_name = None
        if ALLOW_THUMBNAILS:
            try:
                f.stream.seek(0)
                thumb_bytes = make_thumb(f.stream, ext)
                if thumb_bytes:
                    thumb_name = f"thumb_{stored_name}"
                    thumb_path = os.path.join(target_dir, thumb_name)
                    with open(thumb_path, 'wb') as tf:
                        tf.write(thumb_bytes)
            except Exception:
                thumb_name = None
        # 插入 DB（原生 SQL）
        execute_db(
            'INSERT INTO photos (user_id, filename, thumb_filename, original_name, is_public) VALUES (?, ?, ?, ?, ?)',
            (user['id'], stored_name, thumb_name, orig_name, is_public)
        )
        flash('上传成功')
        return redirect(url_for('gallery'))
    body = render_template_string(UPLOAD_BODY)
    return render_template_string(BASE_HTML, title="上传图片", body=body, user=user)

@app.route('/gallery')
def gallery():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    photos = query_db('SELECT * FROM photos WHERE user_id = ? ORDER BY uploaded_at DESC', (user['id'],))
    body = render_template_string(GALLERY_BODY, photos=photos, user=user)
    return render_template_string(BASE_HTML, title="我的相册", body=body, user=user)
@app.route('/media/<scope>/<filename>')
def media(scope, filename):
    # scope must be 'public' or 'private'
    if scope not in ('public', 'private'):
        abort(404)
    # Public files are served directly
    if scope == 'public':
        return send_from_directory(PUBLIC_DIR, filename, as_attachment=False)
    # Private files: only allow access to the owner
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    # Check photo exists, is private, and belongs to current user (原生 SQL)
    photo = query_db('SELECT * FROM photos WHERE filename = ? AND is_public = 0', (filename,), one=True)
    if not photo or photo['user_id'] != user['id']:
        abort(403)
    return send_from_directory(PRIVATE_DIR, filename, as_attachment=False)
@app.route('/toggle/<int:photo_id>', methods=['POST'])
def toggle(photo_id):
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    photo = query_db('SELECT * FROM photos WHERE id = ?', (photo_id,), one=True)
    if not photo or photo['user_id'] != user['id']:
        abort(403)
    # Flip state
    new_state = 0 if photo['is_public'] == 1 else 1
    # Update DB (原生 SQL)
    execute_db('UPDATE photos SET is_public = ? WHERE id = ?', (new_state, photo_id))
    # Move files between public/private directories (including thumbnail if exists)
    src_dir = PUBLIC_DIR if photo['is_public'] == 1 else PRIVATE_DIR
    dst_dir = PUBLIC_DIR if new_state == 1 else PRIVATE_DIR
    src_path = os.path.join(src_dir, photo['filename'])
    dst_path = os.path.join(dst_dir, photo['filename'])
    try:
        if os.path.exists(src_path):
            os.replace(src_path, dst_path)
    except Exception:
        pass
    # move thumbnail if present
    if photo['thumb_filename']:
        src_thumb = os.path.join(src_dir, photo['thumb_filename'])
        dst_thumb = os.path.join(dst_dir, photo['thumb_filename'])
        try:
            if os.path.exists(src_thumb):
                os.replace(src_thumb, dst_thumb)
        except Exception:
            pass
    return redirect(url_for('gallery'))
@app.route('/delete/<int:photo_id>', methods=['POST'])
def delete(photo_id):
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    photo = query_db('SELECT * FROM photos WHERE id = ?', (photo_id,), one=True)
    if not photo or photo['user_id'] != user['id']:
        abort(403)
    folder = PUBLIC_DIR if photo['is_public'] == 1 else PRIVATE_DIR
    path = os.path.join(folder, photo['filename'])
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    if photo['thumb_filename']:
        tpath = os.path.join(folder, photo['thumb_filename'])
        try:
            if os.path.exists(tpath):
                os.remove(tpath)
        except Exception:
            pass
    # Delete DB record (原生 SQL)
    execute_db('DELETE FROM photos WHERE id = ?', (photo_id,))
    flash('已删除')
    return redirect(url_for('gallery'))
if __name__ == '__main__':
    # create DB if missing (safe)
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True)
