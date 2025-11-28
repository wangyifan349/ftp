# app.py - 单文件简易论坛（Flask + SQLite3 + Bootstrap）
# 运行: pip install Flask
#       python app.py
from flask import Flask, g, render_template_string, request, redirect, url_for, flash, session, abort
import sqlite3, os, hashlib, functools
from markupsafe import escape
from datetime import datetime

# 配置
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(APP_DIR, 'forum.db')
SECRET_KEY = 'change-this-secret-in-production'
PER_PAGE = 20

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---- DB helpers ----
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def init_db():
    if not os.path.exists(DATABASE):
        db = sqlite3.connect(DATABASE)
        c = db.cursor()
        c.executescript('''
        PRAGMA foreign_keys = ON;
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            is_closed INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        ''')
        db.commit()
        db.close()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ---- utilities ----
def hash_pwd(pw):
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

def current_user():
    if 'user_id' in session:
        return query_db('SELECT id, username FROM users WHERE id = ?', (session['user_id'],), one=True)
    return None

# ---- Jinja filters ----
from jinja2 import Markup, escape as jescape
@app.template_filter('nl2br')
def nl2br(s):
    if s is None:
        return ''
    return Markup('<br>'.join(jescape(s).splitlines()))

# ---- Templates (单文件模板) ----
BASE = '''
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>简易论坛</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
      <div class="container">
        <a class="navbar-brand" href="{{ url_for('index') }}">简易论坛</a>
        <form class="d-flex" action="{{ url_for('search_user') }}" method="get">
          <input name="q" class="form-control form-control-sm me-2" placeholder="搜索用户名" value="{{ request.args.get('q','') }}">
          <button class="btn btn-sm btn-outline-light" type="submit">搜索</button>
        </form>
        <div>
          {% if g.user %}
            <span class="text-light me-2">hi，{{ g.user['username'] }}</span>
            <a class="btn btn-sm btn-outline-light me-1" href="{{ url_for('new_post') }}">新建帖子</a>
            <a class="btn btn-sm btn-secondary" href="{{ url_for('logout') }}">退出</a>
          {% else %}
            <a class="btn btn-sm btn-outline-light me-1" href="{{ url_for('login') }}">登录</a>
            <a class="btn btn-sm btn-secondary" href="{{ url_for('register') }}">注册</a>
          {% endif %}
        </div>
      </div>
    </nav>

    <div class="container">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
              {{ message }}
              <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}
      {{ content }}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
'''

# ---- Before request: set g.user ----
@app.before_request
def load_user():
    g.user = current_user()

# ---- Routes ----
@app.route('/')
def index():
    posts = query_db('''
      SELECT p.id,p.title,p.is_closed,p.created_at,u.username,u.id as user_id
      FROM posts p JOIN users u ON p.user_id=u.id
      ORDER BY p.created_at DESC
      LIMIT ?
    ''', (PER_PAGE,))
    content = render_template_string('''
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h1 class="h3">帖子列表</h1>
      <div>
        <a class="btn btn-primary" href="{{ url_for('new_post') }}">新建帖子</a>
      </div>
    </div>
    {% if posts %}
      <div class="list-group">
        {% for p in posts %}
          <a href="{{ url_for('view_post', post_id=p['id']) }}" class="list-group-item list-group-item-action">
            <div class="d-flex w-100 justify-content-between">
              <h5 class="mb-1">{{ p['title'] }}</h5>
              <small class="text-muted">{{ p['created_at'] }}</small>
            </div>
            <div class="small text-muted">作者：<a href="{{ url_for('user_posts', username=p['username']) }}">{{ p['username'] }}</a>
              {% if p['is_closed'] %} <span class="badge bg-secondary ms-2">已关闭</span>{% endif %}
            </div>
          </a>
        {% endfor %}
      </div>
    {% else %}
      <p class="text-muted">无帖子。</p>
    {% endif %}
    ''', posts=posts)
    return render_template_string(BASE, content=content)

# 注册
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        if not username or not password:
            flash('用户名和密码不能为空', 'danger')
            return redirect(url_for('register'))
        if len(username) < 3 or len(password) < 4:
            flash('用户名至少3位，密码至少4位', 'danger')
            return redirect(url_for('register'))
        try:
            db = get_db()
            db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, hash_pwd(password)))
            db.commit()
            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在', 'danger')
            return redirect(url_for('register'))
    content = render_template_string('''
    <h2 class="h4 mb-3">注册</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input name="username" class="form-control" required minlength="3">
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input name="password" type="password" class="form-control" required minlength="4">
      </div>
      <button class="btn btn-primary">注册</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">取消</a>
    </form>
    ''')
    return render_template_string(BASE, content=content)

# 登录
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        user = query_db('SELECT * FROM users WHERE username = ?', (username,), one=True)
        if user and user['password_hash'] == hash_pwd(password):
            session['user_id'] = user['id']
            flash('登录成功', 'success')
            nxt = request.args.get('next') or url_for('index')
            return redirect(nxt)
        flash('用户名或密码错误', 'danger')
        return redirect(url_for('login'))
    content = render_template_string('''
    <h2 class="h4 mb-3">登录</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">用户名</label>
        <input name="username" class="form-control" required>
      </div>
      <div class="mb-3">
        <label class="form-label">密码</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      <button class="btn btn-primary">登录</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">取消</a>
    </form>
    ''')
    return render_template_string(BASE, content=content)
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('已退出', 'info')
    return redirect(url_for('index'))
# 新建帖子
@app.route('/post/new', methods=['GET','POST'])
@login_required
def new_post():
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        body = request.form.get('body','').strip()
        if not title or not body:
            flash('标题和内容不能为空', 'danger')
            return redirect(url_for('new_post'))
        db = get_db()
        db.execute('INSERT INTO posts (user_id, title, body) VALUES (?, ?, ?)', (g.user['id'], title, body))
        db.commit()
        flash('帖子已创建', 'success')
        return redirect(url_for('index'))
    content = render_template_string('''
    <h2 class="h4 mb-3">新建帖子</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">标题</label>
        <input name="title" class="form-control" maxlength="200" required>
      </div>
      <div class="mb-3">
        <label class="form-label">内容</label>
        <textarea name="body" rows="8" class="form-control" required></textarea>
      </div>
      <button class="btn btn-success">发布</button>
      <a class="btn btn-secondary" href="{{ url_for('index') }}">取消</a>
    </form>
    ''')
    return render_template_string(BASE, content=content)
# 查看帖子并评论
@app.route('/post/<int:post_id>', methods=['GET','POST'])
def view_post(post_id):
    post = query_db('SELECT p.*, u.username FROM posts p JOIN users u ON p.user_id=u.id WHERE p.id = ?', (post_id,), one=True)
    if not post:
        abort(404)
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('请先登录再评论', 'warning')
            return redirect(url_for('login', next=request.path))
        if post['is_closed']:
            flash('帖子已关闭，不能评论', 'danger')
            return redirect(url_for('view_post', post_id=post_id))
        body = request.form.get('body','').strip()
        if not body:
            flash('评论不能为空', 'danger')
            return redirect(url_for('view_post', post_id=post_id))
        db = get_db()
        db.execute('INSERT INTO comments (post_id, user_id, body) VALUES (?, ?, ?)', (post_id, session['user_id'], body))
        db.commit()
        flash('评论已添加', 'success')
        return redirect(url_for('view_post', post_id=post_id))
    comments = query_db('SELECT c.*, u.username FROM comments c JOIN users u ON c.user_id=u.id WHERE c.post_id = ? ORDER BY c.created_at ASC', (post_id,))
    content = render_template_string('''
    <div class="mb-3">
      <h2>{{ post['title'] }}</h2>
      <p class="text-muted">作者：<a href="{{ url_for('user_posts', username=post['username']) }}">{{ post['username'] }}</a> · 创建于 {{ post['created_at'] }}</p>
      <div class="border p-3 mb-3">{{ post['body'] | nl2br }}</div>

      {% if g.user and g.user['id'] == post['user_id'] %}
        <div class="mb-2">
          <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_post', post_id=post['id']) }}">编辑</a>
          <form method="post" action="{{ url_for('toggle_post', post_id=post['id']) }}" style="display:inline;">
            {% if post['is_closed'] %}
              <button class="btn btn-sm btn-success">打开帖子</button>
            {% else %}
              <button class="btn btn-sm btn-warning">关闭帖子（临时）</button>
            {% endif %}
          </form>
          <form method="post" action="{{ url_for('delete_post', post_id=post['id']) }}" style="display:inline;" onsubmit="return confirm('确认删除此帖子？');">
            <button class="btn btn-sm btn-danger">删除帖子</button>
          </form>
        </div>
      {% else %}
        {% if post['is_closed'] %}
          <div class="mb-2"><span class="badge bg-secondary">已关闭</span></div>
        {% endif %}
      {% endif %}
    </div>

    <hr>
    <h5>评论</h5>
    {% if g.user and not post['is_closed'] %}
    <form method="post" class="mb-3">
      <div class="mb-2">
        <textarea name="body" rows="3" class="form-control" placeholder="写下你的评论..." required></textarea>
      </div>
      <button class="btn btn-primary btn-sm" type="submit">添加评论</button>
    </form>
    {% elif post['is_closed'] %}
      <p class="text-muted">此帖子已关闭，不能添加评论。</p>
    {% else %}
      <p class="text-muted">请 <a href="{{ url_for('login', next=request.path) }}">登录</a> 后评论。</p>
    {% endif %}

    {% if comments %}
      <ul class="list-group">
        {% for c in comments %}
          <li class="list-group-item">
            <div class="d-flex justify-content-between">
              <div><strong><a href="{{ url_for('user_posts', username=c['username']) }}">{{ c['username'] }}</a></strong> · <small class="text-muted">{{ c['created_at'] }}</small></div>
              {% if g.user and g.user['id'] == c['user_id'] %}
                <form method="post" action="{{ url_for('delete_comment', comment_id=c['id']) }}" onsubmit="return confirm('确认删除评论？');">
                  <button class="btn btn-sm btn-outline-danger">删除</button>
                </form>
              {% endif %}
            </div>
            <div class="mt-2">{{ c['body'] | nl2br }}</div>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="text-muted">暂无评论。</p>
    {% endif %}
    ''', post=post, comments=comments)
    return render_template_string(BASE, content=content)
# 编辑帖子（仅作者）
@app.route('/post/<int:post_id>/edit', methods=['GET','POST'])
@login_required
def edit_post(post_id):
    post = query_db('SELECT p.*, u.username FROM posts p JOIN users u ON p.user_id=u.id WHERE p.id = ?', (post_id,), one=True)
    if not post:
        abort(404)
    if post['user_id'] != g.user['id']:
        abort(403)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        if not title or not body:
            flash('标题和内容不能为空', 'danger')
            return redirect(url_for('edit_post', post_id=post_id))
        db = get_db()
        db.execute('UPDATE posts SET title = ?, body = ?, updated_at = ? WHERE id = ?',
                   (title, body, datetime.utcnow().isoformat(), post_id))
        db.commit()
        flash('帖子已更新', 'success')
        return redirect(url_for('view_post', post_id=post_id))
    # GET：渲染编辑表单
    content = render_template_string('''
    <h2 class="h4 mb-3">编辑帖子</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">标题</label>
        <input name="title" class="form-control" maxlength="200" required value="{{ post['title'] }}">
      </div>
      <div class="mb-3">
        <label class="form-label">内容</label>
        <textarea name="body" rows="8" class="form-control" required>{{ post['body'] }}</textarea>
      </div>
      <button class="btn btn-primary">保存</button>
      <a class="btn btn-secondary" href="{{ url_for('view_post', post_id=post['id']) }}">取消</a>
    </form>
    ''', post=post)
    return render_template_string(BASE, content=content)
# 切换帖子状态：关闭（临时）或打开（仅作者）
@app.route('/post/<int:post_id>/toggle', methods=['POST'])
@login_required
def toggle_post(post_id):
    post = query_db('SELECT * FROM posts WHERE id = ?', (post_id,), one=True)
    if not post:
        abort(404)
    if post['user_id'] != g.user['id']:
        abort(403)
    new_state = 0 if post['is_closed'] else 1
    db = get_db()
    db.execute('UPDATE posts SET is_closed = ? WHERE id = ?', (new_state, post_id))
    db.commit()
    flash('帖子已{}'.format('打开' if new_state == 0 else '关闭'), 'info')
    return redirect(url_for('view_post', post_id=post_id))
# 删除帖子（仅作者）
@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = query_db('SELECT * FROM posts WHERE id = ?', (post_id,), one=True)
    if not post:
        abort(404)
    if post['user_id'] != g.user['id']:
        abort(403)
    db = get_db()
    db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    db.commit()
    flash('帖子已删除', 'info')
    return redirect(url_for('index'))
# 删除评论（仅评论作者）
@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = query_db('SELECT * FROM comments WHERE id = ?', (comment_id,), one=True)
    if not comment:
        abort(404)
    if comment['user_id'] != g.user['id']:
        abort(403)
    db = get_db()
    db.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
    db.commit()
    flash('评论已删除', 'info')
    # 尽量回到评论所属帖子页
    return redirect(request.referrer or url_for('index'))
# 查看某用户所有帖子
@app.route('/user/<username>')
def user_posts(username):
    user = query_db('SELECT id, username, created_at FROM users WHERE username = ?', (username,), one=True)
    if not user:
        flash('未找到用户', 'warning')
        return redirect(url_for('index'))
    posts = query_db('SELECT p.*, (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) as comment_count FROM posts p WHERE p.user_id = ? ORDER BY p.created_at DESC', (user['id'],))
    content = render_template_string('''
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h1 class="h5">用户：{{ user['username'] }} 的帖子</h1>
      <div><a class="btn btn-sm btn-secondary" href="{{ url_for('index') }}">返回</a></div>
    </div>
    {% if posts %}
      <div class="list-group">
        {% for p in posts %}
          <a href="{{ url_for('view_post', post_id=p['id']) }}" class="list-group-item list-group-item-action">
            <div class="d-flex w-100 justify-content-between">
              <h5 class="mb-1">{{ p['title'] }}</h5>
              <small class="text-muted">{{ p['created_at'] }}</small>
            </div>
            <div class="small text-muted">
              评论：{{ p['comment_count'] }}
              {% if p['is_closed'] %}<span class="badge bg-secondary ms-2">已关闭</span>{% endif %}
            </div>
          </a>
        {% endfor %}
      </div>
    {% else %}
      <p class="text-muted">该用户没有帖子。</p>
    {% endif %}
    ''', user=user, posts=posts)
    return render_template_string(BASE, content=content)
# 搜索用户名并重定向到该用户页面（若多个匹配则列出）
@app.route('/search_user')
def search_user():
    q = request.args.get('q', '').strip()
    if not q:
        flash('请输入用户名进行搜索', 'warning')
        return redirect(url_for('index'))
    # 模糊匹配
    like = f'%{q}%'
    users = query_db('SELECT id, username FROM users WHERE username LIKE ? ORDER BY username LIMIT 50', (like,))
    if not users:
        flash('未找到匹配用户', 'warning')
        return redirect(url_for('index'))
    if len(users) == 1:
        return redirect(url_for('user_posts', username=users[0]['username']))
    # 多个匹配时列出
    content = render_template_string('''
    <h2 class="h5 mb-3">搜索结果：{{ q }}</h2>
    <ul class="list-group">
      {% for u in users %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <div><a href="{{ url_for('user_posts', username=u['username']) }}">{{ u['username'] }}</a></div>
          <div><a class="btn btn-sm btn-outline-secondary" href="{{ url_for('user_posts', username=u['username']) }}">查看</a></div>
        </li>
      {% endfor %}
    </ul>
    ''', users=users, q=q)
    return render_template_string(BASE, content=content)
# 程序入口
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
