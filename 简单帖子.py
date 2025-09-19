from flask import Flask, g, render_template_string, request, redirect, url_for, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
from datetime import datetime
import os
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'issues.db')
app = Flask(__name__)
app.config['SECRET_KEY'] = 'replace-with-secure-random-key'
login_manager = LoginManager(app)
login_manager.login_view = 'login'
# ---------- Database helpers (raw SQL) ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        db.row_factory = sqlite3.Row
    return db
def query(sql, args=(), one=False, commit=False):
    db = get_db()
    cur = db.execute(sql, args)
    if commit:
        db.commit()
        cur.close()
        return None
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
def init_db():
    if os.path.exists(DB_PATH):
        return
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.executescript("""
    CREATE TABLE user (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE issue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      body TEXT,
      author_id INTEGER NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP,
      FOREIGN KEY(author_id) REFERENCES user(id)
    );
    CREATE TABLE comment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      body TEXT NOT NULL,
      author_id INTEGER NOT NULL,
      issue_id INTEGER NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP,
      FOREIGN KEY(author_id) REFERENCES user(id),
      FOREIGN KEY(issue_id) REFERENCES issue(id)
    );
    """)
    db.commit()
    db.close()

# ---------- User class for Flask-Login ----------
class SimpleUser(UserMixin):
    def __init__(self, id_, username):
        self.id = id_
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    try:
        uid = int(user_id)
    except Exception:
        return None
    user_row = query("SELECT id, username FROM user WHERE id = ?", (uid,), one=True)
    if not user_row:
        return None
    return SimpleUser(user_row['id'], user_row['username'])

# ---------- Templates ----------
base_tpl = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Issues</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('list_issues') }}">Issues</a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav me-auto mb-2 mb-lg-0"></ul>
          <span class="navbar-text text-white me-3">
            {% if current_user.is_authenticated %}
              已登录：{{ current_user.username }}
            {% endif %}
          </span>
          {% if current_user.is_authenticated %}
            <a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}">登出</a>
          {% else %}
            <a class="btn btn-outline-light btn-sm me-2" href="{{ url_for('login') }}">登录</a>
            <a class="btn btn-outline-light btn-sm" href="{{ url_for('register') }}">注册</a>
          {% endif %}
        </div>
      </div>
    </nav>
    <div class="container my-4">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="alert alert-warning" role="alert">
            {% for m in messages %}{{ m }}{% if not loop.last %}<br>{% endif %}{% endfor %}
          </div>
        {% endif %}
      {% endwith %}
      {{ body|safe }}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

list_tpl = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1 class="h3">All Issues</h1>
  {% if current_user.is_authenticated %}
    <a class="btn btn-primary" href="{{ url_for('new_issue') }}">New Issue</a>
  {% else %}
    <a class="btn btn-secondary" href="{{ url_for('login') }}">登录并创建</a>
  {% endif %}
</div>

{% for it in issues %}
  <div class="card mb-3">
    <div class="card-body">
      <h5 class="card-title"><a href="{{ url_for('view_issue', issue_id=it.id) }}" class="link-dark">{{ it.title }}</a></h5>
      <h6 class="card-subtitle mb-2 text-muted">作者: {{ it.author_name }} · {{ it.created_at }}</h6>
      <p class="card-text text-truncate" style="max-height:4.5rem;overflow:hidden;">{{ it.body or '' }}</p>
      <a href="{{ url_for('view_issue', issue_id=it.id) }}" class="card-link">查看详情</a>
    </div>
  </div>
{% else %}
  <div class="alert alert-secondary">暂无 Issues。</div>
{% endfor %}
"""

auth_tpl = """
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card">
      <div class="card-body">
        <h3 class="card-title mb-3">{{ title }}</h3>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">用户名</label>
            <input class="form-control" name="username" required value="{{ username|default('') }}">
          </div>
          <div class="mb-3">
            <label class="form-label">密码</label>
            <input class="form-control" name="password" type="password" required>
          </div>
          <button class="btn btn-primary">{{ btn_text }}</button>
        </form>
      </div>
    </div>
  </div>
</div>
"""

issue_view_tpl = """
<div class="mb-3">
  <a class="btn btn-light btn-sm" href="{{ url_for('list_issues') }}">&larr; 返回</a>
  {% if current_user.is_authenticated and (current_user.id | int) == (issue.author_id | int) %}
    <a class="btn btn-outline-primary btn-sm" href="{{ url_for('edit_issue', issue_id=issue.id) }}">编辑</a>
    <a class="btn btn-outline-danger btn-sm" href="{{ url_for('delete_issue', issue_id=issue.id) }}" onclick="return confirm('删除本 Issue？')">删除</a>
  {% endif %}
</div>

<div class="card mb-4">
  <div class="card-body">
    <h2 class="card-title">{{ issue.title }}</h2>
    <h6 class="text-muted">作者: {{ issue.author_name }} · {{ issue.created_at }}</h6>
    <hr>
    <p>{{ issue.body or '' }}</p>
  </div>
</div>

<div class="mb-3">
  <h4>评论</h4>
  {% for c in comments %}
    <div class="card mb-2">
      <div class="card-body">
        <h6 class="card-subtitle mb-2 text-muted">{{ c.author_name }} · {{ c.created_at }}</h6>
        <p class="card-text">{{ c.body }}</p>
        {% if current_user.is_authenticated and (current_user.id | int) == (c.author_id | int) %}
          <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_comment', comment_id=c.id) }}">编辑</a>
          <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_comment', comment_id=c.id) }}" onclick="return confirm('删除本评论？')">删除</a>
        {% endif %}
      </div>
    </div>
  {% else %}
    <div class="text-muted">暂无评论。</div>
  {% endfor %}
</div>

{% if current_user.is_authenticated %}
  <div class="card">
    <div class="card-body">
      <form method="post" action="{{ url_for('add_comment', issue_id=issue.id) }}">
        <div class="mb-3">
          <label class="form-label">添加评论</label>
          <textarea class="form-control" name="body" rows="4" required></textarea>
        </div>
        <button class="btn btn-primary">提交评论</button>
      </form>
    </div>
  </div>
{% else %}
  <div class="alert alert-secondary">请先 <a href="{{ url_for('login') }}">登录</a> 后发表评论。</div>
{% endif %}
"""

issue_form_tpl = """
<div class="row justify-content-center">
  <div class="col-md-8">
    <div class="card">
      <div class="card-body">
        <h3 class="card-title mb-3">{{ title }}</h3>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">标题</label>
            <input class="form-control" name="title" required value="{{ issue.title|default('') }}">
          </div>
          <div class="mb-3">
            <label class="form-label">内容</label>
            <textarea class="form-control" name="body" rows="8">{{ issue.body|default('') }}</textarea>
          </div>
          <button class="btn btn-primary">{{ btn_text }}</button>
        </form>
      </div>
    </div>
  </div>
</div>
"""

comment_form_tpl = """
<div class="row justify-content-center">
  <div class="col-md-8">
    <div class="card">
      <div class="card-body">
        <h3 class="card-title mb-3">编辑评论</h3>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">内容</label>
            <textarea class="form-control" name="body" rows="6" required>{{ comment.body }}</textarea>
          </div>
          <button class="btn btn-primary">保存</button>
        </form>
      </div>
    </div>
  </div>
</div>
"""
# ---------- Routes ----------
@app.route('/')
@app.route('/issues')
def list_issues():
    rows = query("""
      SELECT issue.id, issue.title, issue.body, issue.created_at,
             user.username AS author_name
      FROM issue
      JOIN user ON issue.author_id = user.id
      ORDER BY issue.created_at DESC
    """)
    issues = []
    for r in rows:
        issues.append({
            'id': r['id'],
            'title': r['title'],
            'body': r['body'],
            'created_at': r['created_at'],
            'author_name': r['author_name']
        })
    body = render_template_string(list_tpl, issues=issues)
    return render_template_string(base_tpl, body=body)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        exists = query("SELECT id FROM user WHERE username = ?", (username,), one=True)
        if exists:
            flash('用户名已存在')
            return redirect(url_for('register'))
        pw_hash = generate_password_hash(password)
        query("INSERT INTO user (username, password_hash) VALUES (?, ?)", (username, pw_hash), commit=True)
        user_row = query("SELECT id, username FROM user WHERE username = ?", (username,), one=True)
        user = SimpleUser(int(user_row['id']), user_row['username'])
        login_user(user)
        return redirect(url_for('list_issues'))
    body = render_template_string(auth_tpl, title='注册', btn_text='注册', username='')
    return render_template_string(base_tpl, body=body)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user_row = query("SELECT id, username, password_hash FROM user WHERE username = ?", (username,), one=True)
        if not user_row or not check_password_hash(user_row['password_hash'], password):
            flash('用户名或密码错误')
            return redirect(url_for('login'))
        user = SimpleUser(int(user_row['id']), user_row['username'])
        login_user(user)
        return redirect(url_for('list_issues'))
    body = render_template_string(auth_tpl, title='登录', btn_text='登录')
    return render_template_string(base_tpl, body=body)
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('list_issues'))
@app.route('/issues/new', methods=['GET', 'POST'])
@login_required
def new_issue():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        body_text = (request.form.get('body') or '').strip()
        if not title:
            flash('标题不能为空')
            return redirect(url_for('new_issue'))
        query("INSERT INTO issue (title, body, author_id) VALUES (?, ?, ?)",
              (title, body_text, int(current_user.id)), commit=True)
        last_row = query("SELECT id FROM issue ORDER BY id DESC LIMIT 1", one=True)
        issue_id = int(last_row['id'])
        return redirect(url_for('view_issue', issue_id=issue_id))
    body = render_template_string(issue_form_tpl, title='创建 Issue', btn_text='创建', issue={})
    return render_template_string(base_tpl, body=body)
@app.route('/issues/<int:issue_id>')
def view_issue(issue_id):
    issue_row = query("""
      SELECT issue.*, user.username AS author_name
      FROM issue JOIN user ON issue.author_id = user.id
      WHERE issue.id = ?
    """, (issue_id,), one=True)
    if not issue_row:
        abort(404)
    comments_rows = query("""
      SELECT comment.*, user.username AS author_name
      FROM comment JOIN user ON comment.author_id = user.id
      WHERE comment.issue_id = ?
      ORDER BY comment.created_at ASC
    """, (issue_id,))
    comments = []
    for c in comments_rows:
        comments.append({
            'id': c['id'],
            'body': c['body'],
            'author_id': c['author_id'],
            'author_name': c['author_name'],
            'created_at': c['created_at']
        })
    issue_dict = {
        'id': issue_row['id'],
        'title': issue_row['title'],
        'body': issue_row['body'],
        'author_id': issue_row['author_id'],
        'author_name': issue_row['author_name'],
        'created_at': issue_row['created_at']
    }
    body = render_template_string(issue_view_tpl, issue=issue_dict, comments=comments)
    return render_template_string(base_tpl, body=body)
@app.route('/issues/<int:issue_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_issue(issue_id):
    issue_row = query("SELECT * FROM issue WHERE id = ?", (issue_id,), one=True)
    if not issue_row:
        abort(404)
    if int(issue_row['author_id']) != int(current_user.id):
        abort(403)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        body_text = (request.form.get('body') or '').strip()
        if not title:
            flash('标题不能为空')
            return redirect(url_for('edit_issue', issue_id=issue_id))
        query("UPDATE issue SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
              (title, body_text, issue_id), commit=True)
        return redirect(url_for('view_issue', issue_id=issue_id))
    issue = {'title': issue_row['title'], 'body': issue_row['body'] or ''}
    body = render_template_string(issue_form_tpl, title='编辑 Issue', btn_text='保存', issue=issue)
    return render_template_string(base_tpl, body=body)
@app.route('/issues/<int:issue_id>/delete')
@login_required
def delete_issue(issue_id):
    issue_row = query("SELECT author_id FROM issue WHERE id = ?", (issue_id,), one=True)
    if not issue_row:
        abort(404)
    if int(issue_row['author_id']) != int(current_user.id):
        abort(403)
    # delete comments first due to FK
    query("DELETE FROM comment WHERE issue_id = ?", (issue_id,), commit=True)
    query("DELETE FROM issue WHERE id = ?", (issue_id,), commit=True)
    return redirect(url_for('list_issues'))
@app.route('/issues/<int:issue_id>/comments', methods=['POST'])
@login_required
def add_comment(issue_id):
    issue_row = query("SELECT id FROM issue WHERE id = ?", (issue_id,), one=True)
    if not issue_row:
        abort(404)
    body_text = (request.form.get('body') or '').strip()
    if not body_text:
        flash('评论不能为空')
        return redirect(url_for('view_issue', issue_id=issue_id))
    query("INSERT INTO comment (body, author_id, issue_id) VALUES (?, ?, ?)",
          (body_text, int(current_user.id), issue_id), commit=True)
    return redirect(url_for('view_issue', issue_id=issue_id))
@app.route('/comments/<int:comment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_comment(comment_id):
    comment_row = query("SELECT * FROM comment WHERE id = ?", (comment_id,), one=True)
    if not comment_row:
        abort(404)
    if int(comment_row['author_id']) != int(current_user.id):
        abort(403)
    if request.method == 'POST':
        body_text = (request.form.get('body') or '').strip()
        if not body_text:
            flash('评论不能为空')
            return redirect(url_for('edit_comment', comment_id=comment_id))
        query("UPDATE comment SET body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
              (body_text, comment_id), commit=True)
        return redirect(url_for('view_issue', issue_id=comment_row['issue_id']))
    comment = {'body': comment_row['body']}
    body = render_template_string(comment_form_tpl, comment=comment)
    return render_template_string(base_tpl, body=body)
@app.route('/comments/<int:comment_id>/delete')
@login_required
def delete_comment(comment_id):
    comment_row = query("SELECT * FROM comment WHERE id = ?", (comment_id,), one=True)
    if not comment_row:
        abort(404)
    if int(comment_row['author_id']) != int(current_user.id):
        abort(403)
    issue_id = comment_row['issue_id']
    query("DELETE FROM comment WHERE id = ?", (comment_id,), commit=True)
    return redirect(url_for('view_issue', issue_id=issue_id))
# ---------- Error handlers ----------
@app.errorhandler(403)
def forbidden(e):
    return render_template_string(base_tpl, body='<div class="alert alert-danger">403 Forbidden</div>'), 403
@app.errorhandler(404)
def not_found(e):
    return render_template_string(base_tpl, body='<div class="alert alert-warning">404 Not Found</div>'), 404
# ---------- Init and run ----------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
