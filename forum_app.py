# forum_app.py
import os
import time
import sqlite3
from functools import wraps
from flask import (
    Flask, g, render_template_string, request, redirect, url_for,
    session, abort, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, TextAreaField, FileField, SubmitField
from wtforms.validators import DataRequired, Length
# -------------------
# Configuration
# -------------------
BASE_DIR = os.path.dirname(__file__)
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_DIR, 'forum.sqlite')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif'}
# Ensure directories exist
os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'change-this-in-production'),
    DATABASE=DB_PATH,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=5 * 1024 * 1024  # 5 MB
)
csrf = CSRFProtect(app)
# -------------------
# DB helpers (原生 sqlite3)
# -------------------
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db
@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()
def init_db():
    schema = """
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS user (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL,
      created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS post (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      author_id INTEGER NOT NULL,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      image TEXT,
      created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated TIMESTAMP,
      FOREIGN KEY(author_id) REFERENCES user(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS comment (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      post_id INTEGER NOT NULL,
      author_id INTEGER NOT NULL,
      body TEXT NOT NULL,
      created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(post_id) REFERENCES post(id) ON DELETE CASCADE,
      FOREIGN KEY(author_id) REFERENCES user(id) ON DELETE CASCADE
    );
    """
    db = get_db()
    db.executescript(schema)
    db.commit()
# For convenience: a route to initialize DB (only for dev)
@app.route('/init-db')
def init_db_route():
    try:
        init_db()
        return "initialized database"
    except Exception as e:
        return f"init failed: {e}", 500
# -------------------
# Forms (Flask-WTF)
# -------------------
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(3, 30)])
    password = PasswordField('密码', validators=[DataRequired(), Length(6, 128)])
    submit = SubmitField('注册')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('登录')
class PostForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(max=200)])
    body = TextAreaField('内容', validators=[DataRequired()])
    image = FileField('图片（可选）')
    submit = SubmitField('发布')
class CommentForm(FlaskForm):
    body = TextAreaField('评论', validators=[DataRequired(), Length(max=1000)])
    submit = SubmitField('发表评论')
# -------------------
# Utilities
# -------------------
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapped
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT
# -------------------
# Templates (内嵌)
# -------------------
base_template = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>小红书样例论坛</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
    .text-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-light bg-light mb-4">
      <div class="container">
        <a class="navbar-brand" href="{{ url_for('index') }}">论坛样例</a>
        <div class="collapse navbar-collapse">
          <ul class="navbar-nav ms-auto">
            {% if session.get('user_id') %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('create') }}">发帖</a></li>
              <li class="nav-item"><a class="nav-link" href="#"> {{ session.get('username') }} </a></li>
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

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

index_template = """
{% extends 'base' %}
{% block content %}
<h1>最新帖子</h1>
<div class="list-group">
  {% for p in posts %}
  <a href="{{ url_for('view_post', post_id=p.id) }}" class="list-group-item list-group-item-action">
    <div class="d-flex w-100 justify-content-between">
      <h5 class="mb-1">{{ p.title }}</h5>
      <small>{{ p.created }}</small>
    </div>
    <p class="mb-1 text-truncate">{{ p.body }}</p>
    <small>作者: {{ p.author }}</small>
  </a>
  {% else %}
  <div class="alert alert-secondary">还没有帖子，快去发第一篇！</div>
  {% endfor %}
</div>
{% endblock %}
"""

register_template = """
{% extends 'base' %}
{% block content %}
<h2>注册</h2>
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
  <button class="btn btn-primary">{{ form.submit.label.text }}</button>
</form>
{% endblock %}
"""

login_template = """
{% extends 'base' %}
{% block content %}
<h2>登录</h2>
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
  <button class="btn btn-primary">{{ form.submit.label.text }}</button>
</form>
{% endblock %}
"""

create_template = """
{% extends 'base' %}
{% block content %}
<h2>发帖</h2>
<form method="post" enctype="multipart/form-data">
  {{ form.hidden_tag() }}
  <div class="mb-3">
    {{ form.title.label(class="form-label") }}
    {{ form.title(class="form-control") }}
  </div>
  <div class="mb-3">
    {{ form.body.label(class="form-label") }}
    {{ form.body(class="form-control", rows="6") }}
  </div>
  <div class="mb-3">
    {{ form.image.label(class="form-label") }}
    {{ form.image(class="form-control") }}
  </div>
  <button class="btn btn-success">{{ form.submit.label.text }}</button>
</form>
{% endblock %}
"""

edit_template = """
{% extends 'base' %}
{% block content %}
<h2>编辑帖子</h2>
<form method="post">
  {{ form.hidden_tag() }}
  <div class="mb-3">
    {{ form.title.label(class="form-label") }}
    {{ form.title(class="form-control", value=post.title) }}
  </div>
  <div class="mb-3">
    {{ form.body.label(class="form-label") }}
    {{ form.body(class="form-control", rows="6") }} 
  </div>
  <button class="btn btn-primary">{{ form.submit.label.text }}</button>
</form>
{% endblock %}
"""

post_template = """
{% extends 'base' %}
{% block content %}
<div class="card mb-3">
  <div class="card-body">
    <h3 class="card-title">{{ post.title }}</h3>
    <h6 class="card-subtitle mb-2 text-muted">作者：{{ post.author }} · {{ post.created }}</h6>
    {% if post.image %}
      <img src="{{ url_for('uploads', filename=post.image) }}" class="img-fluid mb-2" alt="post image">
    {% endif %}
    <p class="card-text">{{ post.body }}</p>
    {% if session.get('user_id') == post.author_id %}
      <a href="{{ url_for('edit', post_id=post.id) }}" class="btn btn-sm btn-outline-primary">编辑</a>
      <form action="{{ url_for('delete', post_id=post.id) }}" method="post" style="display:inline;">
        {{ csrf_token() }}
        <button class="btn btn-sm btn-outline-danger" onclick="return confirm('确认删除？')">删除</button>
      </form>
    {% endif %}
  </div>
</div>

<h5>评论</h5>
{% for c in comments %}
  <div class="mb-2">
    <strong>{{ c.author }}</strong> <small class="text-muted">{{ c.created }}</small>
    <p>{{ c.body }}</p>
    {% if session.get('user_id') == c.author_id or session.get('user_id') == post.author_id %}
      <form action="{{ url_for('delete_comment', comment_id=c.id) }}" method="post">
        {{ csrf_token() }}
        <button class="btn btn-sm btn-outline-danger">删除</button>
      </form>
    {% endif %}
  </div>
{% else %}
  <div class="text-muted">暂无评论</div>
{% endfor %}

<hr>
{% if session.get('user_id') %}
  <form method="post">
    {{ form.hidden_tag() }}
    <div class="mb-3">
      {{ form.body(class="form-control", rows="3") }}
    </div>
    <button class="btn btn-primary">{{ form.submit.label.text }}</button>
  </form>
{% else %}
  <p><a href="{{ url_for('login') }}">登录</a> 后可以发表评论。</p>
{% endif %}
{% endblock %}
"""
# Template map for render_template_string
templates = {
    'base': base_template,
    'index': index_template,
    'register': register_template,
    'login': login_template,
    'create': create_template,
    'edit': edit_template,
    'post': post_template
}
def render(name, **context):
    # Render named template with base as parent
    env = dict(templates)
    # Jinja will look up extends 'base' so we provide loader via render_template_string using combined templates
    # Build a wrapper that defines each template in one string using Jinja's {% raw %} trick isn't necessary.
    # Simpler: inject base as a template global by replacing extends line to inline base.
    # But Jinja supports multiple templates separation with special syntax not available here, so we do:
    tpl = templates[name]
    # Prepend base as a global template by using Jinja's include via a custom environment isn't trivial here.
    # Instead, replace "{% extends 'base' %}" with base content embedding a block marker.
    # We'll implement a quick substitution: replace extends line with base content that contains a placeholder.
    if "{% extends 'base' %}" in tpl:
        combined = templates['base'].replace("{% block content %}{% endblock %}", tpl.replace("{% extends 'base' %}", ""))
    else:
        combined = tpl
    return render_template_string(combined, **context)
# -------------------
# Routes
# -------------------
@app.route('/')
def index():
    db = get_db()
    posts = db.execute("""
        SELECT p.*, u.username as author
        FROM post p JOIN user u ON p.author_id = u.id
        ORDER BY p.created DESC
    """).fetchall()
    return render('index', posts=posts)
@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        db = get_db()
        try:
            db.execute("INSERT INTO user (username, password) VALUES (?, ?)",
                       (username, generate_password_hash(password)))
            db.commit()
            flash('注册成功，请登录。', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在。', 'danger')
    return render('register', form=form)
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        db = get_db()
        user = db.execute("SELECT * FROM user WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('登录成功', 'success')
            next_page = request.args.get('next') or url_for('index')
            return redirect(next_page)
        flash('用户名或密码错误', 'danger')
    return render('login', form=form)
@app.route('/logout')
def logout():
    session.clear()
    flash('已登出', 'info')
    return redirect(url_for('index'))
@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = PostForm()
    if form.validate_on_submit():
        title = form.title.data.strip()
        body = form.body.data.strip()
        image_filename = None
        f = form.image.data
        if f:
            filename = secure_filename(f.filename)
            if filename and allowed_file(filename):
                image_filename = f"{session['user_id']}_{int(time.time())}_{filename}"
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        db = get_db()
        db.execute("INSERT INTO post (author_id, title, body, image) VALUES (?, ?, ?, ?)",
                   (session['user_id'], title, body, image_filename))
        db.commit()
        flash('发布成功', 'success')
        return redirect(url_for('index'))
    return render('create', form=form)
@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def view_post(post_id):
    db = get_db()
    post = db.execute("SELECT p.*, u.username author FROM post p JOIN user u ON p.author_id=u.id WHERE p.id = ?", (post_id,)).fetchone()
    if not post:
        abort(404)
    form = CommentForm()
    if form.validate_on_submit():
        if 'user_id' not in session:
            flash('请先登录再评论', 'warning')
            return redirect(url_for('login'))
        body = form.body.data.strip()
        db.execute("INSERT INTO comment (post_id, author_id, body) VALUES (?, ?, ?)",
                   (post_id, session['user_id'], body))
        db.commit()
        return redirect(url_for('view_post', post_id=post_id))
    comments = db.execute("""
        SELECT c.*, u.username author FROM comment c JOIN user u ON c.author_id=u.id
        WHERE c.post_id = ? ORDER BY c.created ASC
    """, (post_id,)).fetchall()
    return render('post', post=post, comments=comments, form=form)
@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit(post_id):
    db = get_db()
    post = db.execute("SELECT * FROM post WHERE id = ?", (post_id,)).fetchone()
    if not post:
        abort(404)
    if post['author_id'] != session['user_id']:
        abort(403)
    form = PostForm()
    if request.method == 'GET':
        form.title.data = post['title']
        form.body.data = post['body']
    if form.validate_on_submit():
        title = form.title.data.strip()
        body = form.body.data.strip()
        db.execute("UPDATE post SET title = ?, body = ?, updated = CURRENT_TIMESTAMP WHERE id = ?",
                   (title, body, post_id))
        db.commit()
        flash('更新成功', 'success')
        return redirect(url_for('view_post', post_id=post_id))
    return render('edit', form=form, post=post)
@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete(post_id):
    db = get_db()
    post = db.execute("SELECT * FROM post WHERE id = ?", (post_id,)).fetchone()
    if not post:
        abort(404)
    if post['author_id'] != session['user_id']:
        abort(403)
    # delete image file if exists
    if post['image']:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], post['image']))
        except Exception:
            pass
    db.execute("DELETE FROM post WHERE id = ?", (post_id,))
    db.commit()
    flash('帖子已删除', 'info')
    return redirect(url_for('index'))
@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    db = get_db()
    c = db.execute("SELECT * FROM comment WHERE id = ?", (comment_id,)).fetchone()
    if not c:
        abort(404)
    post = db.execute("SELECT * FROM post WHERE id = ?", (c['post_id'],)).fetchone()
    if c['author_id'] != session['user_id'] and post['author_id'] != session['user_id']:
        abort(403)
    db.execute("DELETE FROM comment WHERE id = ?", (comment_id,))
    db.commit()
    flash('评论已删除', 'info')
    return redirect(url_for('view_post', post_id=c['post_id']))
@app.route('/uploads/<filename>')
def uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
# -------------------
# Run
# -------------------
if __name__ == '__main__':
    # Ensure DB exists for first run
    if not os.path.exists(app.config['DATABASE']):
        with app.app_context():
            init_db()
            print('数据库已初始化')
    app.run(debug=True)
