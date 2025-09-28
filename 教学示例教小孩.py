from flask import Flask, g, request, redirect, url_for, session, flash, abort
from flask import render_template_string
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "replace-this-with-a-secure-random-key"  # 生产请更换
USER_DB = "users.db"
FORUM_DB = "forum.db"

# ---------- DB helpers ----------
def get_db(path):
    attr = "_db_" + path
    db = getattr(g, attr, None)
    if db is None:
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        setattr(g, attr, db)
    return db

@app.teardown_appcontext
def close_dbs(exception):
    for k, v in list(g.__dict__.items()):
        if k.startswith("_db_"):
            try:
                v.close()
            except:
                pass

def init_user_db():
    db = sqlite3.connect(USER_DB)
    cur = db.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    db.commit()
    db.close()

def init_forum_db():
    db = sqlite3.connect(FORUM_DB)
    cur = db.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    db.commit()
    db.close()

if not os.path.exists(USER_DB):
    init_user_db()
if not os.path.exists(FORUM_DB):
    init_forum_db()

# ---------- Auth ----------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db(USER_DB)
    u = db.execute("SELECT id, username, created_at FROM users WHERE id = ?", (uid,)).fetchone()
    return u

def login_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("请先登录")
            return redirect(url_for("login", next=request.path))
        return func(*args, **kwargs)
    return wrapper

# ---------- Templates (Bootstrap 5 via CDN) ----------
BASE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title or "贴吧" }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{padding-top:70px;}
    .post-snippet{white-space:pre-wrap; max-height:4.8em; overflow:hidden;}
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">简单贴吧</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="nav">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
        {% if user %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('new_post') }}">发帖</a></li>
        {% endif %}
      </ul>
      <form class="d-flex" method="get" action="{{ url_for('index') }}">
        <input class="form-control me-2" name="q" placeholder="搜索标题或内容" value="{{ request.args.get('q','') }}">
        <button class="btn btn-outline-light" type="submit">搜索</button>
      </form>
      <ul class="navbar-nav ms-3">
        {% if user %}
          <li class="nav-item"><a class="nav-link">欢迎，{{ user['username'] }}</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<div class="container">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="mt-2">
      {% for m in messages %}
        <div class="alert alert-info">{{ m }}</div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  {{ body }}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

INDEX_TPL = """
{% extends base %}
{% block body %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3 class="mb-0">帖子列表</h3>
  <small class="text-muted">共 {{ posts|length }} 条</small>
</div>
{% if posts %}
  <div class="list-group">
  {% for p in posts %}
    <a class="list-group-item list-group-item-action" href="{{ url_for('post_detail', post_id=p['id']) }}">
      <div class="d-flex w-100 justify-content-between">
        <h5 class="mb-1">{{ p['title'] }}</h5>
        <small>{{ p['created_at'][:19].replace('T',' ') }}</small>
      </div>
      <p class="mb-1 post-snippet">{{ p['content'] }}</p>
      <small class="text-muted">作者: {{ p['username'] }}</small>
    </a>
  {% endfor %}
  </div>
{% else %}
  <div class="alert alert-secondary">暂无帖子，快去发一个吧。</div>
{% endif %}
{% endblock %}
"""

POST_DETAIL_TPL = """
{% extends base %}
{% block body %}
<div class="card mb-3">
  <div class="card-body">
    <h4 class="card-title">{{ post['title'] }}</h4>
    <h6 class="card-subtitle mb-2 text-muted">作者: {{ post['username'] }} | {{ post['created_at'][:19].replace('T',' ') }}</h6>
    <p class="card-text" style="white-space:pre-wrap;">{{ post['content'] }}</p>
    {% if user and user['id']==post['user_id'] %}
      <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_post', post_id=post['id']) }}">编辑</a>
      <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_post', post_id=post['id']) }}" onclick="return confirm('确认删除该帖子？此操作不可撤销');">删除</a>
    {% endif %}
  </div>
</div>

<h5>回复 ({{ replies|length }})</h5>
{% for r in replies %}
  <div class="mb-2 p-3 border rounded">
    <div class="d-flex justify-content-between">
      <strong>{{ r['username'] }}</strong>
      <small class="text-muted">{{ r['created_at'][:19].replace('T',' ') }}</small>
    </div>
    <div style="white-space:pre-wrap;">{{ r['content'] }}</div>
    {% if user and user['id']==r['user_id'] %}
      <div class="mt-2">
        <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_reply', reply_id=r['id']) }}">编辑</a>
        <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_reply', reply_id=r['id']) }}" onclick="return confirm('确认删除回复？');">删除</a>
      </div>
    {% endif %}
  </div>
{% else %}
  <div class="alert alert-secondary">暂无回复</div>
{% endfor %}

{% if user %}
  <div class="card mt-3">
    <div class="card-body">
      <form method="post" action="{{ url_for('reply', post_id=post['id']) }}">
        <div class="mb-3">
          <label class="form-label">发表回复</label>
          <textarea class="form-control" name="content" rows="4" required></textarea>
        </div>
        <button class="btn btn-primary" type="submit">回复</button>
      </form>
    </div>
  </div>
{% else %}
  <div class="mt-3">请 <a href="{{ url_for('login') }}">登录</a> 后回复。</div>
{% endif %}
{% endblock %}
"""

NEW_POST_TPL = """
{% extends base %}
{% block body %}
<div class="card">
  <div class="card-body">
    <h5 class="card-title">发新帖</h5>
    <form method="post">
      <div class="mb-3">
        <input class="form-control" name="title" placeholder="标题" required>
      </div>
      <div class="mb-3">
        <textarea class="form-control" name="content" rows="8" placeholder="内容" required></textarea>
      </div>
      <button class="btn btn-primary" type="submit">发布</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">取消</a>
    </form>
  </div>
</div>
{% endblock %}
"""

LOGIN_TPL = """
{% extends base %}
{% block body %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">登录</h5>
        <form method="post">
          <div class="mb-3"><input class="form-control" name="username" placeholder="用户名" required></div>
          <div class="mb-3"><input class="form-control" name="password" type="password" placeholder="密码" required></div>
          <button class="btn btn-primary" type="submit">登录</button>
          <a class="btn btn-link" href="{{ url_for('register') }}">注册</a>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

REGISTER_TPL = """
{% extends base %}
{% block body %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card">
      <div class="card-body">
        <h5 class="card-title">注册</h5>
        <form method="post">
          <div class="mb-3"><input class="form-control" name="username" placeholder="用户名" required></div>
          <div class="mb-3"><input class="form-control" name="password" type="password" placeholder="密码" required></div>
          <button class="btn btn-primary" type="submit">注册</button>
          <a class="btn btn-link" href="{{ url_for('login') }}">已有账号？登录</a>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

EDIT_POST_TPL = """
{% extends base %}
{% block body %}
<div class="card">
  <div class="card-body">
    <h5 class="card-title">编辑帖子</h5>
    <form method="post">
      <div class="mb-3"><input class="form-control" name="title" value="{{ post['title'] }}" required></div>
      <div class="mb-3"><textarea class="form-control" name="content" rows="8" required>{{ post['content'] }}</textarea></div>
      <button class="btn btn-primary" type="submit">保存</button>
      <a class="btn btn-secondary" href="{{ url_for('post_detail', post_id=post['id']) }}">取消</a>
    </form>
  </div>
</div>
{% endblock %}
"""

EDIT_REPLY_TPL = """
{% extends base %}
{% block body %}
<div class="card">
  <div class="card-body">
    <h5 class="card-title">编辑回复</h5>
    <form method="post">
      <div class="mb-3"><textarea class="form-control" name="content" rows="6" required>{{ reply['content'] }}</textarea></div>
      <button class="btn btn-primary" type="submit">保存</button>
      <a class="btn btn-secondary" href="{{ url_for('post_detail', post_id=reply['post_id']) }}">取消</a>
    </form>
  </div>
</div>
{% endblock %}
"""

# Jinja environment using templates dict
from jinja2 import Environment, DictLoader
tpls = {
    "base": BASE,
    "index.html": INDEX_TPL,
    "post_detail.html": POST_DETAIL_TPL,
    "new_post.html": NEW_POST_TPL,
    "login.html": LOGIN_TPL,
    "register.html": REGISTER_TPL,
    "edit_post.html": EDIT_POST_TPL,
    "edit_reply.html": EDIT_REPLY_TPL,
}
jinja_env = Environment(loader=DictLoader(tpls))
def render(tpl_name, **context):
    context.setdefault("base", jinja_env.get_template("base"))
    context.setdefault("user", current_user())
    context.setdefault("request", request)
    t = jinja_env.get_template(tpl_name)
    return t.render(**context)

# ---------- Routes ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    db = get_db(FORUM_DB)
    if q:
        like = f"%{q}%"
        rows = db.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN (SELECT id, username FROM users) u ON p.user_id = u.id
            WHERE p.title LIKE ? OR p.content LIKE ?
            ORDER BY p.created_at DESC
        """, (like, like)).fetchall()
    else:
        rows = db.execute("""
            SELECT p.*, u.username FROM posts p
            JOIN (SELECT id, username FROM users) u ON p.user_id = u.id
            ORDER BY p.created_at DESC
        """).fetchall()
    posts = [dict(r) for r in rows]
    return render("index.html", title="首页", posts=posts)

@app.route("/post/<int:post_id>")
def post_detail(post_id):
    db = get_db(FORUM_DB)
    post_row = db.execute("SELECT p.*, u.username FROM posts p JOIN (SELECT id, username FROM users) u ON p.user_id = u.id WHERE p.id = ?", (post_id,)).fetchone()
    if not post_row:
        flash("帖子不存在")
        return redirect(url_for("index"))
    post = dict(post_row)
    replies_rows = db.execute("SELECT r.*, u.username FROM replies r JOIN (SELECT id, username FROM users) u ON r.user_id = u.id WHERE r.post_id = ? ORDER BY r.created_at ASC", (post_id,)).fetchall()
    replies = [dict(r) for r in replies_rows]
    return render("post_detail.html", title=post['title'], post=post, replies=replies)

@app.route("/new", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "GET":
        return render("new_post.html", title="发帖")
    title = request.form.get("title","").strip()
    content = request.form.get("content","").strip()
    if not title or not content:
        flash("标题和内容不能为空")
        return redirect(url_for("new_post"))
    user = current_user()
    db = get_db(FORUM_DB)
    db.execute("INSERT INTO posts (user_id, title, content, created_at) VALUES (?, ?, ?, ?)",
               (user["id"], title, content, datetime.utcnow().isoformat()))
    db.commit()
    flash("发布成功")
    return redirect(url_for("index"))

@app.route("/post/<int:post_id>/reply", methods=["POST"])
@login_required
def reply(post_id):
    content = request.form.get("content","").strip()
    if not content:
        flash("回复不能为空")
        return redirect(url_for("post_detail", post_id=post_id))
    db = get_db(FORUM_DB)
    # check post exists
    p = db.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not p:
        flash("帖子不存在")
        return redirect(url_for("index"))
    user = current_user()
    db.execute("INSERT INTO replies (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
               (post_id, user["id"], content, datetime.utcnow().isoformat()))
    db.commit()
    flash("回复成功")
    return redirect(url_for("post_detail", post_id=post_id))

# Edit post
@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    db = get_db(FORUM_DB)
    post_row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post_row:
        flash("帖子不存在")
        return redirect(url_for("index"))
    user = current_user()
    if post_row["user_id"] != user["id"]:
        abort(403)
    post = dict(post_row)
    if request.method == "GET":
        return render("edit_post.html", title="编辑帖子", post=post)
    title = request.form.get("title","").strip()
    content = request.form.get("content","").strip()
    if not title or not content:
        flash("标题和内容不能为空")
        return redirect(url_for("edit_post", post_id=post_id))
    db.execute("UPDATE posts SET title = ?, content = ? WHERE id = ?", (title, content, post_id))
    db.commit()
    flash("保存成功")
    return redirect(url_for("post_detail", post_id=post_id))

# Delete post (and its replies)
@app.route("/post/<int:post_id>/delete")
@login_required
def delete_post(post_id):
    db = get_db(FORUM_DB)
    post_row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post_row:
        flash("帖子不存在")
        return redirect(url_for("index"))
    user = current_user()
    if post_row["user_id"] != user["id"]:
        abort(403)
    db.execute("DELETE FROM replies WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    db.commit()
    flash("帖子已删除")
    return redirect(url_for("index"))

# Edit reply
@app.route("/reply/<int:reply_id>/edit", methods=["GET", "POST"])
@login_required
def edit_reply(reply_id):
    db = get_db(FORUM_DB)
    r = db.execute("SELECT * FROM replies WHERE id = ?", (reply_id,)).fetchone()
    if not r:
        flash("回复不存在")
        return redirect(url_for("index"))
    user = current_user()
    if r["user_id"] != user["id"]:
        abort(403)
    reply = dict(r)
    if request.method == "GET":
        return render("edit_reply.html", title="编辑回复", reply=reply)
    content = request.form.get("content","").strip()
    if not content:
        flash("回复不能为空")
        return redirect(url_for("edit_reply", reply_id=reply_id))
    db.execute("UPDATE replies SET content = ? WHERE id = ?", (content, reply_id))
    db.commit()
    flash("保存成功")
    return redirect(url_for("post_detail", post_id=reply["post_id"]))

# Delete reply
@app.route("/reply/<int:reply_id>/delete")
@login_required
def delete_reply(reply_id):
    db = get_db(FORUM_DB)
    r = db.execute("SELECT * FROM replies WHERE id = ?", (reply_id,)).fetchone()
    if not r:
        flash("回复不存在")
        return redirect(url_for("index"))
    user = current_user()
    if r["user_id"] != user["id"]:
        abort(403)
    db.execute("DELETE FROM replies WHERE id = ?", (reply_id,))
    db.commit()
    flash("回复已删除")
    return redirect(url_for("post_detail", post_id=r["post_id"]))

# Auth routes
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render("register.html", title="注册")
    username = request.form.get("username","").strip()
    password = request.form.get("password","")
    if not username or not password:
        flash("用户名和密码不能为空")
        return redirect(url_for("register"))
    db = get_db(USER_DB)
    hashed = generate_password_hash(password)
    try:
        cur = db.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                         (username, hashed, datetime.utcnow().isoformat()))
        db.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        flash("用户名已存在")
        return redirect(url_for("register"))
    session["user_id"] = uid
    flash("注册并登录成功")
    return redirect(url_for("index"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render("login.html", title="登录")
    username = request.form.get("username","").strip()
    password = request.form.get("password","")
    db = get_db(USER_DB)
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not check_password_hash(row["password"], password):
        flash("用户名或密码错误")
        return redirect(url_for("login"))
    session["user_id"] = row["id"]
    flash("登录成功")
    next_url = request.args.get("next") or url_for("index")
    return redirect(next_url)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("已登出")
    return redirect(url_for("index"))

# Run
if __name__ == "__main__":
    app.run(debug=True, port=5000)
