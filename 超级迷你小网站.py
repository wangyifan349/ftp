import os
import sqlite3
import bcrypt
from flask import Flask, request, redirect, url_for, session, flash, render_template
from werkzeug.utils import secure_filename
from jinja2 import DictLoader
app = Flask(__name__)
app.secret_key = "REPLACE_WITH_YOUR_SECRET_KEY"
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

TEMPLATE_DICT = {
    "base.html": """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Flask Video App</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/css/bootstrap.min.css">
</head>
<body>
  <nav class="navbar navbar-expand-lg navbar-light bg-light">
    <a class="navbar-brand" href=" 'index') }}">视频站</a >
    <div class="collapse navbar-collapse" id="navbarNav">
      <ul class="navbar-nav mr-auto">
        {% if 'user_id' in session %}
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('profile') }}">我的主页</a >
        </li>
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('logout') }}">退出</a >
        </li>
        {% else %}
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('login') }}">登录</a >
        </li>
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('register') }}">注册</a >
        </li>
        {% endif %}
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('search') }}">搜索用户</a >
        </li>
      </ul>
    </div>
  </nav>
  <div class="container mt-3">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for message in messages %}
        <div class="alert alert-info">{{ message }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </div>
  <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
""",
    "index.html": """
{% extends "base.html" %}
{% block content %}
<h1>所有公开视频</h1>
<div class="row">
  {% for v in videos %}
  <div class="col-md-4">
    <div class="card mb-4">
      <video class="card-img-top" controls style="width:100%;">
        <source src="{{ url_for('static', filename='uploads/'+v['filename']) }}" type="video/mp4">
      </video>
      <div class="card-body">
        <h5 class="card-title">{{ v['title'] if v['title'] else '未命名' }}</h5>
        <p class="card-text">作者: {{ v['username'] }}</p >
        <a href="{{ url_for('video_detail', video_id=v['id']) }}" class="btn btn-primary">查看详情</a >
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endblock %}
""",
    "register.html": """
{% extends "base.html" %}
{% block content %}
<h1>注册</h1>
<form method="POST">
  <div class="form-group">
    <label>用户名</label>
    <input type="text" name="username" class="form-control" required>
  </div>
  <div class="form-group">
    <label>密码</label>
    <input type="password" name="password" class="form-control" required>
  </div>
  <button type="submit" class="btn btn-primary">注册</button>
</form>
{% endblock %}
""",
    "login.html": """
{% extends "base.html" %}
{% block content %}
<h1>登录</h1>
<form method="POST">
  <div class="form-group">
    <label>用户名</label>
    <input type="text" name="username" class="form-control" required>
  </div>
  <div class="form-group">
    <label>密码</label>
    <input type="password" name="password" class="form-control" required>
  </div>
  <button type="submit" class="btn btn-primary">登录</button>
</form>
{% endblock %}
""",
    "profile.html": """
{% extends "base.html" %}
{% block content %}
<h1>我的主页</h1>
<h3>上传视频</h3>
<form method="POST" enctype="multipart/form-data">
  <div class="form-group">
    <label>标题 (可选)</label>
    <input type="text" name="title" class="form-control">
  </div>
  <div class="form-check">
    <input type="checkbox" class="form-check-input" name="is_public" checked>
    <label class="form-check-label">是否公开 (默认公开)</label>
  </div>
  <div class="form-group">
    <label>选择视频</label>
    <input type="file" name="video_file" class="form-control-file" required>
  </div>
  <button type="submit" class="btn btn-success">上传</button>
</form>
<hr>
<h3>已上传视频</h3>
<div class="row">
  {% for v in videos %}
  <div class="col-md-4">
    <div class="card mb-4">
      <video class="card-img-top" controls style="width:100%;">
        <source src="{{ url_for('static', filename='uploads/'+v['filename']) }}" type="video/mp4">
      </video>
      <div class="card-body">
        <h5 class="card-title">{{ v['title'] if v['title'] else '未命名' }}</h5>
        <p class="card-text">可见性: {{ '公开' if v['is_public'] == 1 else '隐藏' }}</p >
        {% if v['is_public'] == 1 %}
        <a href="{{ url_for('set_visibility', video_id=v['id'], visibility=0) }}" class="btn btn-info">隐藏</a >
        {% else %}
        <a href="{{ url_for('set_visibility', video_id=v['id'], visibility=1) }}" class="btn btn-info">公开</a >
        {% endif %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endblock %}
""",
    "search.html": """
{% extends "base.html" %}
{% block content %}
<h1>搜索用户</h1>
<form method="POST">
  <div class="form-group">
    <label>用户名关键字</label>
    <input type="text" name="keyword" class="form-control" value="{{ keyword }}">
  </div>
  <button type="submit" class="btn btn-primary">搜索</button>
</form>
<hr>
{% if results %}
<h3>搜索结果:</h3>
<ul class="list-group">
  {% for r in results %}
  <li class="list-group-item">{{ r['username'] }}</li>
  {% endfor %}
</ul>
{% endif %}
{% endblock %}
""",
    "video.html": """
{% extends "base.html" %}
{% block content %}
<div class="card">
  <video class="card-img-top" controls style="width:100%;">
    <source src="{{ url_for('static', filename='uploads/'+video['filename']) }}" type="video/mp4">
  </video>
  <div class="card-body">
    <h5 class="card-title">{{ video['title'] if video['title'] else '未命名' }}</h5>
    <p class="card-text">作者: {{ video['username'] }}</p >
    <p class="card-text">可见性: {{ '公开' if video['is_public'] == 1 else '隐藏' }}</p >
  </div>
</div>
{% endblock %}
"""
}

app.jinja_loader = DictLoader(TEMPLATE_DICT)
def get_db_connection():
    conn = sqlite3.connect('mydatabase.db')
    conn.row_factory = sqlite3.Row
    return conn
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
@app.route('/')
def index():
    conn = get_db_connection()
    videos = conn.execute("SELECT videos.id, videos.filename, videos.title, videos.is_public, users.username FROM videos JOIN users ON videos.user_id = users.id WHERE videos.is_public = 1").fetchall()
    conn.close()
    return render_template('index.html', videos=videos)
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        hashed_pw = bcrypt.hashpw(password, bcrypt.gensalt())
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
            conn.commit()
            flash('注册成功，请登录')
            return redirect(url_for('login'))
        except:
            flash('用户名已存在！请换一个。')
        conn.close()
    return render_template('register.html')
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user:
            stored_pw = user['password']
            if bcrypt.hashpw(password, stored_pw) == stored_pw:
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('登录成功！')
                return redirect(url_for('profile'))
        flash('用户名或密码错误')
    return render_template('login.html')
@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录')
    return redirect(url_for('index'))
@app.route('/profile', methods=['GET','POST'])
def profile():
    if 'user_id' not in session:
        flash('请先登录！')
        return redirect(url_for('login'))
    conn = get_db_connection()
    if request.method == 'POST':
        title = request.form.get('title',"")
        is_public = request.form.get('is_public',"on")
        is_public_value = 1 if is_public == "on" else 0
        if 'video_file' not in request.files:
            flash('未选择文件')
            return redirect(request.url)
        file = request.files['video_file']
        if file.filename == '':
            flash('未选择文件')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            conn.execute("INSERT INTO videos (user_id, filename, title, is_public) VALUES (?,?,?,?)",(session['user_id'], filename, title, is_public_value))
            conn.commit()
            flash('视频上传成功！')
        else:
            flash('不支持的文件格式！')
    videos = conn.execute("SELECT * FROM videos WHERE user_id = ?", (session['user_id'],)).fetchall()
    conn.close()
    return render_template('profile.html', videos=videos)
@app.route('/set_visibility/<int:video_id>/<int:visibility>')
def set_visibility(video_id, visibility):
    if 'user_id' not in session:
        flash('请先登录！')
        return redirect(url_for('login'))
    conn = get_db_connection()
    video = conn.execute("SELECT * FROM videos WHERE id=? AND user_id=?", (video_id, session['user_id'])).fetchone()
    if video:
        conn.execute("UPDATE videos SET is_public=? WHERE id=?", (visibility, video_id))
        conn.commit()
        flash('视频可见性已更新')
    else:
        flash('无权操作该视频')
    conn.close()
    return redirect(url_for('profile'))
@app.route('/search', methods=['GET','POST'])
def search():
    results = []
    keyword = ""
    if request.method == 'POST':
        keyword = request.form['keyword']
        conn = get_db_connection()
        results = conn.execute("SELECT * FROM users WHERE username LIKE ?", ('%'+keyword+'%',)).fetchall()
        conn.close()
    return render_template('search.html', results=results, keyword=keyword)
@app.route('/video/<int:video_id>')
def video_detail(video_id):
    conn = get_db_connection()
    video = conn.execute("SELECT videos.*, users.username FROM videos JOIN users ON videos.user_id = users.id WHERE videos.id=?", (video_id,)).fetchone()
    conn.close()
    if not video:
        flash('视频不存在')
        return redirect(url_for('index'))
    if video['is_public'] == 0 and (('user_id' not in session) or (session['user_id'] != video['user_id'])):
        flash('该视频已被设为隐藏')
        return redirect(url_for('index'))
    return render_template('video.html', video=video)
if __name__ == '__main__':
    with get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password BLOB NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, filename TEXT NOT NULL, title TEXT, is_public INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(user_id) REFERENCES users(id))")
    app.run(debug=True)
