# app.py
import os, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, g, render_template_string, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = 'forum.db'
SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-secret')
DEBUG = True

app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET_KEY, DEBUG=DEBUG)

def get_db():
    db = getattr(g, '_db_conn', None)
    if db is None:
        db = g._db_conn = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db_connection(exc):
    db = getattr(g, '_db_conn', None)
    if db is not None:
        db.close()

def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        author_id INTEGER NOT NULL,
        moderator_id INTEGER,
        closed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(author_id) REFERENCES users(id),
        FOREIGN KEY(moderator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        ip TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(post_id) REFERENCES posts(id),
        FOREIGN KEY(author_id) REFERENCES users(id)
    );
    """
    db = get_db()
    db.executescript(schema)
    db.commit()

def login_required(view_fn):
    @wraps(view_fn)
    def wrapped_view(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return view_fn(*args, **kwargs)
    return wrapped_view

def get_current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    return db.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()

def lcs_length(a: str, b: str) -> int:
    if not a or not b:
        return 0
    n, m = len(a), len(b)
    dp = [0] * (m + 1)
    for i in range(1, n + 1):
        prev = 0
        ai = a[i - 1]
        for j in range(1, m + 1):
            temp = dp[j]
            if ai == b[j - 1]:
                dp[j] = prev + 1
            else:
                dp[j] = max(dp[j], dp[j - 1])
            prev = temp
    return dp[m]

def compute_match_score(post_row, query):
    q = (query or '').lower()
    title = (post_row['title'] or '').lower()
    body = (post_row['body'] or '').lower()
    s_title = lcs_length(title, q)
    s_body = lcs_length(body, q)
    return s_title * 3 + s_body

BASE_HTML = """<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>简单论坛</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet"><style>.small-muted{font-size:0.85rem;color:#6c757d}.meta-small{font-size:0.78rem;color:#6c757d}.ip-small{font-size:0.72rem;color:#888}.container{max-width:900px}</style></head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-light mb-4"><div class="container"><a class="navbar-brand" href="{{ url_for('index') }}">简易论坛</a><div class="collapse navbar-collapse"><form class="d-flex ms-auto" method="get" action="{{ url_for('index') }}"><input class="form-control me-2" name="q" placeholder="搜索帖子（支持模糊 LCS）" value="{{ request.args.get('q','') }}"><button class="btn btn-outline-primary" type="submit">搜索</button></form><ul class="navbar-nav ms-3">{% if user %}<li class="nav-item"><span class="nav-link">你好，{{ user['username'] }}</span></li><li class="nav-item"><a class="nav-link" href="{{ url_for('create_post') }}">发帖</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>{% else %}<li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>{% endif %}</ul></div></div></nav>
<div class="container">{% with messages = get_flashed_messages() %}{% if messages %}<div class="mb-3">{% for m in messages %}<div class="alert alert-info">{{ m }}</div>{% endfor %}</div>{% endif %}{% endwith %}{% block content %}{% endblock %}</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script></body></html>"""

@app.route('/', methods=['GET'])
def index():
    db = get_db()
    query = (request.args.get('q') or '').strip()
    rows = db.execute('''SELECT p.*, a.username AS author_name, m.username AS moderator_name FROM posts p JOIN users a ON p.author_id = a.id LEFT JOIN users m ON p.moderator_id = m.id ORDER BY p.created_at DESC''').fetchall()
    posts = list(rows)
    if query:
        scored = []
        for r in posts:
            score = compute_match_score(r, query)
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: (-x[0], x[1]['created_at']))
        posts = [p for s, p in scored]
    user = get_current_user()
    return render_template_string(BASE_HTML + """{% block content %}<div class="d-flex justify-content-between align-items-center mb-3"><h3 class="mb-0">帖子列表</h3>{% if q %}<div class="small-muted">搜索：“{{ q }}” 结果：{{ posts|length }} 项</div>{% endif %}</div><ul class="list-group">{% for p in posts %}<li class="list-group-item"><a href="{{ url_for('post_detail', post_id=p['id']) }}" class="h5 text-decoration-none">{{ p['title'] }}</a><div class="meta-small">作者：{{ p['author_name'] }}{% if p['moderator_name'] %}（版主：{{ p['moderator_name'] }}）{% endif %} · {{ p['created_at'] }} {% if p['closed'] %}<span class="badge bg-secondary">已关闭</span>{% endif %}</div><p class="mt-2 mb-0 text-truncate">{{ p['body'] }}</p></li>{% else %}<li class="list-group-item">暂无帖子</li>{% endfor %}</ul>{% endblock %}""", posts=posts, user=user, q=query)

@app.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空'); return redirect(url_for('register'))
        db = get_db()
        try:
            now = datetime.utcnow().isoformat(sep=' ', timespec='seconds')
            db.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)', (username, generate_password_hash(password), now))
            db.commit(); flash('注册成功，请登录'); return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在'); return redirect(url_for('register'))
    return render_template_string(BASE_HTML + """{% block content %}<h3>注册</h3><form method="post" class="row g-3"><div class="col-12"><input name="username" class="form-control" placeholder="用户名"></div><div class="col-12"><input name="password" type="password" class="form-control" placeholder="密码"></div><div class="col-12"><button class="btn btn-primary">注册</button></div></form>{% endblock %}""", user=get_current_user())

@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip(); password = request.form.get('password') or ''
        db = get_db(); user_row = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user_row and check_password_hash(user_row['password_hash'], password):
            session.clear(); session['user_id'] = user_row['id']; flash('登录成功'); next_page = request.args.get('next') or url_for('index'); return redirect(next_page)
        flash('用户名或密码错误')
    return render_template_string(BASE_HTML + """{% block content %}<h3>登录</h3><form method="post" class="row g-3"><div class="col-12"><input name="username" class="form-control" placeholder="用户名"></div><div class="col-12"><input name="password" type="password" class="form-control" placeholder="密码"></div><div class="col-12"><button class="btn btn-primary">登录</button></div></form>{% endblock %}""", user=get_current_user())

@app.route('/logout')
def logout():
    session.clear(); flash('已登出'); return redirect(url_for('index'))

@app.route('/create_post', methods=('GET', 'POST'))
@login_required
def create_post():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip(); body = (request.form.get('body') or '').strip(); moderator_username = (request.form.get('moderator') or '').strip()
        if not title or not body:
            flash('标题和内容不能为空'); return redirect(url_for('create_post'))
        db = get_db(); moderator_id = None
        if moderator_username:
            mod_row = db.execute('SELECT id FROM users WHERE username = ?', (moderator_username,)).fetchone()
            if mod_row: moderator_id = mod_row['id']
            else: flash('指定版主不存在，已忽略该字段')
        now = datetime.utcnow().isoformat(sep=' ', timespec='seconds')
        db.execute('INSERT INTO posts (title, body, author_id, moderator_id, created_at) VALUES (?, ?, ?, ?, ?)', (title, body, session['user_id'], moderator_id, now))
        db.commit(); flash('帖子已创建'); return redirect(url_for('index'))
    return render_template_string(BASE_HTML + """{% block content %}<h3>发帖</h3><form method="post" class="row g-3"><div class="col-12"><input name="title" class="form-control" placeholder="标题"></div><div class="col-12"><textarea name="body" class="form-control" rows="6" placeholder="内容"></textarea></div><div class="col-12"><input name="moderator" class="form-control" placeholder="版主用户名（可选）"></div><div class="col-12"><button class="btn btn-primary">创建</button></div></form>{% endblock %}""", user=get_current_user())

@app.route('/post/<int:post_id>', methods=('GET', 'POST'))
def post_detail(post_id):
    db = get_db()
    post = db.execute('''SELECT p.*, a.username AS author_name, m.username AS moderator_name FROM posts p JOIN users a ON p.author_id = a.id LEFT JOIN users m ON p.moderator_id = m.id WHERE p.id = ?''', (post_id,)).fetchone()
    if not post: abort(404)
    comments = db.execute('''SELECT c.*, u.username AS author_name FROM comments c JOIN users u ON c.author_id = u.id WHERE c.post_id = ? ORDER BY c.created_at ASC''', (post_id,)).fetchall()
    user = get_current_user()
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('请先登录'); return redirect(url_for('login', next=request.path))
        if post['closed'] and post['moderator_id'] != session['user_id']:
            flash('该帖子已关闭，不能发表评论'); return redirect(url_for('post_detail', post_id=post_id))
        comment_body = (request.form.get('body') or '').strip()
        if not comment_body: flash('评论内容不能为空'); return redirect(url_for('post_detail', post_id=post_id))
        author_ip = request.remote_addr or ''; now = datetime.utcnow().isoformat(sep=' ', timespec='seconds')
        db.execute('INSERT INTO comments (post_id, author_id, body, ip, created_at) VALUES (?, ?, ?, ?, ?)', (post_id, session['user_id'], comment_body, author_ip, now))
        db.commit(); flash('评论已添加'); return redirect(url_for('post_detail', post_id=post_id))
    return render_template_string(BASE_HTML + """{% block content %}<div class="mb-3"><h3 class="mb-0">{{ post['title'] }} {% if post['closed'] %}<span class="badge bg-secondary">已关闭</span>{% endif %}</h3><div class="meta-small">作者：{{ post['author_name'] }} {% if post['moderator_name'] %}（版主：{{ post['moderator_name'] }}）{% endif %} · {{ post['created_at'] }}</div></div><div class="card mb-4"><div class="card-body">{{ post['body'] | e }}</div></div><h5>评论（{{ comments|length }}）</h5><ul class="list-group mb-4">{% for c in comments %}<li class="list-group-item"><div><strong>{{ c['author_name'] }}</strong> <span class="small-muted">于 {{ c['created_at'] }}</span></div><div class="mt-2">{{ c['body'] | e }}</div><div class="ip-small mt-1">IP: {{ c['ip'] or '未知' }}</div></li>{% else %}<li class="list-group-item">暂无评论</li>{% endfor %}</ul>{% if user %}{% if post['closed'] and post['moderator_id'] != user['id'] %}<div class="alert alert-warning">该帖子已关闭，您无法发表评论。</div>{% else %}<form method="post" class="mb-3"><div class="mb-2"><textarea name="body" class="form-control" rows="4" placeholder="发表评论"></textarea></div><button class="btn btn-primary">发表评论</button></form>{% endif %}{% if post['moderator_id'] and user['id'] == post['moderator_id'] %}<form method="post" action="{{ url_for('toggle_close', post_id=post['id']) }}">{% if not post['closed'] %}<button class="btn btn-sm btn-outline-danger">关闭帖子（只读）</button>{% else %}<button class="btn btn-sm btn-outline-success">打开帖子</button>{% endif %}</form>{% endif %}{% else %}<p>请先 <a href="{{ url_for('login', next=request.path) }}">登录</a> 后发表评论。</p>{% endif %}{% endblock %}""", post=post, comments=comments, user=user)

@app.route('/toggle_close/<int:post_id>', methods=('POST',))
@login_required
def toggle_close(post_id):
    db = get_db(); post = db.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post: abort(404)
    if post['moderator_id'] is None or post['moderator_id'] != session['user_id']:
        flash('只有版主可以执行此操作'); return redirect(url_for('post_detail', post_id=post_id))
    new_state = 0 if post['closed'] else 1
    db.execute('UPDATE posts SET closed = ? WHERE id = ?', (new_state, post_id)); db.commit(); flash('操作已执行'); return redirect(url_for('post_detail', post_id=post_id))

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        with app.app_context(): init_db(); print('初始化数据库:', DB_PATH)
    app.run(host='127.0.0.1', port=5000, debug=DEBUG)
