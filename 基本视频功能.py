import os
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, FileField
from wtforms.validators import InputRequired, Length, DataRequired

# 配置
app = Flask(__name__)
app.secret_key = 'your_secret_key'

# 设置数据库
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/videos'
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi'}
db = SQLAlchemy(app)
# 数据库模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    videos = db.relationship('Video', backref='owner', lazy=True)
class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

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

# 用户注册表单
class RegistrationForm(FlaskForm):
    username = StringField('用户名', validators=[InputRequired(), Length(min=3, max=50)])
    password = PasswordField('密码', validators=[InputRequired(), Length(min=6)])

# 用户登录表单
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[InputRequired()])
    password = PasswordField('密码', validators=[InputRequired()])

# 上传视频表单
class UploadVideoForm(FlaskForm):
    title = StringField('视频标题', validators=[InputRequired()])
    file = FileField('视频文件', validators=[DataRequired()])

# 首页：显示视频
@app.route('/')
def index():
    videos = Video.query.all()
    return render_template_string(HTML_INDEX_TEMPLATE, videos=videos)

# 用户注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data, method='sha256')
        user = User(username=form.username.data, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，您可以登录了！', 'success')
        return redirect(url_for('login'))
    return render_template_string(HTML_REGISTER_TEMPLATE, form=form)

# 用户登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('登录成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('登录失败，请检查用户名和密码。', 'danger')
    return render_template_string(HTML_LOGIN_TEMPLATE, form=form)

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
    form = UploadVideoForm()
    if form.validate_on_submit():
        file = form.file.data
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            video = Video(title=form.title.data, filename=filename, user_id=session['user_id'])
            db.session.add(video)
            db.session.commit()
            flash('视频上传成功！', 'success')
            return redirect(url_for('index'))
    return render_template_string(HTML_UPLOAD_TEMPLATE, form=form)

# 删除视频
@app.route('/delete_video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.user_id != session['user_id']:
        flash('您无权删除此视频！', 'danger')
        return redirect(url_for('index'))
    db.session.delete(video)
    db.session.commit()
    flash('视频已删除！', 'success')
    return redirect(url_for('index'))

# 搜索视频
@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('query', '')
    videos = Video.query.filter(Video.title.like(f'%{query}%')).all()
    return render_template_string(HTML_SEARCH_TEMPLATE, videos=videos, query=query)

# 用户主页
@app.route('/user/<username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    videos = Video.query.filter_by(user_id=user.id).all()
    return render_template_string(HTML_USER_PROFILE_TEMPLATE, user=user, videos=videos)

# HTML 模板
HTML_INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>首页 - 视频管理系统</title>
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
        <form action="{{ url_for('search') }}" method="GET" class="mb-3">
            <input type="text" name="query" placeholder="搜索视频" class="form-control" value="{{ request.args.get('query') }}">
            <button type="submit" class="btn btn-secondary mt-2">搜索</button>
        </form>
        <h3>所有视频</h3>
        <div class="row">
            {% for video in videos %}
                <div class="col-md-4 mb-4">
                    <div class="card">
                        <video width="100%" height="auto" controls>
                            <source src="{{ url_for('static', filename='videos/' + video.filename) }}" type="video/mp4">
                        </video>
                        <div class="card-body">
                            <h5 class="card-title">{{ video.title }}</h5>
                            <a href="{{ url_for('user_profile', username=video.owner.username) }}" class="btn btn-link">查看用户</a>
                            {% if session['user_id'] == video.user_id %}
                            <form action="{{ url_for('delete_video', video_id=video.id) }}" method="POST" class="mt-2">
                                <button type="submit" class="btn btn-danger">删除视频</button>
                            </form>
                            {% endif %}
                        </div>
                    </div>
                </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

HTML_REGISTER_TEMPLATE = """
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
            {{ form.csrf_token }}
            <input type="text" name="username" class="form-control" placeholder="用户名" value="{{ form.username.data }}" required>
            <input type="password" name="password" class="form-control my-2" placeholder="密码" required>
            <button type="submit" class="btn btn-primary w-100">注册</button>
        </form>
        <p class="mt-3">已有账号？<a href="{{ url_for('login') }}">登录</a></p>
    </div>
</body>
</html>
"""

HTML_LOGIN_TEMPLATE = """
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
            {{ form.csrf_token }}
            <input type="text" name="username" class="form-control" placeholder="用户名" value="{{ form.username.data }}" required>
            <input type="password" name="password" class="form-control my-2" placeholder="密码" required>
            <button type="submit" class="btn btn-primary w-100">登录</button>
        </form>
        <p class="mt-3">没有账号？<a href="{{ url_for('register') }}">注册</a></p>
    </div>
</body>
</html>
"""

HTML_UPLOAD_TEMPLATE = """
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
            {{ form.csrf_token }}
            <input type="text" name="title" class="form-control" placeholder="视频标题" required>
            <input type="file" name="file" class="form-control my-2" required>
            <button type="submit" class="btn btn-primary w-100">上传</button>
        </form>
    </div>
</body>
</html>
"""

HTML_SEARCH_TEMPLATE = """
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
        <form action="{{ url_for('search') }}" method="GET" class="mb-3">
            <input type="text" name="query" placeholder="搜索视频" class="form-control" value="{{ query }}">
            <button type="submit" class="btn btn-secondary mt-2">搜索</button>
        </form>
        <h3>视频</h3>
        <div class="row">
            {% for video in videos %}
                <div class="col-md-4 mb-4">
                    <div class="card">
                        <video width="100%" height="auto" controls>
                            <source src="{{ url_for('static', filename='videos/' + video.filename) }}" type="video/mp4">
                        </video>
                        <div class="card-body">
                            <h5 class="card-title">{{ video.title }}</h5>
                        </div>
                    </div>
                </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

HTML_USER_PROFILE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ user.username }}的主页</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container">
        <h1 class="my-4">{{ user.username }}的主页</h1>
        <h3>上传的视频</h3>
        <div class="row">
            {% for video in videos %}
                <div class="col-md-4 mb-4">
                    <div class="card">
                        <video width="100%" height="auto" controls>
                            <source src="{{ url_for('static', filename='videos/' + video.filename) }}" type="video/mp4">
                        </video>
                        <div class="card-body">
                            <h5 class="card-title">{{ video.title }}</h5>
                        </div>
                    </div>
                </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

# 创建数据库和启动应用
if __name__ == "__main__":
    db.create_all()  # 创建数据库表
    app.run(debug=True)
