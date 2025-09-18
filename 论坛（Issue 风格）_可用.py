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
# disable CSRF token expiration to make local testing easier
app.config['WTF_CSRF_TIME_LIMIT'] = None

# ----- Schema -----
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
    labels TEXT DEFAULT '',
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

# ----- CSS (visual improvements) -----
STYLE_CSS = """
:root{
  --bg: #f6f8fa;
  --nav-bg: #0d1117;
  --muted: #6c7781;
  --accent: #1f6feb;
  --success: #2ea44f;
  --danger: #d73a49;
  --card-bg: #ffffff;
}
*{box-sizing:border-box}
body{
  margin:0;
  font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial;
  background: linear-gradient(180deg,var(--bg) 0%, #eef3f7 100%);
  color: #0b1220;
  -webkit-font-smoothing:antialiased;
}
.app-header{
  background: var(--nav-bg);
  color: #c9d1d9;
  padding: 0.6rem 1rem;
  box-shadow: 0 1px 0 rgba(0,0,0,0.4);
}
.container{
  max-width: 1600px;
  margin: 1.25rem auto;
  padding: 0 1.25rem;
}
.header-row{ display:flex; align-items:center; gap:1rem; }
.brand{ font-weight:700; font-size:1.25rem; color:#ffffff; margin-right:0.75rem; text-decoration:none; }
.header-search{ flex:1; }
.nav-actions{ margin-left:auto; display:flex; gap:0.5rem; align-items:center; }

.btn {
  display:inline-block;
  padding:0.45rem 0.7rem;
  border-radius:6px;
  background: #fff;
  color: #0b1220;
  text-decoration:none;
  font-size:0.9rem;
  border:1px solid rgba(27,31,35,0.06);
}
.btn-primary { background: var(--accent); color:#fff; border-color:rgba(31,111,235,0.12); }
.small { font-size:0.86rem; color:var(--muted); }

.layout {
  display:flex;
  gap:1.5rem;
  align-items:flex-start;
}
.main {
  flex: 1 1 auto;
  min-width: 0;
  background: var(--card-bg);
  border-radius:10px;
  padding: 1.25rem;
  box-shadow: 0 8px 24px rgba(15,23,42,0.06);
}
.sidebar {
  width: 320px;
  background: var(--card-bg);
  border-radius:10px;
  padding:1rem;
  box-shadow: 0 8px 20px rgba(15,23,42,0.04);
}
/* Issues list */
.issue-list { list-style:none; padding:0; margin:0; }
.issue-item {
  border-bottom:1px solid #eef3f6;
  padding:1rem 0;
  display:flex;
  gap:1rem;
  align-items:flex-start;
}
.issue-metadata { width:160px; flex-shrink:0; color:var(--muted); font-size:0.9rem; }
.issue-main { flex:1; }
.issue-title { margin:0; font-size:1.05rem; color:var(--accent); text-decoration:none; font-weight:600; }
.issue-excerpt { margin:0.35rem 0; color:#374151; }
.issue-flags { display:flex; gap:0.6rem; align-items:center; margin-top:0.35rem; flex-wrap:wrap; }
.label {
  display:inline-block;
  padding:0.18rem 0.5rem;
  background:#e6f0ff;
  color: #0b4dd8;
  border-radius:999px;
  font-size:0.78rem;
  border:1px solid rgba(11,77,216,0.08);
}

/* Issue detail */
.issue-header { border-bottom:1px solid #eef3f6; padding-bottom:0.6rem; margin-bottom:0.9rem; }
.issue-title-big { font-size:1.45rem; margin:0; color:#0b1220; }
.issue-meta { color:var(--muted); margin-top:0.35rem; }
.issue-body {
  background:#fff;
  padding:1rem;
  border-radius:8px;
  border:1px solid #eef3f6;
  color:#111827;
  margin-bottom:0.9rem;
}

/* Comment */
.comment {
  border:1px solid #eef3f6;
  border-radius:12px;
  padding:0.9rem;
  margin-bottom:0.75rem;
  background: #fff;
  box-shadow: 0 2px 6px rgba(12,18,28,0.03);
}
.comment .meta { color:var(--muted); font-size:0.86rem; margin-bottom:0.5rem; }
.comment .body { color:#111827; white-space:pre-wrap; }

/* Forms */
.form-control {
  width:100%;
  padding:0.6rem 0.75rem;
  border-radius:8px;
  border:1px solid #e6eef6;
  font-size:0.95rem;
  background:#fff;
}

/* footer */
.footer {
  text-align:center;
  color:var(--muted);
  margin:1rem 0;
  font-size:0.95rem;
}

/* Responsive */
@media (max-width: 1000px){
  .layout{ flex-direction:column; }
  .sidebar{ width:100%;}
}
"""
# ----- BASE_HTML (no Jinja blocks) -----
BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>{{ style_css }}</style>
</head>
<body>
<header class="app-header">
  <div class="container header-row">
    <a class="brand" href="{{ url_for('index') }}">Repo·Mini</a>
    <div class="header-search">
      <form method="get" action="{{ url_for('index') }}">
        <input name="q" class="form-control" placeholder="Search issues (LCS relevance)" value="{{ request.args.get('q','') }}">
      </form>
    </div>
    <div class="nav-actions">
      {% if user %}
        <a class="btn" href="#">{{ user['username'] }}</a>
        <a class="btn" href="{{ url_for('new_issue') }}">New issue</a>
        <a class="btn" href="{{ url_for('logout') }}">Sign out</a>
      {% else %}
        <a class="btn" href="{{ url_for('login') }}">Sign in</a>
        <a class="btn btn-primary" href="{{ url_for('register') }}">Sign up</a>
      {% endif %}
    </div>
  </div>
</header>

<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div style="margin-top:0.6rem;">
      {% for category, msg in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  {{ body|safe }}
</div>
<div class="container footer">
  版权所有2025
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# ----- Body templates -----
INDEX_BODY = """
<div class="layout">
  <main class="main">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.6rem;">
      <h1 style="margin:0;">Issues</h1>
      <div class="small">共 {{ total }} 个 · 第 {{ page }} 页 / 共 {{ last_page }} 页</div>
    </div>

    <ul class="issue-list">
      {% for issue, score in issues %}
      <li class="issue-item">
        <div class="issue-metadata">
          {% if issue['is_open'] %}
            <div style="color:var(--success); font-weight:700;">● Open</div>
          {% else %}
            <div style="color:var(--danger); font-weight:700;">● Closed</div>
          {% endif %}
          <div style="margin-top:0.5rem;">{{ issue['created_at'][:10] }}</div>
        </div>
        <div class="issue-main">
          <a class="issue-title" href="{{ url_for('view_issue', issue_id=issue['id']) }}">{{ issue['title'] }}</a>
          <div class="issue-excerpt">{{ issue['body'][:220] }}{% if issue['body']|length > 220 %}...{% endif %}</div>
          <div class="issue-flags">
            <div class="small">#{{ issue['id'] }}</div>
            <div class="small">opened by {{ issue['author_name'] }}</div>
            <div class="small">relevance: {{ score }}</div>
            {% if issue['labels'] %}
              {% for l in issue['labels'].split(',') if l %}
                <span class="label">{{ l }}</span>
              {% endfor %}
            {% endif %}
          </div>
        </div>
      </li>
      {% else %}
      <li class="small">暂无帖子</li>
      {% endfor %}
    </ul>

    <nav aria-label="Page navigation" class="mt-3">
      <ul class="pagination">
        <li class="page-item {% if page<=1 %}disabled{% endif %}">
          <a class="page-link" href="{{ url_for('index', page=page-1, q=request.args.get('q','')) }}">Previous</a>
        </li>
        <li class="page-item disabled"><span class="page-link">Page {{ page }} / {{ last_page }}</span></li>
        <li class="page-item {% if page>=last_page %}disabled{% endif %}">
          <a class="page-link" href="{{ url_for('index', page=page+1, q=request.args.get('q','')) }}">Next</a>
        </li>
      </ul>
    </nav>
  </main>
</div>
"""

REGISTER_BODY = """
<h2>Sign up</h2>
<form method="post" style="max-width:720px;" novalidate>
  {{ form.hidden_tag() }}
  <div class="mb-3">
    {{ form.username.label(class="form-label") }}
    {{ form.username(class="form-control") }}
    {% for err in form.username.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="mb-3">
    {{ form.password.label(class="form-label") }}
    {{ form.password(class="form-control") }}
    {% for err in form.password.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div>
    {{ form.submit(class="btn btn-primary") }}
    <a class="btn" href="{{ url_for('login') }}">Have an account? Sign in</a>
  </div>
</form>
"""

LOGIN_BODY = """
<h2>Sign in</h2>
<form method="post" style="max-width:720px;" novalidate>
  {{ form.hidden_tag() }}
  {{ form.next }}
  <div class="mb-3">
    {{ form.username.label(class="form-label") }}
    {{ form.username(class="form-control") }}
    {% for err in form.username.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div class="mb-3">
    {{ form.password.label(class="form-label") }}
    {{ form.password(class="form-control") }}
    {% for err in form.password.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
  </div>
  <div>
    {{ form.submit(class="btn btn-primary") }}
    <a class="btn" href="{{ url_for('register') }}">Create an account</a>
  </div>
</form>
"""

NEW_ISSUE_BODY = """
<h2>New issue</h2>
<form method="post" style="max-width:1000px;" novalidate>
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
  <div class="mb-3">
    <label class="form-label">Labels (comma separated)</label>
    <input name="labels" class="form-control" placeholder="bug, enhancement, docs" value="{{ labels|default('') }}">
  </div>
  {{ form.submit(class="btn btn-primary") }}
  <a class="btn" href="{{ url_for('index') }}">Cancel</a>
</form>
"""

ISSUE_BODY = """
<div class="issue-header">
  <div style="display:flex; justify-content:space-between; align-items:flex-start;">
    <div>
      <h2 class="issue-title-big">{{ issue['title'] }}</h2>
      <div class="issue-meta small">#{{ issue['id'] }} opened {{ issue['created_at'][:10] }} by {{ issue['author_name'] }}</div>
    </div>
    <div style="display:flex; gap:0.5rem; align-items:center;">
      {% if issue['is_open'] %}
        <form method="post" action="{{ url_for('toggle_issue', issue_id=issue['id']) }}" style="margin:0;">
          <button class="btn" type="submit">Close issue</button>
        </form>
      {% else %}
        <form method="post" action="{{ url_for('toggle_issue', issue_id=issue['id']) }}" style="margin:0;">
          <button class="btn btn-primary" type="submit">Reopen issue</button>
        </form>
      {% endif %}
      {% if user and user['id'] == issue['author_id'] %}
        <form method="post" action="{{ url_for('delete_issue', issue_id=issue['id']) }}" onsubmit="return confirm('Delete this issue?');" style="margin:0;">
          <button class="btn" type="submit">Delete</button>
        </form>
      {% endif %}
    </div>
  </div>

  <div style="margin-top:0.6rem;">
    {% if issue['labels'] %}
      {% for l in issue['labels'].split(',') if l %}
        <span class="label">{{ l }}</span>
      {% endfor %}
    {% endif %}
  </div>
</div>

<div class="issue-body">
  <div class="small">作者: {{ issue['author_name'] }} · {{ issue['created_at'] }}</div>
  <div style="height:8px;"></div>
  <div>{{ issue['body'] }}</div>
</div>
<h4>Comments ({{ comments|length }})</h4>
<div>
  {% for comment in comments %}
    <div class="comment">
      <div class="meta">{{ comment['author_name'] }} commented · {{ comment['created_at'] }}</div>
      <div class="body">{{ comment['body'] }}</div>
      <div style="margin-top:0.5rem;">
        {% if user and (user['id'] == comment['author_id'] or user['id'] == issue['author_id']) %}
        <form method="post" action="{{ url_for('delete_comment', comment_id=comment['id']) }}" style="display:inline;" onsubmit="return confirm('Delete comment?');">
          <button class="btn" type="submit">Delete</button>
        </form>
        {% endif %}
      </div>
    </div>
  {% else %}
    <div class="small">暂无评论</div>
  {% endfor %}
</div>

<div style="margin-top:0.9rem;">
  {% if user %}
  <form method="post" novalidate>
    {{ comment_form.hidden_tag() }}
    <div class="mb-2">
      {{ comment_form.body(class="form-control", rows="4") }}
      {% for err in comment_form.body.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
    </div>
    {{ comment_form.submit(class="btn btn-primary") }}
  </form>
  {% else %}
    <div class="small">请 <a href="{{ url_for('login', next=request.path) }}">登录</a> 后发表评论。</div>
  {% endif %}
</div>
"""
# ----- DB helpers -----
def get_db():
    """Return a sqlite3 connection stored on flask.g; set row_factory for dict-like access."""
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_db(e=None):
    """Close DB connection at the end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()
def init_db_if_needed():
    """Create database file and schema if it doesn't exist."""
    if not os.path.exists(app.config['DATABASE']):
        with sqlite3.connect(app.config['DATABASE']) as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
# ----- Auth helpers -----
def login_required(fn):
    """Decorator to require login for a route."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper
def current_user():
    """Return current logged-in user row or None."""
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    return db.execute('SELECT id, username FROM users WHERE id = ?', (uid,)).fetchone()
# ----- Forms -----
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[InputRequired(), Length(min=3, max=50)])
    password = PasswordField('密码', validators=[InputRequired(), Length(min=6, max=128)])
    submit = SubmitField('Sign up')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[InputRequired(), Length(min=1, max=50)])
    password = PasswordField('密码', validators=[InputRequired(), Length(min=1, max=128)])
    next = HiddenField()
    submit = SubmitField('Sign in')
class IssueForm(FlaskForm):
    title = StringField('标题', validators=[InputRequired(), Length(min=1, max=200)])
    body = TextAreaField('正文', validators=[InputRequired(), Length(min=1)])
    submit = SubmitField('Submit new issue')
class CommentForm(FlaskForm):
    body = TextAreaField('评论', validators=[InputRequired(), Length(min=1)])
    submit = SubmitField('Comment')
# ----- Utility: LCS (longest common subsequence) -----
def lcs_length(a: str, b: str) -> int:
    """Compute LCS length between strings a and b using dynamic programming with O(min(n,m)) space."""
    a = a or ''
    b = b or ''
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    # ensure m is the smaller dimension to slightly reduce memory (we use m+1 array)
    dp = [0] * (m + 1)
    for i in range(1, n + 1):
        prev = 0
        ai = a[i-1]
        for j in range(1, m + 1):
            temp = dp[j]
            if ai == b[j-1]:
                dp[j] = prev + 1
            else:
                # max(dp[j], dp[j-1])
                if dp[j] < dp[j-1]:
                    dp[j] = dp[j-1]
            prev = temp
    return dp[m]
# ----- Rendering helper -----
def render_full_page(title, body_template, **context):
    """Render body template into BASE_HTML with style and context."""
    # render body HTML first
    body_html = app.jinja_env.from_string(body_template).render(**context)
    # render base with body_html and style
    return render_template_string(BASE_HTML, title=title, style_css=STYLE_CSS, body=body_html, **context)
# ----- Routes -----
@app.route('/')
def index():
    """List issues with optional search. If q is provided and not special 'is:open'/'is:closed',
    perform client-side ranking using LCS on a candidate window."""
    page = max(1, int(request.args.get('page', 1)))
    per_page = 12
    offset = (page - 1) * per_page
    q = (request.args.get('q') or '').strip()
    db = get_db()
    # build where clause for special filters
    where_clauses = []
    params = []
    if q:
        if q == 'is:open':
            where_clauses.append('issues.is_open = 1')
        elif q == 'is:closed':
            where_clauses.append('issues.is_open = 0')
        else:
            # free text: do not add SQL filter, we'll rank in Python
            pass
    where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
    # total count
    count_sql = f"""
    SELECT COUNT(1)
    FROM issues
    JOIN users ON issues.author_id = users.id
    {where_sql}
    """
    total = db.execute(count_sql, tuple(params)).fetchone()[0]
    # fetch page candidates (basic)
    fetch_sql = f"""
    SELECT issues.*, users.username AS author_name
    FROM issues
    JOIN users ON issues.author_id = users.id
    {where_sql}
    ORDER BY issues.is_open DESC, issues.updated_at DESC
    LIMIT ? OFFSET ?
    """
    rows = db.execute(fetch_sql, tuple(params + [per_page, offset])).fetchall()
    issues_with_score = []
    if q and q not in ('is:open', 'is:closed'):
        # fetch more candidates to improve ranking coverage
        fetch_more_sql = f"""
        SELECT issues.*, users.username AS author_name
        FROM issues
        JOIN users ON issues.author_id = users.id
        ORDER BY issues.is_open DESC, issues.updated_at DESC
        LIMIT 200
        """
        candidates = db.execute(fetch_more_sql).fetchall()
        for r in candidates:
            text = (r['title'] or '') + "\n" + (r['body'] or '')
            score = lcs_length(q.lower(), text.lower())
            issues_with_score.append((r, score))
        # sort by score then updated_at
        issues_with_score.sort(key=lambda x: (x[1], x[0]['updated_at']), reverse=True)
        total = len(issues_with_score)
        start = offset
        end = offset + per_page
        issues_page = issues_with_score[start:end]
    else:
        # convert rows to (row, score) pairs for template compatibility
        issues_page = [(r, 1) for r in rows]

    user = current_user()
    last_page = max(1, (total + per_page - 1) // per_page)
    return render_full_page("Issues · Repo·Mini", INDEX_BODY,
                            issues=issues_page, user=user, page=page, last_page=last_page, total=total)
@app.route('/register', methods=('GET', 'POST'))
def register():
    """User registration route."""
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
    return render_full_page("Sign up · Repo·Mini", REGISTER_BODY, form=form, user=current_user())
@app.route('/login', methods=('GET', 'POST'))
def login():
    """User login route."""
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
    return render_full_page("Sign in · Repo·Mini", LOGIN_BODY, form=form, user=current_user())
@app.route('/logout')
def logout():
    """Log out current user."""
    session.clear()
    flash('已登出。', 'info')
    return redirect(url_for('index'))
# NOTE: decorator must be immediately above function definition (fixed)
@app.route('/issues/new', methods=('GET', 'POST'))
@login_required
def new_issue():
    """Create a new issue."""
    form = IssueForm()
    # when rendering GET, request.form will be empty; preserve labels from form submission if any
    labels = request.form.get('labels', '')
    if form.validate_on_submit():
        db = get_db()
        insert_sql = """
        INSERT INTO issues (title, body, author_id, labels, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """
        db.execute(insert_sql, (
            form.title.data.strip(),
            form.body.data.strip(),
            session['user_id'],
            labels.strip(),
            datetime.utcnow()
        ))
        db.commit()
        flash('Issue created.', 'success')
        return redirect(url_for('index'))
    return render_full_page("New issue · Repo·Mini", NEW_ISSUE_BODY, form=form, user=current_user(), labels=labels)
@app.route('/issues/<int:issue_id>', methods=('GET', 'POST'))
def view_issue(issue_id):
    """View single issue and handle posting comments."""
    db = get_db()
    issue_sql = """
    SELECT issues.*, users.username AS author_name
    FROM issues
    JOIN users ON issues.author_id = users.id
    WHERE issues.id = ?
    """
    issue = db.execute(issue_sql, (issue_id,)).fetchone()
    if not issue:
        abort(404)
    comment_form = CommentForm()
    if comment_form.validate_on_submit():
        if 'user_id' not in session:
            flash('请先登录以发表评论。', 'warning')
            return redirect(url_for('login', next=request.path))
        insert_comment_sql = "INSERT INTO comments (issue_id, author_id, body) VALUES (?, ?, ?)"
        db.execute(insert_comment_sql, (issue_id, session['user_id'], comment_form.body.data.strip()))
        db.execute('UPDATE issues SET updated_at = ? WHERE id = ?', (datetime.utcnow(), issue_id))
        db.commit()
        flash('评论已发布。', 'success')
        return redirect(url_for('view_issue', issue_id=issue_id))
    comments_sql = """
    SELECT comments.*, users.username AS author_name
    FROM comments
    JOIN users ON comments.author_id = users.id
    WHERE comments.issue_id = ?
    ORDER BY comments.created_at ASC
    """
    comments = db.execute(comments_sql, (issue_id,)).fetchall()
    return render_full_page(issue['title'] + " · Repo·Mini", ISSUE_BODY,
                            issue=issue, comments=comments, user=current_user(), comment_form=comment_form)
@app.route('/issues/<int:issue_id>/toggle', methods=('POST',))
@login_required
def toggle_issue(issue_id):
    """Toggle issue open/closed. Only the author may toggle."""
    db = get_db()
    issue = db.execute('SELECT id, author_id, is_open FROM issues WHERE id = ?', (issue_id,)).fetchone()
    if not issue:
        abort(404)
    if issue['author_id'] != session['user_id']:
        abort(403)
    new_state = 0 if issue['is_open'] else 1
    db.execute('UPDATE issues SET is_open = ?, updated_at = ? WHERE id = ?', (new_state, datetime.utcnow(), issue_id))
    db.commit()
    flash('Issue 状态已更新。', 'success')
    return redirect(url_for('view_issue', issue_id=issue_id))
@app.route('/issues/<int:issue_id>/delete', methods=('POST',))
@login_required
def delete_issue(issue_id):
    """Delete an issue. Only the author may delete."""
    db = get_db()
    issue = db.execute('SELECT id, author_id FROM issues WHERE id = ?', (issue_id,)).fetchone()
    if not issue:
        abort(404)
    if issue['author_id'] != session['user_id']:
        abort(403)
    db.execute('DELETE FROM issues WHERE id = ?', (issue_id,))
    db.commit()
    flash('Issue 已删除。', 'info')
    return redirect(url_for('index'))
@app.route('/comments/<int:comment_id>/delete', methods=('POST',))
@login_required
def delete_comment(comment_id):
    """Delete a comment. Allowed for comment author or issue author."""
    db = get_db()
    comment = db.execute('''
        SELECT comments.*, issues.author_id AS issue_author_id
        FROM comments JOIN issues ON comments.issue_id = issues.id
        WHERE comments.id = ?
    ''', (comment_id,)).fetchone()
    if not comment:
        abort(404)
    uid = session['user_id']
    if comment['author_id'] != uid and comment['issue_author_id'] != uid:
        abort(403)
    db.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    db.commit()
    flash('评论已删除。', 'info')
    return redirect(url_for('view_issue', issue_id=comment['issue_id']))
# ----- Start server -----
if __name__ == '__main__':
    # ensure DB exists with schema
    init_db_if_needed()
    # run Flask app
    app.run(debug=False)
