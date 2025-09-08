# app.py
"""
单文件 Flask 视频上传与管理示例（带 Bootstrap 美化）
依赖:
  pip install Flask Flask-WTF Flask-SQLAlchemy WTForms
运行:
  python app.py
访问:
  http://127.0.0.1:5000/
"""

import os
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template_string, request, redirect, url_for, flash,
    session, send_from_directory, abort
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, FileField
from wtforms.validators import DataRequired, Length

# --- 配置 ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_ROOT = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov', 'mkv'}
DB_PATH = os.path.join(BASE_DIR, 'app.db')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-change-me'  # 生产请修改
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_ROOT'] = UPLOAD_ROOT
os.makedirs(UPLOAD_ROOT, exist_ok=True)
db = SQLAlchemy(app)
# --- 模型 ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    filename = db.Column(db.String(256), nullable=False)
    title = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# --- 表单 ---
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(3, 80)])
    password = PasswordField('密码', validators=[DataRequired(), Length(6, 128)])
    submit = SubmitField('注册')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('登录')
class UploadForm(FlaskForm):
    title = StringField('标题')
    file = FileField('视频文件', validators=[DataRequired()])
    submit = SubmitField('上传')
class SearchForm(FlaskForm):
    query = StringField('搜索用户名', validators=[DataRequired()])
    submit = SubmitField('搜索')
# --- 工具 ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录。')
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapper
# --- 模板片段（Bootstrap 美化） ---
base_tpl = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>视频站</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {{ background:#f8f9fa; }}
    .card-video video {{ max-height:360px; width:100%; object-fit:contain; }}
    .user-badge {{ font-weight:600; }}
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频站</a>
    <div class="collapse navbar-collapse">
      <form class="d-flex ms-3" method="post" action="{{ url_for('index') }}">
        {{ search_form.hidden_tag() }}
        {{ search_form.query(class_="form-control me-2", placeholder="搜索用户名") }}
        <button class="btn btn-outline-light" type="submit">搜索</button>
      </form>
    </div>
    <div class="d-flex">
      {% if session.username %}
        <span class="navbar-text text-light me-2">你好，<span class="user-badge">{{ session.username }}</span></span>
        <a class="btn btn-light btn-sm me-2" href="{{ url_for('dashboard') }}">面板</a>
        <a class="btn btn-outline-light btn-sm" href="{{ url_for('logout') }}">登出</a>
      {% else %}
        <a class="btn btn-light btn-sm me-2" href="{{ url_for('login') }}">登录</a>
        <a class="btn btn-outline-light btn-sm" href="{{ url_for('register') }}">注册</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container my-4">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      {% for m in messages %}
      <div class="alert alert-info">{{ m }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {{ content }}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

index_content = """
<div class="row">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title">发现用户</h4>
        <p class="text-muted">在上方搜索框中输入用户名进行查找，或浏览热门用户。</p>
        {% if users is not none %}
          {% if users %}
            <div class="list-group">
              {% for u in users %}
                <a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                   href="{{ url_for('user_profile', username=u.username) }}">
                  <div>
                    <strong>{{ u.username }}</strong>
                    <div class="text-muted small">用户 ID: {{ u.id }}</div>
                  </div>
                  <span class="badge bg-primary rounded-pill">查看</span>
                </a>
              {% endfor %}
            </div>
          {% else %}
            <p class="text-muted">未找到用户。</p>
          {% endif %}
        {% else %}
          <p class="text-muted">输入用户名然后搜索。</p>
        {% endif %}
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card shadow-sm">
      <div class="card-body">
        <h5 class="card-title">快速操作</h5>
        {% if session.username %}
          <a class="btn btn-primary w-100 mb-2" href="{{ url_for('upload') }}">上传视频</a>
          <a class="btn btn-outline-primary w-100" href="{{ url_for('dashboard') }}">我的面板</a>
        {% else %}
          <p>登录后可上传并管理你的视频。</p>
          <a class="btn btn-primary w-100" href="{{ url_for('login') }}">登录</a>
        {% endif %}
      </div>
    </div>
  </div>
</div>
"""

auth_form_tpl = """
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">{{ title }}</h4>
        <form method="post">
          {{ form.hidden_tag() }}
          <div class="mb-3">
            {{ form.username.label(class_="form-label") }}
            {{ form.username(class_="form-control") }}
          </div>
          <div class="mb-3">
            {{ form.password.label(class_="form-label") }}
            {{ form.password(class_="form-control") }}
          </div>
          <div>
            {{ form.submit(class_="btn btn-primary") }}
            <a class="btn btn-link" href="{{ url_for('index') }}">返回</a>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
"""

dashboard_tpl = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4>个人面板 - {{ user.username }}</h4>
  <div>
    <a class="btn btn-success me-2" href="{{ url_for('upload') }}">上传视频</a>
    <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">返回首页</a>
  </div>
</div>

{% if videos %}
  <div class="row">
    {% for v in videos %}
      <div class="col-md-6 mb-4">
        <div class="card shadow-sm h-100">
          <div class="card-body d-flex flex-column">
            <h5 class="card-title">{{ v.title or v.filename }}</h5>
            <div class="card-video mb-3">
              <video controls preload="metadata">
                <source src="{{ url_for('uploaded_file', username=user.username, filename=v.filename) }}">
                您的浏览器不支持 video 标签。
              </video>
            </div>
            <div class="mt-auto d-flex justify-content-between align-items-center">
              <small class="text-muted">上传于 {{ v.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
              <form method="post" action="{{ url_for('delete_video', video_id=v.id) }}" onsubmit="return confirm('确认删除该视频？');">
                <button class="btn btn-danger btn-sm" type="submit">删除</button>
              </form>
            </div>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="card shadow-sm">
    <div class="card-body">
      <p class="text-muted">尚无视频。点击“上传视频”开始。 </p>
    </div>
  </div>
{% endif %}
"""

upload_tpl = """
<div class="row justify-content-center">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title">上传视频</h4>
        <form method="post" enctype="multipart/form-data">
          {{ form.hidden_tag() }}
          <div class="mb-3">
            {{ form.title.label(class_="form-label") }}
            {{ form.title(class_="form-control", placeholder="可选：视频标题") }}
          </div>
          <div class="mb-3">
            {{ form.file.label(class_="form-label") }}
            {{ form.file(class_="form-control") }}
            <div class="form-text">支持 mp4、webm、ogg、mov、mkv。单文件大小不超过服务器限制。</div>
          </div>
          <div>
            {{ form.submit(class_="btn btn-primary") }}
            <a class="btn btn-link" href="{{ url_for('dashboard') }}">取消</a>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
"""

user_profile_tpl = """
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4>{{ profile_user.username }} 的主页</h4>
  <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">返回首页</a>
</div>

{% if videos %}
  <div class="row">
    {% for v in videos %}
      <div class="col-md-6 mb-4">
        <div class="card shadow-sm">
          <div class="card-body">
            <h5 class="card-title">{{ v.title or v.filename }}</h5>
            <div class="card-video mb-3">
              <video controls preload="metadata">
                <source src="{{ url_for('uploaded_file', username=profile_user.username, filename=v.filename) }}">
                您的浏览器不支持 video 标签。
              </video>
            </div>
            <small class="text-muted">上传于 {{ v.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>
{% else %}
  <div class="card shadow-sm">
    <div class="card-body">
      <p class="text-muted">该用户没有公开视频。</p>
    </div>
  </div>
{% endif %}
"""
# --- 路由 ---
@app.route('/', methods=['GET', 'POST'])
def index():
    form = SearchForm()
    users = None
    if form.validate_on_submit():
        q = form.query.data.strip()
        users = User.query.filter(User.username.ilike(f'%{q}%')).all()
    content = render_template_string(index_content, users=users)
    return render_template_string(base_tpl, content=content, session=session, search_form=form)
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('用户名已存在。')
            return redirect(url_for('register'))
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录。')
        return redirect(url_for('login'))
    content = render_template_string(auth_form_tpl, form=form, title="注册")
    return render_template_string(base_tpl, content=content, session=session, search_form=SearchForm())
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('登录成功。')
            return redirect(url_for('dashboard'))
        flash('用户名或密码错误。')
    content = render_template_string(auth_form_tpl, form=form, title="登录")
    return render_template_string(base_tpl, content=content, session=session, search_form=SearchForm())

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录。')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    videos = Video.query.filter_by(owner_id=user.id).order_by(Video.created_at.desc()).all()
    content = render_template_string(dashboard_tpl, user=user, videos=videos)
    return render_template_string(base_tpl, content=content, session=session, search_form=SearchForm())
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        file = request.files.get(form.file.name)
        title = (form.title.data or '').strip()
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            user_folder = os.path.join(app.config['UPLOAD_ROOT'], session['username'])
            os.makedirs(user_folder, exist_ok=True)
            base, ext = os.path.splitext(filename)
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
            saved_name = f"{base}_{timestamp}{ext}"
            file_path = os.path.join(user_folder, saved_name)
            file.save(file_path)
            vid = Video(owner_id=session['user_id'], filename=saved_name, title=title or saved_name, created_at=datetime.utcnow())
            db.session.add(vid)
            db.session.commit()
            flash('上传成功。')
            return redirect(url_for('dashboard'))
        flash('不支持的文件类型或未选择文件。')
    content = render_template_string(upload_tpl, form=form)
    return render_template_string(base_tpl, content=content, session=session, search_form=SearchForm())
@app.route('/user/<username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    videos = Video.query.filter_by(owner_id=user.id).order_by(Video.created_at.desc()).all()
    content = render_template_string(user_profile_tpl, profile_user=user, videos=videos)
    return render_template_string(base_tpl, content=content, session=session, search_form=SearchForm())
@app.route('/uploads/<username>/<filename>')
def uploaded_file(username, filename):
    user_folder = os.path.join(app.config['UPLOAD_ROOT'], username)
    if not os.path.exists(os.path.join(user_folder, filename)):
        abort(404)
    return send_from_directory(user_folder, filename)
@app.route('/delete/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if vid.owner_id != session['user_id']:
        abort(403)
    user = User.query.get(session['user_id'])
    file_path = os.path.join(app.config['UPLOAD_ROOT'], user.username, vid.filename)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    db.session.delete(vid)
    db.session.commit()
    flash('视频已删除。')
    return redirect(url_for('dashboard'))
# --- 启动 ---
if __name__ == '__main__':
    app.run(debug=True)
