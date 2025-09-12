#!/usr/bin/env python3
# app.py - 单文件版 GreenForum（Flask + SQLite3）
# 依赖: flask, werkzeug
# 运行: pip install flask werkzeug
#       python app.py
import os
import sqlite3
from flask import Flask, g, request, redirect, url_for, session, flash, render_template_string, abort
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
APP_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(APP_DIR, 'forum.db')
app = Flask(__name__)
app.secret_key = 'replace-with-secure-random-key'  # 部署时替换为强随机值
# ---------- DB ----------
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db:
        db.close()
def init_db():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        author_id INTEGER NOT NULL,
        post_admin TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
        FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    db.commit()
    db.close()
if not os.path.exists(DB_PATH):
    init_db()
# ---------- helpers ----------
def current_user():
    username = session.get('username')
    if not username:
        return None
    db = get_db()
    cur = db.execute("SELECT id, username, created FROM users WHERE username = ?", (username,))
    return cur.fetchone()
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("请先登录", "warning")
            return redirect(url_for('auth', next=request.path))
        return f(*args, **kwargs)
    return wrapped
# ---------- routes ----------
@app.route('/', methods=['GET', 'POST'])
def index():
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create_post':
            if not current_user():
                flash("请先登录再发帖", "warning")
                return redirect(url_for('auth', next=url_for('index')))
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            post_admin = request.form.get('post_admin', '').strip()
            if not title or not content or not post_admin:
                flash("标题、内容和帖子管理员必填", "danger")
                return redirect(url_for('index'))
            user = current_user()
            cur = db.execute("SELECT id FROM users WHERE username = ?", (post_admin,))
            if not cur.fetchone():
                db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                           (post_admin, generate_password_hash(os.urandom(16).hex())))
            db.execute("INSERT INTO posts (title, content, author_id, post_admin) VALUES (?, ?, ?, ?)",
                       (title, content, user['id'], post_admin))
            db.commit()
            flash("帖子发布成功", "success")
            return redirect(url_for('index'))
        if action == 'add_comment':
            if not current_user():
                flash("请先登录再评论", "warning")
                return redirect(url_for('auth', next=url_for('index')))
            post_id = request.form.get('post_id')
            content = request.form.get('comment_content', '').strip()
            if not content or not post_id:
                flash("评论内容不能为空", "danger")
                return redirect(url_for('index'))
            user = current_user()
            db.execute("INSERT INTO comments (post_id, author_id, content) VALUES (?, ?, ?)",
                       (post_id, user['id'], content))
            db.commit()
            flash("评论已发布", "success")
            return redirect(url_for('index') + f"#post-{post_id}")
        if action == 'delete_post':
            if not current_user():
                flash("请先登录", "warning")
                return redirect(url_for('auth', next=url_for('index')))
            post_id = request.form.get('post_id')
            if not post_id:
                return redirect(url_for('index'))
            user = current_user()
            cur = db.execute("SELECT author_id FROM posts WHERE id = ?", (post_id,))
            row = cur.fetchone()
            if not row:
                flash("帖子不存在", "danger")
                return redirect(url_for('index'))
            if row['author_id'] != user['id']:
                flash("只有帖子作者可以删除自己的帖子", "danger")
                return redirect(url_for('index'))
            db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            db.commit()
            flash("帖子已删除", "success")
            return redirect(url_for('index'))
        if action == 'delete_comment':
            if not current_user():
                flash("请先登录", "warning")
                return redirect(url_for('auth', next=url_for('index')))
            comment_id = request.form.get('comment_id')
            if not comment_id:
                return redirect(url_for('index'))
            user = current_user()
            cur = db.execute("SELECT author_id, post_id FROM comments WHERE id = ?", (comment_id,))
            row = cur.fetchone()
            if not row:
                flash("评论不存在", "danger")
                return redirect(url_for('index'))
            if row['author_id'] != user['id']:
                flash("只有评论作者可以删除自己的评论", "danger")
                return redirect(url_for('index'))
            db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
            db.commit()
            flash("评论已删除", "success")
            return redirect(url_for('index') + f"#post-{row['post_id']}")
    # GET 渲染
    posts = db.execute("""
        SELECT p.id, p.title, p.content, p.post_admin, p.created, u.username AS author_name, u.id AS author_id
        FROM posts p JOIN users u ON p.author_id = u.id
        ORDER BY p.created DESC
    """).fetchall()
    posts_with_comments = []
    for p in posts:
        comments = db.execute("""
            SELECT c.id, c.content, c.created, u.username AS author_name, u.id AS author_id
            FROM comments c JOIN users u ON c.author_id = u.id
            WHERE c.post_id = ?
            ORDER BY c.created ASC
        """, (p['id'],)).fetchall()
        posts_with_comments.append((p, comments))
    return render_template_string(INDEX_HTML, user=current_user(), posts_with_comments=posts_with_comments)
@app.route('/auth', methods=['GET', 'POST'])
def auth():
    db = get_db()
    next_url = request.args.get('next') or url_for('index')
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'login':
            username = request.form.get('login_username', '').strip()
            password = request.form.get('login_password', '')
            if not username or not password:
                flash("请输入用户名和密码", "danger")
                return redirect(url_for('auth'))
            cur = db.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
            user = cur.fetchone()
            if not user or not check_password_hash(user['password_hash'], password):
                flash("用户名或密码错误", "danger")
                return redirect(url_for('auth'))
            session['username'] = user['username']
            flash("登录成功", "success")
            return redirect(next_url)
        if action == 'register':
            username = request.form.get('reg_username', '').strip()
            password = request.form.get('reg_password', '')
            if not username or not password:
                flash("用户名和密码必填", "danger")
                return redirect(url_for('auth'))
            cur = db.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cur.fetchone():
                flash("用户名已存在", "danger")
                return redirect(url_for('auth'))
            pwd_hash = generate_password_hash(password)
            db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pwd_hash))
            db.commit()
            session['username'] = username
            flash("注册并登录成功", "success")
            return redirect(next_url)
    return render_template_string(AUTH_HTML, user=current_user())
@app.route('/logout', methods=['GET'])
def logout():
    session.pop('username', None)
    flash("已登出", "info")
    return redirect(url_for('index'))
# ---------- HTML Templates as strings ----------
INDEX_HTML = r'''
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>淡绿色主题 简易论坛</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root{
      --mint-50: #f2fbf6;
      --mint-100: #e6f8ef;
      --mint-200: #cff0dd;
      --mint-300: #b8e7cc;
      --mint-400: #9ee0bd;
      --mint-500: #7fd1a0;
      --mint-600: #61b788;
      --accent: #2b6b4a;
    }
    body{
      background: linear-gradient(180deg,var(--mint-50),white 60%);
      color: #0b3d2f;
      padding-top: 2rem;
      font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
    }
    .card-post { border: none; box-shadow: 0 6px 18px rgba(45, 125, 85, 0.08); border-radius: 12px; }
    .site-header { max-width: 1100px; margin: 0 auto; padding: 0 1rem; }
    .brand { font-weight:700; color: var(--accent); letter-spacing: .3px; }
    .muted { color: rgba(11,61,47,0.7); }
    .btn-mint { background: linear-gradient(90deg,var(--mint-500),var(--mint-600)); color: white; border: none; }
    .btn-ghost { background: transparent; border: 1px solid rgba(11,61,47,0.08); color: var(--accent); }
    .post-meta { font-size: .9rem; color: rgba(11,61,47,0.6); }
    .admin-badge { background: rgba(43,107,74,0.12); color: var(--accent); padding: .2rem .5rem; border-radius: 999px; font-size:.85rem; }
    textarea.form-control { min-height: 120px; resize: vertical; }
    .form-card { border-radius: 12px; box-shadow: 0 6px 18px rgba(45,125,85,0.06); padding: 1rem; background: white; }
    .form-auth-note { background: linear-gradient(180deg,var(--mint-200),var(--mint-50)); padding: .6rem; border-radius: 8px; }
  </style>
</head>
<body>
<div class="container site-header">
  <div class="d-flex justify-content-between align-items-center mb-4">
    <div>
      <div class="brand h4 mb-0">GreenForum</div>
      <div class="muted small">轻松、清新的社区</div>
    </div>
    <div>
      {% if user %}
        <span class="me-3">已登录：<strong>{{ user.username }}</strong></span>
        <a class="btn btn-ghost btn-sm" href="{{ url_for('logout') }}">登出</a>
      {% else %}
        <a class="btn btn-mint btn-sm" href="{{ url_for('auth') }}">登录 / 注册</a>
      {% endif %}
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-3">
        {% for category, msg in messages %}
          <div class="alert alert-{{ 'success' if category=='success' else ('warning' if category=='warning' else ('danger' if category=='danger' else 'info')) }} alert-sm">
            {{ msg }}
          </div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="row g-4">
    <div class="col-lg-5">
      <div class="form-card">
        <h5 class="mb-2">发一条新帖</h5>
        <p class="muted small">请填写标题、内容与该帖的管理员用户名（管理员不会自动获得删除他人帖子的权限）</p>
        <form method="post">
          <input type="hidden" name="action" value="create_post">
          <div class="mb-2">
            <input name="title" class="form-control" placeholder="标题">
          </div>
          <div class="mb-2">
            <textarea name="content" class="form-control" placeholder="说点什么吧..."></textarea>
          </div>
          <div class="mb-3">
            <input name="post_admin" class="form-control" placeholder="帖子管理员用户名（示例：alice）">
          </div>
          <div class="d-flex gap-2">
            <button class="btn btn-mint" type="submit">发布帖子</button>
            <a class="btn btn-ghost" href="#posts">查看帖子</a>
          </div>
          <div class="mt-2 muted small">提示：需先登录才能在服务器端成功发布（会提示）。</div>
        </form>
      </div>

      <div class="mt-3 form-auth-note">
        <div class="small">登录后可发布与评论。若指定的帖子管理员不存在，系统会为该用户名创建一个账户（仅作为标签）。</div>
      </div>
    </div>

    <div class="col-lg-7">
      <div id="posts">
        {% for p, comments in posts_with_comments %}
          <div class="card mb-3 card-post" id="post-{{ p.id }}">
            <div class="card-body">
              <div class="d-flex justify-content-between">
                <div>
                  <h5 class="card-title mb-1">{{ p.title }}</h5>
                  <div class="post-meta">
                    作者：<strong>{{ p.author_name }}</strong>
                    · <span class="admin-badge">管理员：{{ p.post_admin }}</span>
                    · {{ p.created }}
                  </div>
                </div>
                <div class="text-end">
                  {% if user and p.author_id == user.id %}
                    <form method="post">
                      <input type="hidden" name="action" value="delete_post">
                      <input type="hidden" name="post_id" value="{{ p.id }}">
                      <button class="btn btn-sm btn-outline-danger">删除</button>
                    </form>
                  {% endif %}
                </div>
              </div>

              <p class="mt-3 mb-2">{{ p.content }}</p>

              <hr>
              <div>
                <strong class="small">评论（{{ comments|length }}）</strong>
                <ul class="list-unstyled mt-2">
                  {% for c in comments %}
                    <li class="mb-2">
                      <div class="d-flex justify-content-between">
                        <div class="small"><strong>{{ c.author_name }}</strong> · <span class="muted">{{ c.created }}</span></div>
                        <div>
                          {% if user and c.author_id == user.id %}
                            <form method="post" class="d-inline">
                              <input type="hidden" name="action" value="delete_comment">
                              <input type="hidden" name="comment_id" value="{{ c.id }}">
                              <button class="btn btn-sm btn-outline-secondary">删除</button>
                            </form>
                          {% endif %}
                        </div>
                      </div>
                      <div class="mt-1">{{ c.content }}</div>
                    </li>
                  {% else %}
                    <li class="small muted">暂无评论</li>
                  {% endfor %}
                </ul>

                <div class="mt-3">
                  <form method="post">
                    <input type="hidden" name="action" value="add_comment">
                    <input type="hidden" name="post_id" value="{{ p.id }}">
                    <div class="mb-2">
                      <textarea name="comment_content" class="form-control" placeholder="写评论..." {% if not user %}disabled{% endif %}></textarea>
                    </div>
                    <div>
                      <button class="btn btn-sm btn-mint" type="submit" {% if not user %}disabled{% endif %}>发送</button>
                      {% if not user %}
                        <small class="ms-2 muted">请先登录再评论</small>
                      {% endif %}
                    </div>
                  </form>
                </div>

              </div>
            </div>
          </div>
        {% else %}
          <div class="card card-post p-3"><div class="muted">当前还没有帖子，快来发第一条吧！</div></div>
        {% endfor %}
      </div>
    </div>
  </div>
  <footer class="mt-4">
    <small>GreenForum · 简易演示 · 帖子管理员为标签，不授予删除他人帖子的权限</small>
  </footer>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

AUTH_HTML = r'''
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>登录 / 注册 - GreenForum</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{ background: linear-gradient(180deg,#f2fbf6,white 60%); color:#0b3d2f; padding-top:3rem; }
    .card-auth { max-width:980px; margin:0 auto; border-radius:12px; box-shadow:0 8px 30px rgba(43,107,74,0.06); overflow:hidden; }
    .left{ background:linear-gradient(180deg,#def7e9,#bff0d3); padding:2rem; }
    .brand{ font-weight:700; color:#2b6b4a; }
    .btn-mint { background: linear-gradient(90deg,#7fd1a0,#61b788); color: white; border: none; }
    .btn-ghost { background: transparent; border: 1px solid rgba(11,61,47,0.08); color: #2b6b4a; }
  </style>
</head>
<body>
  <div class="container">
    <div class="card card-auth">
      <div class="row g-0">
        <div class="col-md-6 left d-flex flex-column justify-content-center">
          <div class="px-4">
            <div class="brand h3">GreenForum</div>
            <p class="muted">轻松的社区，留下友好的声音。注册后即可发帖与评论。</p>
            <p class="small">已有账号？请在右侧登录。新用户请注册。</p>
          </div>
        </div>
        <div class="col-md-6 p-4">
          {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
              <div class="mb-3">
                {% for category, msg in messages %}
                  <div class="alert alert-{{ 'success' if category=='success' else ('warning' if category=='warning' else ('danger' if category=='danger' else 'info')) }} alert-sm">
                    {{ msg }}
                  </div>
                {% endfor %}
              </div>
            {% endif %}
          {% endwith %}

          <ul class="nav nav-tabs mb-3" id="authTabs" role="tablist">
            <li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#login">登录</button></li>
            <li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#register">注册</button></li>
          </ul>

          <div class="tab-content">
            <div class="tab-pane fade show active" id="login">
              <form method="post">
                <input type="hidden" name="action" value="login">
                <div class="mb-2"><input name="login_username" class="form-control" placeholder="用户名"></div>
                <div class="mb-3"><input name="login_password" type="password" class="form-control" placeholder="密码"></div>
                <div class="d-flex justify-content-between">
                  <a href="{{ url_for('index') }}" class="btn btn-ghost btn-sm">返回</a>
                  <button class="btn btn-mint" type="submit">登录</button>
                </div>
              </form>
            </div>

            <div class="tab-pane fade" id="register">
              <form method="post">
                <input type="hidden" name="action" value="register">
                <div class="mb-2"><input name="reg_username" class="form-control" placeholder="用户名"></div>
                <div class="mb-3"><input name="reg_password" type="password" class="form-control" placeholder="密码"></div>
                <div class="d-flex justify-content-between">
                  <a href="{{ url_for('index') }}" class="btn btn-ghost btn-sm">返回</a>
                  <button class="btn btn-mint" type="submit">注册并登录</button>
                </div>
              </form>
            </div>
          </div>

        </div>
      </div>
    </div>

    <div class="text-center mt-3"><a href="{{ url_for('index') }}" class="small muted">回到首页</a></div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
if __name__ == '__main__':
    app.run(debug=False)
