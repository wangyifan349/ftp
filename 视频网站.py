import os
import sqlite3
from datetime import datetime
from flask import Flask, g, request, redirect, url_for, flash, session, send_from_directory, abort, render_template_string
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# ---------------- Config ----------------
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(APP_ROOT, 'static', 'uploads')
DATABASE_PATH = os.path.join(APP_ROOT, 'app.db')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DATABASE'] = DATABASE_PATH
app.secret_key = 'change_this_secret_for_prod'  # change to secure random value in production
# ---------------- Database helpers ----------------
def get_db():
    """
    Return a sqlite3.Connection stored in flask.g.
    Initialize DB if file does not exist.
    """
    db = getattr(g, '_database', None)
    if db is None:
        need_init = not os.path.exists(app.config['DATABASE'])
        db = g._database = sqlite3.connect(app.config['DATABASE'], check_same_thread=False)
        db.row_factory = sqlite3.Row
        if need_init:
            init_db(db)
    return db
def init_db(db_conn):
    """
    Initialize database schema.
    """
    schema_sql = """
    BEGIN TRANSACTION;
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS media (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      filename TEXT NOT NULL,
      title TEXT,
      is_public INTEGER DEFAULT 1,
      is_deleted INTEGER DEFAULT 0,
      uploaded_at TEXT,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    COMMIT;
    """
    db_conn.executescript(schema_sql)
    db_conn.commit()
@app.teardown_appcontext
def close_db_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
# ---------------- Utilities ----------------
def allowed_file(filename):
    """
    Check if file extension is allowed.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def lcs_length(a: str, b: str) -> int:
    """
    Compute length of Longest Common Subsequence (LCS) between strings a and b.
    Uses dynamic programming (O(len(a)*len(b))).
    """
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la - 1, -1, -1):
        for j in range(lb - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = 1 + dp[i + 1][j + 1]
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    return dp[0][0]
def username_similarity(a: str, b: str) -> float:
    """
    Compute similarity between two usernames using LCS length normalized by length of longer string.
    Returns float in [0.0, 1.0].
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    lcs = lcs_length(a.lower(), b.lower())
    longer = max(len(a), len(b))
    return lcs / longer
def get_all_users():
    """
    Query and return all users (id, username).
    """
    db = get_db()
    cur = db.execute('SELECT id, username FROM users')
    return cur.fetchall()
# ---------------- Templates (inline) ----------------
# Note: page text remains Chinese to keep site language; variables, ids, comments are English.
base_template = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or '视频站' }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding-top: 4.5rem; }
      .media-card { margin-bottom: 1.25rem; }
      .thumb { max-width:100%; height:auto; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-md navbar-dark bg-dark fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('index') }}">视频站</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarsExampleDefault" aria-controls="navbarsExampleDefault" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarsExampleDefault">
          <ul class="navbar-nav me-auto mb-2 mb-md-0">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('search') }}">搜索用户</a></li>
            {% if session.get('user_id') %}
            <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
            {% endif %}
          </ul>
          <ul class="navbar-nav ms-auto mb-2 mb-md-0">
            {% if session.get('user_id') %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('profile', user_id=session['user_id']) }}">我的主页 ({{ session.get('username') }})</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('change_password') }}">改密</a></li>
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
            <div class="alert alert-info alert-dismissible fade show" role="alert">
              {{ m }}
              <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
          {% endfor %}
          </div>
        {% endif %}
      {% endwith %}

      {{ body }}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""
index_template = """
{% set title='首页' %}
{% block body %}
  <h1 class="mb-3">最新公开媒体</h1>
  {% if medias %}
    <div class="row">
      {% for m in medias %}
      <div class="col-md-6 media-card">
        <div class="card">
          <div class="card-body">
            <h5 class="card-title">{{ m['title'] or '(无标题)' }}</h5>
            <h6 class="card-subtitle mb-2 text-muted">by <a href="{{ url_for('profile', user_id=m['user_id']) }}">{{ m['username'] }}</a></h6>
            {% set ext = m['filename'].rsplit('.',1)[1].lower() %}
            {% if ext in ['mp4','webm','ogg'] %}
              <video class="thumb" controls>
                <source src="{{ url_for('media_file', user_id=m['user_id'], filename=m['filename']) }}">
                您的浏览器不支持 video 标签。
              </video>
            {% else %}
              <img class="thumb" src="{{ url_for('media_file', user_id=m['user_id'], filename=m['filename']) }}" alt="thumb">
            {% endif %}
            <p class="mt-2"><small class="text-muted">上传: {{ m['uploaded_at'] or '' }}</small></p>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="alert alert-secondary">暂无公开媒体</div>
  {% endif %}
{% endblock %}
"""

register_template = """
{% set title='注册' %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <h2>注册</h2>
      <form method="post" novalidate>
        <div class="mb-3">
          <label class="form-label">用户名</label>
          <input class="form-control" name="username" required>
        </div>
        <div class="mb-3">
          <label class="form-label">密码</label>
          <input class="form-control" type="password" name="password" required>
        </div>
        <button class="btn btn-primary" type="submit">注册</button>
        <a class="btn btn-link" href="{{ url_for('login') }}">已有账号？登录</a>
      </form>
    </div>
  </div>
{% endblock %}
"""

login_template = """
{% set title='登录' %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <h2>登录</h2>
      <form method="post" novalidate>
        <div class="mb-3">
          <label class="form-label">用户名</label>
          <input class="form-control" name="username" required>
        </div>
        <div class="mb-3">
          <label class="form-label">密码</label>
          <input class="form-control" type="password" name="password" required>
        </div>
        <button class="btn btn-primary" type="submit">登录</button>
        <a class="btn btn-link" href="{{ url_for('register') }}">注册新账号</a>
      </form>
    </div>
  </div>
{% endblock %}
"""

change_password_template = """
{% set title='修改密码' %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <h2>修改密码</h2>
      <form method="post" novalidate>
        <div class="mb-3">
          <label class="form-label">旧密码</label>
          <input class="form-control" type="password" name="old_password" required>
        </div>
        <div class="mb-3">
          <label class="form-label">新密码</label>
          <input class="form-control" type="password" name="new_password" required>
        </div>
        <button class="btn btn-primary" type="submit">提交</button>
      </form>
    </div>
  </div>
{% endblock %}
"""

upload_template = """
{% set title='上传媒体' %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-8">
      <h2>上传媒体</h2>
      <form method="post" enctype="multipart/form-data" novalidate>
        <div class="mb-3">
          <label class="form-label">标题（可选）</label>
          <input class="form-control" name="title">
        </div>
        <div class="mb-3">
          <label class="form-label">选择文件</label>
          <input class="form-control" type="file" name="file" required>
          <div class="form-text">支持: png, jpg, jpeg, gif, mp4, webm, ogg</div>
        </div>
        <div class="form-check mb-3">
          <input class="form-check-input" type="checkbox" name="is_public" id="is_public" checked>
          <label class="form-check-label" for="is_public">公开</label>
        </div>
        <button class="btn btn-primary" type="submit">上传</button>
      </form>
    </div>
  </div>
{% endblock %}
"""

profile_template = """
{% set title = user['username'] ~ ' 的主页' %}
{% block body %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h2>{{ user['username'] }} 的主页</h2>
    <div>
      <a class="btn btn-sm btn-secondary" href="{{ url_for('index') }}">返回首页</a>
      {% if session.get('user_id') and session.get('user_id') == user['id'] %}
        <a class="btn btn-sm btn-primary" href="{{ url_for('upload') }}">上传</a>
      {% endif %}
    </div>
  </div>

  {% if medias %}
    <div class="row">
      {% for m in medias %}
      <div class="col-md-6 media-card">
        <div class="card">
          <div class="card-body">
            <h5 class="card-title">{{ m['title'] or '(无标题)' }}</h5>
            <p class="text-muted">状态: {% if m['is_deleted'] %}已删除{% else %}{{ '公开' if m['is_public'] else '隐藏' }}{% endif %}</p>
            {% set ext = m['filename'].rsplit('.',1)[1].lower() %}
            {% if ext in ['mp4','webm','ogg'] %}
              <video class="thumb" controls>
                <source src="{{ url_for('media_file', user_id=m['user_id'], filename=m['filename']) }}">
                您的浏览器不支持 video 标签。
              </video>
            {% else %}
              <img class="thumb" src="{{ url_for('media_file', user_id=m['user_id'], filename=m['filename']) }}" alt="thumb">
            {% endif %}
            <p class="mt-2"><small class="text-muted">上传: {{ m['uploaded_at'] or '' }}</small></p>

            {% if session.get('user_id') and session.get('user_id') == user['id'] and not m['is_deleted'] %}
              <form class="d-inline" method="post" action="{{ url_for('media_action', media_id=m['id'], action='toggle_public') }}">
                <button class="btn btn-sm btn-outline-secondary" type="submit">{{ '隐藏' if m['is_public'] else '公开' }}</button>
              </form>
              <form class="d-inline" method="post" action="{{ url_for('media_action', media_id=m['id'], action='delete') }}" onsubmit="return confirm('确定删除？');">
                <button class="btn btn-sm btn-danger" type="submit">删除</button>
              </form>
            {% endif %}
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="alert alert-secondary">暂无媒体</div>
  {% endif %}
{% endblock %}
"""

search_template = """
{% set title='搜索用户' %}
{% block body %}
  <h2 class="mb-3">搜索用户</h2>
  <form class="row g-2 mb-3" method="get">
    <div class="col-auto" style="flex:1">
      <input class="form-control" name="q" placeholder="输入用户名" value="{{ q }}">
    </div>
    <div class="col-auto">
      <button class="btn btn-primary" type="submit">搜索</button>
    </div>
  </form>

  {% if q %}
    <h5>结果 (按相似度降序)</h5>
    {% if results %}
      <ul class="list-group">
      {% for r in results %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <a href="{{ url_for('profile', user_id=r['id']) }}">{{ r['username'] }}</a>
          <span class="badge bg-primary rounded-pill">{{ ('%.2f' % r['sim']) }}</span>
        </li>
      {% endfor %}
      </ul>
    {% else %}
      <div class="alert alert-secondary">无匹配结果</div>
    {% endif %}
  {% endif %}
{% endblock %}
"""
# ---------------- Routes ----------------
@app.route('/')
def index():
    db = get_db()
    cur = db.execute(
        'SELECT m.id, m.title, m.filename, m.user_id, u.username, m.uploaded_at '
        'FROM media m JOIN users u ON m.user_id=u.id '
        'WHERE m.is_public=1 AND m.is_deleted=0 '
        'ORDER BY m.uploaded_at DESC LIMIT 20'
    )
    medias = cur.fetchall()
    body = render_template_string(index_template, medias=medias)
    return render_template_string(base_template, body=body)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        db = get_db()
        existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if existing:
            flash('用户名已存在')
            return redirect(url_for('register'))
        pw_hash = generate_password_hash(password)
        db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
        db.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    body = render_template_string(register_template)
    return render_template_string(base_template, body=body)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        db = get_db()
        user = db.execute('SELECT id, username, password_hash FROM users WHERE username=?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('登录成功')
            return redirect(url_for('index'))
        flash('用户名或密码错误')
        return redirect(url_for('login'))
    body = render_template_string(login_template)
    return render_template_string(base_template, body=body)
@app.route('/logout')
def logout():
    session.clear()
    flash('已登出')
    return redirect(url_for('index'))
@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        old_password = request.form.get('old_password') or ''
        new_password = request.form.get('new_password') or ''
        if not old_password or not new_password:
            flash('请填写旧密码和新密码')
            return redirect(url_for('change_password'))
        db = get_db()
        user = db.execute('SELECT password_hash FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if not user or not check_password_hash(user['password_hash'], old_password):
            flash('旧密码错误')
            return redirect(url_for('change_password'))
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash(new_password), session['user_id']))
        db.commit()
        flash('密码已更新')
        return redirect(url_for('index'))
    body = render_template_string(change_password_template)
    return render_template_string(base_template, body=body)
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        upload_file = request.files.get('file')
        is_public = 1 if request.form.get('is_public') == 'on' else 0
        if not upload_file or upload_file.filename == '':
            flash('请选择文件')
            return redirect(url_for('upload'))
        if not allowed_file(upload_file.filename):
            flash('不支持的文件类型')
            return redirect(url_for('upload'))
        filename = secure_filename(upload_file.filename)
        user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(session['user_id']))
        os.makedirs(user_folder, exist_ok=True)
        save_path = os.path.join(user_folder, filename)
        if os.path.exists(save_path):
            base, ext = os.path.splitext(filename)
            filename = f"{base}_{int(datetime.utcnow().timestamp())}{ext}"
            save_path = os.path.join(user_folder, filename)
        upload_file.save(save_path)
        db = get_db()
        db.execute(
            'INSERT INTO media (user_id, filename, title, is_public, is_deleted, uploaded_at) VALUES (?, ?, ?, ?, 0, ?)',
            (session['user_id'], filename, title, is_public, datetime.utcnow().isoformat())
        )
        db.commit()
        flash('上传成功')
        return redirect(url_for('profile', user_id=session['user_id']))
    body = render_template_string(upload_template)
    return render_template_string(base_template, body=body)
@app.route('/media/<int:user_id>/<path:filename>')
def media_file(user_id, filename):
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))
    full_path = os.path.join(user_folder, filename)
    if not os.path.exists(full_path):
        abort(404)
    return send_from_directory(user_folder, filename)
@app.route('/profile/<int:user_id>')
def profile(user_id):
    db = get_db()
    user = db.execute('SELECT id, username FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        abort(404)
    if 'user_id' in session and session['user_id'] == user_id:
        cur = db.execute('SELECT * FROM media WHERE user_id=? AND is_deleted=0 ORDER BY uploaded_at DESC', (user_id,))
    else:
        cur = db.execute('SELECT * FROM media WHERE user_id=? AND is_deleted=0 AND is_public=1 ORDER BY uploaded_at DESC', (user_id,))
    medias = cur.fetchall()
    body = render_template_string(profile_template, user=user, medias=medias)
    return render_template_string(base_template, body=body)
@app.route('/media_action/<int:media_id>/<action>', methods=['POST'])
def media_action(media_id, action):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    media_row = db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
    if not media_row or media_row['user_id'] != session['user_id']:
        abort(403)
    if action == 'toggle_public':
        new_public = 0 if media_row['is_public'] else 1
        db.execute('UPDATE media SET is_public=? WHERE id=?', (new_public, media_id))
    elif action == 'delete':
        db.execute('UPDATE media SET is_deleted=1 WHERE id=?', (media_id,))
    else:
        abort(400)
    db.commit()
    flash('操作已完成')
    return redirect(url_for('profile', user_id=session['user_id']))
@app.route('/search', methods=['GET'])
def search():
    q = (request.args.get('q') or '').strip()
    users = get_all_users()
    results = []
    if q:
        for u in users:
            sim = username_similarity(q, u['username'])
            results.append({'id': u['id'], 'username': u['username'], 'sim': sim})
        results.sort(key=lambda x: x['sim'], reverse=True)
    body = render_template_string(search_template, q=q, results=results)
    return render_template_string(base_template, body=body)
# ---------------- Run ----------------
if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5000)
