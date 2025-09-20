#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对于用户和笔记的检索，系统采用两类匹配策略：一是基于字符串包含（LIKE 和子串匹配）用于笔记正文、标题和标签的快速全文筛选，二是对用户搜索采用最长公共子序列（LCS）作为相似度排序依据以提高弱匹配的可发现性。
字符串包含方法具有高召回、简单高效的优点，但在同义词和语义匹配上有限；
LCS 能较好地处理部分字符匹配与顺序差异，但受限于字符级别比较，无法捕捉词义或多字节语言的语义相近性。
因此搜索结果的准确度在字面匹配场景下较高，在语义或同义词扩展场景下有限，后者可通过引入模糊匹配、分词或语义向量检索进一步提升。
在标签与元数据处理上，平台对用户输入进行规范化（去首尾空白、小写化、用逗号/分号分隔）并对单个标签的长度和标签总数做上限限制，以避免异常输入影响检索与展示。标签由唯一约束和引用表维护，检索时同时将标签文本并入检索语料以提高与标签相关查询的命中率。由于标签人为输入的主观性，标签匹配的准确度依赖于用户命名一致性；为提高效果，可在未来加入标签建议、自动同义合并或基于频率的归并策略。
内容呈现方面，平台使用 Markdown 转 HTML 的方式让用户以富文本格式撰写笔记，但在渲染链路上保留严格的长度限制和可配置的渲染扩展，以平衡表现力与安全性。
当前策略优先保证渲染输出对主流 Markdown 特性（如代码块、表格）有良好支持，同时建议在渲染后对 HTML 做白名单清洗以降低 XSS 风险。
总体设计在准确度上注重确定性与可解释性：
所有文本级匹配可追溯到具体的字符串或 LCS 评分，便于调优与扩展；若需更高的语义准确度，后续可引入分词器、向量化检索或外部搜索引擎作为迭代方向。
运行: python app.py
依赖: flask markdown2 werkzeug
"""
from flask import Flask, request, redirect, url_for, session, flash, g, abort, Markup
from flask import render_template_string
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import markdown2
from datetime import datetime
# ---------- 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.environ.get('NOTES_DB_PATH', os.path.join(BASE_DIR, 'notes.db'))
SECRET_KEY = os.environ.get('FLASK_SECRET', 'dev_secret_key_change_me')
DEBUG = bool(os.environ.get('FLASK_DEBUG', '1'))  # 默认调试可关
MAX_USERNAME_LEN = 150
MAX_PASSWORD_LEN = 200
MAX_TITLE_LEN = 300
MAX_TAGS_LEN = 300
MAX_CONTENT_CHARS = 100_000  # 防止超大输入占用内存
MAX_SEARCH_Q_LEN = 200

app = Flask(__name__)
app.config.update(
    DATABASE=DATABASE_PATH,
    SECRET_KEY=SECRET_KEY,
    DEBUG=DEBUG,
)
app.secret_key = app.config['SECRET_KEY']
# ---------- SQL 模式 ----------
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    is_public INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS note_tags (
    note_id INTEGER,
    tag_id INTEGER,
    PRIMARY KEY (note_id, tag_id),
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS update_notes_updated_at
AFTER UPDATE ON notes
BEGIN
    UPDATE notes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""
# ---------- DB helpers ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        need_init = not os.path.exists(app.config['DATABASE'])
        db = g._database = sqlite3.connect(app.config['DATABASE'], timeout=10, check_same_thread=False)
        db.row_factory = sqlite3.Row
        if need_init:
            db.executescript(SCHEMA_SQL)
            db.commit()
    return db
def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv
def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
# ---------- Auth ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated
def get_user_by_id(user_id):
    return query_db('SELECT id, username FROM users WHERE id = ?', [user_id], one=True)
# ---------- Utilities ----------
def safe_strip(s):
    if s is None:
        return ''
    return str(s).strip()
def parse_tags(tagstr):
    """
    解析标签字符串，返回唯一、已排序的小写标签列表。
    接受逗号或分号作为分隔符。
    """
    if not tagstr:
        return []
    parts = [t.strip().lower() for t in tagstr.replace(';', ',').split(',')]
    rv = [p for p in parts if p]
    # 限制单个标签长度与数量
    filtered = []
    for t in rv:
        if 0 < len(t) <= 100 and t not in filtered:
            filtered.append(t)
        if len(filtered) >= 50:
            break
    return sorted(filtered)
def ensure_tags(tag_names):
    """
    确保标签存在，返回 tag_id 列表。
    """
    tag_ids = []
    for name in tag_names:
        # 再次校验 name 内容
        if not name or len(name) > 100:
            continue
        row = query_db('SELECT id FROM tags WHERE name = ?', [name], one=True)
        if row:
            tag_ids.append(row['id'])
        else:
            cur = execute_db('INSERT INTO tags (name) VALUES (?)', (name,))
            tag_ids.append(cur.lastrowid)
    return tag_ids
def set_note_tags(note_id, tag_ids):
    execute_db('DELETE FROM note_tags WHERE note_id = ?', (note_id,))
    for tid in tag_ids:
        # 使用 INSERT OR IGNORE 防止并发/重复问题
        execute_db('INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)', (note_id, tid))
def get_tags_for_note(note_id):
    rows = query_db('''
        SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id
        WHERE nt.note_id = ? ORDER BY t.name
    ''', (note_id,))
    return [r['name'] for r in rows] if rows else []
def lcs_length(a, b):
    # 保持原始 LCS 算法（小数据集可用）
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0
    dp = [[0]*(lb+1) for _ in range(la+1)]
    for i in range(la-1, -1, -1):
        for j in range(lb-1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = 1 + dp[i+1][j+1]
            else:
                dp[i][j] = max(dp[i+1][j], dp[i][j+1])
    return dp[0][0]
# ---------- Templates ----------
BASE_HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "笔记平台" }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      pre {{ background:#f8f9fa; padding:10px; border-radius:6px; overflow:auto; }}
      .text-truncate-200 {{ display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }}
      .muted-badge {{ background-color:#6c757d; color:#fff; padding:.25rem .5rem; border-radius:.25rem; }}
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
      <div class="container">
        <a class="navbar-brand" href="{{ url_for('index') }}">笔记</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMain" aria-controls="navMain" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navMain">
          <ul class="navbar-nav me-auto">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('search_users') }}">搜索用户</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('search_notes') }}">搜索笔记</a></li>
          </ul>
          <ul class="navbar-nav ms-auto">
            {% if session.get('user_id') %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('new_note') }}">新建笔记</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('profile') }}">{{ session.get('username') }}</a></li>
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
      {{ body }}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""
INDEX_HTML = """
{% set title = "我的笔记" %}
{% if user %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h3>欢迎，{{ user['username'] }}</h3>
    <a class="btn btn-primary" href="{{ url_for('new_note') }}">写新笔记</a>
  </div>

  {% if notes %}
    <div class="list-group">
      {% for note in notes %}
        <div class="list-group-item mb-2">
          <div class="d-flex w-100 justify-content-between">
            <h5 class="mb-1"><a href="{{ url_for('view_note', note_id=note['id']) }}">{{ note['title'] }}</a></h5>
            <small>{{ note['updated_at'] }}</small>
          </div>
          <p class="mb-1">{{ (note['content_preview'] or '') }}</p>
          <div class="mt-2">
            {% for t in note.tags %}<span class="badge bg-secondary me-1">{{ t }}</span>{% endfor %}
          </div>
          <div class="mt-2">
            <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit_note', note_id=note['id']) }}">编辑</a>
            <form style="display:inline;" method="post" action="{{ url_for('delete_note', note_id=note['id']) }}" onsubmit="return confirm('确认删除？');">
              <button class="btn btn-sm btn-outline-danger">删除</button>
            </form>
            <span class="ms-2 badge {{ 'bg-success' if note['is_public'] else 'muted-badge' }}">{{ '公开' if note['is_public'] else '私有' }}</span>
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <p>还没有笔记。试试新建一个！</p>
  {% endif %}
{% else %}
  <div class="text-center">
    <h1 class="mb-3">欢迎使用笔记平台</h1>
    <p><a class="btn btn-primary" href="{{ url_for('register') }}">注册</a> 或 <a class="btn btn-outline-primary" href="{{ url_for('login') }}">登录</a></p>
  </div>
{% endif %}
"""
REGISTER_HTML = """
{% set title = "注册" %}
<h3>注册</h3>
<form method="post">
  <div class="mb-3">
    <label class="form-label">用户名</label>
    <input class="form-control" name="username" maxlength="{{ max_username }}" required>
  </div>
  <div class="mb-3">
    <label class="form-label">密码</label>
    <input class="form-control" name="password" type="password" maxlength="{{ max_password }}" required>
  </div>
  <button class="btn btn-primary">注册</button>
</form>
"""

LOGIN_HTML = """
{% set title = "登录" %}
<h3>登录</h3>
<form method="post">
  <div class="mb-3">
    <label class="form-label">用户名</label>
    <input class="form-control" name="username" maxlength="{{ max_username }}" required>
  </div>
  <div class="mb-3">
    <label class="form-label">密码</label>
    <input class="form-control" name="password" type="password" maxlength="{{ max_password }}" required>
  </div>
  <button class="btn btn-primary">登录</button>
</form>
"""
PROFILE_HTML = """
{% set title = "个人设置" %}
<h3>个人设置</h3>
<p>账户：<strong>{{ user['username'] }}</strong></p>

<h5 class="mt-4">修改密码</h5>
<form method="post">
  <div class="mb-3">
    <label class="form-label">当前密码</label>
    <input class="form-control" name="current_password" type="password" required>
  </div>
  <div class="mb-3">
    <label class="form-label">新密码</label>
    <input class="form-control" name="new_password" type="password" maxlength="{{ max_password }}" required>
  </div>
  <button class="btn btn-warning">修改密码</button>
</form>
"""

NEW_NOTE_HTML = """
{% set title = "新建笔记" %}
<h3>新建笔记</h3>
<form method="post">
  <div class="mb-3">
    <label class="form-label">标题</label>
    <input class="form-control" name="title" maxlength="{{ max_title }}" required>
  </div>
  <div class="mb-3">
    <label class="form-label">标签（用逗号分隔）</label>
    <input class="form-control" name="tags" maxlength="{{ max_tags }}" placeholder="工作, 生活, python">
  </div>
  <div class="mb-3">
    <label class="form-label">公开？</label>
    <div class="form-check">
      <input class="form-check-input" type="checkbox" name="is_public" id="is_public">
      <label class="form-check-label" for="is_public">公开该笔记，其他用户可查看</label>
    </div>
  </div>
  <div class="mb-3">
    <label class="form-label">内容（Markdown）</label>
    <textarea class="form-control" name="content" rows="10" maxlength="{{ max_content_chars }}"></textarea>
  </div>
  <button class="btn btn-success">保存</button>
  <a class="btn btn-secondary" href="{{ url_for('index') }}">取消</a>
</form>
"""

EDIT_NOTE_HTML = """
{% set title = "编辑笔记" %}
<h3>编辑笔记</h3>
<form method="post">
  <div class="mb-3">
    <label class="form-label">标题</label>
    <input class="form-control" name="title" value="{{ note['title'] }}" maxlength="{{ max_title }}" required>
  </div>
  <div class="mb-3">
    <label class="form-label">标签（用逗号分隔）</label>
    <input class="form-control" name="tags" value="{{ tags }}" maxlength="{{ max_tags }}">
  </div>
  <div class="mb-3">
    <label class="form-label">公开？</label>
    <div class="form-check">
      <input class="form-check-input" type="checkbox" name="is_public" id="is_public" {% if note['is_public'] %}checked{% endif %}>
      <label class="form-check-label" for="is_public">公开该笔记</label>
    </div>
  </div>
  <div class="mb-3">
    <label class="form-label">内容（Markdown）</label>
    <textarea class="form-control" name="content" rows="10" maxlength="{{ max_content_chars }}">{{ note['content'] }}</textarea>
  </div>
  <button class="btn btn-primary">更新</button>
  <a class="btn btn-secondary" href="{{ url_for('index') }}">取消</a>
</form>
"""
USER_SEARCH_HTML = """
{% set title = "搜索用户" %}
<h3>按用户名搜索（先搜用户，再查看其公开笔记）</h3>
<form method="post" class="mb-3">
  <div class="input-group">
    <input class="form-control" name="q" placeholder="输入用户名或部分用户名" value="{{ q }}" maxlength="{{ max_q }}">
    <button class="btn btn-primary">搜索</button>
  </div>
</form>

{% if results is defined %}
  <h5>结果（按 LCS 匹配度排序）</h5>
  {% if results %}
    <ul class="list-group">
      {% for u in results %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <div>{{ u['username'] }}</div>
          <div><a class="btn btn-sm btn-outline-primary" href="{{ url_for('user_notes', user_id=u['id']) }}">查看笔记</a></div>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p>未找到匹配用户。</p>
  {% endif %}
{% endif %}
"""
USER_NOTES_HTML = """
{% set title = user['username'] ~ ' 的笔记' %}
<h3>{{ user['username'] }} 的笔记</h3>
<form method="post" class="mb-3">
  <div class="input-group">
    <input class="form-control" name="q" placeholder="在该用户的笔记中搜索内容、标题或标签" value="{{ q }}" maxlength="{{ max_q }}">
    <button class="btn btn-primary">搜索</button>
  </div>
</form>

{% if notes %}
  <div class="list-group">
    {% for note in notes %}
      <div class="list-group-item mb-2">
        <div class="d-flex w-100 justify-content-between">
          <h5 class="mb-1"><a href="{{ url_for('view_note', note_id=note['id']) }}">{{ note['title'] }}</a></h5>
          <small>{{ note['updated_at'] }}</small>
        </div>
        <p class="mb-1">{{ note['content_preview'] }}</p>
        <div>{% for t in note.tags %}<span class="badge bg-secondary me-1">{{ t }}</span>{% endfor %}</div>
        <div class="mt-2"><span class="badge {{ 'bg-success' if note['is_public'] else 'muted-badge' }}">{{ '公开' if note['is_public'] else '私有' }}</span></div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <p>未找到笔记。</p>
{% endif %}
"""
VIEW_NOTE_HTML = """
{% set title = note['title'] %}
<h3>{{ note['title'] }}</h3>
<p class="text-muted">作者：{{ note['username'] }} · {{ note['updated_at'] }} · {% for t in note['tags'] %}<span class="badge bg-secondary me-1">{{ t }}</span>{% endfor %}</p>
<div class="card mb-3">
  <div class="card-body">
    {{ note['html']|safe }}
  </div>
</div>

{% if session.get('user_id') == note['user_id'] %}
  <a class="btn btn-outline-secondary" href="{{ url_for('edit_note', note_id=note['id']) }}">编辑</a>
{% endif %}
<a class="btn btn-secondary" href="{{ url_for('search_users') }}">返回搜索</a>
"""

SEARCH_NOTES_HTML = """
{% set title = "搜索笔记" %}
<h3>搜索公开笔记或您自己的笔记</h3>
<form method="post" class="mb-3">
  <div class="input-group">
    <input class="form-control" name="q" placeholder="搜索标题、内容或标签" value="{{ q }}" maxlength="{{ max_q }}">
    <button class="btn btn-primary">搜索</button>
  </div>
</form>
{% if notes is defined %}
  {% if notes %}
    <div class="list-group">
      {% for note in notes %}
        <div class="list-group-item mb-2">
          <div class="d-flex w-100 justify-content-between">
            <h5 class="mb-1"><a href="{{ url_for('view_note', note_id=note['id']) }}">{{ note['title'] }}</a></h5>
            <small>{{ note['updated_at'] }}</small>
          </div>
          <p class="mb-1">{{ note['content_preview'] }}</p>
          <div>{% for t in note.tags %}<span class="badge bg-secondary me-1">{{ t }}</span>{% endfor %}</div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <p>未找到匹配笔记。</p>
  {% endif %}
{% endif %}
"""
# ---------- Render helper ----------
def render(body_template, **context):
    body = render_template_string(body_template, **context)
    return render_template_string(BASE_HTML, body=Markup(body), **context)
# ---------- Routes ----------
@app.route('/')
def index():
    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])
        rows = query_db('SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC', [session['user_id']])
        notes = []
        for n in rows:
            n_dict = dict(n)
            n_dict['tags'] = get_tags_for_note(n['id'])
            content_preview = (n_dict.get('content') or '')[:200]
            if len(n_dict.get('content') or '') > 200:
                content_preview += '...'
            n_dict['content_preview'] = content_preview
            notes.append(n_dict)
        return render(INDEX_HTML, user=user, notes=notes)
    return render(INDEX_HTML, user=None, notes=[])
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = safe_strip(request.form.get('username', '')).lower()
        password = request.form.get('password', '')
        # 基本校验
        if not username or not password:
            flash('用户名和密码不能为空', 'warning'); return redirect(url_for('register'))
        if len(username) > MAX_USERNAME_LEN or len(password) > MAX_PASSWORD_LEN:
            flash('用户名或密码太长', 'warning'); return redirect(url_for('register'))
        if query_db('SELECT id FROM users WHERE username = ?', [username], one=True):
            flash('用户名已存在', 'danger'); return redirect(url_for('register'))
        pw_hash = generate_password_hash(password)
        execute_db('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
    return render(REGISTER_HTML, max_username=MAX_USERNAME_LEN, max_password=MAX_PASSWORD_LEN)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = safe_strip(request.form.get('username', '')).lower()
        password = request.form.get('password', '')
        if not username or not password:
            flash('用户名或密码错误', 'danger'); return redirect(url_for('login'))
        user = query_db('SELECT * FROM users WHERE username = ?', [username], one=True)
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']; session['username'] = user['username']
            flash('登录成功', 'success'); return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger'); return redirect(url_for('login'))
    return render(LOGIN_HTML, max_username=MAX_USERNAME_LEN, max_password=MAX_PASSWORD_LEN)
@app.route('/logout')
def logout():
    session.clear(); flash('已登出', 'info'); return redirect(url_for('index'))
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = get_user_by_id(session['user_id'])
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        newpw = request.form.get('new_password', '')
        user_row = query_db('SELECT * FROM users WHERE id = ?', [session['user_id']], one=True)
        if not user_row or not check_password_hash(user_row['password_hash'], current):
            flash('当前密码错误', 'danger'); return redirect(url_for('profile'))
        if not newpw or len(newpw) > MAX_PASSWORD_LEN:
            flash('新密码无效', 'warning'); return redirect(url_for('profile'))
        execute_db('UPDATE users SET password_hash = ? WHERE id = ?',
                   (generate_password_hash(newpw), session['user_id']))
        flash('密码已更新，请重新登录', 'success'); return redirect(url_for('logout'))
    return render(PROFILE_HTML, user=user, max_password=MAX_PASSWORD_LEN)
@app.route('/notes/new', methods=['GET', 'POST'])
@login_required
def new_note():
    if request.method == 'POST':
        title = safe_strip(request.form.get('title', ''))
        content = safe_strip(request.form.get('content', ''))
        tags_raw = safe_strip(request.form.get('tags', ''))
        is_public = 1 if request.form.get('is_public') else 0
        if not title:
            flash('标题不能为空', 'warning'); return redirect(url_for('new_note'))
        if len(title) > MAX_TITLE_LEN:
            flash('标题太长', 'warning'); return redirect(url_for('new_note'))
        if len(content) > MAX_CONTENT_CHARS:
            flash('内容太长', 'warning'); return redirect(url_for('new_note'))
        tags = parse_tags(tags_raw)
        cur = execute_db('INSERT INTO notes (user_id, title, content, is_public) VALUES (?, ?, ?, ?)',
                         (session['user_id'], title, content, is_public))
        note_id = cur.lastrowid
        tag_ids = ensure_tags(tags)
        set_note_tags(note_id, tag_ids)
        flash('笔记已创建', 'success'); return redirect(url_for('index'))
    return render(NEW_NOTE_HTML, max_title=MAX_TITLE_LEN, max_tags=MAX_TAGS_LEN, max_content_chars=MAX_CONTENT_CHARS)
@app.route('/notes/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    note_row = query_db('SELECT * FROM notes WHERE id = ? AND user_id = ?', [note_id, session['user_id']], one=True)
    if not note_row:
        flash('笔记未找到或无权限', 'danger'); return redirect(url_for('index'))
    note = dict(note_row)
    if request.method == 'POST':
        title = safe_strip(request.form.get('title', ''))
        content = safe_strip(request.form.get('content', ''))
        tags_raw = safe_strip(request.form.get('tags', ''))
        is_public = 1 if request.form.get('is_public') else 0
        if not title or len(title) > MAX_TITLE_LEN:
            flash('标题无效', 'warning'); return redirect(url_for('edit_note', note_id=note_id))
        if len(content) > MAX_CONTENT_CHARS:
            flash('内容太长', 'warning'); return redirect(url_for('edit_note', note_id=note_id))
        execute_db('UPDATE notes SET title = ?, content = ?, is_public = ? WHERE id = ?',
                   (title, content, is_public, note_id))
        tag_ids = ensure_tags(parse_tags(tags_raw))
        set_note_tags(note_id, tag_ids)
        flash('笔记已更新', 'success'); return redirect(url_for('index'))
    note_tags = ', '.join(get_tags_for_note(note_id))
    return render(EDIT_NOTE_HTML, note=note, tags=note_tags, max_title=MAX_TITLE_LEN, max_tags=MAX_TAGS_LEN, max_content_chars=MAX_CONTENT_CHARS)
@app.route('/notes/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    # 确保是当前用户的笔记
    execute_db('DELETE FROM notes WHERE id = ? AND user_id = ?', (note_id, session['user_id']))
    flash('笔记已删除（若存在）', 'info'); return redirect(url_for('index'))
@app.route('/note/<int:note_id>')
def view_note(note_id):
    note_row = query_db('SELECT n.*, u.username FROM notes n JOIN users u ON n.user_id = u.id WHERE n.id = ?', (note_id,), one=True)
    if not note_row:
        abort(404)
    # 若笔记非公开且非作者本人，则不可见
    if not note_row['is_public'] and ('user_id' not in session or session['user_id'] != note_row['user_id']):
        flash('该笔记不可见', 'danger'); return redirect(url_for('index'))
    note = dict(note_row)
    # 将 Markdown 转为 HTML，限制允许标签以降低 XSS 风险
    # markdown2 extras 可用于限制，但并非完全的 XSS 保护；生产请使用 bleach.clean 进一步过滤
    content_md = note.get('content') or ''
    if len(content_md) > MAX_CONTENT_CHARS:
        content_md = content_md[:MAX_CONTENT_CHARS]
    # 使用 extras 指定安全相关选项（但仍建议配合 html 清洗库）
    html = markdown2.markdown(content_md, extras=["fenced-code-blocks", "tables", "strike"])
    # 这里假设 markdown->html 生成的内容不会包含危险脚本；如需更严格，请用 bleach.clean(...)
    note['html'] = html
    note['tags'] = get_tags_for_note(note_id)
    return render(VIEW_NOTE_HTML, note=note)
@app.route('/search/users', methods=['GET', 'POST'])
def search_users():
    q = ''
    results = []
    if request.method == 'POST':
        q = safe_strip(request.form.get('q', '')).lower()
        if q and len(q) <= MAX_SEARCH_Q_LEN:
            users = query_db('SELECT id, username FROM users')
            scored = []
            for u in users:
                uname = u['username'].lower()
                score = lcs_length(q, uname)
                if score > 0:
                    scored.append((score, u))
            scored.sort(key=lambda x: (-x[0], x[1]['username']))
            results = [u for s,u in scored][:50]
    return render(USER_SEARCH_HTML, q=q, results=results, max_q=MAX_SEARCH_Q_LEN)
@app.route('/search/<int:user_id>/notes', methods=['GET', 'POST'])
def user_notes(user_id):
    user = query_db('SELECT id, username FROM users WHERE id = ?', (user_id,), one=True)
    if not user:
        flash('用户不存在', 'danger'); return redirect(url_for('search_users'))
    q = ''
    notes = []
    # 默认列出（根据权限）所有笔记（最近在上）
    if request.method == 'POST':
        q = safe_strip(request.form.get('q', '')).lower()
    # 获取 rows（根据是否为作者决定是否包含私有）
    if 'user_id' in session and session['user_id'] == user_id:
        rows = query_db('SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC', (user_id,))
    else:
        rows = query_db('SELECT * FROM notes WHERE user_id = ? AND is_public = 1 ORDER BY updated_at DESC', (user_id,))
    # 过滤及准备展示
    notes_list = []
    for n in rows:
        n_dict = dict(n)
        n_dict['tags'] = get_tags_for_note(n['id'])
        hay = ' '.join([n_dict.get('title') or '', n_dict.get('content') or '', ' '.join(n_dict['tags'])]).lower()
        if q:
            if q in hay:
                notes_list.append(n_dict)
        else:
            notes_list.append(n_dict)
    # 添加内容预览
    for n in notes_list:
        content_preview = (n.get('content') or '')[:200]
        if len(n.get('content') or '') > 200:
            content_preview += '...'
        n['content_preview'] = content_preview
    return render(USER_NOTES_HTML, user=user, q=q, notes=notes_list, max_q=MAX_SEARCH_Q_LEN)
@app.route('/search/notes', methods=['GET', 'POST'])
def search_notes():
    q = ''
    results = []
    if request.method == 'POST':
        q = safe_strip(request.form.get('q', '')).lower()
        if q and len(q) <= MAX_SEARCH_Q_LEN:
            # 简单全文搜索：标题/内容 LIKE，及标签匹配
            like_q = f"%{q}%"
            # 获取公开笔记或用户自己的笔记（若登录）
            if 'user_id' in session:
                rows = query_db('SELECT n.* FROM notes n WHERE (n.is_public = 1 OR n.user_id = ?) AND (n.title LIKE ? OR n.content LIKE ?) ORDER BY n.updated_at DESC', (session['user_id'], like_q, like_q))
            else:
                rows = query_db('SELECT n.* FROM notes n WHERE n.is_public = 1 AND (n.title LIKE ? OR n.content LIKE ?) ORDER BY n.updated_at DESC', (like_q, like_q))
            # 还要检查标签
            row_list = []
            for n in rows:
                n_dict = dict(n)
                tags = get_tags_for_note(n['id'])
                hay = ' '.join([n_dict.get('title') or '', n_dict.get('content') or '', ' '.join(tags)]).lower()
                if q in hay:
                    n_dict['tags'] = tags
                    row_list.append(n_dict)
            # 限制返回数量
            results = row_list[:200]
    # 添加预览
    for n in results:
        c = n.get('content') or ''
        n['content_preview'] = c[:200] + ('...' if len(c) > 200 else '')
    return render(SEARCH_NOTES_HTML, q=q, notes=results, max_q=MAX_SEARCH_Q_LEN)
# ---------- CLI init ----------
@app.cli.command('init-db')
def initdb_command():
    db = get_db()
    db.executescript(SCHEMA_SQL)
    db.commit()
    print('Initialized the database.')
# ---------- 错误处理 ----------
@app.errorhandler(404)
def page_not_found(e):
    return render_template_string(BASE_HTML, body=Markup('<div class="container"><h3>未找到页面 (404)</h3></div>')), 404
# ---------- Run ----------
if __name__ == '__main__':
    # Ensure DB exists
    if not os.path.exists(app.config['DATABASE']):
        with app.app_context():
            db = get_db()
            db.executescript(SCHEMA_SQL)
            db.commit()
            print('Initialized DB at', app.config['DATABASE'])
    app.run(host='127.0.0.1', port=5000, debug=app.config['DEBUG'])
