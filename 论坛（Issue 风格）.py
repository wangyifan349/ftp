# app.py — 单文件 Flask 论坛（Issue 风格），SQLite，Flask-WTF，分页，淡绿色主题
import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import (Flask, g, render_template_string, request, redirect,
                   url_for, flash, session, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField, HiddenField
from wtforms.validators import InputRequired, Length
# ----- Config -----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'forum.db')
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-me')
app = Flask(__name__)
app.config['DATABASE'] = DATABASE
app.config['SECRET_KEY'] = SECRET_KEY
app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF token 不过期便于本地测试
# ----- Schema (will be executed on first run) -----
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    is_open INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
);
"""
# ----- Static CSS and templates embedded as strings -----
STYLE_CSS = """
:root{
  --primary-green: #8fbf9f;
  --primary-dark: #6aa37a;
  --muted-text: #3a4a3a;
  --bg: #f6fbf7;
}
body{
  background: var(--bg);
  color: var(--muted-text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial;
  line-height: 1.6;
  padding-bottom: 60px;
}
.container-fluid {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem;
}
.navbar {
  background: linear-gradient(90deg, rgba(143,191,159,0.12), rgba(106,163,122,0.06));
  border: none;
  box-shadow: none;
}
.navbar-brand { color: var(--primary-dark) !important; font-weight: 600; }
.nav-link { color: rgba(58,74,58,0.9) !important; }
.btn-primary {
  background-color: var(--primary-green);
  border-color: var(--primary-green);
  color: #fff;
}
.btn-outline-secondary {
  color: var(--primary-dark);
  border-color: rgba(106,163,122,0.35);
}
.btn-outline-danger {
  border-color: rgba(200,80,80,0.2);
  color: #c85050;
}
.list-group-item {
  border: none;
  background: transparent;
  padding: 0.75rem 0;
}
.list-group-item + .list-group-item { border-top: 1px solid rgba(100,140,110,0.06); }
.issue-body { background: transparent; padding: 0; }
.card {
  border: none;
  background: rgba(143,191,159,0.06);
  padding: 0.6rem 0.9rem;
  margin-bottom: 0.6rem;
  box-shadow: none;
}
.form-control {
  border-radius: 6px;
  border: 1px solid rgba(100,140,110,0.14);
  background: #fff;
}
.main-row { display: flex; gap: 1.25rem; align-items: flex-start; }
.left-col { flex: 2; }
.right-col { flex: 1; max-width: 380px; }
.text-muted { color: rgba(58,74,58,0.6) !important; font-size: 0.95rem; }
small { font-size: 0.9rem; }
footer { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(143,191,159,0.04); padding: 0.5rem 0; text-align: center; font-size: 0.9rem; color: rgba(58,74,58,0.6); }
"""

BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{% block title %}MiniForum{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>{{ style_css }}</style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">MiniForum</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
        {% if user %}
          <li class="nav-item"><a class="nav-link" href="#">{{ user['username'] }}</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('new_issue') }}">New Issue</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<div class="container-fluid">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% block content %}{% endblock %}
</div>

<footer>轻量 Issue 风格论坛 — 淡绿色护眼主题</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
INDEX_HTML = """
{% extends base %}
{% block title %}Issues - MiniForum{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1>Issues</h1>
  <a class="btn btn-primary" href="{{ url_for('new_issue') }}">New Issue</a>
</div>
<div class="main-row">
  <div class="left-col">
    <div class="list-group">
      {% for issue in issues %}
        <a href="{{ url_for('view_issue', issue_id=issue['id']) }}" class="list-group-item list-group-item-action">
          <div class="d-flex w-100 justify-content-between">
            <h5 class="mb-1">{{ issue['title'] }}</h5>
            <small class="text-muted">{{ issue['created_at'] }}</small>
          </div>
          <p class="mb-1 text-truncate issue-body" style="max-width:85%">{{ issue['body'] }}</p>
          <small>作者: {{ issue['author_name'] }} — {% if issue['is_open'] %}<span class="text-success">Open</span>{% else %}<span class="text-danger">Closed</span>{% endif %}</small>
        </a>
      {% else %}
        <div class="text-muted">暂无帖子</div>
      {% endfor %}
    </div>

    <nav aria-label="Page navigation" class="mt-3">
      <ul class="pagination">
        <li class="page-item {% if page<=1 %}disabled{% endif %}">
          <a class="page-link" href="{{ url_for('index', page=page-1) }}">上一页</a>
        </li>
        <li class="page-item disabled"><span class="page-link">第 {{ page }} 页 / 共 {{ last_page }} 页</span></li>
        <li class="page-item {% if page>=last_page %}disabled{% endif %}">
          <a class="page-link" href="{{ url_for('index', page=page+1) }}">下一页</a>
        </li>
      </ul>
    </nav>
  </div>

  <div class="right-col">
    <div>
      <h5>说明</h5>
      <p class="text-muted small">轻量 Issue 风格论坛，支持注册、登录、发帖与评论。作者可关闭/删除自己的帖子。</p>
    </div>
  </div>
</div>
{% endblock %}
"""

REGISTER_HTML = """
{% extends base %}
{% block title %}注册{% endblock %}
{% block content %}
<h2>注册</h2>
<form method="post" class="row g-3" novalidate>
  {{ form.hidden_tag() }}
  <div class="col-6">
    {{ form.username.label(class="form-label") }}
    {{ form.username(class="form-control") }}
    {% for err in form.username.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="col-6">
    {{ form.password.label(class="form-label") }}
    {{ form.password(class="form-control") }}
    {% for err in form.password.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="col-12">
    {{ form.submit(class="btn btn-primary") }}
  </div>
</form>
{% endblock %}
"""

LOGIN_HTML = """
{% extends base %}
{% block title %}登录{% endblock %}
{% block content %}
<h2>登录</h2>
<form method="post" class="row g-3" novalidate>
  {{ form.hidden_tag() }}
  {{ form.next }}
  <div class="col-6">
    {{ form.username.label(class="form-label") }}
    {{ form.username(class="form-control") }}
    {% for err in form.username.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="col-6">
    {{ form.password.label(class="form-label") }}
    {{ form.password(class="form-control") }}
    {% for err in form.password.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="col-12">
    {{ form.submit(class="btn btn-primary") }}
  </div>
</form>
{% endblock %}
"""

NEW_ISSUE_HTML = """
{% extends base %}
{% block title %}创建帖子{% endblock %}
{% block content %}
<h2>创建帖子</h2>
<form method="post" novalidate>
  {{ form.hidden_tag() }}
  <div class="mb-3">
    {{ form.title.label(class="form-label") }}
    {{ form.title(class="form-control") }}
    {% for err in form.title.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="mb-3">
    {{ form.body.label(class="form-label") }}
    {{ form.body(class="form-control", rows="8") }}
    {% for err in form.body.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  {{ form.submit(class="btn btn-primary") }}
</form>
{% endblock %}
"""

ISSUE_HTML = """
{% extends base %}
{% block title %}{{ issue['title'] }}{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-start mb-2">
  <div>
    <h2 style="margin-bottom:0">{{ issue['title'] }}</h2>
    <p class="text-muted small">作者: {{ issue['author_name'] }} · 创建于 {{ issue['created_at'] }}</p>
  </div>
  <div>
    {% if issue['is_open'] %}
      <span class="badge bg-success">Open</span>
    {% else %}
      <span class="badge bg-danger">Closed</span>
    {% endif %}
  </div>
</div>

<div class="mb-3 issue-body">
  <p>{{ issue['body'] }}</p>

  {% if user and user['id'] == issue['author_id'] %}
  <form method="post" action="{{ url_for('toggle_issue', issue_id=issue['id']) }}" class="d-inline">
    <button class="btn btn-sm btn-outline-secondary" type="submit">{% if issue['is_open'] %}Close{% else %}Reopen{% endif %}</button>
  </form>
  <form method="post" action="{{ url_for('delete_issue', issue_id=issue['id']) }}" class="d-inline" onsubmit="return confirm('删除将不可恢复，确定吗？');">
    <button class="btn btn-sm btn-outline-danger" type="submit">Delete</button>
  </form>
  {% endif %}
</div>

<hr>

<h4>讨论</h4>
<div class="mb-3">
  {% for comment in comments %}
    <div class="card">
      <div>
        <p class="mb-1">{{ comment['body'] }}</p>
        <small class="text-muted">by {{ comment['author_name'] }} · {{ comment['created_at'] }}</small>
        {% if user and (user['id'] == comment['author_id'] or user['id'] == issue['author_id']) %}
        <form method="post" action="{{ url_for('delete_comment', comment_id=comment['id']) }}" class="d-inline float-end" onsubmit="return confirm('删除评论？');">
          <button class="btn btn-sm btn-outline-danger">删除</button>
        </form>
        {% endif %}
      </div>
    </div>
  {% else %}
    <div class="text-muted">暂无评论</div>
  {% endfor %}
</div>

{% if user %}
<form method="post" novalidate>
  {{ comment_form.hidden_tag() }}
  <div class="mb-3">
    {{ comment_form.body.label(class="form-label") }}
    {{ comment_form.body(class="form-control", rows="4") }}
    {% for err in comment_form.body.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  {{ comment_form.submit(class="btn btn-primary") }}
</form>
{% else %}
<p><a href="{{ url_for('login', next=request.path) }}">登录</a> 后可以发表评论。</p>
{% endif %}
{% endblock %}
"""
# ----- DB helpers -----
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
def init_db_if_needed():
    if not os.path.exists(app.config['DATABASE']):
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
# ----- Auth helpers -----
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    return db.execute('SELECT id, username FROM users WHERE id = ?', (uid,)).fetchone()
# ----- Forms -----
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[InputRequired(), Length(min=3, max=50)])
    password = PasswordField('密码', validators=[InputRequired(), Length(min=6, max=128)])
    submit = SubmitField('注册')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[InputRequired(), Length(min=1, max=50)])
    password = PasswordField('密码', validators=[InputRequired(), Length(min=1, max=128)])
    next = HiddenField()
    submit = SubmitField('登录')
class IssueForm(FlaskForm):
    title = StringField('标题', validators=[InputRequired(), Length(min=1, max=200)])
    body = TextAreaField('正文', validators=[InputRequired(), Length(min=1)])
    submit = SubmitField('发布')

class CommentForm(FlaskForm):
    body = TextAreaField('评论', validators=[InputRequired(), Length(min=1)])
    submit = SubmitField('发表评论')
# ----- Routes -----
@app.route('/')
def index():
    page = max(1, int(request.args.get('page', 1)))
    per_page = 10
    offset = (page - 1) * per_page
    db = get_db()
    total = db.execute('SELECT COUNT(1) FROM issues').fetchone()[0]
    issues = db.execute('''
        SELECT issues.*, users.username AS author_name
        FROM issues JOIN users ON issues.author_id = users.id
        ORDER BY issues.is_open DESC, issues.updated_at DESC
        LIMIT ? OFFSET ?
    ''', (per_page, offset)).fetchall()
    user = current_user()
    last_page = max(1, (total + per_page - 1) // per_page)
    return render_template_string(INDEX_HTML, base=BASE_HTML, style_css=STYLE_CSS,
                                  issues=issues, user=user, page=page, last_page=last_page)
@app.route('/register', methods=('GET', 'POST'))
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        db = get_db()
        existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            flash('用户名已存在。', 'danger')
        else:
            pw_hash = generate_password_hash(password)
            db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
            db.commit()
            flash('注册成功，请登录。', 'success')
            return redirect(url_for('login'))
    return render_template_string(REGISTER_HTML, base=BASE_HTML, style_css=STYLE_CSS, form=form, user=current_user())

@app.route('/login', methods=('GET', 'POST'))
def login():
    form = LoginForm()
    if request.method == 'GET':
        form.next.data = request.args.get('next', '')
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        db = get_db()
        user = db.execute('SELECT id, username, password_hash FROM users WHERE username = ?', (username,)).fetchone()
        if user is None or not check_password_hash(user['password_hash'], password):
            flash('无效的用户名或密码。', 'danger')
        else:
            session.clear()
            session['user_id'] = user['id']
            flash('登录成功。', 'success')
            next_url = form.next.data or url_for('index')
            return redirect(next_url)
    return render_template_string(LOGIN_HTML, base=BASE_HTML, style_css=STYLE_CSS, form=form, user=current_user())
@app.route('/logout')
def logout():
    session.clear()
    flash('已登出。', 'info')
    return redirect(url_for('index'))
@app.route('/issues/new', methods=('GET', 'POST'))
@login_required
def new_issue():
    form = IssueForm()
    if form.validate_on_submit():
        db = get_db()
        db.execute('INSERT INTO issues (title, body, author_id) VALUES (?, ?, ?)',
                   (form.title.data.strip(), form.body.data.strip(), session['user_id']))
        db.commit()
        flash('创建成功。', 'success')
        return redirect(url_for('index'))
    return render_template_string(NEW_ISSUE_HTML, base=BASE_HTML, style_css=STYLE_CSS, form=form, user=current_user())
@app.route('/issues/<int:issue_id>', methods=('GET', 'POST'))
def view_issue(issue_id):
    db = get_db()
    issue = db.execute('''
        SELECT issues.*, users.username AS author_name
        FROM issues JOIN users ON issues.author_id = users.id
        WHERE issues.id = ?
    ''', (issue_id,)).fetchone()
    if not issue:
        abort(404)
    comment_form = CommentForm()
    if comment_form.validate_on_submit():
        if 'user_id' not in session:
            flash('请先登录以发表评论。', 'warning')
            return redirect(url_for('login', next=request.path))
        db.execute('INSERT INTO comments (issue_id, author_id, body) VALUES (?, ?, ?)',
                   (issue_id, session['user_id'], comment_form.body.data.strip()))
        db.execute('UPDATE issues SET updated_at = ? WHERE id = ?', (datetime.utcnow(), issue_id))
        db.commit()
        flash('评论已发布。', 'success')
        return redirect(url_for('view_issue', issue_id=issue_id))
    comments = db.execute('''
        SELECT comments.*, users.username AS author_name
        FROM comments JOIN users ON comments.author_id = users.id
        WHERE comments.issue_id = ?
        ORDER BY comments.created_at ASC
    ''', (issue_id,)).fetchall()
    return render_template_string(ISSUE_HTML, base=BASE_HTML, style_css=STYLE_CSS,
                                  issue=issue, comments=comments, user=current_user(), comment_form=comment_form)
@app.route('/issues/<int:issue_id>/toggle', methods=('POST',))
@login_required
def toggle_issue(issue_id):
    db = get_db()
    issue = db.execute('SELECT id, author_id, is_open FROM issues WHERE id = ?', (issue_id,)).fetchone()
    if not issue: abort(404)
    if issue['author_id'] != session['user_id']: abort(403)
    new_state = 0 if issue['is_open'] else 1
    db.execute('UPDATE issues SET is_open = ?, updated_at = ? WHERE id = ?', (new_state, datetime.utcnow(), issue_id))
    db.commit()
    flash('已更新状态。', 'success')
    return redirect(url_for('view_issue', issue_id=issue_id))
@app.route('/issues/<int:issue_id>/delete', methods=('POST',))
@login_required
def delete_issue(issue_id):
    db = get_db()
    issue = db.execute('SELECT id, author_id FROM issues WHERE id = ?', (issue_id,)).fetchone()
    if not issue: abort(404)
    if issue['author_id'] != session['user_id']: abort(403)
    db.execute('DELETE FROM issues WHERE id = ?', (issue_id,))
    db.commit()
    flash('帖子已删除。', 'info')
    return redirect(url_for('index'))
@app.route('/comments/<int:comment_id>/delete', methods=('POST',))
@login_required
def delete_comment(comment_id):
    db = get_db()
    comment = db.execute('''
        SELECT comments.*, issues.author_id AS issue_author_id
        FROM comments JOIN issues ON comments.issue_id = issues.id
        WHERE comments.id = ?
    ''', (comment_id,)).fetchone()
    if not comment: abort(404)
    uid = session['user_id']
    if comment['author_id'] != uid and comment['issue_author_id'] != uid:
        abort(403)
    db.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    db.commit()
    flash('评论已删除。', 'info')
    return redirect(url_for('view_issue', issue_id=comment['issue_id']))
# ----- Start -----
if __name__ == '__main__':
    init_db_if_needed()
    app.run(debug=True)
