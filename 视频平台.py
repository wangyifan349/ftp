#!/usr/bin/env python3
# app.py - 视频平台
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import (Flask, g, render_template_string, request, redirect,
                   url_for, flash, session, send_file, abort, Response)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# -------- 配置 --------
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_ROOT = BASE_DIR / "uploads"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
DATABASE = INSTANCE_DIR / "app.db"
ALLOWED_EXT = {'mp4', 'webm', 'ogg', 'mov', 'mkv'}
MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2GB
app = Flask(__name__)
app.config['DATABASE'] = str(DATABASE)
app.config['UPLOAD_ROOT'] = str(UPLOAD_ROOT)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.secret_key = os.environ.get('APP_SECRET', 'dev-secret-change-me')
# -------- DB schema --------
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL,
  filename TEXT NOT NULL,
  original_name TEXT NOT NULL,
  mimetype TEXT NOT NULL,
  is_public INTEGER NOT NULL DEFAULT 0,
  uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

# -------- DB helpers --------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON;")
        g._database = db
    return db

def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
# -------- Utilities --------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    cur = db.execute("SELECT id, username FROM users WHERE id = ?", (uid,))
    return cur.fetchone()
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            flash("请先登录")
            return redirect(url_for('login', next=request.path))
        return fn(*a, **kw)
    return wrapper
# -------- Templates (嵌入单文件) --------
BASE_HTML = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>视频平台</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-light mb-4">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频平台</a>
    <div class="collapse navbar-collapse">
      <form class="d-flex ms-auto" action="{{ url_for('index') }}" method="get">
        <input class="form-control me-2" type="search" placeholder="搜索用户名" name="q" value="{{ q or '' }}">
        <button class="btn btn-outline-primary" type="submit">搜索</button>
      </form>
      <ul class="navbar-nav ms-3">
        {% if user %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('my_videos') }}">我的视频</a></li>
          <li class="nav-item"><span class="nav-link">Hi, {{ user.username }}</span></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="mb-3">
        {% for m in messages %}<div class="alert alert-info">{{ m }}</div>{% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
INDEX_HTML = """
{% extends "base" %}
{% block content %}
<div class="row">
  <div class="col-md-8">
    <h4>最新公开视频</h4>
    {% if videos %}
      <div class="list-group">
      {% for v in videos %}
        <a class="list-group-item list-group-item-action" href="{{ url_for('play', video_id=v['id']) }}">
          <strong>{{ v['original_name'] }}</strong>
          <div class="small text-muted">上传者：{{ v['username'] }} · {{ v['uploaded_at'] }}</div>
        </a>
      {% endfor %}
      </div>
    {% else %}
      <p>暂无公开视频。</p>
    {% endif %}
  </div>
  <div class="col-md-4">
    <h5>用户搜索</h5>
    <form action="{{ url_for('index') }}" method="get" class="mb-3">
      <div class="input-group">
        <input name="q" class="form-control" placeholder="用户名" value="{{ q or '' }}">
        <button class="btn btn-primary">搜索</button>
      </div>
    </form>
    {% if users %}
      <ul class="list-group">
        {% for u in users %}
          <li class="list-group-item"><a href="{{ url_for('user_videos', username=u['username']) }}">{{ u['username'] }}</a></li>
        {% endfor %}
      </ul>
    {% endif %}
  </div>
</div>
{% endblock %}
"""
REGISTER_HTML = """
{% extends "base" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>注册</h3>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input name="username" class="form-control" required>
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      <button class="btn btn-primary">注册</button>
    </form>
  </div>
</div>
{% endblock %}
"""
LOGIN_HTML = """
{% extends "base" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>登录</h3>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input name="username" class="form-control" required>
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      <button class="btn btn-primary">登录</button>
    </form>
  </div>
</div>
{% endblock %}
"""
UPLOAD_HTML = """
{% extends "base" %}
{% block content %}
<div class="row">
  <div class="col-md-8">
    <h3>上传视频</h3>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label class="form-label">选择视频</label>
        <input type="file" name="file" accept="video/*" class="form-control" required>
      </div>
      <div class="form-check mb-3">
        <input class="form-check-input" type="checkbox" id="is_public" name="is_public">
        <label class="form-check-label" for="is_public">公开视频（所有人可见）</label>
      </div>
      <button class="btn btn-success">上传</button>
    </form>
  </div>
</div>
{% endblock %}
"""
MY_VIDEOS_HTML = """
{% extends "base" %}
{% block content %}
<h3>我的视频</h3>
{% if videos %}
  <table class="table">
    <thead><tr><th>名称</th><th>可见性</th><th>上传时间</th><th>操作</th></tr></thead>
    <tbody>
      {% for v in videos %}
      <tr>
        <td>{{ v['original_name'] }}</td>
        <td>{{ '公开' if v['is_public'] else '私有' }}</td>
        <td>{{ v['uploaded_at'] }}</td>
        <td>
          <a class="btn btn-sm btn-primary" href="{{ url_for('play', video_id=v['id']) }}">播放</a>
          <form style="display:inline" method="post" action="{{ url_for('toggle_visibility', video_id=v['id']) }}">
            <button class="btn btn-sm btn-secondary" type="submit">{{ '设为私有' if v['is_public'] else '设为公开' }}</button>
          </form>
          <form style="display:inline" method="post" action="{{ url_for('delete_video', video_id=v['id']) }}" onsubmit="return confirm('确认删除？')">
            <button class="btn btn-sm btn-danger" type="submit">删除</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
{% else %}
  <p>还没有上传视频。<a href="{{ url_for('upload') }}">现在上传</a></p>
{% endif %}
{% endblock %}
"""
USER_VIDEOS_HTML = """
{% extends "base" %}
{% block content %}
<h3>{{ owner['username'] }} 的公开视频</h3>
{% if videos %}
  <div class="list-group">
    {% for v in videos %}
      <a class="list-group-item list-group-item-action" href="{{ url_for('play', video_id=v['id']) }}">{{ v['original_name'] }} <div class="small text-muted">{{ v['uploaded_at'] }}</div></a>
    {% endfor %}
  </div>
{% else %}
  <p>暂无公开视频。</p>
{% endif %}
{% endblock %}
"""
PLAY_HTML = """
{% extends "base" %}
{% block content %}
<h4>{{ video['original_name'] }}</h4>
<div class="mb-3">
  <video controls style="max-width:100%">
    <source src="{{ url_for('stream', video_id=video['id']) }}" type="{{ video['mimetype'] }}">
    你的浏览器不支持 video 标签。
  </video>
</div>
<p>
  {% if video['is_public'] or (user and user['id']==video['owner_id']) %}
    <a class="btn btn-outline-primary" href="{{ url_for('download', video_id=video['id']) }}">下载</a>
  {% endif %}
</p>
{% endblock %}
"""
# Template loader wrapper
def render(tpl, **ctx):
    # 支持 base 模板通过 render_template_string 的继承
    templates = {
        'base': BASE_HTML,
        'index': INDEX_HTML,
        'register': REGISTER_HTML,
        'login': LOGIN_HTML,
        'upload': UPLOAD_HTML,
        'my_videos': MY_VIDEOS_HTML,
        'user_videos': USER_VIDEOS_HTML,
        'play': PLAY_HTML,
    }
    # 合并：先把 base 放入环境名 "base"
    env = { 'base': templates['base'] }
    # Build source by putting desired template and referencing base by name
    src = "{% extends 'base' %}\n" + tpl if tpl.strip().startswith("{% extends") else tpl
    # Use a small trick: render_template_string can accept a dict of templates only by injecting base into context
    # We'll replace {% extends "base" %} with actual base content by using a mini template engine: set base in globals
    # Simpler: combine base and tpl into a single template where base is defined as a block and tpl extends it.
    # We'll create a combined string where base is defined as a macro and then tpl uses it — but Jinja inheritance needs loader.
    # Workaround: use a combined template with the base inserted, then the child template content after (child extends will see base).
    combined = templates['base'] + "\n" + tpl
    return render_template_string(combined, **ctx)
# -------- Routes --------
@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    db = get_db()
    users = []
    if q:
        cur = db.execute("SELECT id, username FROM users WHERE username LIKE ? LIMIT 50", (f'%{q}%',))
        users = cur.fetchall()
    cur = db.execute("""
        SELECT v.id, v.original_name, v.mimetype, v.uploaded_at, u.username
        FROM videos v JOIN users u ON v.owner_id = u.id
        WHERE v.is_public = 1
        ORDER BY v.uploaded_at DESC LIMIT 20
    """)
    videos = cur.fetchall()
    return render(INDEX_HTML, users=users, videos=videos, q=q, user=current_user())
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("用户名和密码不能为空")
            return redirect(url_for('register'))
        db = get_db()
        cur = db.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            flash("用户名已存在")
            return redirect(url_for('register'))
        pwd_hash = generate_password_hash(password)
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pwd_hash))
        db.commit()
        user_dir = Path(app.config['UPLOAD_ROOT']) / username
        user_dir.mkdir(parents=True, exist_ok=True)
        flash("注册成功，请登录")
        return redirect(url_for('login'))
    return render(REGISTER_HTML, user=current_user())
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        cur = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row or not check_password_hash(row['password_hash'], password):
            flash("用户名或密码错误")
            return redirect(url_for('login'))
        session.clear()
        session['user_id'] = row['id']
        flash("登录成功")
        next_url = request.args.get('next') or url_for('index')
        return redirect(next_url)
    return render(LOGIN_HTML, user=current_user())
@app.route('/logout')
def logout():
    session.clear()
    flash("已登出")
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    user = current_user()
    if request.method == 'POST':
        file = request.files.get('file')
        is_public = 1 if request.form.get('is_public') == 'on' else 0
        if not file or file.filename == '':
            flash("请选择文件")
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash("不支持的文件类型")
            return redirect(url_for('upload'))
        filename_secure = secure_filename(file.filename)
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        stored_name = f"{ts}_{filename_secure}"
        user_dir = Path(app.config['UPLOAD_ROOT']) / user['username']
        user_dir.mkdir(parents=True, exist_ok=True)
        save_path = user_dir / stored_name
        file.save(save_path)
        db = get_db()
        db.execute("""INSERT INTO videos (owner_id, filename, original_name, mimetype, is_public)
                      VALUES (?, ?, ?, ?, ?)""",
                   (user['id'], stored_name, filename_secure, file.mimetype or 'application/octet-stream', is_public))
        db.commit()
        flash("上传成功")
        return redirect(url_for('my_videos'))
    return render(UPLOAD_HTML, user=user)

@app.route('/my_videos')
@login_required
def my_videos():
    user = current_user()
    db = get_db()
    cur = db.execute("SELECT * FROM videos WHERE owner_id = ? ORDER BY uploaded_at DESC", (user['id'],))
    videos = cur.fetchall()
    return render(MY_VIDEOS_HTML, user=user, videos=videos)
@app.route('/toggle_visibility/<int:video_id>', methods=['POST'])
@login_required
def toggle_visibility(video_id):
    user = current_user()
    db = get_db()
    cur = db.execute("SELECT owner_id, is_public FROM videos WHERE id = ?", (video_id,))
    v = cur.fetchone()
    if not v:
        abort(404)
    if v['owner_id'] != user['id']:
        abort(403)
    new = 0 if v['is_public'] else 1
    db.execute("UPDATE videos SET is_public = ? WHERE id = ?", (new, video_id))
    db.commit()
    flash("可见性已更新")
    return redirect(url_for('my_videos'))
@app.route('/delete_video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    user = current_user()
    db = get_db()
    cur = db.execute("SELECT owner_id, filename FROM videos WHERE id = ?", (video_id,))
    v = cur.fetchone()
    if not v:
        abort(404)
    if v['owner_id'] != user['id']:
        abort(403)
    user_row = db.execute("SELECT username FROM users WHERE id = ?", (user['id'],)).fetchone()
    filepath = Path(app.config['UPLOAD_ROOT']) / user_row['username'] / v['filename']
    try:
        if filepath.exists():
            filepath.unlink()
    except Exception:
        pass
    db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    db.commit()
    flash("已删除")
    return redirect(url_for('my_videos'))
@app.route('/user/<username>')
def user_videos(username):
    db = get_db()
    cur_u = db.execute("SELECT id, username FROM users WHERE username = ?", (username,))
    u = cur_u.fetchone()
    if not u:
        abort(404)
    cur = db.execute("""
      SELECT id, original_name, uploaded_at
      FROM videos
      WHERE owner_id = ? AND is_public = 1
      ORDER BY uploaded_at DESC
    """, (u['id'],))
    videos = cur.fetchall()
    return render(USER_VIDEOS_HTML, user=current_user(), owner=u, videos=videos)
@app.route('/play/<int:video_id>')
def play(video_id):
    db = get_db()
    cur = db.execute("SELECT v.*, u.username FROM videos v JOIN users u ON v.owner_id = u.id WHERE v.id = ?", (video_id,))
    v = cur.fetchone()
    if not v:
        abort(404)
    viewer = current_user()
    if v['is_public'] == 0:
        if not viewer or viewer['id'] != v['owner_id']:
            abort(403)
    return render(PLAY_HTML, video=v, user=viewer)
@app.route('/stream/<int:video_id>')
def stream(video_id):
    db = get_db()
    cur = db.execute("SELECT v.*, u.username FROM videos v JOIN users u ON v.owner_id = u.id WHERE v.id = ?", (video_id,))
    v = cur.fetchone()
    if not v:
        abort(404)
    viewer = current_user()
    if v['is_public'] == 0 and (not viewer or viewer['id'] != v['owner_id']):
        abort(403)
    file_path = Path(app.config['UPLOAD_ROOT']) / v['username'] / v['filename']
    if not file_path.exists():
        abort(404)
    file_size = file_path.stat().st_size
    range_header = request.headers.get('Range', None)
    if not range_header:
        return send_file(str(file_path), mimetype=v['mimetype'])
    # 解析 range
    byte1, byte2 = 0, None
    m = range_header.replace('bytes=', '').split('-')
    try:
        if m[0]:
            byte1 = int(m[0])
        if len(m) > 1 and m[1]:
            byte2 = int(m[1])
    except ValueError:
        return abort(416)
    start = byte1
    end = byte2 if byte2 is not None else file_size - 1
    if end >= file_size:
        end = file_size - 1
    if start > end:
        return abort(416)
    length = end - start + 1
    def generate():
        with open(file_path, 'rb') as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(8192 if remaining >= 8192 else remaining)
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
    rv = Response(generate(), status=206, mimetype=v['mimetype'],
                  headers={
                      'Content-Range': f'bytes {start}-{end}/{file_size}',
                      'Accept-Ranges': 'bytes',
                      'Content-Length': str(length)
                  })
    return rv
@app.route('/download/<int:video_id>')
def download(video_id):
    db = get_db()
    cur = db.execute("SELECT v.*, u.username FROM videos v JOIN users u ON v.owner_id = u.id WHERE v.id = ?", (video_id,))
    v = cur.fetchone()
    if not v:
        abort(404)
    viewer = current_user()
    if v['is_public'] == 0 and (not viewer or viewer['id'] != v['owner_id']):
        abort(403)
    file_path = Path(app.config['UPLOAD_ROOT']) / v['username'] / v['filename']
    if not file_path.exists():
        abort(404)
    return send_file(str(file_path), as_attachment=True, download_name=v['original_name'], mimetype=v['mimetype'])
# 初始化 DB（若不存在）
if not DATABASE.exists():
    with app.app_context():
        init_db()
        print("Initialized DB at", DATABASE)
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
