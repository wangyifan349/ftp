import os
import sqlite3
from flask import Flask, request, redirect, url_for, session, flash, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
app = Flask(__name__)
app.secret_key = 'your_secret_key'
DATABASE = 'notes.db'
def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL)')
    cur.execute('CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,image BLOB,FOREIGN KEY(user_id) REFERENCES users(id))')
    conn.commit()
    conn.close()
@app.before_first_request
def before_first_request_func():
    init_db()
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn
def get_bootstrap_header(title="云端记事本"):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<div class="container mt-4">
"""

def get_bootstrap_footer():
    return """
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('note_list'))
    else:
        return redirect(url_for('login'))
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash("用户名或密码不能为空", "warning")
            return redirect(url_for('register'))
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if row:
            conn.close()
            flash("该用户名已被占用，请换一个试试", "warning")
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password)
        cur.execute("INSERT INTO users (username,password_hash) VALUES (?,?)", (username, password_hash))
        conn.commit()
        conn.close()
        flash("注册成功，请登录", "success")
        return redirect(url_for('login'))
    page_html = render_template_string(get_bootstrap_header("注册") + """
<h1>注册</h1>
<form method="POST" action="{{ url_for('register') }}">
 <div class="mb-3">
  <label class="form-label">用户名</label>
  <input type="text" class="form-control" name="username" required>
 </div>
 <div class="mb-3">
  <label class="form-label">密码</label>
  <input type="password" class="form-control" name="password" required>
 </div>
 <button type="submit" class="btn btn-primary">注册</button>
</form>
<hr>
<p>已有帐号？<a href="{{ url_for('login') }}">点此登录</a></p>
{% with messages = get_flashed_messages(category_filter=['warning','success','error']) %}
 {% if messages %}
 <ul class="mt-3 alert alert-info">
  {% for msg in messages %}
  <li>{{ msg }}</li>
  {% endfor %}
 </ul>
 {% endif %}
{% endwith %}
""" + get_bootstrap_footer())
    return page_html
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash("用户名或密码不能为空", "warning")
            return redirect(url_for('login'))
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id,password_hash FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        conn.close()
        if not user:
            flash("用户不存在或密码错误", "warning")
            return redirect(url_for('login'))
        if check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = username
            flash("登录成功", "success")
            return redirect(url_for('note_list'))
        else:
            flash("用户不存在或密码错误", "warning")
            return redirect(url_for('login'))
    page_html = render_template_string(get_bootstrap_header("登录") + """
<h1>登录</h1>
<form method="POST" action="{{ url_for('login') }}">
 <div class="mb-3">
  <label class="form-label">用户名</label>
  <input type="text" class="form-control" name="username" required>
 </div>
 <div class="mb-3">
  <label class="form-label">密码</label>
  <input type="password" class="form-control" name="password" required>
 </div>
 <button type="submit" class="btn btn-primary">登录</button>
</form>
<hr>
<p>没有帐号？<a href="{{ url_for('register') }}">点此注册</a></p>
{% with messages = get_flashed_messages(category_filter=['warning','success','error']) %}
 {% if messages %}
 <ul class="mt-3 alert alert-danger">
  {% for msg in messages %}
  <li>{{ msg }}</li>
  {% endfor %}
 </ul>
 {% endif %}
{% endwith %}
""" + get_bootstrap_footer())
    return page_html
@app.route('/logout')
def logout():
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for('login'))
@app.route('/notes', methods=['GET', 'POST'])
def note_list():
    if 'user_id' not in session:
        flash("请先登录", "warning")
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        keyword = request.form.get('keyword', '').strip()
        cur.execute("SELECT id,title,content FROM notes WHERE user_id=? AND title LIKE ? ORDER BY id DESC", (user_id, f"%{keyword}%"))
        notes = cur.fetchall()
        search_info = f"搜索标题包含“{keyword}”的笔记"
    else:
        cur.execute("SELECT id,title,content FROM notes WHERE user_id=? ORDER BY id DESC", (user_id,))
        notes = cur.fetchall()
        search_info = None
    conn.close()
    page_html = render_template_string(get_bootstrap_header("我的笔记") + """
<h1>我的笔记</h1>
<div class="mb-2">
 <span class="text-success">欢迎, {{ session.username }}！</span>
 <a href="{{ url_for('logout') }}" class="btn btn-sm btn-secondary ms-3">退出登录</a>
</div>
<hr>
<form method="POST" action="{{ url_for('note_list') }}" class="row g-3 mb-3">
 <div class="col-auto">
  <input type="text" name="keyword" class="form-control" placeholder="按标题搜索">
 </div>
 <div class="col-auto">
  <button type="submit" class="btn btn-outline-primary">搜索</button>
 </div>
 <div class="col-auto">
  <a href="{{ url_for('note_list') }}" class="btn btn-outline-secondary">清空搜索</a>
 </div>
</form>
{% if search_info %}
<p class="text-info">{{ search_info }}</p>
{% endif %}
<a href="{{ url_for('create_note') }}" class="btn btn-primary mt-2 mb-3">创建新笔记</a>
<ul class="list-group">
{% for note in notes %}
<li class="list-group-item">
 <a href="{{ url_for('note_detail',note_id=note['id']) }}" class="fw-bold">{{ note['title'] }}</a>
 <p class="mb-0 text-muted">{{ note['content'][:30] }}{% if note['content']|length > 30 %}...{% endif %}</p>
</li>
{% endfor %}
</ul>
{% with messages = get_flashed_messages(category_filter=['warning','success','info']) %}
 {% if messages %}
 <ul class="alert alert-info mt-3">
  {% for msg in messages %}
  <li>{{ msg }}</li>
  {% endfor %}
 </ul>
 {% endif %}
{% endwith %}
""" + get_bootstrap_footer(), notes=notes, search_info=search_info)
    return page_html
@app.route('/create_note', methods=['GET', 'POST'])
def create_note():
    if 'user_id' not in session:
        flash("请先登录", "warning")
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        image_file = request.files.get('image_file', None)
        if not title:
            flash("笔记标题不能为空", "warning")
            return redirect(url_for('create_note'))
        user_id = session['user_id']
        image_data = None
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_data = image_file.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO notes (user_id,title,content,image) VALUES (?,?,?,?)", (user_id, title, content, image_data))
        conn.commit()
        conn.close()
        flash("笔记创建成功", "success")
        return redirect(url_for('note_list'))
    page_html = render_template_string(get_bootstrap_header("创建笔记") + """
<h1>创建笔记</h1>
<form method="POST" enctype="multipart/form-data" action="{{ url_for('create_note') }}">
 <div class="mb-3">
  <label class="form-label">笔记标题</label>
  <input type="text" class="form-control" name="title" required>
 </div>
 <div class="mb-3">
  <label class="form-label">笔记内容</label>
  <textarea name="content" class="form-control" rows="5"></textarea>
 </div>
 <div class="mb-3">
  <label class="form-label">图片上传</label>
  <input type="file" class="form-control" name="image_file">
 </div>
 <button type="submit" class="btn btn-primary">保存</button>
</form>
<hr>
<a href="{{ url_for('note_list') }}" class="btn btn-secondary">返回笔记列表</a>
{% with messages = get_flashed_messages(category_filter=['warning','success']) %}
 {% if messages %}
 <ul class="alert alert-info mt-3">
  {% for msg in messages %}
  <li>{{ msg }}</li>
  {% endfor %}
 </ul>
 {% endif %}
{% endwith %}
""" + get_bootstrap_footer())
    return page_html
@app.route('/note/<int:note_id>')
def note_detail(note_id):
    if 'user_id' not in session:
        flash("请先登录", "warning")
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id,title,content,image FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    note = cur.fetchone()
    conn.close()
    if not note:
        flash("笔记不存在或无权访问", "warning")
        return redirect(url_for('note_list'))
    image_base64 = None
    if note['image']:
        import base64
        image_base64 = base64.b64encode(note['image']).decode('utf-8')
    page_html = render_template_string(get_bootstrap_header("笔记详情") + """
<h1>笔记详情</h1>
<div class="card mb-3">
 <div class="card-body">
  <h5 class="card-title">{{ note['title'] }}</h5>
  <p class="card-text">{{ note['content'] }}</p>
  {% if image_base64 %}
  <img src="data:image/jpeg;base64,{{ image_base64 }}" alt="笔记图片" class="img-fluid mt-3">
  {% endif %}
 </div>
</div>
<a href="{{ url_for('note_list') }}" class="btn btn-secondary">返回笔记列表</a>
<a href="{{ url_for('edit_note', note_id=note['id']) }}" class="btn btn-primary ms-2">编辑笔记</a>
{% with messages = get_flashed_messages(category_filter=['warning','success']) %}
 {% if messages %}
 <ul class="alert alert-info mt-3">
  {% for msg in messages %}
  <li>{{ msg }}</li>
  {% endfor %}
 </ul>
 {% endif %}
{% endwith %}
""" + get_bootstrap_footer(), note=note, image_base64=image_base64)
    return page_html
@app.route('/note/<int:note_id>/edit', methods=['GET', 'POST'])
def edit_note(note_id):
    if 'user_id' not in session:
        flash("请先登录", "warning")
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    # 验证笔记归属并取出当前数据
    cur.execute("SELECT id,title,content,image FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    note = cur.fetchone()
    if not note:
        conn.close()
        flash("笔记不存在或无权编辑", "warning")
        return redirect(url_for('note_list'))
    if request.method == 'POST':
        # 获取表单并处理图片（如果上传则替换，否则保留原图）
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        image_file = request.files.get('image_file', None)
        if not title:
            conn.close()
            flash("笔记标题不能为空", "warning")
            return redirect(url_for('edit_note', note_id=note_id))
        image_data = note['image']  # 默认保留原图（可能为 None）
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            image_data = image_file.read()
        cur.execute("UPDATE notes SET title=?, content=?, image=? WHERE id=? AND user_id=?", (title, content, image_data, note_id, user_id))
        conn.commit()
        conn.close()
        flash("笔记已更新", "success")
        return redirect(url_for('note_detail', note_id=note_id))
    # GET 请求，准备页面（若有图片则转 base64）
    image_base64 = None
    if note['image']:
        import base64
        image_base64 = base64.b64encode(note['image']).decode('utf-8')
    page_html = render_template_string(get_bootstrap_header("编辑笔记") + """
<h1>编辑笔记</h1>
<form method="POST" enctype="multipart/form-data" action="{{ url_for('edit_note', note_id=note['id']) }}">
 <div class="mb-3">
  <label class="form-label">笔记标题</label>
  <input type="text" class="form-control" name="title" value="{{ note['title'] }}" required>
 </div>
 <div class="mb-3">
  <label class="form-label">笔记内容</label>
  <textarea name="content" class="form-control" rows="5">{{ note['content'] }}</textarea>
 </div>
 <div class="mb-3">
  <label class="form-label">图片（上传新图片将替换旧图）</label>
  <input type="file" class="form-control" name="image_file">
 </div>
{% if image_base64 %}
<div class="mb-3">
 <label class="form-label">当前图片预览</label>
 <div><img src="data:image/jpeg;base64,{{ image_base64 }}" class="img-fluid" alt="当前图片"></div>
</div>
{% endif %}
 <button type="submit" class="btn btn-primary">保存更改</button>
 <a href="{{ url_for('note_detail', note_id=note['id']) }}" class="btn btn-secondary ms-2">取消</a>
</form>
<hr>
{% with messages = get_flashed_messages(category_filter=['warning','success']) %}
 {% if messages %}
 <ul class="alert alert-info mt-3">
  {% for msg in messages %}
  <li>{{ msg }}</li>
  {% endfor %}
 </ul>
 {% endif %}
{% endwith %}
""" + get_bootstrap_footer(), note=note, image_base64=image_base64)
    conn.close()
    return page_html
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
