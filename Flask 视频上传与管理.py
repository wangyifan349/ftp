# app.py
"""
单文件 Flask 视频上传与管理示例（带 Bootstrap 美化）
依赖:
  pip install Flask Flask-WTF Flask-SQLAlchemy WTForms
运行:
  python app.py
访问:
  http://127.0.0.1:5000/
"""

import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import (
    Flask, render_template_string, request, redirect, url_for, flash,
    session, send_from_directory, abort, g
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# --- 配置 ---
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov', 'mkv'}
DB_PATH = BASE_DIR / 'app.db'
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-change-me'  # 生产请修改
app.config['UPLOAD_ROOT'] = str(UPLOAD_ROOT)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 例如 500MB 上限，可按需调整
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
# --- 原生 SQLite 辅助 ---
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(str(DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
@app.teardown_appcontext
def teardown_db(exception):
    close_db(exception)
def init_db():
    db = get_db()
    db.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS video (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        title TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(owner_id) REFERENCES user(id) ON DELETE CASCADE
    );
    """)
    db.commit()
with app.app_context():
    init_db()
# --- 模板（保留原结构，仅替换表单渲染） ---
base_tpl = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>视频站</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {{ background:#f8f9fa; }}
    .card-video video {{ max-height:360px; width:100%; object-fit:contain; }}
    .user-badge {{ font-weight:600; }}
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频站</a>
    <div class="collapse navbar-collapse">
      <form class="d-flex ms-3" method="post" action="{{ url_for('index') }}">
        <input type="hidden" name="csrf_token" value="">
        <input name="query" class="form-control me-2" placeholder="搜索用户名">
        <button class="btn btn-outline-light" type="submit">搜索</button>
      </form>
    </div>
    <div class="d-flex">
      {% if session.get('username') %}
        <span class="navbar-text text-light me-2">你好，<span class="user-badge">{{ session.username }}</span></span>
        <a class="btn btn-light btn-sm me-2" href="{{ url_for('dashboard') }}">面板</a>
        <a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}">登出</a>
      {% else %}
        <a class="btn btn-light btn-sm me-2" href="{{ url_for('login') }}">登录</a>
        <a class="btn btn-outline-light btn-sm" href="{{ url_for('register') }}">注册</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container my-4">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      {% for m in messages %}
      <div class="alert alert-info">{{ m }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {{ content }}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

index_content = """
<div class="row">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title">发现用户</h4>
        <p class="text-muted">在上方搜索框中输入用户名进行查找，或浏览热门用户。</p>
        {% if users is not none %}
          {% if users %}
            <div class="list-group">
              {% for u in users %}
                <a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                   href="{{ url_for('user_profile', username=u['username']) }}">
                  <div>
                    <strong>{{ u['username'] }}</strong>
                    <div class="text-muted small">用户 ID: {{ u['id'] }}</div>
                  </div>
                  <span class="badge bg-primary rounded-pill">查看</span>
                </a>
              {% endfor %}
            </div>
          {% else %}
            <p class="text-muted">未找到用户。</p>
          {% endif %}
        {% else %}
          <p class="text-muted">输入用户名然后搜索。</p>
        {% endif %}
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">快速操作</h5>
        {% if session.get('username') %}
          <a class="btn btn-primary w-100 mb-2" href="{{ url_for('upload') }}">上传视频</a>
          <a class="btn btn-outline-primary w-100" href="{{ url_for('dashboard') }}">我的面板</a>
        {% else %}
          <p>登录后可上传并管理你的视频。</p>
          <a class="btn btn-primary w-100" href="{{ url_for('login') }}">登录</a>
        {% endif %}
      </div>
    </div>
  </div>
</div>
"""

auth_form_tpl = """
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">{{ title }}</h4>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">用户名</label>
            <input name="username" class="form-control" required minlength="3" maxlength="80">
          </div>
          <div class="mb-3">
            <label class="form-label">密码</label>
            <input name="password" type="password" class="form-control" required minlength="6" maxlength="128">
          </div>
          <div>
            <button class="btn btn-primary" type="submit">{{ submit_text }}</button>
            <a class="btn btn-link" href="{{ url_for('index') }}">返回</a>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
"""

dashboard_tpl = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4>个人面板 - {{ user['username'] }}</h4>
  <div>
    <a class="btn btn-success me-2" href="{{ url_for('upload') }}">上传视频</a>
    <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">返回首页</a>
  </div>
</div>

{% if videos %}
  <div class="row">
    {% for v in videos %}
      <div class="col-md-6 mb-4">
        <div class="card shadow-sm h-100">
          <div class="card-body d-flex flex-column">
            <h5 class="card-title">{{ v['title'] or v['filename'] }}</h5>
            <div class="card-video mb-3">
              <video controls preload="metadata">
                <source src="{{ url_for('uploaded_file', username=user['username'], filename=v['filename']) }}">
                您的浏览器不支持 video 标签。
              </video>
            </div>
            <div class="mt-auto d-flex justify-content-between align-items-center">
              <small class="text-muted">上传于 {{ v['created_at'] }}</small>
              <form method="post" action="{{ url_for('delete_video', video_id=v['id']) }}" onsubmit="return confirm('确认删除该视频？');">
                <button class="btn btn-danger btn-sm" type="submit">删除</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="card shadow-sm">
    <div class="card-body">
      <p class="text-muted">尚无视频。点击“上传视频”开始。 </p>
    </div>
  </div>
{% endif %}
"""

upload_tpl = """
<div class="row justify-content-center">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title">上传视频</h4>
        <form method="post" enctype="multipart/form-data">
          <div class="mb-3">
            <label class="form-label">标题（可选）</label>
            <input name="title" class="form-control" placeholder="可选：视频标题">
          </div>
          <div class="mb-3">
            <label class="form-label">视频文件</label>
            <input name="file" type="file" class="form-control" required>
            <div class="form-text">支持 mp4、webm、ogg、mov、mkv。单文件大小不超过服务器限制。</div>
          </div>
          <div>
            <button class="btn btn-primary" type="submit">上传</button>
            <a class="btn btn-link" href="{{ url_for('dashboard') }}">取消</a>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
"""

user_profile_tpl = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4>{{ profile_user['username'] }} 的主页</h4>
  <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">返回首页</a>
</div>

{% if videos %}
  <div class="row">
    {% for v in videos %}
      <div class="col-md-6 mb-4">
        <div class="card shadow-sm">
          <div class="card-body">
            <h5 class="card-title">{{ v['title'] or v['filename'] }}</h5>
            <div class="card-video mb-3">
              <video controls preload="metadata">
                <source src="{{ url_for('uploaded_file', username=profile_user['username'], filename=v['filename']) }}">
                您的浏览器不支持 video 标签。
              </video>
            </div>
            <small class="text-muted">上传于 {{ v['created_at'] }}</small>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="card shadow-sm">
    <div class="card-body">
      <p class="text-muted">该用户没有公开视频。</p>
    </div>
  </div>
{% endif %}
"""
# --- 工具 ---
def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录。')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper
# --- 路由 ---
@app.route('/', methods=['GET', 'POST'])
def index():
    users = None
    if request.method == 'POST':
        q = (request.form.get('query') or '').strip()
        if q:
            db = get_db()
            cur = db.execute("SELECT id, username FROM user WHERE username LIKE ? ORDER BY id DESC", (f"%{q}%",))
            users = cur.fetchall()
        else:
            users = []
    content = render_template_string(index_content, users=users)
    return render_template_string(base_tpl, content=content, session=session)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not (3 <= len(username) <= 80):
            flash('用户名长度应为 3-80 字符。')
            return redirect(url_for('register'))
        if not (6 <= len(password) <= 128):
            flash('密码长度应为 6-128 字符。')
            return redirect(url_for('register'))
        db = get_db()
        try:
            db.execute("INSERT INTO user (username, password_hash) VALUES (?, ?)",
                       (username, generate_password_hash(password)))
            db.commit()
        except sqlite3.IntegrityError:
            flash('用户名已存在。')
            return redirect(url_for('register'))
        flash('注册成功，请登录。')
        return redirect(url_for('login'))
    content = render_template_string(auth_form_tpl, title="注册", submit_text="注册")
    return render_template_string(base_tpl, content=content, session=session)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        db = get_db()
        cur = db.execute("SELECT id, username, password_hash FROM user WHERE username = ?", (username,))
        row = cur.fetchone()
        if row and check_password_hash(row['password_hash'], password):
            session.clear()
            session['user_id'] = row['id']
            session['username'] = row['username']
            flash('登录成功。')
            return redirect(url_for('dashboard'))
        flash('用户名或密码错误。')
    content = render_template_string(auth_form_tpl, title="登录", submit_text="登录")
    return render_template_string(base_tpl, content=content, session=session)
@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录。')
    return redirect(url_for('index'))
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    cur_u = db.execute("SELECT id, username FROM user WHERE id = ?", (session['user_id'],))
    user = cur_u.fetchone()
    cur = db.execute("SELECT id, filename, title, created_at FROM video WHERE owner_id = ? ORDER BY created_at DESC", (user['id'],))
    videos = cur.fetchall()
    # format created_at as string
    videos = [dict(v) for v in videos]
    for v in videos:
        v['created_at'] = v['created_at']
    content = render_template_string(dashboard_tpl, user=dict(user), videos=videos)
    return render_template_string(base_tpl, content=content, session=session)
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('未选择文件。')
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash('不支持的文件类型。')
            return redirect(url_for('upload'))
        filename = secure_filename(file.filename)
        base, ext = os.path.splitext(filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        saved_name = f"{base}_{timestamp}{ext}"
        user_folder = Path(app.config['UPLOAD_ROOT']) / session['username']
        user_folder.mkdir(parents=True, exist_ok=True)
        file_path = user_folder / saved_name
        file.save(str(file_path))
        db = get_db()
        db.execute("INSERT INTO video (owner_id, filename, title, created_at) VALUES (?, ?, ?, ?)",
                   (session['user_id'], saved_name, title or saved_name, datetime.utcnow()))
        db.commit()
        flash('上传成功。')
        return redirect(url_for('dashboard'))
    content = render_template_string(upload_tpl)
    return render_template_string(base_tpl, content=content, session=session)
@app.route('/user/<username>')
def user_profile(username):
    db = get_db()
    cur = db.execute("SELECT id, username FROM user WHERE username = ?", (username,))
    user = cur.fetchone()
    if not user:
        abort(404)
    cur = db.execute("SELECT id, filename, title, created_at FROM video WHERE owner_id = ? ORDER BY created_at DESC", (user['id'],))
    videos = [dict(r) for r in cur.fetchall()]
    content = render_template_string(user_profile_tpl, profile_user=dict(user), videos=videos)
    return render_template_string(base_tpl, content=content, session=session)
@app.route('/uploads/<username>/<filename>')
def uploaded_file(username, filename):
    user_folder = Path(app.config['UPLOAD_ROOT']) / username
    file_path = user_folder / filename
    if not file_path.exists():
        abort(404)
    # Security: ensure the requested path is inside the user folder
    try:
        file_path.relative_to(user_folder)
    except Exception:
        abort(404)
    return send_from_directory(str(user_folder), filename)
@app.route('/delete/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    db = get_db()
    cur = db.execute("SELECT id, owner_id, filename FROM video WHERE id = ?", (video_id,))
    vid = cur.fetchone()
    if not vid:
        abort(404)
    if vid['owner_id'] != session['user_id']:
        abort(403)
    user_folder = Path(app.config['UPLOAD_ROOT']) / session['username']
    file_path = user_folder / vid['filename']
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass
    db.execute("DELETE FROM video WHERE id = ?", (video_id,))
    db.commit()
    flash('视频已删除。')
    return redirect(url_for('dashboard'))
# --- 启动 ---
if __name__ == '__main__':
    app.run(debug=True)
