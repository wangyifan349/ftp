from flask import Flask, g, request, redirect, url_for, session, flash, render_template_string, abort
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
# 配置
DATABASE = 'issues.db'
SECRET_KEY = os.environ.get('FLASK_SECRET', 'change-this-secret')
DEBUG = True
app = Flask(__name__)
app.config.update(SECRET_KEY=SECRET_KEY, DEBUG=DEBUG)
# ---------------------------
# Helpers: DB connection & init
# ---------------------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON;")
    return db
@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    sql = """
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
        status TEXT NOT NULL DEFAULT 'open',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id INTEGER NOT NULL,
        parent_id INTEGER,
        author_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE,
        FOREIGN KEY(parent_id) REFERENCES comments(id) ON DELETE CASCADE,
        FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """
    db = get_db()
    db.executescript(sql)
    db.commit()

# ---------------------------
# Auth utilities
# ---------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

def get_user(user_id):
    if not user_id:
        return None
    db = get_db()
    cur = db.execute('SELECT id, username, created_at FROM users WHERE id = ?', (user_id,))
    return cur.fetchone()

# ---------------------------
# LCS function for search ranking
# ---------------------------
def lcs_length(a, b):
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0
    if lb < la:
        a, b = b, a
        la, lb = lb, la
    prev = [0] * (la + 1)
    for j in range(1, lb+1):
        cur = [0] * (la + 1)
        bj = b[j-1]
        for i in range(1, la+1):
            if a[i-1] == bj:
                cur[i] = prev[i-1] + 1
            else:
                cur[i] = max(prev[i], cur[i-1])
        prev = cur
    return prev[la]

# ---------------------------
# Templates (Bootstrap) — 全部内嵌，不写文件
# ---------------------------
BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>简易 Issue 系统</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding-top: 4.5rem; }
      .comment-box { margin-left: 1.5rem; border-left: 2px solid #eee; padding-left: 1rem; }
      .search-form { width: 220px; }
      .small-search-btn { padding: .25rem .5rem; font-size: .85rem; }
      .issue-card { margin-bottom: 1rem; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('index') }}">IssueSys</a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav me-auto">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('new_issue') }}">新建 Issue</a></li>
          </ul>

          <form class="d-flex me-2" method="get" action="{{ url_for('search') }}">
            <input class="form-control form-control-sm me-1 search-form" name="q" placeholder="搜索 issues" value="{{ request.args.get('q','') }}">
            <button class="btn btn-outline-light btn-sm small-search-btn" type="submit">搜</button>
          </form>

          {% if user %}
            <span class="navbar-text text-white me-2">已登录：{{ user.username }}</span>
            <a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}">登出</a>
          {% else %}
            <a class="btn btn-outline-light btn-sm me-1" href="{{ url_for('login') }}">登录</a>
            <a class="btn btn-outline-light btn-sm" href="{{ url_for('register') }}">注册</a>
          {% endif %}
        </div>
      </div>
    </nav>

    <main class="container">
      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="mt-2">
            {% for m in messages %}
              <div class="alert alert-warning">{{ m }}</div>
            {% endfor %}
          </div>
        {% endif %}
      {% endwith %}

      {{ content }}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

INDEX_CONTENT = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h1>Issues</h1>
  <small class="text-muted">共 {{ issues|length }} 条</small>
</div>

{% for i in issues %}
  <div class="card issue-card">
    <div class="card-body">
      <h5 class="card-title"><a href="{{ url_for('view_issue', issue_id=i.id) }}">{{ i.title }}</a>
        <span class="badge bg-{{ 'success' if i.status=='open' else 'secondary' }}">{{ i.status }}</span>
      </h5>
      <h6 class="card-subtitle mb-2 text-muted">#{{ i.id }} · {{ i.username }} · {{ i.created_at }}</h6>
      <p class="card-text text-truncate">{{ i.body }}</p>
      <a href="{{ url_for('view_issue', issue_id=i.id) }}" class="card-link">查看</a>
    </div>
  </div>
{% else %}
  <p>暂无 Issue。</p>
{% endfor %}
"""

REGISTER_CONTENT = """
<h2>注册</h2>
<form method="post" class="mt-3">
  <div class="mb-3">
    <label class="form-label">用户名</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="mb-3">
    <label class="form-label">密码</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  <button class="btn btn-primary" type="submit">注册</button>
</form>
"""

LOGIN_CONTENT = """
<h2>登录</h2>
<form method="post" class="mt-3">
  <div class="mb-3">
    <label class="form-label">用户名</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="mb-3">
    <label class="form-label">密码</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  <button class="btn btn-primary" type="submit">登录</button>
</form>
"""

NEW_ISSUE_CONTENT = """
<h2>新建 Issue</h2>
<form method="post" class="mt-3">
  <div class="mb-3">
    <label class="form-label">标题</label>
    <input name="title" class="form-control" required>
  </div>
  <div class="mb-3">
    <label class="form-label">内容</label>
    <textarea name="body" class="form-control" rows="6" required></textarea>
  </div>
  <button class="btn btn-success" type="submit">创建</button>
</form>
"""

ISSUE_VIEW_CONTENT = """
<div class="mb-3">
  <h2>{{ issue.title }} <span class="badge bg-{{ 'success' if issue.status=='open' else 'secondary' }}">{{ issue.status }}</span></h2>
  <div class="text-muted">#{{ issue.id }} · {{ issue.username }} · {{ issue.created_at }}</div>
  <p class="mt-3">{{ issue.body }}</p>

  {% if user and user.id == issue.author_id and issue.status!='closed' %}
    <form method="post" action="{{ url_for('close_issue', issue_id=issue.id) }}">
      <button class="btn btn-outline-secondary btn-sm">关闭 Issue</button>
    </form>
  {% endif %}
</div>

<hr>
<h4>评论</h4>

{% macro render_comments(comments, parent_id=None) %}
  {% for c in comments %}
    {% if c.parent_id == parent_id %}
      <div class="mt-3">
        <div class="d-flex justify-content-between">
          <div><strong>{{ c.username }}</strong> <small class="text-muted">{{ c.created_at }}</small></div>
          <div></div>
        </div>
        <div class="mt-1">{{ c.body }}</div>

        <!-- 回复表单（可折叠） -->
        {% if user %}
          <button class="btn btn-link btn-sm mt-1" type="button" data-bs-toggle="collapse" data-bs-target="#reply-{{ c.id }}">回复</button>
          <div class="collapse" id="reply-{{ c.id }}">
            <form method="post" class="mt-2">
              <input type="hidden" name="parent_id" value="{{ c.id }}">
              <div class="mb-2">
                <textarea name="body" class="form-control" rows="2" required></textarea>
              </div>
              <button class="btn btn-primary btn-sm" type="submit">提交回复</button>
            </form>
          </div>
        {% else %}
          <div class="mt-1"><a href="{{ url_for('login') }}">登录</a> 后可回复</div>
        {% endif %}

        <div class="comment-box">
          {{ render_comments(comments, c.id) }}
        </div>
      </div>
    {% endif %}
  {% endfor %}
{% endmacro %}

<div class="mt-3">
  <h5>添加顶级评论</h5>
  {% if user %}
    <form method="post">
      <input type="hidden" name="parent_id" value="">
      <div class="mb-2">
        <textarea name="body" class="form-control" rows="3" required></textarea>
      </div>
      <button class="btn btn-primary" type="submit">发表评论</button>
    </form>
  {% else %}
    <p><a href="{{ url_for('login') }}">登录</a> 后可发表评论。</p>
  {% endif %}
</div>

<hr>
<h6>全部评论（按创建时间升序）</h6>
<div>
  {{ render_comments(comments) }}
</div>
"""

SEARCH_RESULTS_CONTENT = """
<h2>搜索结果： "{{ q }}"</h2>
<p class="text-muted">按 LCS 长度降序排序（越相关越靠前）。共 {{ results|length }} 条结果。</p>

{% for r in results %}
  <div class="card mb-2">
    <div class="card-body">
      <h5 class="card-title"><a href="{{ url_for('view_issue', issue_id=r.id) }}">{{ r.title }}</a></h5>
      <h6 class="card-subtitle mb-2 text-muted">#{{ r.id }} · {{ r.username }} · {{ r.created_at }}</h6>
      <p class="card-text text-truncate">{{ r.body }}</p>
      <div><small class="text-muted">score: {{ r.score }}</small></div>
    </div>
  </div>
{% else %}
  <p>无结果。</p>
{% endfor %}
"""

# ---------------------------
# Routes
# ---------------------------
@app.route('/')
def index():
    db = get_db()
    cur = db.execute('''
        SELECT issues.id, title, body, status, issues.created_at, issues.author_id, users.username
        FROM issues JOIN users ON issues.author_id = users.id
        ORDER BY issues.created_at DESC
    ''')
    issues = cur.fetchall()
    content = render_template_string(INDEX_CONTENT, issues=issues)
    return render_template_string(BASE_HTML, content=content, user=get_user(session.get('user_id')))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        if not username or not password:
            flash('用户名或密码不能为空')
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password)
        db = get_db()
        try:
            db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
            db.commit()
            flash('注册成功，请登录')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在')
            return redirect(url_for('register'))
    content = render_template_string(REGISTER_CONTENT)
    return render_template_string(BASE_HTML, content=content, user=get_user(session.get('user_id')))

@app.route('/login', methods=['GET','POST'])
def login():
    next_url = request.args.get('next') or url_for('index')
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        db = get_db()
        cur = db.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
        row = cur.fetchone()
        if row and check_password_hash(row['password_hash'], password):
            session.clear()
            session['user_id'] = row['id']
            flash('登录成功')
            return redirect(next_url)
        flash('用户名或密码错误')
        return redirect(url_for('login'))
    content = render_template_string(LOGIN_CONTENT)
    return render_template_string(BASE_HTML, content=content, user=get_user(session.get('user_id')))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/issues/new', methods=['GET','POST'])
@login_required
def new_issue():
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        body = request.form.get('body','').strip()
        if not title or not body:
            flash('标题和内容不能为空')
            return redirect(url_for('new_issue'))
        db = get_db()
        db.execute('INSERT INTO issues (title, body, author_id) VALUES (?, ?, ?)', (title, body, session['user_id']))
        db.commit()
        flash('创建成功')
        return redirect(url_for('index'))
    content = render_template_string(NEW_ISSUE_CONTENT)
    return render_template_string(BASE_HTML, content=content, user=get_user(session.get('user_id')))
@app.route('/issues/<int:issue_id>', methods=['GET','POST'])
def view_issue(issue_id):
    db = get_db()
    # 取 issue 与作者
    cur = db.execute('''
        SELECT issues.id, issues.title, issues.body, issues.status, issues.created_at, issues.updated_at, issues.author_id, users.username
        FROM issues JOIN users ON issues.author_id = users.id
        WHERE issues.id = ?
    ''', (issue_id,))
    issue = cur.fetchone()
    if not issue:
        abort(404)
    # 处理提交评论（包含回复：parent_id 可为空或指定到某条 comment id）
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('请先登录再评论')
            return redirect(url_for('login', next=request.path))
        body = request.form.get('body','').strip()
        parent_id_raw = request.form.get('parent_id', '')
        parent_id = None
        if parent_id_raw and parent_id_raw.isdigit():
            parent_id = int(parent_id_raw)
            # 验证 parent_id 属于同一 issue（防止跨 issue 嵌套）
            pcur = db.execute('SELECT id FROM comments WHERE id = ? AND issue_id = ?', (parent_id, issue_id))
            if pcur.fetchone() is None:
                parent_id = None  # 无效则当作顶级评论
        if body:
            db.execute('INSERT INTO comments (issue_id, parent_id, author_id, body) VALUES (?, ?, ?, ?)', (issue_id, parent_id, session['user_id'], body))
            db.execute('UPDATE issues SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (issue_id,))
            db.commit()
            return redirect(url_for('view_issue', issue_id=issue_id))

    # 查询该 issue 的所有评论（按创建时间升序）
    cur2 = db.execute('''
        SELECT comments.id, comments.issue_id, comments.parent_id, comments.author_id, comments.body, comments.created_at, users.username
        FROM comments JOIN users ON comments.author_id = users.id
        WHERE comments.issue_id = ?
        ORDER BY comments.created_at ASC
    ''', (issue_id,))
    comments = cur2.fetchall()

    # 将 comments 转为列表字典以便模板访问属性名
    comments_list = []
    for c in comments:
        comments_list.append({
            'id': c['id'],
            'issue_id': c['issue_id'],
            'parent_id': c['parent_id'],
            'author_id': c['author_id'],
            'body': c['body'],
            'created_at': c['created_at'],
            'username': c['username']
        })

    # 渲染页面（ISSUE_VIEW_CONTENT 在前文已定义）
    content = render_template_string(ISSUE_VIEW_CONTENT, issue=issue, comments=comments_list)
    return render_template_string(BASE_HTML, content=content, user=get_user(session.get('user_id')))


@app.route('/issues/<int:issue_id>/close', methods=['POST'])
@login_required
def close_issue(issue_id):
    db = get_db()
    cur = db.execute('SELECT author_id FROM issues WHERE id = ?', (issue_id,))
    row = cur.fetchone()
    if not row:
        abort(404)
    if row['author_id'] != session['user_id']:
        abort(403)
    db.execute("UPDATE issues SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (issue_id,))
    db.commit()
    flash('Issue 已关闭')
    return redirect(url_for('view_issue', issue_id=issue_id))


@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return redirect(url_for('index'))
    db = get_db()
    # 拆词并用 LIKE 进行初步筛选，避免全表扫描
    terms = [t for t in q.split() if t]
    if terms:
        like_clauses = []
        params = []
        for t in terms:
            like = f'%{t}%'
            like_clauses.append('title LIKE ?')
            like_clauses.append('body LIKE ?')
            params.extend([like, like])
        where_clause = '(' + ' OR '.join(like_clauses) + ')'
    else:
        where_clause = '1'
        params = []
    sql = f'''
        SELECT issues.id, issues.title, issues.body, issues.status, issues.created_at, issues.author_id, users.username
        FROM issues JOIN users ON issues.author_id = users.id
        WHERE {where_clause}
    '''
    cur = db.execute(sql, params)
    candidates = cur.fetchall()

    # 计算 LCS 得分（忽略大小写）
    qnorm = q.lower()
    scored = []
    for c in candidates:
        text = (c['title'] + ' ' + c['body']).lower()
        score = lcs_length(qnorm, text)
        if score > 0:
            scored.append((score, c))

    # 按 score 降序，再按 created_at 降序
    scored.sort(key=lambda x: (-x[0], x[1]['created_at']))
    results = []
    for score, c in scored:
        results.append({
            'id': c['id'],
            'title': c['title'],
            'body': c['body'],
            'status': c['status'],
            'created_at': c['created_at'],
            'username': c['username'],
            'score': score
        })

    content = render_template_string(SEARCH_RESULTS_CONTENT, q=q, results=results)
    return render_template_string(BASE_HTML, content=content, user=get_user(session.get('user_id')))


# 运行入口：初始化 DB 并启动
if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        with app.app_context():
            init_db()
    app.run(debug=DEBUG)
