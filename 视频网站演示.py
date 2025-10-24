import os
import sqlite3
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# 配置
app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'static/videos'
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 数据库连接
def get_db():
    conn = sqlite3.connect('site.db')
    conn.row_factory = sqlite3.Row
    return conn

# 检查文件类型
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 用户认证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录！', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 首页：显示视频
@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM videos")
    videos = cursor.fetchall()
    conn.close()
    return render_template_string(HTML_TEMPLATE, videos=videos, session=session)

# 用户注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='sha256')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if user:
            flash('用户名已存在！', 'danger')
        else:
            cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()
            flash('注册成功，您可以登录了！', 'success')
            return redirect(url_for('login'))
        conn.close()

    return render_template_string(REGISTER_TEMPLATE)

# 用户登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('登录成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('登录失败，请检查用户名和密码。', 'danger')
        conn.close()

    return render_template_string(LOGIN_TEMPLATE)

# 用户登出
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('您已登出！', 'info')
    return redirect(url_for('login'))

# 上传视频
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_video():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('没有选择文件！', 'danger')
            return redirect(request.url)

        file = request.files['file']
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            title = request.form['title']
            user_id = session['user_id']

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO videos (title, filename, user_id) VALUES (?, ?, ?)", 
                           (title, filename, user_id))
            conn.commit()
            conn.close()
            flash('视频上传成功！', 'success')
            return redirect(url_for('index'))

    return render_template_string(UPLOAD_TEMPLATE)

# 删除视频
@app.route('/delete_video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
    video = cursor.fetchone()

    if video['user_id'] != session['user_id']:
        flash('您无权删除此视频！', 'danger')
        conn.close()
        return redirect(url_for('index'))

    cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    flash('视频已删除！', 'success')
    return redirect(url_for('index'))

# 搜索视频和用户名
@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        query = request.form['query']
        
        conn = get_db()
        cursor = conn.cursor()
        
        # 查找视频
        cursor.execute("SELECT * FROM videos WHERE title LIKE ?", ('%' + query + '%',))
        videos = cursor.fetchall()

        # 查找用户
        cursor.execute("SELECT * FROM users WHERE username LIKE ?", ('%' + query + '%',))
        users = cursor.fetchall()

        conn.close()
        return render_template_string(SEARCH_TEMPLATE, videos=videos, users=users, query=query)

    return redirect(url_for('index'))

# 访问用户主页
@app.route('/user/<username>')
def user_profile(username):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()

    if user:
        cursor.execute("SELECT * FROM videos WHERE user_id = ?", (user['id'],))
        videos = cursor.fetchall()
        conn.close()
        return render_template_string(USER_PROFILE_TEMPLATE, user=user, videos=videos)
    else:
        flash('用户不存在', 'danger')
        conn.close()
        return redirect(url_for('index'))


# HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>视频管理系统</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">视频管理系统</h1>
        {% if session['user_id'] %}
        <div class="mb-3">
            <a href="{{ url_for('logout') }}" class="btn btn-danger">登出</a>
            <a href="{{ url_for('upload_video') }}" class="btn btn-primary">上传视频</a>
        </div>
        {% endif %}
        <form action="{{ url_for('search') }}" method="POST" class="mb-3">
            <input type="text" name="query" placeholder="搜索视频或用户名" class="form-control" required>
            <button type="submit" class="btn btn-secondary mt-2">搜索</button>
        </form>

        <h3>所有视频</h3>
        <ul class="list-group">
        {% for video in videos %}
            <li class="list-group-item">
                <h5>{{ video['title'] }}</h5>
                <video width="320" height="240" controls>
                    <source src="{{ url_for('static', filename='videos/' + video['filename']) }}" type="video/mp4">
                </video>
                <div>
                    {% if session['user_id'] == video['user_id'] %}
                    <form action="{{ url_for('delete_video', video_id=video['id']) }}" method="POST" class="mt-2">
                        <button type="submit" class="btn btn-danger">删除视频</button>
                    </form>
                    {% endif %}
                </div>
            </li>
        {% endfor %}
        </ul>
    </div>
</body>
</html>
"""

REGISTER_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>注册</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">注册</h1>
        <form action="{{ url_for('register') }}" method="POST">
            <input type="text" name="username" class="form-control" placeholder="用户名" required>
            <input type="password" name="password" class="form-control my-2" placeholder="密码" required>
            <button type="submit" class="btn btn-primary w-100">注册</button>
        </form>
        <p class="mt-3">已有账号？<a href="{{ url_for('login') }}">登录</a></p>
    </div>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">登录</h1>
        <form action="{{ url_for('login') }}" method="POST">
            <input type="text" name="username" class="form-control" placeholder="用户名" required>
            <input type="password" name="password" class="form-control my-2" placeholder="密码" required>
            <button type="submit" class="btn btn-primary w-100">登录</button>
        </form>
        <p class="mt-3">没有账号？<a href="{{ url_for('register') }}">注册</a></p>
    </div>
</body>
</html>
"""

UPLOAD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>上传视频</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">上传视频</h1>
        <form action="{{ url_for('upload_video') }}" method="POST" enctype="multipart/form-data">
            <input type="text" name="title" class="form-control" placeholder="视频标题" required>
            <input type="file" name="file" class="form-control my-2" required>
            <button type="submit" class="btn btn-primary w-100">上传</button>
        </form>
    </div>
</body>
</html>
"""

SEARCH_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>搜索结果</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">搜索结果</h1>

        <h3>视频</h3>
        <ul class="list-group">
        {% for video in videos %}
            <li class="list-group-item">
                <h5>{{ video['title'] }}</h5>
                <video width="320" height="240" controls>
                    <source src="{{ url_for('static', filename='videos/' + video['filename']) }}" type="video/mp4">
                </video>
            </li>
        {% endfor %}
        </ul>

        <h3 class="mt-4">用户</h3>
        <ul class="list-group">
        {% for user in users %}
            <li class="list-group-item">
                <a href="{{ url_for('user_profile', username=user['username']) }}">{{ user['username'] }}</a>
            </li>
        {% endfor %}
        </ul>
    </div>
</body>
</html>
"""

USER_PROFILE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ user['username'] }}的主页</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">{{ user['username'] }}的主页</h1>
        <h3>上传的视频</h3>
        <ul class="list-group">
        {% for video in videos %}
            <li class="list-group-item">
                <h5>{{ video['title'] }}</h5>
                <video width="320" height="240" controls>
                    <source src="{{ url_for('static', filename='videos/' + video['filename']) }}" type="video/mp4">
                </video>
            </li>
        {% endfor %}
        </ul>
    </div>
</body>
</html>
"""
# 创建数据库
if __name__ == "__main__":
    app.run(debug=True)
