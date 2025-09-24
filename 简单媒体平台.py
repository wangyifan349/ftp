# app.py
import os
import time
from datetime import datetime
from math import ceil
from flask import (Flask, render_template_string, redirect, url_for, flash,
                   request, send_from_directory, abort, jsonify)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, TextAreaField,
                     FileField, BooleanField)
from wtforms.validators import DataRequired, Length, EqualTo
# ---------- 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov', 'mkv'}
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-secret-key')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = UPLOAD_FOLDER
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024 * 1024  # 1GB

# ---------- 应用与扩展 ----------
app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
# ---------- 模型 ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    bio = db.Column(db.Text, default='')  # 个人简介
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    videos = db.relationship('Video', backref='uploader', lazy=True)
class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(260), nullable=False)
    original_name = db.Column(db.String(260), nullable=False)
    description = db.Column(db.Text, default='')
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    size = db.Column(db.Integer, nullable=True)
    hidden = db.Column(db.Boolean, default=False)
# ---------- 表单 ----------
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(3, 80)])
    password = PasswordField('密码', validators=[DataRequired(), Length(6, 128)])
    confirm = PasswordField('确认密码', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('注册')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('登录')
class UploadForm(FlaskForm):
    file = FileField('视频文件', validators=[DataRequired()])
    description = TextAreaField('描述', validators=[Length(max=1000)])
    hidden = BooleanField('默认隐藏（仅自己可见）')
    submit = SubmitField('上传')
class EditProfileForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(3,80)])
    bio = TextAreaField('个人简介', validators=[Length(max=1000)])
    submit = SubmitField('保存')
class EditVideoForm(FlaskForm):
    description = TextAreaField('描述', validators=[Length(max=1000)])
    hidden = BooleanField('隐藏（仅自己可见）')
    submit = SubmitField('保存')
# ---------- 初始化 ----------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
@app.before_first_request
def create_tables():
    db.create_all()
# ---------- 工具函数 ----------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
# LCS 长度计算（动态规划，优化内存）
def lcs_length(a: str, b: str) -> int:
    if not a or not b:
        return 0
    # 用较短的作为外层循环减少内存
    if len(a) < len(b):
        short, long = a, b
    else:
        short, long = b, a
    m, n = len(short), len(long)
    prev = [0] * (n + 1)
    for i in range(1, m+1):
        cur = [0] * (n + 1)
        ai = short[i-1]
        for j in range(1, n+1):
            if ai == long[j-1]:
                cur[j] = prev[j-1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j-1] else cur[j-1]
        prev = cur
    return prev[n]
def similarity_score(a: str, b: str) -> float:
    if a is None: a = ''
    if b is None: b = ''
    a = a.lower()
    b = b.lower()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    l = lcs_length(a, b)
    denom = max(len(a), len(b))
    return l / denom
# ---------- 模板（内联） ----------
base_html = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>视频平台</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      /* 绿色 + 金色 主题 */
      :root {
        --primary: #0f9d58; /* 绿色 */
        --accent: #d4af37;  /* 金色 */
        --muted: #6c757d;
      }
      .navbar, .bg-primary-custom { background: linear-gradient(90deg, var(--primary), #0aa14b); }
      .btn-accent { background: var(--accent); color:#111; border: none; }
      .btn-accent:hover { opacity:0.9; }
      .card-video { height:200px; display:flex; align-items:center; justify-content:center; overflow:hidden; background:#000; }
      .card-video video{ width:100%; height:100%; object-fit:cover; }
      .small-muted { font-size:0.85rem; color:var(--muted); }
      body { padding-bottom:80px; background: linear-gradient(180deg, #f7fff9, #f2fff5); }
      .badge-accent { background:var(--accent); color:#111; }
      .theme-border { border-left: 4px solid var(--primary); }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4" style="background:linear-gradient(90deg,var(--primary),#0aa14b);">
      <div class="container">
        <a class="navbar-brand" href="{{ url_for('index') }}">视频平台</a>
        <form id="searchForm" class="d-flex ms-3 flex-fill" onsubmit="return false;">
          <input id="searchInput" class="form-control form-control-sm me-2" name="q" type="search" placeholder="搜索用户名或视频名" value="{{ request.args.get('q','') }}">
          <button id="searchBtn" class="btn btn-sm btn-light" type="button">搜索</button>
        </form>
        <div class="collapse navbar-collapse justify-content-end">
          <ul class="navbar-nav">
            {% if current_user.is_authenticated %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('manage') }}">管理</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('profile', user_id=current_user.id) }}">{{ current_user.username }}</a></li>
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
          {% for cat, msg in messages %}
            <div class="alert alert-{{ cat }} alert-dismissible fade show" role="alert">
              {{ msg }}
              <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </div>

    <footer class="fixed-bottom bg-white py-2" style="border-top:1px solid #eee;">
      <div class="container text-center small-muted">简易视频平台 · 单文件实现 · {{ now }}</div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      // AJAX 搜索
      async function doSearch(q) {
        const res = await fetch('/ajax_search?q=' + encodeURIComponent(q));
        if (!res.ok) return;
        const data = await res.json();
        const el = document.getElementById('searchResultsContainer');
        if (!el) return;
        el.innerHTML = '';
        if (data.results.length === 0) {
          el.innerHTML = '<div class="p-3">未找到匹配项。</div>';
          return;
        }
        let html = '<div class="row">';
        data.results.forEach(item => {
          html += `
          <div class="col-md-4 mb-4">
            <div class="card h-100 shadow-sm">
              <div class="card-video">
                <video muted preload="metadata">
                  <source src="${item.src}">
                </video>
              </div>
              <div class="card-body d-flex flex-column">
                <h5 class="card-title">${escapeHtml(item.name)}</h5>
                <p class="card-text text-truncate">${escapeHtml(item.description || '')}</p>
                <div class="mt-auto">
                  <a href="/watch/${item.id}" class="btn btn-sm btn-primary">观看</a>
                  <span class="float-end small-muted">相似度: ${item.score.toFixed(2)}</span>
                </div>
              </div>
            </div>
          </div>`;
        });
        html += '</div>';
        el.innerHTML = html;
      }
      function escapeHtml(unsafe) {
        return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
      }
      document.getElementById('searchBtn')?.addEventListener('click', ()=> {
        const q = document.getElementById('searchInput').value.trim();
        if (!q) return;
        // navigate to search page but also support ajax in-page
        if (window.location.pathname === '/') {
          // inject container and show results via ajax
          let cont = document.getElementById('searchResultsContainer');
          if (!cont) {
            cont = document.createElement('div');
            cont.id = 'searchResultsContainer';
            document.querySelector('.container').prepend(cont);
          }
          doSearch(q);
        } else {
          window.location = '/search?q=' + encodeURIComponent(q);
        }
      });
      // allow Enter key
      document.getElementById('searchInput')?.addEventListener('keydown', (e)=> {
        if (e.key === 'Enter') { e.preventDefault(); document.getElementById('searchBtn').click(); }
      });
    </script>
  </body>
</html>
"""

index_html = """
{% extends "base" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3 class="mb-0">最新视频</h3>
  <div><a class="btn btn-sm btn-accent" href="{{ url_for('upload') }}">上传视频</a></div>
</div>
<div class="row">
  {% for v in videos %}
  <div class="col-md-4 mb-4">
    <div class="card h-100 shadow-sm">
      <div class="card-video">
        <video muted preload="metadata" onclick="location.href='{{ url_for('watch', video_id=v.id) }}'">
          <source src="{{ url_for('uploaded_file', filename=v.filename) }}">
        </video>
      </div>
      <div class="card-body d-flex flex-column">
        <h5 class="card-title">{{ v.original_name }}</h5>
        <p class="card-text text-truncate">{{ v.description or '—' }}</p>
        <div class="mt-auto">
          <a href="{{ url_for('watch', video_id=v.id) }}" class="btn btn-sm btn-primary">观看</a>
          <span class="float-end small-muted">by <a href="{{ url_for('profile', user_id=v.uploader.id) }}">{{ v.uploader.username }}</a> · {{ v.uploaded_at.strftime('%Y-%m-%d') }}</span>
        </div>
      </div>
    </div>
  </div>
  {% else %}
  <div class="col-12"><p>暂无视频。</p></div>
  {% endfor %}
</div>
{% endblock %}
"""

register_html = """
{% extends "base" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">注册</h4>
        <form method="post">
          {{ form.hidden_tag() }}
          <div class="mb-3">
            {{ form.username.label(class="form-label") }}
            {{ form.username(class="form-control") }}
          </div>
          <div class="mb-3">
            {{ form.password.label(class="form-label") }}
            {{ form.password(class="form-control") }}
          </div>
          <div class="mb-3">
            {{ form.confirm.label(class="form-label") }}
            {{ form.confirm(class="form-control") }}
          </div>
          <button class="btn btn-primary" type="submit">{{ form.submit.label }}</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

login_html = """
{% extends "base" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">登录</h4>
        <form method="post">
          {{ form.hidden_tag() }}
          <div class="mb-3">
            {{ form.username.label(class="form-label") }}
            {{ form.username(class="form-control") }}
          </div>
          <div class="mb-3">
            {{ form.password.label(class="form-label") }}
            {{ form.password(class="form-control") }}
          </div>
          <button class="btn btn-primary" type="submit">{{ form.submit.label }}</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

upload_html = """
{% extends "base" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4 class="card-title mb-3">上传视频</h4>
        <form method="post" enctype="multipart/form-data">
          {{ form.hidden_tag() }}
          <div class="mb-3">
            {{ form.file.label(class="form-label") }}
            {{ form.file(class="form-control") }}
          </div>
          <div class="mb-3">
            {{ form.description.label(class="form-label") }}
            {{ form.description(class="form-control", rows="3") }}
          </div>
          <div class="form-check mb-3">
            {{ form.hidden(class="form-check-input") }}
            {{ form.hidden.label(class="form-check-label") }}
          </div>
          <button class="btn btn-success" type="submit">{{ form.submit.label }}</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
"""

watch_html = """
{% extends "base" %}
{% block content %}
<div class="row">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4>{{ video.original_name }}</h4>
        <video id="player" class="w-100 mb-2" controls controlsList="nodownload">
          <source src="{{ url_for('uploaded_file', filename=video.filename) }}">
        </video>
        <p class="small-muted">上传者: <a href="{{ url_for('profile', user_id=video.uploader.id) }}">{{ video.uploader.username }}</a> · {{ video.uploaded_at.strftime('%Y-%m-%d %H:%M') }}</p>
        <p>{{ video.description }}</p>
      </div>
    </div>
  </div>
  <div class="col-md-4">
    <div class="card shadow-sm">
      <div class="card-body">
        <h6 class="card-title">视频信息</h6>
        <p class="mb-1"><strong>文件名：</strong> {{ video.filename }}</p>
        <p class="mb-1"><strong>大小：</strong> {{ (video.size // 1024)|int }} KB</p>
        <p class="mb-1"><strong>隐藏：</strong> {{ '是' if video.hidden else '否' }}</p>
        {% if current_user.is_authenticated and current_user.id == video.uploader_id %}
        <div class="mt-3">
          <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#editVideoModal">编辑</button>
          <form method="post" action="{{ url_for('toggle_visibility', video_id=video.id) }}" class="d-inline">
            <button class="btn btn-sm btn-warning">{{ '取消隐藏' if video.hidden else '隐藏' }}</button>
          </form>
          <form method="post" action="{{ url_for('delete_video', video_id=video.id) }}" class="d-inline" onsubmit="return confirm('确认删除该视频？');">
            <button class="btn btn-sm btn-danger">删除</button>
          </form>
        </div>
        {% endif %}
      </div>
    </div>
  </div>
</div>

<!-- 编辑视频 Modal -->
<div class="modal fade" id="editVideoModal" tabindex="-1">
  <div class="modal-dialog">
    <form method="post" action="{{ url_for('edit_video', video_id=video.id) }}">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">编辑视频</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          {{ edit_form.hidden_tag() }}
          <div class="mb-3">
            {{ edit_form.description.label(class="form-label") }}
            {{ edit_form.description(class="form-control", rows="4") }}
          </div>
          <div class="form-check mb-3">
            {{ edit_form.hidden(class="form-check-input") }}
            {{ edit_form.hidden.label(class="form-check-label") }}
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" data-bs-dismiss="modal" type="button">取消</button>
          <button class="btn btn-primary" type="submit">保存</button>
        </div>
      </div>
    </form>
  </div>
</div>
{% endblock %}
"""

manage_html = """
{% extends "base" %}
{% block content %}
<h4>我的视频管理</h4>
<div class="row">
  <div class="col-12">
    <div class="list-group">
      {% for v in videos %}
      <div class="list-group-item d-flex justify-content-between align-items-center theme-border">
        <div>
          <strong>{{ v.original_name }}</strong>
          <div class="small-muted">上传于 {{ v.uploaded_at.strftime('%Y-%m-%d') }} · {{ (v.size//1024)|int }}KB</div>
          <div class="small-muted">描述：{{ v.description or '—' }}</div>
        </div>
        <div>
          {% if v.hidden %}
            <span class="badge badge-accent me-2">隐藏</span>
          {% endif %}
          <a class="btn btn-sm btn-outline-primary me-1" href="{{ url_for('watch', video_id=v.id) }}">查看</a>
          <form class="d-inline" method="post" action="{{ url_for('toggle_visibility', video_id=v.id) }}">
            <button class="btn btn-sm btn-warning me-1" type="submit">{{ '取消隐藏' if v.hidden else '隐藏' }}</button>
          </form>
          <form class="d-inline" method="post" action="{{ url_for('delete_video', video_id=v.id) }}" onsubmit="return confirm('确认删除？');">
            <button class="btn btn-sm btn-danger" type="submit">删除</button>
          </form>
        </div>
      </div>
      {% else %}
      <div class="list-group-item">暂无上传的视频。</div>
      {% endfor %}
    </div>
  </div>
</div>
{% endblock %}
"""

profile_html = """
{% extends "base" %}
{% block content %}
<div class="row">
  <div class="col-md-8">
    <div class="card shadow-sm">
      <div class="card-body">
        <h4>{{ user.username }}
          {% if current_user.is_authenticated and current_user.id == user.id %}
            <small class="small-muted">（这是你的页面）</small>
          {% endif %}
        </h4>
        <p>{{ user.bio or '暂无个人简介' }}</p>
      </div>
    </div>
    <div class="mt-3">
      <h5>用户视频</h5>
      <div class="row">
        {% for v in videos %}
        <div class="col-md-4 mb-4">
          <div class="card h-100 shadow-sm">
            <div class="card-video">
              <video muted preload="metadata" onclick="location.href='{{ url_for('watch', video_id=v.id) }}'">
                <source src="{{ url_for('uploaded_file', filename=v.filename) }}">
              </video>
            </div>
            <div class="card-body d-flex flex-column">
              <h6 class="card-title">{{ v.original_name }}</h6>
              <p class="card-text text-truncate">{{ v.description or '—' }}</p>
              <div class="mt-auto">
                <a href="{{ url_for('watch', video_id=v.id) }}" class="btn btn-sm btn-primary">观看</a>
              </div>
            </div>
          </div>
        </div>
        {% else %}
        <div class="col-12">暂无视频。</div>
        {% endfor %}
      </div>
    </div>
  </div>
  <div class="col-md-4">
    {% if current_user.is_authenticated and current_user.id == user.id %}
    <div class="card shadow-sm">
      <div class="card-body">
        <h5>编辑资料</h5>
        <form method="post" action="{{ url_for('edit_profile') }}">
          {{ profile_form.hidden_tag() }}
          <div class="mb-3">
            {{ profile_form.username.label(class="form-label") }}
            {{ profile_form.username(class="form-control") }}
          </div>
          <div class="mb-3">
            {{ profile_form.bio.label(class="form-label") }}
            {{ profile_form.bio(class="form-control", rows="4") }}
          </div>
          <button class="btn btn-primary" type="submit">保存</button>
        </form>
      </div>
    </div>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

search_html = """
{% extends "base" %}
{% block content %}
<h4>搜索结果: "{{ q }}"</h4>
<p class="small-muted">按相似度（LCS）降序</p>
<div id="searchResultsContainer">
  {% for item in results %}
  <div class="col-md-4 mb-4" style="display:inline-block; width:32%;">
    <div class="card h-100 shadow-sm">
      <div class="card-video">
        <video muted preload="metadata">
          <source src="{{ url_for('uploaded_file', filename=item.video.filename) }}">
        </video>
      </div>
      <div class="card-body d-flex flex-column">
        <h5 class="card-title">{{ item.video.original_name }}</h5>
        <p class="card-text text-truncate">{{ item.video.description or '—' }}</p>
        <div class="mt-auto">
          <a href="{{ url_for('watch', video_id=item.video.id) }}" class="btn btn-sm btn-primary">观看</a>
          <span class="float-end small-muted">相似度: {{ '%.2f'|format(item.score) }}</span>
        </div>
      </div>
    </div>
  </div>
  {% else %}
  <div>未找到匹配项。</div>
  {% endfor %}
</div>
{% endblock %}
"""

# 模板映射
templates = {
    'base': base_html,
    'index': index_html,
    'register': register_html,
    'login': login_html,
    'upload': upload_html,
    'watch': watch_html,
    'manage': manage_html,
    'profile': profile_html,
    'search': search_html,
}
def render(name, **ctx):
    ctx.setdefault('now', datetime.utcnow().strftime('%Y-%m-%d'))
    return render_template_string(templates[name], **ctx)
# ---------- 路由 ----------
@app.route('/')
def index():
    videos = Video.query.filter_by(hidden=False).order_by(Video.uploaded_at.desc()).all()
    return render('index', videos=videos, current_user=current_user)
@app.route('/register', methods=['GET','POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return redirect(url_for('register'))
        user = User(username=username, password_hash=generate_password_hash(form.password.data))
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
    return render('register', form=form)
@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger')
    return render('login', form=form)
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已登出', 'info')
    return redirect(url_for('index'))
@app.route('/upload', methods=['GET','POST'])
@login_required
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('未选择文件', 'danger')
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash('不支持的文件类型', 'danger')
            return redirect(url_for('upload'))
        filename = secure_filename(file.filename)
        base, ext = os.path.splitext(filename)
        save_name = filename
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
        counter = 1
        while os.path.exists(save_path):
            save_name = f"{base}_{counter}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
            counter += 1
        file.save(save_path)
        size = os.path.getsize(save_path)
        hidden_flag = bool(form.hidden.data)
        video = Video(filename=save_name, original_name=file.filename, description=form.description.data or '', uploader_id=current_user.id, size=size, hidden=hidden_flag)
        db.session.add(video)
        db.session.commit()
        flash('上传成功', 'success')
        return redirect(url_for('manage') if hidden_flag else url_for('index'))
    return render('upload', form=form, current_user=current_user)
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    safe_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(safe_path):
        abort(404)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, conditional=True)
@app.route('/watch/<int:video_id>')
def watch(video_id):
    video = Video.query.get_or_404(video_id)
    if video.hidden and (not current_user.is_authenticated or current_user.id != video.uploader_id):
        abort(404)
    edit_form = EditVideoForm()
    edit_form.description.data = video.description
    edit_form.hidden.data = video.hidden
    return render('watch', video=video, current_user=current_user, edit_form=edit_form)
@app.route('/manage')
@login_required
def manage():
    videos = Video.query.filter_by(uploader_id=current_user.id).order_by(Video.uploaded_at.desc()).all()
    return render('manage', videos=videos, current_user=current_user)
@app.route('/profile/<int:user_id>', methods=['GET'])
def profile(user_id):
    user = User.query.get_or_404(user_id)
    # 公开的视频或本人可见的视频
    vids = []
    for v in user.videos:
        if v.hidden and (not current_user.is_authenticated or current_user.id != user.id):
            continue
        vids.append(v)
    profile_form = EditProfileForm()
    profile_form.username.data = user.username
    profile_form.bio.data = user.bio
    return render('profile', user=user, videos=vids, profile_form=profile_form, current_user=current_user)
@app.route('/edit_profile', methods=['POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        newname = form.username.data.strip()
        if newname != current_user.username and User.query.filter_by(username=newname).first():
            flash('用户名已存在', 'danger')
            return redirect(url_for('profile', user_id=current_user.id))
        current_user.username = newname
        current_user.bio = form.bio.data or ''
        db.session.commit()
        flash('已保存', 'success')
    return redirect(url_for('profile', user_id=current_user.id))

@app.route('/toggle/<int:video_id>', methods=['POST'])
@login_required
def toggle_visibility(video_id):
    video = Video.query.get_or_404(video_id)
    if video.uploader_id != current_user.id:
        abort(403)
    video.hidden = not video.hidden
    db.session.commit()
    flash('操作成功', 'success')
    return redirect(request.referrer or url_for('manage'))
@app.route('/delete/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.uploader_id != current_user.id:
        abort(403)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], video.filename))
    except Exception:
        pass
    db.session.delete(video)
    db.session.commit()
    flash('已删除', 'info')
    return redirect(request.referrer or url_for('manage'))
@app.route('/edit_video/<int:video_id>', methods=['POST'])
@login_required
def edit_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.uploader_id != current_user.id:
        abort(403)
    form = EditVideoForm()
    if form.validate_on_submit():
        video.description = form.description.data or ''
        video.hidden = bool(form.hidden.data)
        db.session.commit()
        flash('已保存', 'success')
    return redirect(request.referrer or url_for('watch', video_id=video.id))
# ---------- 搜索与 AJAX ----------
@app.route('/search')
def search():
    q = (request.args.get('q') or '').strip()
    if not q:
        flash('请输入搜索关键词', 'warning')
        return redirect(url_for('index'))
    results = perform_search(q)
    # wrap items for template
    class Item: pass
    wrapped = []
    for r in results:
        it = Item()
        it.video = r['video']
        it.score = r['score']
        wrapped.append(it)
    return render('search', q=q, results=wrapped, current_user=current_user)
@app.route('/ajax_search')
def ajax_search():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})
    results = perform_search(q)
    out = []
    for r in results:
        v = r['video']
        out.append({
            'id': v.id,
            'name': v.original_name,
            'description': v.description,
            'score': r['score'],
            'src': url_for('uploaded_file', filename=v.filename)
        })
    return jsonify({'results': out})
def perform_search(q: str):
    q_low = q.lower()
    videos_all = Video.query.order_by(Video.uploaded_at.desc()).all()
    results = []
    for v in videos_all:
        # 隐藏的视频只有上传者可见
        if v.hidden and (not current_user.is_authenticated or current_user.id != v.uploader_id):
            continue
        name_score = similarity_score(q_low, v.original_name.lower())
        user_score = similarity_score(q_low, v.uploader.username.lower()) if v.uploader else 0.0
        score = max(name_score, user_score)
        # substring boost
        if q_low in v.original_name.lower() or q_low in v.uploader.username.lower():
            score = max(score, 0.75)
        if score > 0:
            results.append({'video': v, 'score': score})
    # Also include users matching (and their videos) if not already included
    users = User.query.filter(User.username.ilike(f"%{q}%")).all()
    for u in users:
        for v in u.videos:
            if v.hidden and (not current_user.is_authenticated or current_user.id != v.uploader_id):
                continue
            if any(r['video'].id == v.id for r in results):
                continue
            score = similarity_score(q_low, u.username.lower())
            if q_low in v.original_name.lower() or q_low in u.username.lower():
                score = max(score, 0.75)
            if score > 0:
                results.append({'video': v, 'score': score})
    # sort strictly by score desc, then uploaded_at desc
    results.sort(key=lambda x: (x['score'], x['video'].uploaded_at), reverse=True)
    return results
# ---------- 启动 ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
