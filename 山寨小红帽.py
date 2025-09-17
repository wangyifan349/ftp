# app.py
import os
import secrets
from io import BytesIO
from datetime import datetime
from flask import (
    Flask, flash, redirect, render_template_string, request,
    send_from_directory, url_for, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import FileField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

# --------------------------
# 配置
# --------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
STATIC_DIR = os.path.join(BASE_DIR, 'static')
os.makedirs(STATIC_DIR, exist_ok=True)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'app.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024  # 6 MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
# --------------------------
# 模型
# --------------------------
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    about = db.Column(db.Text, nullable=True)
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(220), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(260), nullable=True)
    thumb = db.Column(db.String(260), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='post', lazy='dynamic', cascade='all, delete-orphan')
class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
class Bookmark(db.Model):
    __tablename__ = 'bookmarks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
# --------------------------
# 表单
# --------------------------
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(3, 80)])
    email = StringField('邮箱', validators=[DataRequired(), Email()])
    password = PasswordField('密码', validators=[DataRequired(), Length(6, 128)])
    password2 = PasswordField('确认密码', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('注册')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('登录')
class PostForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(max=220)])
    body = TextAreaField('内容', validators=[DataRequired(), Length(max=5000)])
    image = FileField('图片（可选）')
    submit = SubmitField('发布')
class EditPostForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(max=220)])
    body = TextAreaField('内容', validators=[DataRequired(), Length(max=5000)])
    image = FileField('替换图片（可选）')
    submit = SubmitField('保存')
# --------------------------
# 助手函数
# --------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def _safe_filename(filename: str) -> str:
    return secure_filename(filename).replace(' ', '_')
def _remove_file_if_exists(filename: str) -> None:
    if not filename:
        return
    try:
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
def save_image(file_storage, prefix='post'):
    filename = _safe_filename(file_storage.filename)
    if not allowed_file(filename):
        raise ValueError('不支持的图片格式')
    unique = secrets.token_hex(10)
    image_name = f"{prefix}_{unique}.jpg"
    thumb_name = f"{prefix}_{unique}_thumb.jpg"
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_name)
    thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], thumb_name)
    file_storage.stream.seek(0)
    try:
        data = file_storage.stream.read()
        img = Image.open(BytesIO(data))
        img = img.convert('RGB')
    except UnidentifiedImageError as e:
        raise ValueError('无法识别的图片文件') from e
    max_main = 1600
    img.thumbnail((max_main, max_main), Image.LANCZOS)
    img.save(image_path, format='JPEG', quality=85, optimize=True)
    thumb = img.copy()
    thumb.thumbnail((420, 420), Image.LANCZOS)
    thumb.save(thumb_path, format='JPEG', quality=75, optimize=True)
    try:
        os.chmod(image_path, 0o644)
        os.chmod(thumb_path, 0o644)
    except Exception:
        pass
    return image_name, thumb_name
# --------------------------
# 模板（完整内联）
# --------------------------
BASE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Mini-XHS</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    body{padding-top:70px;background:#f8f9fa;}
    .card-img-top{object-fit:cover;height:220px;}
    .thumb-small{width:56px;height:56px;object-fit:cover;border-radius:6px;}
    .note-body{white-space:pre-wrap;}
    .search-input{max-width:420px;}
    .masonry { column-count: 3; column-gap: 1rem; }
    @media (max-width: 1200px){ .masonry{column-count:2;} }
    @media (max-width: 768px){ .masonry{column-count:1;} }
    .masonry .card{display:inline-block;width:100%;margin-bottom:1rem;}
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-white fixed-top shadow-sm">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}"><i class="bi bi-bookmark-star"></i> Mini-XHS</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMenu">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navMenu">
      <form class="d-flex ms-auto me-3" method="get" action="{{ url_for('index') }}">
        <input name="q" value="{{ request.args.get('q','') }}" class="form-control form-control-sm search-input" placeholder="搜索标题或内容">
        <button class="btn btn-sm btn-outline-secondary ms-2" type="submit"><i class="bi bi-search"></i></button>
      </form>
      <ul class="navbar-nav">
        {% if current_user.is_authenticated %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('new_post') }}"><i class="bi bi-plus-circle"></i> 发布</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('user_page', username=current_user.username) }}"><i class="bi bi-person-circle"></i> {{ current_user.username }}</a></li>
          <li class="nav-item"><a class="nav-link text-danger" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> 登出</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<div class="container mt-3">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{ 'success' if category=='success' else ('warning' if category=='warning' else 'danger') }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% block content %}{% endblock %}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# --------------------------
# 路由：首页（搜索 + 分页 + masonry）
# --------------------------
@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 9
    posts_query = Post.query.order_by(Post.created_at.desc())
    if q:
        posts_query = posts_query.filter(db.or_(Post.title.ilike(f'%{q}%'), Post.body.ilike(f'%{q}%')))
    pagination = posts_query.paginate(page=page, per_page=per_page, error_out=False)
    posts = pagination.items
    return render_template_string(
        BASE_TEMPLATE + """
{% block content %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h4 class="mb-0">推荐</h4>
    <div class="text-muted small">共 {{ pagination.total }} 帖子</div>
  </div>

  <div class="masonry">
    {% for post in posts %}
      <div class="card">
        {% if post.thumb %}
          <img src="{{ url_for('uploaded_file', filename=post.thumb) }}" class="card-img-top" alt="...">
        {% elif post.image %}
          <img src="{{ url_for('uploaded_file', filename=post.image) }}" class="card-img-top" alt="...">
        {% endif %}
        <div class="card-body">
          <h5 class="card-title text-truncate"><a class="stretched-link text-decoration-none" href="{{ url_for('post_detail', post_id=post.id) }}">{{ post.title }}</a></h5>
          <p class="card-text text-muted small">{{ post.body[:120] }}{% if post.body|length > 120 %}...{% endif %}</p>
          <div class="d-flex align-items-center mt-2">
            <img src="{{ url_for('uploaded_file', filename=post.thumb) if post.thumb else url_for('static', filename='avatar_default.png') }}" class="thumb-small me-2">
            <div class="small">
              <div>{{ post.author.username }}</div>
              <div class="text-muted">{{ post.created_at.strftime('%Y-%m-%d') }}</div>
            </div>
            <div class="ms-auto small text-muted">{{ post.likes.count() }} <i class="bi bi-hand-thumbs-up"></i></div>
          </div>
        </div>
      </div>
    {% endfor %}
  </div>

  <nav aria-label="Page navigation" class="mt-3">
    <ul class="pagination justify-content-center">
      {% if pagination.has_prev %}
        <li class="page-item"><a class="page-link" href="{{ url_for('index', page=pagination.prev_num, q=request.args.get('q','')) }}">上一页</a></li>
      {% else %}
        <li class="page-item disabled"><span class="page-link">上一页</span></li>
      {% endif %}
      <li class="page-item disabled"><span class="page-link">第 {{ pagination.page }} 页</span></li>
      {% if pagination.has_next %}
        <li class="page-item"><a class="page-link" href="{{ url_for('index', page=pagination.next_num, q=request.args.get('q','')) }}">下一页</a></li>
      {% else %}
        <li class="page-item disabled"><span class="page-link">下一页</span></li>
      {% endif %}
    </ul>
  </nav>
{% endblock %}
""",
        posts=posts, pagination=pagination
    )


# 上传文件访问
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    # 仅从 UPLOAD_FOLDER 提供文件
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)


# 注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        exists = User.query.filter(db.or_(User.username == form.username.data, User.email == form.email.data)).first()
        if exists:
            flash('用户名或邮箱已被使用', 'warning')
            return redirect(url_for('register'))
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
    return render_template_string(BASE_TEMPLATE + """
{% block content %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <div class="card shadow-sm">
        <div class="card-body">
          <h5 class="card-title">注册</h5>
          <form method="post">
            {{ form.hidden_tag() }}
            <div class="mb-3">{{ form.username.label }} {{ form.username(class_="form-control") }}</div>
            <div class="mb-3">{{ form.email.label }} {{ form.email(class_="form-control") }}</div>
            <div class="mb-3">{{ form.password.label }} {{ form.password(class_="form-control") }}</div>
            <div class="mb-3">{{ form.password2.label }} {{ form.password2(class_="form-control") }}</div>
            <div class="d-grid">{{ form.submit(class_="btn btn-primary") }}</div>
          </form>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
""", form=form)


# 登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        flash('用户名或密码错误', 'warning')
    return render_template_string(BASE_TEMPLATE + """
{% block content %}
  <div class="row justify-content-center">
    <div class="col-md-5">
      <div class="card shadow-sm">
        <div class="card-body">
          <h5 class="card-title">登录</h5>
          <form method="post">
            {{ form.hidden_tag() }}
            <div class="mb-3">{{ form.username.label }} {{ form.username(class_="form-control") }}</div>
            <div class="mb-3">{{ form.password.label }} {{ form.password(class_="form-control") }}</div>
            <div class="d-grid">{{ form.submit(class_="btn btn-primary") }}</div>
          </form>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
""", form=form)


# 登出
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# 新建帖子
@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    form = PostForm()
    if form.validate_on_submit():
        image_name = None
        thumb_name = None
        file = request.files.get(form.image.name)
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('不支持的图片格式', 'warning')
                return redirect(url_for('new_post'))
            try:
                image_name, thumb_name = save_image(file, prefix='post')
            except Exception as e:
                print("image save error:", e)
                flash('图片处理失败', 'danger')
                return redirect(url_for('new_post'))

        post = Post(title=form.title.data, body=form.body.data, image=image_name, thumb=thumb_name, author=current_user)
        db.session.add(post)
        db.session.commit()
        flash('发布成功', 'success')
        return redirect(url_for('post_detail', post_id=post.id))
    return render_template_string(BASE_TEMPLATE + """
{% block content %}
  <div class="row justify-content-center">
    <div class="col-lg-8">
      <div class="card shadow-sm">
        <div class="card-body">
          <h5 class="card-title">新建笔记</h5>
          <form method="post" enctype="multipart/form-data">
            {{ form.hidden_tag() }}
            <div class="mb-3">{{ form.title.label }} {{ form.title(class_="form-control") }}</div>
            <div class="mb-3">{{ form.body.label }} {{ form.body(class_="form-control", rows="6") }}</div>
            <div class="mb-3">{{ form.image.label }} {{ form.image(class_="form-control") }}</div>
            <div class="d-grid">{{ form.submit(class_="btn btn-primary") }}</div>
          </form>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
""", form=form)


# 帖子详情、点赞、收藏、编辑、删除
@app.route('/post/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template_string(BASE_TEMPLATE + """
{% block content %}
  <div class="row">
    <div class="col-lg-8">
      <div class="card mb-3">
        {% if post.image %}
          <img src="{{ url_for('uploaded_file', filename=post.image) }}" class="card-img-top" alt="">
        {% endif %}
        <div class="card-body">
          <h3>{{ post.title }}</h3>
          <div class="text-muted small mb-2">by <a href="{{ url_for('user_page', username=post.author.username) }}">{{ post.author.username }}</a> · {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</div>
          <div class="note-body">{{ post.body }}</div>
          <div class="mt-3 d-flex align-items-center">
            <form method="post" action="{{ url_for('toggle_like', post_id=post.id) }}">
              <button class="btn btn-sm btn-outline-primary" type="submit">
                {% if current_user.is_authenticated and post.likes.filter_by(user_id=current_user.id).first() %}已赞{% else %}点赞{% endif %} ({{ post.likes.count() }})
              </button>
            </form>
            <form method="post" action="{{ url_for('toggle_bookmark', post_id=post.id) }}" class="ms-2">
              <button class="btn btn-sm btn-outline-secondary" type="submit">
                {% if current_user.is_authenticated and post.bookmarks.filter_by(user_id=current_user.id).first() %}已收藏{% else %}收藏{% endif %}
              </button>
            </form>

            {% if current_user.is_authenticated and current_user.id == post.author_id %}
              <div class="ms-auto">
                <a class="btn btn-sm btn-outline-success" href="{{ url_for('edit_post', post_id=post.id) }}">编辑</a>
                <form method="post" action="{{ url_for('delete_post', post_id=post.id) }}" style="display:inline;" onsubmit="return confirm('确认删除？');">
                  <button class="btn btn-sm btn-outline-danger">删除</button>
                </form>
              </div>
            {% endif %}
          </div>
        </div>
      </div>
    </div>

    <div class="col-lg-4">
      <div class="card shadow-sm mb-3">
        <div class="card-body">
          <h6>作者</h6>
          <div class="d-flex align-items-center">
            <img src="{{ url_for('uploaded_file', filename=post.thumb) if post.thumb else url_for('static', filename='avatar_default.png') }}" class="thumb-small me-2">
            <div>
              <div><a href="{{ url_for('user_page', username=post.author.username) }}">{{ post.author.username }}</a></div>
              <div class="text-muted small">共 {{ post.author.posts.count() }} 篇</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
""", post=post)


@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash('已取消点赞', 'success')
    else:
        lk = Like(user_id=current_user.id, post_id=post.id)
        db.session.add(lk)
        db.session.commit()
        flash('已点赞', 'success')
    return redirect(request.referrer or url_for('post_detail', post_id=post.id))
@app.route('/post/<int:post_id>/bookmark', methods=['POST'])
@login_required
def toggle_bookmark(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash('已取消收藏', 'success')
    else:
        bm = Bookmark(user_id=current_user.id, post_id=post.id)
        db.session.add(bm)
        db.session.commit()
        flash('已收藏', 'success')
    return redirect(request.referrer or url_for('post_detail', post_id=post.id))
@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author_id != current_user.id:
        flash('无权限', 'warning')
        return redirect(url_for('post_detail', post_id=post.id))
    form = EditPostForm(obj=post)
    if form.validate_on_submit():
        post.title = form.title.data
        post.body = form.body.data
        file = request.files.get(form.image.name)
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('不支持的图片格式', 'warning')
                return redirect(url_for('edit_post', post_id=post.id))
            try:
                image_name, thumb_name = save_image(file, prefix='post')
                # 删除旧图
                _remove_file_if_exists(post.image)
                _remove_file_if_exists(post.thumb)
                post.image = image_name
                post.thumb = thumb_name
            except Exception as e:
                print("image save error:", e)
                flash('图片处理失败', 'danger')
                return redirect(url_for('edit_post', post_id=post.id))
        db.session.commit()
        flash('已保存', 'success')
        return redirect(url_for('post_detail', post_id=post.id))
    return render_template_string(BASE_TEMPLATE + """
{% block content %}
  <div class="row justify-content-center">
    <div class="col-lg-8">
      <div class="card shadow-sm">
        <div class="card-body">
          <h5 class="card-title">编辑笔记</h5>
          <form method="post" enctype="multipart/form-data">
            {{ form.hidden_tag() }}
            <div class="mb-3">{{ form.title.label }} {{ form.title(class_="form-control") }}</div>
            <div class="mb-3">{{ form.body.label }} {{ form.body(class_="form-control", rows="6") }}</div>
            <div class="mb-3">{{ form.image.label }} {{ form.image(class_="form-control") }}</div>
            <div class="d-grid">{{ form.submit(class_="btn btn-primary") }}</div>
          </form>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
""", form=form)
@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author_id != current_user.id:
        flash('无权限', 'warning')
        return redirect(url_for('post_detail', post_id=post.id))
    _remove_file_if_exists(post.image)
    _remove_file_if_exists(post.thumb)
    db.session.delete(post)
    db.session.commit()
    flash('已删除', 'success')
    return redirect(url_for('index'))
# 用户页面：用户的帖子与收藏
@app.route('/user/<username>')
def user_page(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = user.posts.order_by(Post.created_at.desc()).all()
    bookmarks = Post.query.join(Bookmark, Bookmark.post_id == Post.id).filter(Bookmark.user_id == user.id).order_by(Bookmark.created_at.desc()).limit(10).all()
    return render_template_string(BASE_TEMPLATE + """
{% block content %}
  <div class="row">
    <div class="col-lg-8">
      <div class="d-flex align-items-center mb-3">
        <img src="{{ url_for('static', filename='avatar_default.png') }}" class="thumb-small me-3">
        <div>
          <h4 class="mb-0">{{ user.username }}</h4>
          <div class="text-muted small">共 {{ user.posts.count() }} 篇</div>
        </div>
      </div>

      <h6>文章</h6>
      <div class="list-group mb-3">
        {% for p in posts %}
          <a class="list-group-item list-group-item-action" href="{{ url_for('post_detail', post_id=p.id) }}">
            <div class="d-flex w-100 justify-content-between">
              <h6 class="mb-1">{{ p.title }}</h6>
              <small class="text-muted">{{ p.created_at.strftime('%Y-%m-%d') }}</small>
            </div>
            <p class="mb-1 text-muted">{{ p.body[:120] }}{% if p.body|length>120 %}...{% endif %}</p>
          </a>
        {% else %}
          <div class="list-group-item">暂无内容</div>
        {% endfor %}
      </div>
    </div>

    <div class="col-lg-4">
      <div class="card shadow-sm mb-3">
        <div class="card-body">
          <h6>收藏</h6>
          {% for bm in bookmarks %}
            <div><a href="{{ url_for('post_detail', post_id=bm.id) }}">{{ bm.title }}</a></div>
          {% else %}
            <div class="text-muted small">暂无收藏</div>
          {% endfor %}
        </div>
      </div>
    </div>
  </div>
{% endblock %}
""", user=user, posts=posts, bookmarks=bookmarks)
@app.route('/home')
def home_redirect():
    return redirect(url_for('index'))
# 确保默认头像存在
DEFAULT_AVATAR = os.path.join(STATIC_DIR, 'avatar_default.png')
if not os.path.exists(DEFAULT_AVATAR):
    img = Image.new('RGB', (200, 200), color=(240, 240, 240))
    img.save(DEFAULT_AVATAR, format='PNG')
# --------------------------
# 运行
# --------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
