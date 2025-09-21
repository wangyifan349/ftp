#!/usr/bin/env python3
# coding: utf-8
"""
多用户在线记事本（Flask + SQLite）
特性：
- 用户注册 / 登录 / 登出 / 修改密码
- 每个用户拥有自己的记事（notes），只能查看/编辑自己的记事
- 使用 werkzeug.security 存储密码哈希
- 单文件模板（render_template_string），便于演示与部署
"""
from flask import Flask, request, g, render_template_string, redirect, url_for, flash, session
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
# 创建 Flask 应用
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 运行时请替换为安全随机字符串
# 数据库文件路径：与当前文件在同一目录下的 notes.db 文件
DATABASE = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'notes.db')
def get_db():
    """
    获取数据库连接并设置 row_factory
    """
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db
def init_db():
    """
    初始化数据库，创建 users 与 notes 表（如果尚不存在）
    users: id, username (unique), password_hash
    notes: id, user_id (foreign key), title, content
    """
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        db.commit()
        cursor.close()
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
# --- Helpers ---
def login_required(f):
    """
    装饰器：要求登录才能访问
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("请先登录。")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
def get_current_user():
    """
    返回当前登录用户的 row（或 None）
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    cursor.close()
    return user
# --- 模板（与之前风格一致，仅增加用户相关链接） ---
base_nav = '''
<nav class="navbar navbar-expand-lg">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">在线记事本</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navbarNav">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">记事列表</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('new_note') }}">新增记事</a></li>
      </ul>
      <ul class="navbar-nav">
        {% if current_user %}
          <li class="nav-item"><span class="nav-link">用户：{{ current_user.username }}</span></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('change_password') }}">修改密码</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
'''

index_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>记事列表</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 20px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <h2 class="mb-4">我的记事</h2>
    {% if notes|length == 0 %}
      <p>暂时没有记事。<a href="{{ url_for('new_note') }}">新增一条</a></p>
    {% else %}
      <div class="row">
        {% for note in notes %}
          <div class="col-md-4">
            <div class="card">
              <div class="card-body">
                <h5 class="card-title">{{ note.title }}</h5>
                <p class="card-text">
                  {{ note.content[:100] }}{% if note.content|length > 100 %}...{% endif %}
                </p>
                <a href="{{ url_for('view_note', note_id=note.id) }}" class="btn btn-custom">查看详情</a>
                <a href="{{ url_for('edit_note', note_id=note.id) }}" class="btn btn-outline-dark">编辑</a>
              </div>
            </div>
          </div>
        {% endfor %}
      </div>
    {% endif %}
  </div>

  <footer class="footer text-center mt-4">
    <p>&copy; 2025 在线记事本</p>
  </footer>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

view_note_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{{ note.title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 20px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <h2>{{ note.title }}</h2>
    <p>{{ note.content }}</p>
    <a href="{{ url_for('edit_note', note_id=note.id) }}" class="btn btn-custom">编辑记事</a>
    <a href="{{ url_for('index') }}" class="btn btn-secondary">返回列表</a>
  </div>

  <footer class="footer text-center mt-4">
      <p>&copy; 2025 在线记事本</p>
  </footer>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

new_note_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>新增记事</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 20px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <h2>新增记事</h2>
    <form method="POST" action="{{ url_for('new_note') }}">
      <div class="mb-3">
        <label for="title" class="form-label">标题：</label>
        <input type="text" class="form-control" id="title" name="title" required>
      </div>
      <div class="mb-3">
        <label for="content" class="form-label">内容：</label>
        <textarea class="form-control" id="content" name="content" rows="6" required></textarea>
      </div>
      <button type="submit" class="btn btn-custom">保存记事</button>
    </form>
    <a href="{{ url_for('index') }}" class="btn btn-secondary mt-2">返回列表</a>
  </div>

  <footer class="footer text-center mt-4">
      <p>&copy; 2025 在线记事本</p>
  </footer>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
edit_note_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>编辑记事</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 20px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <h2>编辑记事</h2>
    <form method="POST" action="{{ url_for('edit_note', note_id=note.id) }}">
      <div class="mb-3">
        <label for="title" class="form-label">标题：</label>
        <input type="text" class="form-control" id="title" name="title" value="{{ note.title }}" required>
      </div>
      <div class="mb-3">
        <label for="content" class="form-label">内容：</label>
        <textarea class="form-control" id="content" name="content" rows="6" required>{{ note.content }}</textarea>
      </div>
      <button type="submit" class="btn btn-custom">修改记事</button>
      <a href="{{ url_for('view_note', note_id=note.id) }}" class="btn btn-secondary">取消</a>
    </form>
  </div>

  <footer class="footer text-center mt-4">
      <p>&copy; 2025 在线记事本</p>
  </footer>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

login_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>登录</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 40px; max-width: 480px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <h2>用户登录</h2>
    <form method="POST" action="{{ url_for('login') }}">
      <div class="mb-3">
        <label for="username" class="form-label">用户名：</label>
        <input type="text" class="form-control" id="username" name="username" required>
      </div>
      <div class="mb-3">
        <label for="password" class="form-label">密码：</label>
        <input type="password" class="form-control" id="password" name="password" required>
      </div>
      <button type="submit" class="btn btn-custom">登录</button>
      <a href="{{ url_for('register') }}" class="btn btn-secondary">注册</a>
    </form>
  </div>
  <footer class="footer text-center mt-4"><p>&copy; 2025 在线记事本</p></footer>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
register_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>注册</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 40px; max-width: 480px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <h2>用户注册</h2>
    <form method="POST" action="{{ url_for('register') }}">
      <div class="mb-3">
        <label for="username" class="form-label">用户名：</label>
        <input type="text" class="form-control" id="username" name="username" required>
      </div>
      <div class="mb-3">
        <label for="password" class="form-label">密码：</label>
        <input type="password" class="form-control" id="password" name="password" required>
      </div>
      <div class="mb-3">
        <label for="password2" class="form-label">确认密码：</label>
        <input type="password" class="form-control" id="password2" name="password2" required>
      </div>
      <button type="submit" class="btn btn-custom">注册</button>
      <a href="{{ url_for('login') }}" class="btn btn-secondary">已有账号？登录</a>
    </form>
  </div>
  <footer class="footer text-center mt-4"><p>&copy; 2025 在线记事本</p></footer>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
change_password_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>修改密码</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background-color: #eafaf1; }
    .navbar { background-color: #28a745; }
    .navbar-brand, .nav-link, .footer { color: #ffd700 !important; }
    .container { margin-top: 40px; max-width: 480px; }
    .btn-custom { background-color: #28a745; color: #ffd700; }
    .btn-custom:hover { background-color: #218838; color: #fff; }
  </style>
</head>
<body>
  ''' + base_nav + '''
  <div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
          <div class="alert alert-warning alert-dismissible fade show mt-2" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <h2>修改密码</h2>
    <form method="POST" action="{{ url_for('change_password') }}">
      <div class="mb-3">
        <label for="old_password" class="form-label">当前密码：</label>
        <input type="password" class="form-control" id="old_password" name="old_password" required>
      </div>
      <div class="mb-3">
        <label for="new_password" class="form-label">新密码：</label>
        <input type="password" class="form-control" id="new_password" name="new_password" required>
      </div>
      <div class="mb-3">
        <label for="new_password2" class="form-label">确认新密码：</label>
        <input type="password" class="form-control" id="new_password2" name="new_password2" required>
      </div>
      <button type="submit" class="btn btn-custom">修改密码</button>
    </form>
  </div>
  <footer class="footer text-center mt-4"><p>&copy; 2025 在线记事本</p></footer>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
# --- 路由与视图函数 ---
@app.route('/')
@login_required
def index():
    """
    仅显示当前登录用户的记事
    """
    user = get_current_user()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY id DESC', (user['id'],))
    notes = cursor.fetchall()
    cursor.close()
    return render_template_string(index_template, notes=notes, current_user=user)
@app.route('/note/<int:note_id>')
@login_required
def view_note(note_id):
    """
    查看当前用户的记事详情；若记事不存在或不属于用户，提示并重定向
    """
    user = get_current_user()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?', (note_id, user['id']))
    note = cursor.fetchone()
    cursor.close()
    if note is None:
        flash("该记事不存在或无权限查看。")
        return redirect(url_for('index'))
    return render_template_string(view_note_template, note=note, current_user=user)
@app.route('/new', methods=['GET', 'POST'])
@login_required
def new_note():
    """
    新增记事（关联当前用户）
    """
    user = get_current_user()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash("标题和内容都不能为空！")
        else:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('INSERT INTO notes (user_id, title, content) VALUES (?, ?, ?)', (user['id'], title, content))
            db.commit()
            cursor.close()
            flash("记事保存成功！")
            return redirect(url_for('index'))
    return render_template_string(new_note_template, current_user=user)
@app.route('/edit/<int:note_id>', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    """
    编辑当前用户的记事
    """
    user = get_current_user()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?', (note_id, user['id']))
    note = cursor.fetchone()
    if note is None:
        cursor.close()
        flash("该记事不存在或无权限编辑。")
        return redirect(url_for('index'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash("标题和内容都不能为空！")
        else:
            cursor.execute('UPDATE notes SET title = ?, content = ? WHERE id = ? AND user_id = ?', (title, content, note_id, user['id']))
            db.commit()
            cursor.close()
            flash("记事修改成功！")
            return redirect(url_for('view_note', note_id=note_id))
    else:
        cursor.close()
    return render_template_string(edit_note_template, note=note, current_user=user)
# --- 用户相关路由 ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    用户注册：用户名唯一，密码确认
    """
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if not username or not password:
            flash("用户名和密码不能为空。")
        elif password != password2:
            flash("两次输入的密码不一致。")
        else:
            db = get_db()
            cursor = db.cursor()
            try:
                password_hash = generate_password_hash(password)
                cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
                db.commit()
                cursor.close()
                flash("注册成功，请登录。")
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                cursor.close()
                flash("用户名已存在，请换一个。")
    return render_template_string(register_template, current_user=None)
@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    用户登录：核验密码哈希，登录后写入 session
    """
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("用户名和密码不能为空。")
        else:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            cursor.close()
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash("登录成功。")
                return redirect(url_for('index'))
            else:
                flash("用户名或密码错误。")
    return render_template_string(login_template, current_user=None)
@app.route('/logout')
def logout():
    """
    注销登录
    """
    session.clear()
    flash("已登出。")
    return redirect(url_for('login'))
@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    修改密码：需要输入当前密码并确认新密码
    """
    user = get_current_user()
    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        new_password2 = request.form.get('new_password2', '')
        if not old_password or not new_password:
            flash("请填写所有字段。")
        elif new_password != new_password2:
            flash("两次输入的新密码不一致。")
        elif not check_password_hash(user['password_hash'], old_password):
            flash("当前密码错误。")
        else:
            db = get_db()
            cursor = db.cursor()
            new_hash = generate_password_hash(new_password)
            cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user['id']))
            db.commit()
            cursor.close()
            flash("密码修改成功，请重新登录。")
            session.clear()
            return redirect(url_for('login'))
    return render_template_string(change_password_template, current_user=user)
# --- 启动入口 ---
if __name__ == '__main__':
    init_db()
    # 小提示：生产环境请使用 gunicorn/uwsgi 并更安全地管理 SECRET_KEY
    app.run(debug=False)
